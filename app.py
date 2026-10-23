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

HERE = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "invidious-piped-checker"
EXTRA = CONFIG_DIR / "extra.json"  # [[app, url], ...]
MARKS = CONFIG_DIR / "marks.json"  # {web_url: {"ok": bool, "date": "YYYY-MM-DD"}}

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


class InstanceModel(QAbstractListModel):
    FIELDS = ["app", "url", "webUrl", "flag", "latency", "status", "note", "sources"]
    ROLES = {Qt.UserRole + n: f.encode() for n, f in enumerate(FIELDS)}
    ORDER = {"fav": 0, "online": 1, "pending": 2, "bad": 3, "dead": 4}

    def __init__(self):
        super().__init__()
        self.items: list[core.Instance] = []
        self.done: set[str] = set()
        self.marks: dict = _load(MARKS, {})

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
            self.marks[web_url] = {"ok": ok, "date": time.strftime("%Y-%m-%d")}
        _save(MARKS, self.marks)
        self._sort()

    def count(self, status):
        return sum(self.status(i) == status for i in self.items)

    def _sort(self):
        self.beginResetModel()
        self.items.sort(key=lambda i: (self.ORDER[self.status(i)], i.latency or 99))
        self.endResetModel()


class Backend(QObject):
    logLine = Signal(str)
    progressChanged = Signal()
    busyChanged = Signal()
    _instanceDone = Signal(object)
    _collected = Signal(list)
    _finished = Signal()

    def __init__(self):
        super().__init__()
        self._model = InstanceModel()
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

    @Property(str, notify=progressChanged)
    def bestUrl(self):
        fav = next((i for i in self._model.items if self._model.status(i) == "fav"), None)
        return fav.web_url if fav else ""

    def _set_busy(self, v):
        self._busy = v
        self.busyChanged.emit()

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
        self.open(f"{web_url}/watch?v={core.VIDEO_ID}")

    @Slot(str, bool)
    def mark(self, web_url, ok):
        self._model.mark(web_url, ok)
        self.progressChanged.emit()
        self.logLine.emit(f"{web_url}: {'works ✔ – saved as favorite' if ok else 'does not work ✗'}")

    @Slot(str)
    def unmark(self, web_url):
        self._model.mark(web_url, None)
        self.progressChanged.emit()

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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
