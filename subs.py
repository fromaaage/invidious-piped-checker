"""Local subscriptions: import/export in the formats Invidious understands, plus a feed from YouTube RSS.

Subscriptions live on your machine, so they survive when an instance dies.
"""

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

UCID = re.compile(r"UC[\w-]{22}")
ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"}


# ---------- import ----------

def parse_file(text):
    """Detects the format and returns {ucid: name}. Supports Invidious JSON, NewPipe JSON,
    FreeTube (.db, one JSON per line), OPML and YouTube Takeout CSV."""
    text = text.lstrip("﻿").strip()
    out = {}
    if text.startswith("<"):  # OPML
        for o in ET.fromstring(text).iter("outline"):
            m = UCID.search(o.get("xmlUrl", "") + " " + o.get("htmlUrl", ""))
            if m:
                out[m.group()] = o.get("title") or o.get("text") or ""
        return out
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for s in data.get("subscriptions", []):
                if isinstance(s, str):  # Invidious
                    out[s] = ""
                elif isinstance(s, dict):  # NewPipe / FreeTube profile
                    m = UCID.search(s.get("url", "") + " " + s.get("id", ""))
                    if m:
                        out[m.group()] = s.get("name", "")
            return out
        if data is None:  # FreeTube: one JSON object per line
            for line in text.splitlines():
                try:
                    out.update(parse_file(line))
                except ValueError:
                    pass
            return out
    for row in csv.reader(io.StringIO(text)):  # YouTube Takeout CSV: id, url, title
        if row and UCID.fullmatch(row[0].strip()):
            out[row[0].strip()] = row[2].strip() if len(row) > 2 else ""
    return out


def resolve_channel(url):
    """Channel URL (/channel/UC…, /@handle, /c/…) → (ucid, name). Raises ValueError."""
    url = url.strip()
    m = UCID.search(url)
    if m:
        return m.group(), ""
    if not url.startswith("http"):
        url = "https://www.youtube.com/" + url.lstrip("/")
    html = requests.get(url, headers=UA, cookies={"SOCS": "CAI"}, timeout=10).text
    m = re.search(r'rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
    if not m:
        raise ValueError("channel not found")
    name = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    return m.group(1), (name.group(1) if name else "")


# ---------- export ----------

def to_invidious_json(subs):
    """For Invidious: Settings → Import/export data → 'Import Invidious JSON data'."""
    return json.dumps({"subscriptions": sorted(subs)}, indent=2)


def to_opml(subs):
    """Universal format (Invidious, FreeTube, NewPipe, RSS readers)."""
    root = ET.Element("opml", version="1.1")
    body = ET.SubElement(ET.SubElement(root, "body"), "outline", text="YouTube Subscriptions",
                         title="YouTube Subscriptions")
    for ucid, name in sorted(subs.items(), key=lambda x: x[1].lower()):
        ET.SubElement(body, "outline", text=name or ucid, title=name or ucid, type="rss",
                      xmlUrl=f"https://www.youtube.com/feeds/videos.xml?channel_id={ucid}")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# ---------- feed ----------

def fetch_channel(ucid):
    """Latest videos of a channel from YouTube's public RSS feed. Returns (name, [video dicts])."""
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={ucid}", headers=UA, timeout=10)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    name = root.findtext("a:title", "", ATOM)
    videos = []
    for e in root.findall("a:entry", ATOM):
        videos.append({
            "id": e.findtext("yt:videoId", "", ATOM),
            "title": e.findtext("a:title", "", ATOM),
            "channel": name,
            "ucid": ucid,
            "published": e.findtext("a:published", "", ATOM),
        })
    return name, videos


def fetch_feed(subs, limit=150):
    """All subscriptions in parallel. Returns (videos newest first, {ucid: name}, errors)."""
    names, videos, errors = {}, [], 0

    def one(ucid):
        try:
            return ucid, *fetch_channel(ucid)
        except Exception:
            return ucid, None, []

    with ThreadPoolExecutor(12) as ex:
        for ucid, name, vids in ex.map(one, subs):
            if name is None:
                errors += 1
            else:
                names[ucid] = name
                videos += vids
    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos[:limit], names, errors


def age(iso):
    """'3 h', '2 d', … since an ISO timestamp."""
    try:
        secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return ""
    for unit, n in (("d", 86400), ("h", 3600), ("min", 60)):
        if secs >= n:
            return f"{int(secs // n)} {unit}"
    return "now"
