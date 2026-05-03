"""Locus Windows Tray UI

Runs the daemon in a background thread in the SAME process as the tray UI.
This is required so dialogs.py's _REQUEST_QUEUE is shared between the
daemon and the tray UI's main-thread drainer.

On first launch, automatically sets up the browser debug port for website
blocking via a one-time UAC prompt. Never asks again after that.

Dependencies:
    pip install PyQt6 psutil pywin32 websocket-client requests win10toast

Run:
    python tray_app.py
    pythonw tray_app.py   (suppresses console window)
"""

import json
import os
import sys
import threading
import time
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox,
)
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH


# ── Icon factory ──────────────────────────────────────────────────────────────

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


def _send_command(cmd_type: str, data: dict = None):
    cmd = {"type": cmd_type, "data": data or {}}
    tmp = COMMAND_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cmd, f)
        os.replace(tmp, COMMAND_PATH)
    except Exception as e:
        print(f"[Locus UI] Failed to write command: {e}")


# ── Dialog queue drainer ──────────────────────────────────────────────────────
# Runs on the Qt main thread every 100ms.
# Picks up dialog callables that dialogs.py pushed from background threads
# and executes them here -- same process, same queue object, dialogs show.

def _drain_dialog_queue():
    from focuslock.dialogs import _REQUEST_QUEUE
    try:
        while True:
            fn = _REQUEST_QUEUE.get_nowait()
            fn()
    except Exception:
        pass


# ── Daemon thread launcher ────────────────────────────────────────────────────

def _start_daemon_thread():
    """Run the Locus daemon in a background thread of this process.

    Same process = shared _REQUEST_QUEUE = dialogs actually work.
    """
    from focuslock.app import main as daemon_main

    def _run():
        try:
            daemon_main()
        except SystemExit:
            pass
        except Exception as e:
            print(f"[Locus] Daemon crashed: {e}")

    t = threading.Thread(target=_run, daemon=True, name="locusd")
    t.start()
    return t


# ── Browser debug setup ───────────────────────────────────────────────────────

def _browser_debug_is_active() -> bool:
    """Check if a browser is already running with the debug port open."""
    try:
        import requests
        resp = requests.get("http://localhost:9222/json/version", timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _browser_debug_already_configured() -> bool:
    """Check if the debug port flag is already in any known browser registry key."""
    try:
        import winreg
        flag = "--remote-debugging-port=9222"
        # Cast a wide net -- different browsers and install types use different keys
        keys_to_check = [
            # Standard StartMenuInternet keys
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
            # Vivaldi per-user install (the actual key on most machines)
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\Vivaldi\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Vivaldi\shell\open\command"),
            # Chrome per-user
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\ChromeHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\ChromeHTML\shell\open\command"),
            # Edge
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\MSEdgeHTM\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\MSEdgeHTM\shell\open\command"),
            # Brave
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Classes\BraveHTML\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\BraveHTML\shell\open\command"),
        ]
        for hive, path in keys_to_check:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if flag in value:
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _run_browser_setup_elevated():
    """Launch setup_browser_debug.py with a UAC elevation prompt."""
    import ctypes
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "setup_browser_debug.py"
    )
    if not os.path.exists(script):
        print("[Locus] setup_browser_debug.py not found, skipping browser setup.")
        return
    # "runas" triggers the UAC prompt -- user clicks Yes once, never again
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}"', None, 1
    )


def _setup_browser_debug_if_needed():
    """Automatically set up the browser debug port on first launch.

    Checks if already configured -- if so, does nothing.
    If not, triggers a one-time UAC prompt to write the registry key.
    After that first run it never prompts again.
    """
    if _browser_debug_is_active():
        return  # already working, browser is open with debug port
    if _browser_debug_already_configured():
        return  # flag already in registry, just need to reopen browser

    print("[Locus] First launch: setting up browser debug port for website blocking...")
    # Run in a thread so it doesn't block the tray from appearing
    threading.Thread(target=_run_browser_setup_elevated, daemon=True).start()


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


# ── Session picker ────────────────────────────────────────────────────────────

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

        layout.addWidget(QLabel("Or start a custom session:"))
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


# ── Tray app ──────────────────────────────────────────────────────────────────

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
        menu.addAction("Refresh Schedule").triggered.connect(
            lambda: _send_command("refresh")
        )
        menu.addSeparator()
        menu.addAction("Quit Locus").triggered.connect(self._quit)

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

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Locus")

    global ICON_IDLE, ICON_ACTIVE
    ICON_IDLE   = _make_icon("#5A5A5A")
    ICON_ACTIVE = _make_icon("#E53935")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[Locus] System tray not available.")
        sys.exit(1)

    # On first launch, automatically configure the browser debug port.
    # Triggers a one-time UAC prompt -- never asks again after that.
    _setup_browser_debug_if_needed()

    # Start daemon in background thread -- same process so queue is shared
    _start_daemon_thread()

    # Drain dialog requests from the daemon onto the main thread every 100ms
    dialog_timer = QTimer()
    dialog_timer.timeout.connect(_drain_dialog_queue)
    dialog_timer.start(100)

    tray = LocusTrayApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
