#!/usr/bin/env python3
"""GUI: find working Invidious/Piped sites, test them in your browser, remember favorites."""

import json
import shutil
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, QUrl, Property, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

import core
import subs

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # PyInstaller bundle or source
CONFIG_DIR = Path.home() / ".config" / "invidious-piped-checker"
EXTRA = CONFIG_DIR / "extra.json"  # [[app, url], ...]
MARKS = CONFIG_DIR / "marks.json"  # {web_url: {"ok": bool, "date": "YYYY-MM-DD", "app": str}}
HISTORY = CONFIG_DIR / "history.json"  # {url: [[unix_ts, online 0/1], ...]}
SUBS = CONFIG_DIR / "subscriptions.json"  # {ucid: channel name}
UPTIME_DAYS = 30
KEEP_DAYS = 90

# take over data from the old name
_OLD = Path.home() / ".config" / "yattee-manifest"
if _OLD.is_dir() and not CONFIG_DIR.exists():
    shutil.copytree(_OLD, CONFIG_DIR)


def _load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


class DictModel(QAbstractListModel):
    """List of dicts; every key is a QML role."""

    def __init__(self, keys):
        super().__init__()
        self.keys = keys
        self.rows: list[dict] = []

    def roleNames(self):
        return {Qt.UserRole + n: k.encode() for n, k in enumerate(self.keys)}

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def data(self, index, role):
        return self.rows[index.row()].get(self.keys[role - Qt.UserRole], "")

    def set(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class InstanceModel(QAbstractListModel):
    FIELDS = ["app", "url", "webUrl", "flag", "latency", "status", "note", "sources", "uptime"]
    ROLES = {Qt.UserRole + n: f.encode() for n, f in enumerate(FIELDS)}
    ORDER = {"fav": 0, "online": 1, "pending": 2, "bad": 3, "dead": 4}

    def __init__(self):
        super().__init__()
        self.items: list[core.Instance] = []
        self.done: set[str] = set()
        self.marks: dict = _load(MARKS, {})
        self.history: dict = _load(HISTORY, {})

    def key(self, i):
        return i.web_url or i.url

    def uptime(self, i):
        """(percent, number of checks) from own history, or invidious.io's value as fallback."""
        since = time.time() - UPTIME_DAYS * 86400
        checks = [ok for ts, ok in self.history.get(self.key(i), []) if ts >= since]
        if len(checks) >= 2:
            return 100 * sum(checks) / len(checks), len(checks)
        if i.monitor_uptime is not None:
            return i.monitor_uptime, 0
        return None, len(checks)

    def uptime_text(self, i):
        pct, n = self.uptime(i)
        if pct is None:
            return ""
        return f"{pct:.0f} % up ({n} checks)" if n else f"{pct:.0f} % up (invidious.io)"

    def record(self):
        """Store the result of the finished check for every tested instance."""
        now = int(time.time())
        cutoff = now - KEEP_DAYS * 86400
        for i in self.items:
            if i.url in self.done:
                entries = [e for e in self.history.get(self.key(i), []) if e[0] >= cutoff]
                self.history[self.key(i)] = entries + [[now, int(i.online or i.working)]]
        _save(HISTORY, self.history)
        self._sort()

    def status(self, i):
        if i.url not in self.done:
            return "pending"
        mark = self.marks.get(i.web_url)
        if i.working or (i.online and mark and mark["ok"]):
            return "fav"
        if not i.online:
            return "dead"
        if mark:
            return "bad"
        return "online"

    def note(self, i):
        st = self.status(i)
        mark = self.marks.get(i.web_url)
        if st == "pending":
            return "checking …"
        if st == "fav":
            return f"Works for you (tested {mark['date']})" if mark else "Videos play (API works too)"
        if st == "bad":
            return f"Did not work for you ({mark['date']})"
        if st == "online":
            return "Online – click “Test” to try it in your browser"
        return i.error or "offline"

    def roleNames(self):
        return self.ROLES

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role):
        i = self.items[index.row()]
        name = self.ROLES[role].decode()
        if name == "latency":
            return f"{i.latency:.2f} s" if i.latency else "–"
        if name == "status":
            return self.status(i)
        if name == "note":
            return self.note(i)
        if name == "webUrl":
            return i.web_url
        if name == "sources":
            return ", ".join(i.sources)
        if name == "uptime":
            return self.uptime_text(i)
        return getattr(i, name)

    def reset(self, items):
        self.beginResetModel()
        self.items, self.done = items, set()
        self.endResetModel()

    def prepend(self, inst):
        self.beginResetModel()
        self.items = [inst] + [i for i in self.items if i.url != inst.url]
        self.done.discard(inst.url)
        self.endResetModel()

    def update(self, inst):
        self.done.add(inst.url)
        self._sort()

    def mark(self, web_url, ok):
        if ok is None:
            self.marks.pop(web_url, None)
        else:
            app = next((i.app for i in self.items if i.web_url == web_url), "Invidious")
            self.marks[web_url] = {"ok": ok, "date": time.strftime("%Y-%m-%d"), "app": app}
        _save(MARKS, self.marks)
        self._sort()

    def count(self, status):
        return sum(self.status(i) == status for i in self.items)

    def _sort(self):
        self.beginResetModel()
        self.items.sort(key=lambda i: (self.ORDER[self.status(i)], -(self.uptime(i)[0] or 0), i.latency or 99))
        self.endResetModel()


class Backend(QObject):
    logLine = Signal(str)
    progressChanged = Signal()
    busyChanged = Signal()
    _instanceDone = Signal(object)
    _collected = Signal(list)
    _finished = Signal()
    subsChanged = Signal()
    feedBusyChanged = Signal()
    _feedLoaded = Signal(list, dict, int)
    _channelResolved = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self._model = InstanceModel()
        self._subs: dict = _load(SUBS, {})
        self._subsModel = DictModel(["ucid", "name"])
        self._feedModel = DictModel(["id", "title", "channel", "ucid", "age"])
        self._feedBusy = False
        self._feedLoaded.connect(self._on_feed)
        self._channelResolved.connect(self._on_channel)
        self._refresh_subs()
        self._busy = False
        self._done = 0
        self._total = 0
        self._instanceDone.connect(self._on_instance)
        self._collected.connect(self._on_collected)
        self._finished.connect(self._on_finished)

    # ----- properties -----
    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(int, notify=progressChanged)
    def done(self):
        return self._done

    @Property(int, notify=progressChanged)
    def total(self):
        return self._total

    @Property(int, notify=progressChanged)
    def favCount(self):
        return self._model.count("fav")

    @Property(int, notify=progressChanged)
    def onlineCount(self):
        return self._model.count("online")

    @Property(int, notify=progressChanged)
    def deadCount(self):
        return self._model.count("dead")

    def _best(self):
        return next((i for i in self._model.items if self._model.status(i) == "fav"), None)

    @Property(str, notify=progressChanged)
    def bestUrl(self):
        fav = self._best()
        return fav.web_url if fav else ""

    def _set_busy(self, v):
        self._busy = v
        self.busyChanged.emit()

    @Property(QObject, constant=True)
    def subsModel(self):
        return self._subsModel

    @Property(QObject, constant=True)
    def feedModel(self):
        return self._feedModel

    @Property(int, notify=subsChanged)
    def subsCount(self):
        return len(self._subs)

    @Property(bool, notify=feedBusyChanged)
    def feedBusy(self):
        return self._feedBusy

    # ----- custom instances -----
    @Slot(str, str)
    def addInstance(self, app, url):
        u = core._norm(url)
        if not u:
            self.logLine.emit(f"Invalid URL: {url} (https only)")
            return
        extras = _load(EXTRA, [])
        if [app, u] not in extras:
            extras.append([app, u])
            _save(EXTRA, extras)
        self.logLine.emit(f"Saved: {app} {u} – included in every check")
        if not self._busy:
            inst = core.Instance(app=app, url=u, web_url=u, sources=["manual"])
            self._model.prepend(inst)
            self._total = len(self._model.items)
            self._run([inst])

    # ----- check -----
    @Slot()
    def scan(self):
        if self._busy:
            return
        self._set_busy(True)
        self._done = 0
        self.progressChanged.emit()
        self.logLine.emit("Collecting instances from public lists …")

        def work():
            items = core.collect([tuple(x) for x in _load(EXTRA, [])], log=self.logLine.emit)
            self._collected.emit(items)
        threading.Thread(target=work, daemon=True).start()

    def _on_collected(self, items):
        self._model.reset(items)
        self._total = len(items)
        self.progressChanged.emit()
        self.logLine.emit(f"{len(items)} unique instances – testing in parallel …")
        self._run(items)

    def _run(self, items):
        self._set_busy(True)

        def work():
            core.test_all(items, self._instanceDone.emit)
            self._finished.emit()
        threading.Thread(target=work, daemon=True).start()

    def _on_instance(self, inst):
        self._model.update(inst)
        self._done = len(self._model.done)
        self.progressChanged.emit()

    def _on_finished(self):
        self._set_busy(False)
        self._model.record()
        self.progressChanged.emit()
        m = self._model
        self.logLine.emit(f"Done: {m.count('fav')} working for you, {m.count('online')} online and untested, "
                          f"{m.count('dead')} dead.")

    # ----- browser & marks -----
    @Slot(str)
    def open(self, url):
        QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def openTest(self, web_url):
        """Opens a short test video on the instance."""
        app = next((i.app for i in self._model.items if i.web_url == web_url), "Invidious")
        self.open(web_url.rstrip("/") + core.video_path(app))

    @Slot(str, bool)
    def mark(self, web_url, ok):
        self._model.mark(web_url, ok)
        self.progressChanged.emit()
        self.logLine.emit(f"{web_url}: {'works ✔ – saved as favorite' if ok else 'does not work ✗'}")

    @Slot(str)
    def unmark(self, web_url):
        self._model.mark(web_url, None)
        self.progressChanged.emit()

    @Slot(result=str)
    def clipboardLink(self):
        """YouTube link from the clipboard, or ''."""
        text = QGuiApplication.clipboard().text().strip()
        return text if core.convert_link(text, "https://x") else ""

    @Slot(str)
    def openLink(self, yt_url):
        fav = self._best()
        if not fav:
            self.logLine.emit("No favorite yet – test an instance first")
            return
        url = core.convert_link(yt_url, fav.web_url, fav.app)
        if not url:
            self.logLine.emit(f"Not a YouTube link: {yt_url}")
            return
        self.logLine.emit(f"Opening {url}")
        self.open(url)

    def _open_on_fav(self, yt_url):
        fav = self._best()
        if not fav:
            self.logLine.emit("No favorite yet – test an instance on the Instances tab first")
            return
        self.open(core.convert_link(yt_url, fav.web_url, fav.app))

    # ----- subscriptions -----
    def _refresh_subs(self):
        rows = [{"ucid": u, "name": n or u} for u, n in self._subs.items()]
        self._subsModel.set(sorted(rows, key=lambda r: r["name"].lower()))
        self.subsChanged.emit()

    def _save_subs(self):
        _save(SUBS, self._subs)
        self._refresh_subs()

    @Slot(str)
    def importSubs(self, file_url):
        path = QUrl(file_url).toLocalFile()
        try:
            found = subs.parse_file(Path(path).read_text(errors="replace"))
        except Exception as e:
            self.logLine.emit(f"Import failed: {e}")
            return
        new = {u: n for u, n in found.items() if u not in self._subs or (n and not self._subs[u])}
        self._subs.update(new)
        self._save_subs()
        self.logLine.emit(f"Imported {len(found)} channels from {Path(path).name} ({len(new)} new or renamed)")
        if new:
            self.refreshFeed()

    @Slot(str, str)
    def exportSubs(self, file_url, fmt):
        path = Path(QUrl(file_url).toLocalFile())
        text = subs.to_opml(self._subs) if fmt == "opml" else subs.to_invidious_json(self._subs)
        path.write_text(text)
        self.logLine.emit(f"Exported {len(self._subs)} channels to {path}")

    @Slot(str)
    def addChannel(self, url):
        self.logLine.emit(f"Looking up {url} …")

        def work():
            try:
                ucid, name = subs.resolve_channel(url)
                self._channelResolved.emit(ucid, name, "")
            except Exception as e:
                self._channelResolved.emit("", "", f"Channel not found: {url} ({e})")
        threading.Thread(target=work, daemon=True).start()

    def _on_channel(self, ucid, name, error):
        if error:
            self.logLine.emit(error)
            return
        self._subs[ucid] = name or self._subs.get(ucid, "")
        self._save_subs()
        self.logLine.emit(f"Subscribed: {name or ucid}")
        self.refreshFeed()

    @Slot(str)
    def removeChannel(self, ucid):
        self._subs.pop(ucid, None)
        self._save_subs()
        self._feedModel.set([v for v in self._feedModel.rows if v["ucid"] != ucid])

    @Slot()
    def refreshFeed(self):
        if self._feedBusy or not self._subs:
            return
        self._feedBusy = True
        self.feedBusyChanged.emit()

        def work():
            videos, names, errors = subs.fetch_feed(list(self._subs))
            self._feedLoaded.emit(videos, names, errors)
        threading.Thread(target=work, daemon=True).start()

    def _on_feed(self, videos, names, errors):
        self._feedBusy = False
        self.feedBusyChanged.emit()
        for v in videos:
            v["age"] = subs.age(v["published"])
        self._feedModel.set(videos)
        renamed = {u: n for u, n in names.items() if n and self._subs.get(u) != n}
        if renamed:
            self._subs.update(renamed)
            self._save_subs()
        self.logLine.emit(f"Feed: {len(videos)} videos" + (f", {errors} channels failed" if errors else ""))

    @Slot(str)
    def openVideo(self, video_id):
        self._open_on_fav(f"https://www.youtube.com/watch?v={video_id}")

    @Slot(str)
    def openChannel(self, ucid):
        self._open_on_fav(f"https://www.youtube.com/channel/{ucid}")

    @Slot()
    def openImportPage(self):
        fav = self._best()
        if fav and fav.app == "Invidious":
            self.open(f"{fav.web_url}/data_control")
        else:
            self.logLine.emit("Importing into an account needs an Invidious favorite")

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.logLine.emit("Copied to clipboard")


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Invidious & Piped Checker")
    app.setDesktopFileName("invidious-piped-checker")
    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(HERE / "Main.qml")
    if not engine.rootObjects():
        sys.exit(1)
    if "--no-autoscan" not in sys.argv:
        backend.scan()
    backend.refreshFeed()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
