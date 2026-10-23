#!/usr/bin/env python3
"""Collects public Invidious and Piped instances from several lists and tests them.

CLI: `python core.py` (table) or `python core.py --json`.
"""

import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import requests

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
VIDEO_ID = "jNQXAC9IVRw"  # "Me at the zoo" – stable since 2005
TIMEOUT = 10
UA = {"User-Agent": "Mozilla/5.0 (invidious-piped-checker)", "Accept": "application/json"}


@dataclass
class Instance:
    app: str  # "Piped" | "Invidious"
    url: str  # API base URL without path
    country: str = ""  # ISO code, e.g. "DE"
    sources: list = field(default_factory=list)
    web_url: str = ""  # website for watching (Invidious = url, Piped = frontend)
    # test results
    online: bool = False  # website responds (bot-check pages count as online)
    api_ok: bool = False
    search_ok: bool = False
    playback_ok: bool = False
    latency: float | None = None  # median, seconds
    version: str = ""
    error: str = ""

    @property
    def working(self):
        """Fully usable via API (videos, search, stream) – what apps need."""
        return self.api_ok and self.search_ok and self.playback_ok

    @property
    def flag(self):
        if len(self.country) != 2:
            return "🌐"
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.country.upper())


def _norm(url):
    url = url.strip().rstrip("/")
    url = re.sub(r"/(api/v1|healthcheck)$", "", url)
    p = urlparse(url)
    if p.scheme != "https" or not p.netloc or p.netloc.endswith((".onion", ".i2p", ".ygg", ".loki")):
        return None
    return f"https://{p.netloc.lower()}"


def _flag_to_code(flag):
    letters = [chr(ord(ch) - 0x1F1E6 + ord("A")) for ch in flag if 0x1F1E6 <= ord(ch) <= 0x1F1FF]
    return "".join(letters[:2])


def _get(url, **kw):
    return requests.get(url, headers=UA, timeout=TIMEOUT, **kw)


# ---------- Sources ----------

def src_invidious_api():
    out = []
    for host, info in _get("https://api.invidious.io/instances.json").json():
        if info.get("type") == "https":
            out.append(("Invidious", info.get("uri", f"https://{host}"), info.get("region", "")))
    return out


def src_piped_docs():
    md = _get("https://raw.githubusercontent.com/TeamPiped/documentation/main/content/docs/public-instances/index.md").text
    out = []
    for line in md.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 3 and cols[1].startswith("https://"):
            out.append(("Piped", cols[1], _flag_to_code(cols[2])))
    return out


def src_piped_uptime():
    data = _get("https://raw.githubusercontent.com/TeamPiped/piped-uptime/master/history/summary.json").json()
    return [("Piped", x["url"], "") for x in data]


def src_libredirect():
    data = _get("https://raw.githubusercontent.com/libredirect/instances/main/data.json").json()
    return [("Invidious", u, "") for u in data.get("invidious", {}).get("clearnet", [])]


def src_farside():
    out = []
    for s in _get("https://raw.githubusercontent.com/benbusby/farside/main/services.json").json():
        if s["type"] == "invidious":
            out += [("Invidious", u, "") for u in s["instances"]]
        elif s["type"] == "piped":
            # format "frontend|api"
            out += [("Piped", u.split("|")[-1], "", u.split("|")[0]) for u in s["instances"]]
    return out


SOURCES = {
    "api.invidious.io": src_invidious_api,
    "Piped docs": src_piped_docs,
    "piped-uptime": src_piped_uptime,
    "LibRedirect": src_libredirect,
    "Farside": src_farside,
}


def collect(extra=(), log=print):
    """Query all sources and merge duplicates. extra: [(app, url)]"""
    found: dict[tuple, Instance] = {}

    def add(app, url, country, source, web=""):
        u = _norm(url)
        if not u:
            return
        inst = found.setdefault((app, u), Instance(app=app, url=u))
        if app == "Invidious":
            inst.web_url = u
        elif web and not inst.web_url:
            inst.web_url = _norm(web) or ""
        if country and not inst.country:
            inst.country = country.upper()
        if source not in inst.sources:
            inst.sources.append(source)

    with ThreadPoolExecutor(len(SOURCES)) as ex:
        futs = {ex.submit(fn): name for name, fn in SOURCES.items()}
        for f in as_completed(futs):
            name = futs[f]
            try:
                rows = f.result()
                log(f"Source {name}: {len(rows)} entries")
                for row in rows:
                    add(*row[:3], name, *row[3:])
            except Exception as e:
                log(f"Source {name}: error – {e}")
    for app, url in extra:
        add(app, url, "", "manual", url if app == "Piped" else "")
    return list(found.values())


# ---------- Tests ----------

def _playable(stream_url):
    """Checks that the first bytes of a stream actually arrive."""
    try:
        r = requests.get(stream_url, headers={**UA, "Range": "bytes=0-2047"}, timeout=TIMEOUT, stream=True)
        ok = r.status_code in (200, 206) and len(next(r.iter_content(2048), b"")) > 0
        r.close()
        return ok
    except requests.RequestException:
        return False


def _test_piped(inst):
    t = []
    s = time.monotonic(); r = _get(f"{inst.url}/streams/{VIDEO_ID}"); t.append(time.monotonic() - s)
    d = r.json()
    streams = d.get("videoStreams") or []
    inst.api_ok = r.status_code == 200 and bool(streams or d.get("hls"))
    if not inst.api_ok:
        inst.error = d.get("error") or d.get("message") or f"HTTP {r.status_code}"
        return t
    s = time.monotonic(); r = _get(f"{inst.url}/search", params={"q": "test", "filter": "all"}); t.append(time.monotonic() - s)
    inst.search_ok = r.status_code == 200 and bool(r.json().get("items"))
    url = next((x["url"] for x in streams if not x.get("videoOnly")), None) or (streams[0]["url"] if streams else d.get("hls"))
    inst.playback_ok = bool(url) and _playable(url)
    if not inst.playback_ok:
        inst.error = "stream does not load"
    try:
        inst.version = _get(f"{inst.url}/version").text.strip()[:40]
    except Exception:
        pass
    return t


def _test_invidious(inst):
    t = []
    s = time.monotonic(); r = _get(f"{inst.url}/api/v1/videos/{VIDEO_ID}", params={"local": "true"}); t.append(time.monotonic() - s)
    try:
        d = r.json()
    except ValueError:
        inst.error = f"HTTP {r.status_code}"
        return t
    fmts = d.get("formatStreams") or d.get("adaptiveFormats") or []
    inst.api_ok = r.status_code == 200 and bool(fmts)
    if not inst.api_ok:
        inst.error = d.get("error") or f"HTTP {r.status_code}"
        return t
    s = time.monotonic(); r = _get(f"{inst.url}/api/v1/search", params={"q": "test"}); t.append(time.monotonic() - s)
    inst.search_ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0
    url = fmts[0]["url"]
    if url.startswith("/"):
        url = inst.url + url
    inst.playback_ok = _playable(url)
    if not inst.playback_ok:
        inst.error = "stream does not load"
    try:
        inst.version = _get(f"{inst.url}/api/v1/stats").json()["software"]["version"][:40]
    except Exception:
        pass
    return t


def _short(msg):
    msg = str(msg).splitlines()[0] if msg else ""
    if "NotBot" in msg or "Sign in to confirm" in msg:
        return "blocked by YouTube (bot check)"
    if "Endpoint disabled" in msg or "HTTP 401" in msg or "HTTP 403" in msg:
        return "API disabled"
    if "Expecting value" in msg:
        return "no JSON response"
    return msg[:80]


def check_online(inst):
    """Does the website respond at all? Bot-check pages (403/418/429) count as online."""
    inst.online = False
    if not inst.web_url:
        return
    try:
        s = time.monotonic()
        r = requests.get(inst.web_url, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT)
        inst.online = r.status_code < 500
        if inst.online and inst.latency is None:
            inst.latency = time.monotonic() - s
        if not inst.online and not inst.error:
            inst.error = f"website HTTP {r.status_code}"
    except requests.RequestException:
        pass


def test(inst):
    inst.api_ok = inst.search_ok = inst.playback_ok = False
    inst.latency = None
    inst.error = ""
    try:
        times = (_test_piped if inst.app == "Piped" else _test_invidious)(inst)
        inst.latency = statistics.median(times) if times else None
    except requests.Timeout:
        inst.error = "timeout"
    except requests.ConnectionError as e:
        inst.error = "domain does not exist" if "resolve" in str(e).lower() else "unreachable"
    except Exception as e:
        inst.error = f"{type(e).__name__}: {e}"
    inst.error = _short(inst.error)
    check_online(inst)
    return inst


def test_all(instances, on_done=None, workers=16):
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(test, i) for i in instances]):
            if on_done:
                on_done(f.result())
    return instances


def main():
    as_json = "--json" in sys.argv
    insts = collect(log=(lambda *_: None) if as_json else print)
    if not as_json:
        print(f"\n{len(insts)} unique instances, testing …\n")
    test_all(insts)
    insts.sort(key=lambda i: (not i.working, not i.online, i.latency or 99))
    if as_json:
        print(json.dumps([asdict(i) | {"working": i.working} for i in insts], indent=2, ensure_ascii=False))
        return
    for i in insts:
        state = "API ✅" if i.working else ("web 🟡" if i.online else "dead ❌")
        lat = f"{i.latency:.2f}s" if i.latency else "–"
        print(f"{state:8} {i.app:9} {lat:>6}  {(i.web_url or i.url):42} {i.error}")
    print(f"\n{sum(i.working for i in insts)} fully working via API, "
          f"{sum(i.online and not i.working for i in insts)} website online (test in browser), "
          f"{sum(not i.online and not i.working for i in insts)} dead")


if __name__ == "__main__":
    main()
