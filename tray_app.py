"""Locus Windows Tray UI

Replaces the Swift/SwiftUI macOS app.
Runs as a system tray icon; communicates with the daemon via the same
command.json / state.json files the Swift app used — zero daemon changes.

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


# ── Tiny icon factory (draws a coloured circle — replace with a real .ico) ───

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


ICON_IDLE   = _make_icon("#5A5A5A")
ICON_ACTIVE = _make_icon("#E53935")


# ── State reader ──────────────────────────────────────────────────────────────

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
            label = f"{ev.get('title', '?')}  ·  {ev.get('date', '')}"
            if ev.get("start_time"):
                label += f"  {ev['start_time']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ev)
            self.list_widget.addItem(item)
        self.list_widget.doubleClicked.connect(self._pick_selected)
        layout.addWidget(self.list_widget)

        layout.addWidget(QLabel("— or start a custom session —"))
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("Session name…")
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


# ── Reason dialog (mirrors Swift PromptView) ──────────────────────────────────

class ReasonDialog(QDialog):
    def __init__(self, subject: str, subject_type: str, session_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Locus — Access Request")
        self.setMinimumWidth(400)
        self.action = "cancel"
        self.reason = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{subject}</b> is blocked during <i>{session_name}</i>.")
        header.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(QLabel(f"Why do you need this {subject_type}?"))

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Enter your reason…")
        self.reason_input.returnPressed.connect(self._submit)
        layout.addWidget(self.reason_input)

        btn_row = QHBoxLayout()
        submit_btn = QPushButton("Submit")
        submit_btn.setDefault(True)
        submit_btn.clicked.connect(self._submit)
        override_btn = QPushButton("Override…")
        override_btn.clicked.connect(self._override)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(override_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(submit_btn)
        layout.addLayout(btn_row)

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.raise_()
        self.activateWindow()

    def _submit(self):
        self.action = "submit"
        self.reason = self.reason_input.text().strip()
        self.accept()

    def _override(self):
        self.action = "override"
        self.accept()


# ── Override code dialog ──────────────────────────────────────────────────────

class OverrideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Override Code")
        self.setMinimumWidth(300)
        self.code = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Enter the override code:"))
        self.code_input = QLineEdit()
        self.code_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.code_input.returnPressed.connect(self.accept)
        layout.addWidget(self.code_input)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

    def get_code(self) -> str:
        return self.code_input.text()


# ── Main tray application ─────────────────────────────────────────────────────

class LocusTrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(ICON_IDLE)
        self._app = app
        self._session_active = False
        self._events = []
        self._session_info = None

        self.setToolTip("Locus — idle")
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

        self._status_action = menu.addAction("Locus — idle")
        self._status_action.setEnabled(False)
        menu.addSeparator()

        self._start_action = menu.addAction("Start Session…")
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
            self.setToolTip(f"Locus — {name}")
            self._status_action.setText(f"🔴  {name}")
            self._start_action.setEnabled(False)
            self._end_action.setEnabled(True)
        else:
            self.setIcon(ICON_IDLE)
            self.setToolTip("Locus — idle")
            self._status_action.setText("Locus — idle")
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


# ── dialogs.py shim ───────────────────────────────────────────────────────────
# The daemon calls functions in focuslock/dialogs.py. On macOS these were
# AppleScript popups. Below is the Windows PyQt6 replacement — save this
# as focuslock/dialogs.py (it imports cleanly from either the daemon or UI).

DIALOGS_PY = '''"""dialogs.py — Windows replacement for macOS AppleScript popups."""
import sys
import threading
from typing import Tuple

# Toast notifications via win10toast if available, else silent.
try:
    from win10toast import ToastNotifier
    _toaster = ToastNotifier()
    _TOAST = True
except ImportError:
    _TOAST = False


def show_notification(title: str, message: str):
    if _TOAST:
        try:
            threading.Thread(
                target=_toaster.show_toast,
                args=(title, message),
                kwargs={"duration": 5, "threaded": True},
                daemon=True,
            ).start()
        except Exception:
            pass
    print(f"[Locus] {title}: {message}")


def _run_qt_dialog(fn):
    """Run a Qt dialog from a non-Qt thread safely."""
    from PyQt6.QtWidgets import QApplication
    import importlib, sys
    # If a QApplication already exists (tray UI is running), use it.
    app = QApplication.instance()
    _created = False
    if app is None:
        app = QApplication(sys.argv)
        _created = True
    result = {}
    done = threading.Event()

    def _run():
        result["value"] = fn()
        done.set()
        if _created:
            app.quit()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _run)
    if _created:
        app.exec()
    else:
        done.wait(timeout=120)
    return result.get("value")


def ask_reason(subject: str, subject_type: str, session_name: str) -> Tuple[str, str]:
    """Show the reason prompt. Returns (action, reason)."""
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Locus — Access Request")
        dlg.setMinimumWidth(400)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = ["cancel", ""]

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel(f"<b>{subject}</b> is blocked during <i>{session_name}</i>."))
        layout.addWidget(QLabel(f"Why do you need this {subject_type}?"))
        inp = QLineEdit()
        inp.setPlaceholderText("Enter your reason…")
        layout.addWidget(inp)

        btn_row = QHBoxLayout()
        def _submit():
            result[0] = "submit"
            result[1] = inp.text().strip()
            dlg.accept()
        def _override():
            result[0] = "override"
            dlg.accept()
        def _cancel():
            result[0] = "cancel"
            dlg.reject()

        inp.returnPressed.connect(_submit)
        ov = QPushButton("Override…"); ov.clicked.connect(_override)
        ok = QPushButton("Submit"); ok.setDefault(True); ok.clicked.connect(_submit)
        cx = QPushButton("Cancel"); cx.clicked.connect(_cancel)
        btn_row.addWidget(ov); btn_row.addStretch(); btn_row.addWidget(cx); btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")


def ask_override_code(correct_code: str) -> bool:
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Override Code")
        dlg.setMinimumWidth(300)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = [False]

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Enter override code:"))
        inp = QLineEdit(); inp.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(inp)
        btn_row = QHBoxLayout()
        def _ok():
            result[0] = inp.text() == correct_code
            dlg.accept()
        inp.returnPressed.connect(_ok)
        ok = QPushButton("OK"); ok.setDefault(True); ok.clicked.connect(_ok)
        cx = QPushButton("Cancel"); cx.clicked.connect(dlg.reject)
        btn_row.addStretch(); btn_row.addWidget(cx); btn_row.addWidget(ok)
        layout.addLayout(btn_row)
        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


def show_result(approved: bool, explanation: str, subject: str, minutes: int = 15):
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox()
    msg.setWindowFlag(__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WindowType.WindowStaysOnTopHint)
    if approved:
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Access Granted")
        msg.setText(f"<b>{subject}</b> allowed for {minutes} min.\\n\\n{explanation}")
    else:
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Access Denied")
        msg.setText(f"<b>{subject}</b> blocked.\\n\\n{explanation}")
    msg.exec()


def show_override_wrong():
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.warning(None, "Wrong Code", "Incorrect override code.")


def ask_off_topic_reason(domain: str, title: str, session_name: str, ai_reason: str):
    return ask_reason(f"{domain} — \\"{title}\\"", "content", session_name)
'''


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Ensure the daemon is running (launch it if not)
    _ensure_daemon()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Locus")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[Locus] System tray not available.")
        sys.exit(1)

    tray = LocusTrayApp(app)
    sys.exit(app.exec())


def _ensure_daemon():
    """Launch locusd if it isn't already running."""
    import psutil
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "locusd_entry" in cmdline or "locusd" in cmdline:
                return  # already running
        except Exception:
            pass
    # Launch daemon in background
    subprocess.Popen(
        [sys.executable, "locusd_entry.py"],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


if __name__ == "__main__":
    # Also write dialogs.py if it doesn't exist yet
    dialogs_path = os.path.join(os.path.dirname(__file__), "focuslock", "dialogs.py")
    if not os.path.exists(dialogs_path):
        os.makedirs(os.path.dirname(dialogs_path), exist_ok=True)
        with open(dialogs_path, "w") as f:
            f.write(DIALOGS_PY)
        print(f"[Locus] Wrote {dialogs_path}")
    main()
