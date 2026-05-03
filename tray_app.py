"""Locus Windows Tray UI

Replaces the Swift/SwiftUI macOS app.
Runs as a system tray icon; communicates with the daemon via the same
command.json / state.json files the Swift app used -- zero daemon changes.

Dependencies:
    pip install PyQt6

Run:
    pythonw tray_app.py   (pythonw suppresses the console window)
    or bundle with PyInstaller (see build_daemon.ps1)
"""

import json
import os
import sys
import subprocess
import threading
import time
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QListWidget,
    QListWidgetItem, QWidget, QSizePolicy, QMessageBox,
)
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH, ANALYTICS_PATH


# ── Tiny icon factory ─────────────────────────────────────────────────────────

def _make_icon(color: str) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.end()
    return QIcon(px)


# ── State helpers ─────────────────────────────────────────────────────────────

def _read_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _read_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _send_command(cmd_type: str, data: dict = None):
    cmd = {"type": cmd_type, "data": data or {}}
    tmp = COMMAND_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cmd, f)
        os.replace(tmp, COMMAND_PATH)
    except Exception as e:
        print(f"[Locus UI] Failed to write command: {e}")


# ── Dialog queue drainer (THE FIX) ───────────────────────────────────────────
# dialogs.py pushes callables onto _REQUEST_QUEUE from background threads.
# This function runs on the Qt main thread every 100ms and executes them.
# This is the only reliable way to show Qt dialogs from non-main threads.

def _drain_dialog_queue():
    from focuslock.dialogs import _REQUEST_QUEUE
    while True:
        try:
            fn = _REQUEST_QUEUE.get_nowait()
            fn()  # runs on main thread -- dialog shows correctly
        except Exception:
            break


# ── Background state watcher ──────────────────────────────────────────────────

class StateWatcher(QObject):
    state_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._last_mtime = 0.0
        self._running = True

    def run(self):
        while self._running:
            try:
                mtime = os.path.getmtime(STATE_PATH)
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    self.state_changed.emit(_read_state())
            except Exception:
                pass
            time.sleep(0.5)

    def stop(self):
        self._running = False


# ── Session picker dialog ─────────────────────────────────────────────────────

class SessionPickerDialog(QDialog):
    def __init__(self, events: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Start a Focus Session")
        self.setMinimumWidth(420)
        self.selected_event = None
        self.custom_title = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(QLabel("Upcoming assignments:"))
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        for ev in events:
            label = f"{ev.get('title', '?')}  -  {ev.get('date', '')}"
            if ev.get("start_time"):
                label += f"  {ev['start_time']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ev)
            self.list_widget.addItem(item)
        self.list_widget.doubleClicked.connect(self._pick_selected)
        layout.addWidget(self.list_widget)

        layout.addWidget(QLabel("or start a custom session:"))
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("Session name...")
        self.custom_input.returnPressed.connect(self._pick_custom)
        layout.addWidget(self.custom_input)

        btn_row = QHBoxLayout()
        start_btn = QPushButton("Start")
        start_btn.setDefault(True)
        start_btn.clicked.connect(self._pick_any)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(start_btn)
        layout.addLayout(btn_row)

    def _pick_selected(self):
        items = self.list_widget.selectedItems()
        if items:
            self.selected_event = items[0].data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _pick_custom(self):
        title = self.custom_input.text().strip()
        if title:
            self.custom_title = title
            self.accept()

    def _pick_any(self):
        custom = self.custom_input.text().strip()
        if custom:
            self.custom_title = custom
            self.accept()
            return
        self._pick_selected()


# ── Main tray application ─────────────────────────────────────────────────────

class LocusTrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(ICON_IDLE)
        self._app = app
        self._session_active = False
        self._events = []
        self._session_info = None

        self.setToolTip("Locus -- idle")
        self._build_menu()
        self.activated.connect(self._on_activated)

        # State watcher thread
        self._watcher = StateWatcher()
        self._watcher_thread = QThread()
        self._watcher.moveToThread(self._watcher_thread)
        self._watcher_thread.started.connect(self._watcher.run)
        self._watcher.state_changed.connect(self._on_state_changed)
        self._watcher_thread.start()

        self.show()

    def _build_menu(self):
        menu = QMenu()

        self._status_action = menu.addAction("Locus -- idle")
        self._status_action.setEnabled(False)
        menu.addSeparator()

        self._start_action = menu.addAction("Start Session...")
        self._start_action.triggered.connect(self._start_session)

        self._end_action = menu.addAction("End Session")
        self._end_action.triggered.connect(self._end_session)
        self._end_action.setEnabled(False)

        menu.addSeparator()
        refresh_action = menu.addAction("Refresh Schedule")
        refresh_action.triggered.connect(lambda: _send_command("refresh"))

        menu.addSeparator()
        quit_action = menu.addAction("Quit Locus")
        quit_action.triggered.connect(self._quit)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.contextMenu().popup(self.geometry().center())

    def _on_state_changed(self, state: dict):
        self._events = state.get("events", [])
        self._session_info = state.get("session")
        self._session_active = self._session_info is not None

        if self._session_active:
            name = self._session_info.get("display_name", "Session")
            self.setIcon(ICON_ACTIVE)
            self.setToolTip(f"Locus -- {name}")
            self._status_action.setText(f"  {name}")
            self._start_action.setEnabled(False)
            self._end_action.setEnabled(True)
        else:
            self.setIcon(ICON_IDLE)
            self.setToolTip("Locus -- idle")
            self._status_action.setText("Locus -- idle")
            self._start_action.setEnabled(True)
            self._end_action.setEnabled(False)

    def _start_session(self):
        dlg = SessionPickerDialog(self._events)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.custom_title:
            _send_command("start_custom_session", {"title": dlg.custom_title})
        elif dlg.selected_event:
            ev = dlg.selected_event
            _send_command("start_session", {
                "title": ev.get("title", ""),
                "date": ev.get("date", ""),
            })

    def _end_session(self):
        _send_command("end_session")

    def _quit(self):
        self._watcher.stop()
        self._watcher_thread.quit()
        self._watcher_thread.wait(2000)
        self._app.quit()


# ── Entry point ───────────────────────────────────────────────────────────────

def _ensure_daemon():
    """Launch locusd if it isn't already running."""
    import psutil
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "locusd_entry" in cmdline or "locusd" in cmdline:
                return
        except Exception:
            pass
    subprocess.Popen(
        [sys.executable, "locusd_entry.py"],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def main():
    _ensure_daemon()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Locus")

    # Icons must be created AFTER QApplication
    global ICON_IDLE, ICON_ACTIVE
    ICON_IDLE   = _make_icon("#5A5A5A")
    ICON_ACTIVE = _make_icon("#E53935")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[Locus] System tray not available.")
        sys.exit(1)

    # THE FIX: drain the dialog request queue on the main thread every 100ms.
    # dialogs.py pushes callables here from background threads; we execute
    # them here so Qt dialogs always run on the main thread.
    dialog_timer = QTimer()
    dialog_timer.timeout.connect(_drain_dialog_queue)
    dialog_timer.start(100)

    tray = LocusTrayApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
