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

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QScrollArea, QFrame, QSizePolicy,
    QStackedWidget, QGraphicsOpacityEffect,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QPainter, QPainterPath, QFont,
    QFontDatabase, QPen, QBrush, QPalette,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QThread, QPropertyAnimation,
    QEasingCurve, QSize, QPoint, QRect,
)

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH


# ── Theme ─────────────────────────────────────────────────────────────────────

class Theme:
    # Light palette
    ACCENT       = "#E8A020"
    ACCENT_MUTED = "#FDF3E0"
    SURFACE      = "#FDFAF5"
    CARD         = "#F7F2E8"
    BORDER       = "#E8DFC8"
    TEXT         = "#1A1409"
    TEXT_SECONDARY = "#7A6A4A"

    # Dark palette
    SURFACE_DARK = "#151009"
    CARD_DARK    = "#211A0B"
    BORDER_DARK  = "#FFFFFF17"
    TEXT_DARK    = "#F5EDD8"
    TEXT_SECONDARY_DARK = "#9A8A6A"

    _dark = False

    @classmethod
    def set_dark(cls, dark: bool):
        cls._dark = dark

    @classmethod
    def surface(cls): return cls.SURFACE_DARK if cls._dark else cls.SURFACE
    @classmethod
    def card(cls): return cls.CARD_DARK if cls._dark else cls.CARD
    @classmethod
    def border(cls): return cls.BORDER_DARK if cls._dark else cls.BORDER
    @classmethod
    def text(cls): return cls.TEXT_DARK if cls._dark else cls.TEXT
    @classmethod
    def text_secondary(cls): return cls.TEXT_SECONDARY_DARK if cls._dark else cls.TEXT_SECONDARY

    @classmethod
    def stylesheet(cls) -> str:
        s = cls.surface()
        c = cls.card()
        b = cls.border()
        t = cls.text()
        ts = cls.text_secondary()
        return f"""
        QWidget {{
            background-color: {s};
            color: {t};
            font-family: 'Segoe UI', sans-serif;
            font-size: 13px;
            border: none;
            outline: none;
        }}
        QLabel {{ background: transparent; color: {t}; }}
        QLabel#secondary {{ color: {ts}; font-size: 12px; }}
        QLabel#section_label {{
            color: {ts};
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 1.2px;
        }}
        QLineEdit {{
            background: {c};
            border: 1px solid {b};
            border-radius: 8px;
            padding: 8px 12px;
            color: {t};
            font-size: 13px;
        }}
        QLineEdit:focus {{ border-color: {cls.ACCENT}; }}
        QPushButton#primary {{
            background: {cls.ACCENT};
            color: #1A1409;
            font-weight: 600;
            font-size: 13px;
            border-radius: 8px;
            padding: 8px 20px;
            border: none;
        }}
        QPushButton#primary:hover {{ background: #D4911C; }}
        QPushButton#primary:pressed {{ background: #C07F10; }}
        QPushButton#secondary_btn {{
            background: transparent;
            color: {t};
            font-size: 13px;
            border: 1px solid {b};
            border-radius: 8px;
            padding: 8px 16px;
        }}
        QPushButton#secondary_btn:hover {{ border-color: {cls.ACCENT}; color: {cls.ACCENT}; }}
        QPushButton#ghost {{
            background: transparent;
            color: {ts};
            font-size: 12px;
            border: none;
            padding: 4px 8px;
        }}
        QPushButton#ghost:hover {{ color: {t}; }}
        QListWidget {{
            background: transparent;
            border: none;
            outline: none;
        }}
        QListWidget::item {{
            background: {c};
            border: 1px solid {b};
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 4px;
            color: {t};
        }}
        QListWidget::item:selected {{
            background: {cls.ACCENT_MUTED};
            border-color: {cls.ACCENT};
            color: {cls.TEXT};
        }}
        QListWidget::item:hover:!selected {{
            border-color: {cls.ACCENT};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {b};
            border-radius: 3px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollArea {{ border: none; background: transparent; }}
        QMenu {{
            background: {s};
            border: 1px solid {b};
            border-radius: 10px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 16px;
            border-radius: 6px;
            color: {t};
        }}
        QMenu::item:selected {{ background: {cls.ACCENT_MUTED}; color: {cls.TEXT}; }}
        QMenu::separator {{ background: {b}; height: 1px; margin: 4px 10px; }}
        """


def _is_system_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as k:
            val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return val == 0
    except Exception:
        return False


# ── Font loading ──────────────────────────────────────────────────────────────

def _load_fonts():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FocusLockApp", "Fonts")
    for fname in [
        "InstrumentSerif-Regular.ttf",
        "InstrumentSerif-Italic.ttf",
        "DMMono-Regular.ttf",
        "DMMono-Medium.ttf",
    ]:
        path = os.path.join(base, fname)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def serif_font(size: int, italic: bool = False) -> QFont:
    f = QFont("Instrument Serif")
    if not f.exactMatch():
        f = QFont("Georgia")
    f.setPointSize(size)
    f.setItalic(italic)
    return f


def mono_font(size: int, medium: bool = False) -> QFont:
    f = QFont("DM Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSize(size)
    f.setWeight(QFont.Weight.Medium if medium else QFont.Weight.Normal)
    return f


# ── Icon drawing ──────────────────────────────────────────────────────────────

def _draw_lock_icon(size: int, locked: bool, color: str) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    c = QColor(color)
    p.setPen(QPen(c, size * 0.09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Shackle (arc on top)
    sw = size * 0.42
    sh = size * 0.38
    sx = (size - sw) / 2
    sy = size * 0.08 if locked else size * 0.02
    from PyQt6.QtCore import QRectF
    p.drawArc(QRectF(sx, sy, sw, sh), 0 * 16, 180 * 16)

    # Body (rounded rect bottom half)
    bw = size * 0.62
    bh = size * 0.42
    bx = (size - bw) / 2
    by = size * 0.46
    p.setBrush(QBrush(c))
    p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    path.addRoundedRect(bx, by, bw, bh, size * 0.08, size * 0.08)
    p.fillPath(path, QBrush(c))

    # Keyhole
    kc = QColor(Theme.surface())
    p.setBrush(QBrush(kc))
    kr = size * 0.07
    p.drawEllipse(QRectF(size/2 - kr, by + bh*0.28 - kr, kr*2, kr*2))
    p.fillRect(QRect(int(size/2 - kr*0.6), int(by + bh*0.28 + kr*0.3), int(kr*1.2), int(kr*1.4)), kc)

    p.end()
    return px


def _draw_tray_icon(active: bool) -> QIcon:
    color = "#E53935" if active else "#7A6A4A"
    px = _draw_lock_icon(32, active, color)
    return QIcon(px)


def _draw_nav_icon(name: str, size: int, color: str) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    m = size * 0.15
    w = size - m * 2
    h = size - m * 2

    from PyQt6.QtCore import QRectF, QPointF

    if name == "start":
        # Play triangle
        path = QPainterPath()
        path.moveTo(m + w*0.2, m + h*0.1)
        path.lineTo(m + w*0.2, m + h*0.9)
        path.lineTo(m + w*0.9, m + h*0.5)
        path.closeSubpath()
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

    elif name == "settings":
        # Gear circle + dots
        p.drawEllipse(QRectF(m + w*0.25, m + h*0.25, w*0.5, h*0.5))
        for i in range(6):
            import math
            angle = i * 60 * math.pi / 180
            ox = size/2 + math.cos(angle) * w*0.42
            oy = size/2 + math.sin(angle) * h*0.42
            p.setBrush(QBrush(c))
            p.drawEllipse(QRectF(ox - 1.5, oy - 1.5, 3, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)

    elif name == "connectors":
        # Three horizontal lines with dots (bolt/connections)
        for i, y_frac in enumerate([0.25, 0.5, 0.75]):
            y = m + h * y_frac
            p.drawLine(QPoint(int(m + w*0.1), int(y)), QPoint(int(m + w*0.9), int(y)))

    elif name == "analytics":
        # Simple bar chart
        bars = [0.4, 0.7, 0.55, 0.9]
        bw = w / (len(bars) * 2 - 1)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        for i, frac in enumerate(bars):
            bx = m + i * bw * 2
            bh2 = h * frac
            by = m + h - bh2
            path = QPainterPath()
            path.addRoundedRect(bx, by, bw, bh2, 1.5, 1.5)
            p.drawPath(path)

    p.end()
    return px


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


def _setup_browser_debug_if_needed():
    if _browser_debug_is_active():
        return
    import ctypes
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_browser_debug.py")
    if not os.path.exists(script):
        return
    threading.Thread(
        target=lambda: ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}"', None, 1
        ),
        daemon=True,
    ).start()


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


# ── Sidebar nav item ──────────────────────────────────────────────────────────

class NavItem(QPushButton):
    def __init__(self, label: str, icon_name: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon_name = icon_name
        self._selected = False
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)
        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()
        self.update()

    def _update_style(self):
        if self._selected:
            bg = Theme.ACCENT_MUTED
            tc = Theme.TEXT
        else:
            bg = "transparent"
            tc = Theme.text()
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {tc};
                border-radius: 8px;
                text-align: left;
                padding-left: 36px;
                font-size: 13px;
                font-weight: {'600' if self._selected else '400'};
                border: none;
            }}
            QPushButton:hover {{
                background: {'#F0E8D0' if not Theme._dark else '#2A2010'};
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = Theme.ACCENT if self._selected else Theme.text_secondary()
        icon_px = _draw_nav_icon(self._icon_name, 16, color)
        p.drawPixmap(10, (self.height() - 16) // 2, icon_px)
        p.end()


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    page_changed = pyqtSignal(int)

    PAGES = [
        ("Start",      "start"),
        ("Settings",   "settings"),
        ("Connectors", "connectors"),
        ("Analytics",  "analytics"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self._current = 0
        self._nav_items = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 16)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(64)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 0, 0)
        hl.setSpacing(10)

        lock_px = _draw_lock_icon(22, True, Theme.ACCENT)
        lock_lbl = QLabel()
        lock_lbl.setPixmap(lock_px)
        lock_lbl.setFixedSize(22, 22)

        title = QLabel("Locus")
        title.setFont(serif_font(22))
        title.setStyleSheet(f"color: {Theme.text()}; background: transparent;")

        hl.addWidget(lock_lbl)
        hl.addWidget(title)
        hl.addStretch()
        layout.addWidget(header)

        # Nav items
        for i, (label, icon_name) in enumerate(self.PAGES):
            item = NavItem(label, icon_name)
            item.clicked.connect(lambda checked, idx=i: self._select(idx))
            self._nav_items.append(item)
            layout.addWidget(item)

        layout.addStretch()

        self._nav_items[0].set_selected(True)

    def _select(self, idx: int):
        self._nav_items[self._current].set_selected(False)
        self._current = idx
        self._nav_items[idx].set_selected(True)
        self.page_changed.emit(idx)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(Theme.surface()))
        # Right border line
        p.setPen(QPen(QColor(Theme.border()), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()


# ── Card widget ───────────────────────────────────────────────────────────────

class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor(Theme.card()))
        pen = QPen(QColor(Theme.border()), 1)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


# ── Launcher pane ─────────────────────────────────────────────────────────────

class LauncherPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._events = []
        self._session_active = False
        self._session_name = ""
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(20)

        # Hero card
        hero = Card()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(8)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lock_label = QLabel()
        self._lock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lock_label.setFixedSize(64, 64)
        self._update_lock_icon()
        hero_layout.addWidget(self._lock_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._hero_title = QLabel("Locus")
        self._hero_title.setFont(serif_font(28))
        self._hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_title.setStyleSheet(f"color: {Theme.text()}; background: transparent;")
        hero_layout.addWidget(self._hero_title)

        self._status_label = QLabel("Ready to focus")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("secondary")
        self._status_label.setFont(mono_font(11))
        self._status_label.setStyleSheet(f"color: {Theme.text_secondary()}; background: transparent; letter-spacing: 0.5px;")
        hero_layout.addWidget(self._status_label)

        outer.addWidget(hero)

        # Session input card
        input_card = Card()
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(20, 16, 20, 16)
        input_layout.setSpacing(10)

        section_lbl = QLabel("WHAT ARE YOU WORKING ON?")
        section_lbl.setObjectName("section_label")
        section_lbl.setFont(mono_font(10, medium=True))
        section_lbl.setStyleSheet(f"color: {Theme.text_secondary()}; background: transparent; letter-spacing: 1.2px;")
        input_layout.addWidget(section_lbl)

        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("Name your session...")
        self._custom_input.returnPressed.connect(self._start_custom)
        input_layout.addWidget(self._custom_input)

        self._start_btn = QPushButton("Start Session")
        self._start_btn.setObjectName("primary")
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self._start_custom)
        input_layout.addWidget(self._start_btn)

        self._end_btn = QPushButton("End Session")
        self._end_btn.setObjectName("secondary_btn")
        self._end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._end_btn.clicked.connect(lambda: _send_command("end_session"))
        self._end_btn.hide()
        input_layout.addWidget(self._end_btn)

        outer.addWidget(input_card)

        # Events section
        or_row = QHBoxLayout()
        line1 = QFrame(); line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet(f"color: {Theme.border()};")
        or_lbl = QLabel("OR")
        or_lbl.setFont(mono_font(10))
        or_lbl.setStyleSheet(f"color: {Theme.text_secondary()}; background: transparent;")
        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet(f"color: {Theme.border()};")
        or_row.addWidget(line1)
        or_row.addWidget(or_lbl)
        or_row.addWidget(line2)
        outer.addLayout(or_row)

        events_lbl = QLabel("UPCOMING ASSIGNMENTS")
        events_lbl.setFont(mono_font(10, medium=True))
        events_lbl.setStyleSheet(f"color: {Theme.text_secondary()}; background: transparent; letter-spacing: 1.2px;")
        outer.addWidget(events_lbl)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.doubleClicked.connect(self._start_selected)
        self._list.setMinimumHeight(120)
        outer.addWidget(self._list)

        start_selected_btn = QPushButton("Start Selected")
        start_selected_btn.setObjectName("secondary_btn")
        start_selected_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_selected_btn.clicked.connect(self._start_selected)
        outer.addWidget(start_selected_btn)

        outer.addStretch()

    def _update_lock_icon(self):
        color = "#E53935" if self._session_active else Theme.ACCENT
        px = _draw_lock_icon(64, self._session_active, color)
        self._lock_label.setPixmap(px)

    def update_state(self, state: dict):
        self._events = state.get("events", [])
        session = state.get("session")
        self._session_active = session is not None
        self._session_name = session.get("display_name", "") if session else ""

        self._update_lock_icon()

        if self._session_active:
            self._hero_title.setText(self._session_name)
            self._status_label.setText("Session active")
            self._start_btn.hide()
            self._end_btn.show()
            self._custom_input.setEnabled(False)
        else:
            self._hero_title.setText("Locus")
            self._status_label.setText("Ready to focus")
            self._start_btn.show()
            self._end_btn.hide()
            self._custom_input.setEnabled(True)

        self._list.clear()
        for ev in self._events:
            label = f"{ev.get('title', '?')}  --  {ev.get('date', '')}"
            if ev.get("start_time"):
                label += f"  {ev['start_time']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ev)
            self._list.addItem(item)

    def _start_custom(self):
        title = self._custom_input.text().strip()
        if title:
            _send_command("start_custom_session", {"title": title})
            self._custom_input.clear()

    def _start_selected(self):
        items = self._list.selectedItems()
        if not items:
            return
        ev = items[0].data(Qt.ItemDataRole.UserRole)
        _send_command("start_session", {
            "title": ev.get("title", ""),
            "date": ev.get("date", ""),
        })


# ── Placeholder panes ─────────────────────────────────────────────────────────

class PlaceholderPane(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel(title)
        t.setFont(serif_font(24))
        t.setStyleSheet(f"color: {Theme.text()}; background: transparent;")
        layout.addWidget(t)

        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {Theme.text_secondary()}; background: transparent; font-size: 13px;")
        layout.addWidget(s)
        layout.addStretch()


# ── Main window ───────────────────────────────────────────────────────────────

class LocusWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Locus")
        self.setMinimumSize(700, 520)
        self.resize(740, 560)
        self.setWindowFlag(Qt.WindowType.Window)

        self._sidebar_visible = True
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.page_changed.connect(self._switch_page)
        root.addWidget(self._sidebar)

        # Content area
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {Theme.surface()};")

        self._launcher = LauncherPane()
        self._stack.addWidget(self._launcher)

        self._settings_pane = PlaceholderPane(
            "Settings",
            "Configure blocking behavior, override code, notification preferences, and appearance."
        )
        self._stack.addWidget(self._settings_pane)

        self._connectors_pane = PlaceholderPane(
            "Connectors",
            "Connect Notion or paste a calendar URL (Google Calendar, Apple Calendar, Schoology) to pull upcoming assignments."
        )
        self._stack.addWidget(self._connectors_pane)

        self._analytics_pane = PlaceholderPane(
            "Analytics",
            "View your focus stats -- total time, sessions, most blocked apps and sites."
        )
        self._stack.addWidget(self._analytics_pane)

        root.addWidget(self._stack)

    def _switch_page(self, idx: int):
        self._stack.setCurrentIndex(idx)

    def update_state(self, state: dict):
        self._launcher.update_state(state)

    def toggle_sidebar(self):
        if self._sidebar_visible:
            self._sidebar.hide()
        else:
            self._sidebar.show()
        self._sidebar_visible = not self._sidebar_visible

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(Theme.surface()))
        p.end()

    def keyPressEvent(self, event):
        # Cmd/Ctrl+\ toggles sidebar
        if event.key() == Qt.Key.Key_Backslash and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.toggle_sidebar()
        super().keyPressEvent(event)


# ── Tray app ──────────────────────────────────────────────────────────────────

class LocusTrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(_draw_tray_icon(False))
        self._app = app
        self._session_active = False
        self._window: LocusWindow = None

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
        menu.addAction("Open Locus").triggered.connect(self._open_window)
        menu.addSeparator()
        self._start_action = menu.addAction("Start Session...")
        self._start_action.triggered.connect(self._open_window)
        self._end_action = menu.addAction("End Session")
        self._end_action.triggered.connect(lambda: _send_command("end_session"))
        self._end_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Refresh Schedule").triggered.connect(lambda: _send_command("refresh"))
        menu.addSeparator()
        menu.addAction("Quit Locus").triggered.connect(self._quit)
        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_window()

    def _open_window(self):
        if self._window is None:
            self._window = LocusWindow()
            self._window.setStyleSheet(Theme.stylesheet())
            # Feed current state
            state = _read_state()
            if state:
                self._window.update_state(state)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_state_changed(self, state: dict):
        session = state.get("session")
        self._session_active = session is not None

        if self._window:
            self._window.update_state(state)

        if self._session_active:
            name = session.get("display_name", "Session")
            self.setIcon(_draw_tray_icon(True))
            self.setToolTip(f"Locus -- {name}")
            self._status_action.setText(f"  {name}")
            self._start_action.setEnabled(False)
            self._end_action.setEnabled(True)
        else:
            self.setIcon(_draw_tray_icon(False))
            self.setToolTip("Locus -- idle")
            self._status_action.setText("Locus -- idle")
            self._start_action.setEnabled(True)
            self._end_action.setEnabled(False)

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

    _load_fonts()

    # Auto-detect system dark mode
    Theme.set_dark(_is_system_dark())
    app.setStyleSheet(Theme.stylesheet())

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
