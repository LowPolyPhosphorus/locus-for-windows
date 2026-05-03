"""Locus Windows Tray UI

Runs the daemon in a background thread in the SAME process as the tray UI.
This is required so dialogs.py's _REQUEST_QUEUE is shared between the
daemon and the tray UI's main-thread drainer.

Dependencies:
    pip install PyQt6 psutil pywin32 websocket-client requests win10toast
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
    QListWidgetItem, QFrame, QScrollArea, QWidget, QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QPainter, QFont, QFontDatabase,
    QPainterPath, QBrush, QPen,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QSize

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH
from focuslock.dialogs import (
    ACCENT, ACCENT_MUTED, SURFACE, CARD, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, STYLESHEET,
    _primary_btn, _secondary_btn,
)


# ── Tray icon factory ─────────────────────────────────────────────────────────

def _make_tray_icon(active: bool) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#E53935") if active else QColor("#8A8A8A")
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    # Lock body
    p.drawRoundedRect(6, 14, 20, 14, 3, 3)
    # Lock shackle
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(color, 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    if active:
        # Closed lock — full arch
        p.drawArc(10, 5, 12, 14, 0, 180 * 16)
    else:
        # Open lock — open on right side
        p.drawArc(10, 3, 12, 14, 0, 135 * 16)
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
    try:
        import requests
        resp = requests.get("http://localhost:9222/json/version", timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _browser_debug_already_configured() -> bool:
    try:
        import winreg
        flag = "--remote-debugging-port=9222"
        keys_to_check = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Vivaldi\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Google Chrome\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Microsoft Edge\shell\open\command"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Clients\StartMenuInternet\Brave\shell\open\command"),
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
    import ctypes
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "setup_browser_debug.py"
    )
    if not os.path.exists(script):
        return
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}"', None, 1
    )


def _setup_browser_debug_if_needed():
    if _browser_debug_is_active():
        return
    if _browser_debug_already_configured():
        return
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


# ── Main window ───────────────────────────────────────────────────────────────
# Matches the Swift NavigationSplitView layout:
#   Left sidebar (220px): lock icon + "Locus", nav rows
#   Right panel: pane content

SIDEBAR_WIDTH = 220

SIDEBAR_STYLE = f"""
QWidget#sidebar {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QLabel#app_title {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 20px;
    color: {TEXT_PRIMARY};
}}
QPushButton#nav_row {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 9px 12px;
    font-size: 14px;
    color: {TEXT_PRIMARY};
    border-radius: 8px;
}}
QPushButton#nav_row:hover {{
    background-color: {CARD};
}}
QPushButton#nav_row_selected {{
    background-color: {ACCENT_MUTED};
    border: none;
    text-align: left;
    padding: 9px 12px;
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
    border-radius: 8px;
}}
"""

CONTENT_STYLE = f"""
QWidget#content_panel {{
    background-color: {SURFACE};
}}
QLabel#pane_heading {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 32px;
    color: {TEXT_PRIMARY};
}}
QLabel#pane_subheading {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}
QFrame#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#field_label {{
    font-family: 'Consolas', monospace;
    font-size: 10px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
    letter-spacing: 1px;
}}
QLabel#secondary {{
    font-size: 11px;
    color: {TEXT_SECONDARY};
}}
QLineEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 14px;
    color: {TEXT_PRIMARY};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
"""

PANES = [
    ("Start",      "▶",  "start"),
    ("Settings",   "⚙",  "settings"),
    ("Connectors", "⚡", "connectors"),
    ("Analytics",  "📊", "analytics"),
]


class LocusWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Locus")
        self.setMinimumSize(720, 520)
        self.setStyleSheet(SIDEBAR_STYLE + CONTENT_STYLE + STYLESHEET)
        self.setWindowFlag(Qt.WindowType.Window)

        self._current_pane = "start"
        self._events = []
        self._session_info = None

        root = QHBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self._sidebar = self._build_sidebar()
        root.addWidget(self._sidebar)

        self._content = QWidget()
        self._content.setObjectName("content_panel")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._content, 1)

        self._show_pane("start")

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(sidebar)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # App header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 22, 18, 18)
        header_layout.setSpacing(10)

        lock_lbl = QLabel("🔒")
        lock_lbl.setStyleSheet(f"font-size: 16px; color: {ACCENT};")
        header_layout.addWidget(lock_lbl)

        title_lbl = QLabel("Locus")
        title_lbl.setObjectName("app_title")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        layout.addWidget(header)

        # Nav rows
        self._nav_btns = {}
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setSpacing(2)
        nav_layout.setContentsMargins(10, 0, 10, 0)

        for label, icon, key in PANES:
            btn = QPushButton(f"  {icon}   {label}")
            btn.setObjectName("nav_row")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._show_pane(k))
            nav_layout.addWidget(btn)
            self._nav_btns[key] = btn

        layout.addWidget(nav_container)
        layout.addStretch()
        return sidebar

    def _update_nav_selection(self, active_key: str):
        for key, btn in self._nav_btns.items():
            if key == active_key:
                btn.setObjectName("nav_row_selected")
            else:
                btn.setObjectName("nav_row")
            # Force style refresh
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Pane routing ──────────────────────────────────────────────────────────

    def _show_pane(self, key: str):
        self._current_pane = key
        self._update_nav_selection(key)

        # Clear content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if key == "start":
            self._content_layout.addWidget(self._build_launcher_pane())
        elif key == "settings":
            self._content_layout.addWidget(self._build_placeholder_pane(
                "Settings", "Appearance and global preferences.", "⚙️"
            ))
        elif key == "connectors":
            self._content_layout.addWidget(self._build_placeholder_pane(
                "Connectors", "Connect Notion, iCal, and other integrations.", "⚡"
            ))
        elif key == "analytics":
            self._content_layout.addWidget(self._build_placeholder_pane(
                "Analytics", "Focus time, session history, and stats.", "📊"
            ))

    # ── Launcher pane (mirrors LauncherView.swift) ────────────────────────────

    def _build_launcher_pane(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(0)
        layout.setContentsMargins(32, 32, 32, 32)

        # Lock icon circle
        icon_circle = QFrame()
        icon_circle.setFixedSize(100, 100)
        session_active = self._session_info is not None
        circle_bg = "rgba(229,57,53,0.10)" if session_active else ACCENT_MUTED
        icon_char = "🔒" if session_active else "🔓"
        icon_color = "#E53935" if session_active else ACCENT
        icon_circle.setStyleSheet(f"""
            QFrame {{
                background-color: {circle_bg};
                border-radius: 50px;
            }}
        """)
        il = QVBoxLayout(icon_circle)
        il.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon_char)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size: 42px; color: {icon_color}; background: transparent;")
        il.addWidget(icon_lbl)

        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(icon_circle)
        icon_row.addStretch()
        layout.addLayout(icon_row)

        layout.addSpacing(16)

        # "Locus" serif title
        locus_lbl = QLabel("Locus")
        locus_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        locus_lbl.setStyleSheet(f"""
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 46px;
            color: {TEXT_PRIMARY};
        """)
        layout.addWidget(locus_lbl)

        layout.addSpacing(6)

        # Status line
        if session_active:
            status_row = QHBoxLayout()
            status_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot = QLabel("●")
            dot.setStyleSheet("color: #E53935; font-size: 10px;")
            status_row.addWidget(dot)
            name = self._session_info.get("display_name", "Session")
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"font-size: 15px; font-weight: 500; color: {TEXT_PRIMARY};")
            status_row.addWidget(name_lbl)
            w = QWidget()
            w.setLayout(status_row)
            layout.addWidget(w)
        else:
            status_lbl = QLabel("Ready to focus")
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_lbl.setObjectName("secondary")
            layout.addWidget(status_lbl)

        layout.addSpacing(28)

        # ── Session active: show end button ──
        if session_active:
            s = self._session_info
            info_card = self._card_widget()
            card_layout = QVBoxLayout(info_card)
            card_layout.setContentsMargins(20, 16, 20, 16)
            card_layout.setSpacing(4)

            t_lbl = QLabel(s.get("title", ""))
            t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t_lbl.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {TEXT_PRIMARY};")
            card_layout.addWidget(t_lbl)

            sub = s.get("class_name", "") + " · " + s.get("event_type", "")
            sub_lbl = QLabel(sub.strip(" ·"))
            sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_lbl.setObjectName("secondary")
            card_layout.addWidget(sub_lbl)

            card_row = QHBoxLayout()
            card_row.addStretch()
            card_row.addWidget(info_card)
            card_row.addStretch()
            layout.addLayout(card_row)
            layout.addSpacing(20)

            end_btn = _primary_btn("⬛  End Session")
            end_btn.setStyleSheet(end_btn.styleSheet() + """
                QPushButton { background-color: #E53935; padding: 14px 40px; border-radius: 12px; font-size: 15px; }
                QPushButton:hover { background-color: #C62828; }
            """)
            end_btn.clicked.connect(self._end_session)
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(end_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

        else:
            # ── Custom task card ──
            custom_card = self._card_widget()
            cl = QVBoxLayout(custom_card)
            cl.setContentsMargins(20, 16, 20, 16)
            cl.setSpacing(10)

            wl = QLabel("WHAT ARE YOU WORKING ON?")
            wl.setObjectName("field_label")
            cl.addWidget(wl)

            self._custom_input = QLineEdit()
            self._custom_input.setPlaceholderText("e.g. Write essay intro")
            cl.addWidget(self._custom_input)

            start_btn = _primary_btn("▶  Start Session")
            start_btn.setStyleSheet(start_btn.styleSheet() + "QPushButton { padding: 14px 40px; border-radius: 12px; font-size: 15px; }")
            start_btn.clicked.connect(self._start_custom_session)
            self._custom_input.returnPressed.connect(self._start_custom_session)

            btn_wrap = QHBoxLayout()
            btn_wrap.addStretch()
            btn_wrap.addWidget(start_btn)
            btn_wrap.addStretch()
            cl.addLayout(btn_wrap)

            card_row = QHBoxLayout()
            card_row.addStretch()
            custom_card.setMaximumWidth(460)
            card_row.addWidget(custom_card, 1)
            card_row.addStretch()
            layout.addLayout(card_row)

            # ── OR divider + event list (if events exist) ──
            if self._events:
                layout.addSpacing(22)
                or_row = QHBoxLayout()
                left_line = QFrame()
                left_line.setFrameShape(QFrame.Shape.HLine)
                left_line.setStyleSheet(f"color: {BORDER};")
                or_lbl = QLabel("OR")
                or_lbl.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {TEXT_SECONDARY}; letter-spacing: 1px;")
                or_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                or_lbl.setFixedWidth(32)
                right_line = QFrame()
                right_line.setFrameShape(QFrame.Shape.HLine)
                right_line.setStyleSheet(f"color: {BORDER};")
                or_row.addWidget(left_line, 1)
                or_row.addWidget(or_lbl)
                or_row.addWidget(right_line, 1)
                layout.addLayout(or_row)

                layout.addSpacing(22)
                events_card = self._build_events_card()
                ev_row = QHBoxLayout()
                ev_row.addStretch()
                events_card.setMaximumWidth(460)
                ev_row.addWidget(events_card, 1)
                ev_row.addStretch()
                layout.addLayout(ev_row)

        scroll.setWidget(inner)
        return scroll

    def _card_widget(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        return card

    def _build_events_card(self) -> QFrame:
        card = self._card_widget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        up_lbl = QLabel("UPCOMING")
        up_lbl.setObjectName("field_label")
        layout.addWidget(up_lbl)

        self._event_list = QListWidget()
        self._event_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 9px 12px;
                margin-bottom: 4px;
                font-size: 13px;
                color: {TEXT_PRIMARY};
            }}
            QListWidget::item:selected {{
                background-color: {ACCENT_MUTED};
                border: 1px solid rgba(232,160,32,0.4);
                color: {TEXT_PRIMARY};
            }}
        """)
        self._event_list.setMaximumHeight(200)

        for ev in self._events:
            label = ev.get("title", "?")
            sub = ev.get("class_name", "")
            if ev.get("start_time"):
                sub = ev["start_time"] + ("  ·  " + sub if sub else "")
            item = QListWidgetItem(f"{label}\n{sub}" if sub else label)
            item.setData(Qt.ItemDataRole.UserRole, ev)
            self._event_list.addItem(item)

        layout.addWidget(self._event_list)

        start_ev_btn = _primary_btn("▶  Start Session")
        start_ev_btn.setStyleSheet(start_ev_btn.styleSheet() + "QPushButton { padding: 14px 40px; border-radius: 12px; font-size: 15px; }")
        start_ev_btn.clicked.connect(self._start_event_session)
        self._event_list.doubleClicked.connect(self._start_event_session)

        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch()
        btn_wrap.addWidget(start_ev_btn)
        btn_wrap.addStretch()
        layout.addLayout(btn_wrap)

        return card

    # ── Placeholder pane ──────────────────────────────────────────────────────

    def _build_placeholder_pane(self, title: str, subtitle: str, icon: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel(title)
        heading.setObjectName("pane_heading")
        layout.addWidget(heading)

        sub = QLabel(subtitle)
        sub.setObjectName("pane_subheading")
        layout.addWidget(sub)

        layout.addSpacing(32)

        # Placeholder card
        card = self._card_widget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(8)

        ph_icon = QLabel(icon)
        ph_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_icon.setStyleSheet(f"font-size: 32px; color: {ACCENT};")
        cl.addWidget(ph_icon)

        ph_lbl = QLabel("Coming soon")
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl.setStyleSheet(f"font-size: 13px; color: {TEXT_SECONDARY};")
        cl.addWidget(ph_lbl)

        layout.addWidget(card)
        return w

    # ── Actions ───────────────────────────────────────────────────────────────

    def _start_custom_session(self):
        text = self._custom_input.text().strip()
        if not text:
            return
        _send_command("start_custom_session", {"title": text})
        self._custom_input.clear()

    def _start_event_session(self):
        items = self._event_list.selectedItems()
        if not items:
            return
        ev = items[0].data(Qt.ItemDataRole.UserRole)
        _send_command("start_session", {
            "title": ev.get("title", ""),
            "date": ev.get("date", ""),
        })

    def _end_session(self):
        _send_command("end_session")

    # ── State update ──────────────────────────────────────────────────────────

    def update_state(self, state: dict):
        self._events = state.get("events", [])
        self._session_info = state.get("session")
        if self._current_pane == "start":
            self._show_pane("start")


# ── Tray app ──────────────────────────────────────────────────────────────────

class LocusTrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(_make_tray_icon(False))
        self._app = app
        self._session_active = False
        self._events = []
        self._session_info = None
        self._window: Optional[LocusWindow] = None

        self.setToolTip("Locus — idle")
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
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                font-size: 13px;
                color: {TEXT_PRIMARY};
            }}
            QMenu::item {{
                padding: 7px 16px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background-color: {ACCENT_MUTED};
                color: {TEXT_PRIMARY};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER};
                margin: 4px 8px;
            }}
        """)

        self._status_action = menu.addAction("Locus — idle")
        self._status_action.setEnabled(False)
        menu.addSeparator()

        menu.addAction("Open Locus").triggered.connect(self._open_window)

        menu.addSeparator()

        self._start_action = menu.addAction("Start Session…")
        self._start_action.triggered.connect(self._open_window)

        self._end_action = menu.addAction("End Session")
        self._end_action.triggered.connect(lambda: _send_command("end_session"))
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
            self._open_window()

    def _open_window(self):
        if self._window is None:
            self._window = LocusWindow()
            self._window.destroyed.connect(lambda: setattr(self, '_window', None))
        self._window.update_state({
            "events": self._events,
            "session": self._session_info,
        })
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_state_changed(self, state: dict):
        self._events = state.get("events", [])
        self._session_info = state.get("session")
        self._session_active = self._session_info is not None

        if self._session_active:
            name = self._session_info.get("display_name", "Session")
            self.setIcon(_make_tray_icon(True))
            self.setToolTip(f"Locus — {name}")
            self._status_action.setText(f"  ● {name}")
            self._start_action.setEnabled(False)
            self._end_action.setEnabled(True)
        else:
            self.setIcon(_make_tray_icon(False))
            self.setToolTip("Locus — idle")
            self._status_action.setText("Locus — idle")
            self._start_action.setEnabled(True)
            self._end_action.setEnabled(False)

        if self._window:
            self._window.update_state(state)

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

    # Set app-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[Locus] System tray not available.")
        sys.exit(1)

    _setup_browser_debug_if_needed()
    _start_daemon_thread()

    dialog_timer = QTimer()
    dialog_timer.timeout.connect(_drain_dialog_queue)
    dialog_timer.start(100)

    tray = LocusTrayApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
