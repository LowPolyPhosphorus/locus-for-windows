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
    QApplication, QSystemTrayIcon, QMenu, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QScrollArea, QFrame, QSizePolicy,
    QStackedWidget,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QPainter, QPainterPath, QFont,
    QFontDatabase, QPen, QBrush,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QThread, QSize, QRectF, QPointF,
    QPropertyAnimation, QEasingCurve,
)

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH


# ── Theme ─────────────────────────────────────────────────────────────────────

ACCENT        = "#E8A020"
ACCENT_HOVER  = "#D4901A"

# Tag colors matching the Swift app
TAG_COLORS = {
    "pre-ap":   ("#7C3AED", "#EDE9FE"),
    "ap":       ("#7C3AED", "#EDE9FE"),
    "biology":  ("#059669", "#D1FAE5"),
    "math":     ("#2563EB", "#DBEAFE"),
    "english":  ("#DC2626", "#FEE2E2"),
    "history":  ("#D97706", "#FEF3C7"),
    "spanish":  ("#DB2777", "#FCE7F3"),
    "science":  ("#059669", "#D1FAE5"),
    "csp":      ("#2563EB", "#DBEAFE"),
    "physics":  ("#7C3AED", "#EDE9FE"),
    "chem":     ("#059669", "#D1FAE5"),
    "default":  ("#6B7280", "#F3F4F6"),
}

_DARK = False

def _init_theme():
    global SURFACE, CARD, BORDER, TEXT, TEXT_SEC, TEXT_LIGHT, ACCENT_MUTED
    global SIDEBAR_BG, SETTINGS_SIDEBAR_BG
    if _DARK:
        SURFACE           = "#151209"
        CARD              = "#201c12"
        BORDER            = "#FFFFFF14"
        TEXT              = "#F0E6CC"
        TEXT_SEC          = "#8A7A5A"
        TEXT_LIGHT        = "#5A4A2A"
        ACCENT_MUTED      = "#3A2E10"
        SIDEBAR_BG        = "#1a1610"
        SETTINGS_SIDEBAR_BG = "#201c12"
    else:
        SURFACE           = "#FDFAF5"
        CARD              = "#F7F2E8"
        BORDER            = "#E8DFC8"
        TEXT              = "#1A1409"
        TEXT_SEC          = "#7A6A4A"
        TEXT_LIGHT        = "#B0A080"
        ACCENT_MUTED      = "#FDF3E0"
        SIDEBAR_BG        = "#F7F2E8"
        SETTINGS_SIDEBAR_BG = "#F0EBD8"

_init_theme()

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

def set_dark_mode(dark: bool):
    global _DARK
    _DARK = dark
    _init_theme()
    _rebuild_stylesheet()

# Forward declaration -- rebuilt after stylesheet is defined
_APP_REF = None

def _rebuild_stylesheet():
    if _APP_REF:
        _APP_REF.setStyleSheet(_make_stylesheet())


def _tag_colors(class_name: str):
    key = class_name.lower().strip()
    for k, v in TAG_COLORS.items():
        if k in key:
            return v
    return TAG_COLORS["default"]


def _make_stylesheet() -> str:
    return f"""
QWidget {{
    background-color: {SURFACE};
    color: {TEXT};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}}
QLabel {{ background: transparent; color: {TEXT}; border: none; }}
QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
    font-size: 13px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {SURFACE}; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 5px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 2px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 5px;
    color: {TEXT};
}}
QListWidget::item:selected {{
    background: {ACCENT_MUTED};
    border-color: {ACCENT};
    color: {TEXT};
}}
QListWidget::item:hover:!selected {{ border-color: {ACCENT}; }}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 16px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: {ACCENT_MUTED}; color: {TEXT}; }}
QMenu::separator {{ background: {BORDER}; height: 1px; margin: 4px 10px; }}
"""

STYLESHEET = _make_stylesheet()


# ── Font helpers ──────────────────────────────────────────────────────────────

def _load_fonts():
    # Try assets/fonts first (correct location), fall back to FocusLockApp/Fonts
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "assets", "fonts"),
        os.path.join(base_dir, "FocusLockApp", "Fonts"),
    ]
    for base in candidates:
        if os.path.isdir(base):
            for fname in ["InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf",
                          "DMMono-Regular.ttf", "DMMono-Medium.ttf"]:
                path = os.path.join(base, fname)
                if os.path.exists(path):
                    fid = QFontDatabase.addApplicationFont(path)
                    if fid >= 0:
                        families = QFontDatabase.applicationFontFamilies(fid)
                        print(f"[Locus] Loaded font: {fname} -> {families}")
            break


def serif(size: int) -> QFont:
    f = QFont("Instrument Serif", size)
    return f


def mono(size: int, medium: bool = False) -> QFont:
    f = QFont("DM Mono" if not medium else "DM Mono Medium", size)
    return f


# ── Icon drawing ──────────────────────────────────────────────────────────────

def _lock_pixmap(size: int, locked: bool, color: str) -> QPixmap:
    """Outline-style lock icon -- stroked shackle and body, no fill."""
    stroke = max(2.0, size * 0.09)
    half = stroke / 2
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)

    pen = QPen(c, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Shackle -- keep inside pixmap bounds with half-stroke padding
    sw = size * 0.46
    sh = size * 0.40
    sx = (size - sw) / 2
    sy = half + 1  # ensure top of arc is never clipped
    if locked:
        p.drawArc(QRectF(sx, sy, sw, sh), 0, 180 * 16)
    else:
        p.drawArc(QRectF(sx, sy, sw, sh * 0.9), 25 * 16, 130 * 16)

    # Body -- outline only, no fill
    bw = size * 0.72
    bh = size * 0.44
    bx = (size - bw) / 2
    by = size * 0.50
    path = QPainterPath()
    path.addRoundedRect(bx + half, by, bw - stroke, bh - half, size * 0.09, size * 0.09)
    p.drawPath(path)

    p.end()
    return px


def _tray_pixmap(active: bool) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = "#E53935" if active else "#7A6A4A"
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.end()
    return QIcon(px)


def _nav_icon(name: str, size: int, color: str) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c, 1.6, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = size * 0.14

    import math

    if name == "start":
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.moveTo(m + size*0.12, m)
        path.lineTo(m + size*0.12, size - m)
        path.lineTo(size - m, size / 2)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "connectors":
        # Two nodes connected by a line -- plug/connection icon
        r = size * 0.13
        p.setBrush(QBrush(c))
        p.drawEllipse(QRectF(m, size/2 - r, r*2, r*2))
        p.drawEllipse(QRectF(size - m - r*2, size/2 - r, r*2, r*2))
        p.setPen(pen)
        p.drawLine(QPointF(m + r*2, size/2), QPointF(size - m - r*2, size/2))
        # tick marks
        for xf in [0.35, 0.5, 0.65]:
            x = size * xf
            p.drawLine(QPointF(x, size/2 - size*0.15), QPointF(x, size/2 + size*0.15))

    elif name == "analytics":
        bars = [0.45, 0.75, 0.55, 0.9]
        bw = (size - m*2) / (len(bars) * 2 - 1)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        for i, frac in enumerate(bars):
            bx = m + i * bw * 2
            bh2 = (size - m*2) * frac
            by = size - m - bh2
            path = QPainterPath()
            path.addRoundedRect(bx, by, bw, bh2, 1.5, 1.5)
            p.drawPath(path)

    elif name == "settings":
        # Gear
        outer_r = size * 0.36
        inner_r = size * 0.22
        teeth = 8
        cx2, cy2 = size / 2, size / 2
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        gear = QPainterPath()
        for i in range(teeth * 2):
            angle = i * math.pi / teeth
            r = outer_r if i % 2 == 0 else outer_r * 0.78
            gear.lineTo(cx2 + math.cos(angle) * r, cy2 + math.sin(angle) * r)
        gear.closeSubpath()
        p.drawPath(gear)
        # Center hole
        hole = QPainterPath()
        hole.addEllipse(QRectF(cx2 - inner_r, cy2 - inner_r, inner_r*2, inner_r*2))
        p.setBrush(QBrush(QColor(SURFACE)))
        p.drawPath(hole)

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
        print(f"[Locus UI] Command error: {e}")


# ── Dialog queue drainer ──────────────────────────────────────────────────────

def _drain_dialog_queue():
    from focuslock.dialogs import _REQUEST_QUEUE
    try:
        while True:
            fn = _REQUEST_QUEUE.get_nowait()
            fn()
    except Exception:
        pass


# ── Daemon launcher ───────────────────────────────────────────────────────────

def _start_daemon_thread():
    from focuslock.app import main as daemon_main

    def _run():
        try:
            daemon_main()
        except SystemExit:
            pass
        except Exception as e:
            print(f"[Locus] Daemon crashed: {e}")

    threading.Thread(target=_run, daemon=True, name="locusd").start()


# ── Browser debug setup ───────────────────────────────────────────────────────

def _browser_debug_is_active() -> bool:
    try:
        import requests
        return requests.get("http://localhost:9222/json/version", timeout=1).status_code == 200
    except Exception:
        return False


def _setup_browser_debug_if_needed():
    if _browser_debug_is_active():
        return
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_browser_debug.py")
    if not os.path.exists(script):
        return
    import ctypes
    threading.Thread(
        target=lambda: ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}"', None, 1),
        daemon=True,
    ).start()


# ── State watcher ─────────────────────────────────────────────────────────────

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


# ── Sidebar nav row ───────────────────────────────────────────────────────────

ICON_SIZE = 18
SIDEBAR_EXPANDED = 200
SIDEBAR_COLLAPSED = 52


class NavRow(QPushButton):
    def __init__(self, label: str, icon_name: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon_name = icon_name
        self._selected = False
        self._collapsed = False
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh()

    def set_selected(self, v: bool):
        self._selected = v
        self._refresh()

    def set_collapsed(self, v: bool):
        self._collapsed = v
        self._refresh()

    def _refresh(self):
        bg = ACCENT_MUTED if self._selected else "transparent"
        fw = "600" if self._selected else "400"
        if self._collapsed:
            self.setText("")
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {bg};
                    border-radius: 8px;
                    border: none;
                    padding: 0;
                }}
                QPushButton:hover {{ background: #F0E8D0; }}
            """)
        else:
            self.setText(self._label)
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {bg};
                    color: {TEXT};
                    border-radius: 8px;
                    border: none;
                    text-align: left;
                    padding-left: {ICON_SIZE + 18}px;
                    font-size: 13px;
                    font-weight: {fw};
                }}
                QPushButton:hover {{ background: {'#F0E8D0' if not self._selected else ACCENT_MUTED}; }}
            """)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = ACCENT if self._selected else TEXT_SEC
        icon_px = _nav_icon(self._icon_name, ICON_SIZE, color)
        # When collapsed or collapsing: center the icon
        # When expanded: fixed 10px from left
        if self._collapsed:
            x = (self.width() - ICON_SIZE) // 2
        else:
            x = 10
        y = (self.height() - ICON_SIZE) // 2
        p.drawPixmap(x, y, icon_px)
        p.end()


class _HamburgerButton(QPushButton):
    """Three-line hamburger button for sidebar toggle."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{ background: {BORDER}; }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(TEXT_SEC), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx = self.width() // 2
        w = 14
        for y in [12, 18, 24]:
            p.drawLine(cx - w//2, y, cx + w//2, y)
        p.end()


# ── Sidebar ───────────────────────────────────────────────────────────────────

# Order matches the screenshot: Start, Connectors, Analytics, Settings
PAGES = [
    ("Start",      "start",      0),
    ("Connectors", "connectors", 1),
    ("Analytics",  "analytics",  2),
    ("Settings",   "settings",   3),
]


class Sidebar(QWidget):
    page_changed = pyqtSignal(int)
    sidebar_toggled = pyqtSignal(bool)  # True = collapsing, False = expanding

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._current = 0
        self._rows = []
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(180)
        self._anim2.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(0)

        # Header -- just lock icon + title, no arrow
        hdr = QWidget()
        hdr.setFixedHeight(62)
        hdr.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 4, 0)
        hl.setSpacing(8)

        self._lock_lbl = QLabel()
        self._lock_lbl.setPixmap(_lock_pixmap(22, True, ACCENT))
        self._lock_lbl.setFixedSize(22, 22)
        hl.addWidget(self._lock_lbl)

        self._title_lbl = QLabel("Locus")
        self._title_lbl.setFont(serif(20))
        self._title_lbl.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 20px; color: {TEXT}; background: transparent;")
        hl.addWidget(self._title_lbl)
        hl.addStretch()
        layout.addWidget(hdr)

        for label, icon_name, idx in PAGES:
            row = NavRow(label, icon_name)
            row.clicked.connect(lambda _, i=idx: self._select(i))
            self._rows.append(row)
            layout.addWidget(row)
            layout.addSpacing(2)

        layout.addStretch()

        # Hamburger toggle at the bottom
        self._hamburger = _HamburgerButton()
        self._hamburger.clicked.connect(self.toggle_collapse)
        layout.addWidget(self._hamburger)

        self._rows[0].set_selected(True)

    def toggle_collapse(self):
        self._collapsed = not self._collapsed
        target = SIDEBAR_COLLAPSED if self._collapsed else SIDEBAR_EXPANDED

        self.sidebar_toggled.emit(self._collapsed)

        for anim in (self._anim, self._anim2):
            anim.stop()
            anim.setStartValue(self.width())
            anim.setEndValue(target)
            anim.start()

        if self._collapsed:
            # Hide text title only -- lock icon stays visible
            self._title_lbl.hide()
        else:
            self._title_lbl.show()

        for row in self._rows:
            row.set_collapsed(self._collapsed)

    def _select(self, idx: int):
        for row in self._rows:
            row.set_selected(False)
        self._rows[idx].set_selected(True)
        self._current = idx
        self.page_changed.emit(idx)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SIDEBAR_BG))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()


# ── Event item widget (with colored class tag) ────────────────────────────────

class EventItem(QWidget):
    def __init__(self, ev: dict, parent=None):
        super().__init__(parent)
        self._ev = ev
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel(ev.get("title", "?"))
        title.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500; background: transparent;")
        layout.addWidget(title)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.setContentsMargins(0, 0, 0, 0)

        class_name = ev.get("class_name", "")
        if class_name:
            fg, bg = _tag_colors(class_name)
            tag = QLabel(class_name.upper())
            tag.setStyleSheet(f"""
                color: {fg};
                background: {bg};
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 0.5px;
            """)
            bottom.addWidget(tag)

        if ev.get("start_time"):
            time_lbl = QLabel(ev["start_time"])
            time_lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; background: transparent;")
            bottom.addWidget(time_lbl)

        bottom.addStretch()
        layout.addLayout(bottom)


# ── Launcher pane ─────────────────────────────────────────────────────────────

class LauncherPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._events = []
        self._session_active = False
        self._session_info = None
        self._build()

    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        self._scroll_inner = inner
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Lock icon circle
        self._icon_circle = QLabel()
        self._icon_circle.setFixedSize(96, 96)
        self._icon_circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_icon()
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(self._icon_circle)
        icon_row.addStretch()
        layout.addLayout(icon_row)
        layout.addSpacing(14)

        # Serif title
        self._title_lbl = QLabel("Locus")
        self._title_lbl.setFont(serif(38))
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 38px; color: {TEXT}; background: transparent;")
        layout.addWidget(self._title_lbl)
        layout.addSpacing(4)

        # Status
        self._status_lbl = QLabel("Ready to focus")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent; font-size: 14px;")
        layout.addWidget(self._status_lbl)
        layout.addSpacing(32)

        # Session input area -- left aligned, max width, centered in column
        input_area = QWidget()
        input_area.setMaximumWidth(480)
        input_layout = QVBoxLayout(input_area)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        wao_lbl = QLabel("WHAT ARE YOU WORKING ON?")
        wao_lbl.setFont(mono(10, medium=True))
        wao_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        wao_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent; letter-spacing: 1.2px;")
        input_layout.addWidget(wao_lbl)

        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("e.g. Write essay intro")
        self._custom_input.setFixedHeight(40)
        self._custom_input.returnPressed.connect(self._start_custom)
        input_layout.addWidget(self._custom_input)
        input_layout.addSpacing(2)

        self._start_btn = QPushButton("  Start Session")
        self._start_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.setFixedHeight(44)
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                color: #1A1100;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 600;
                padding: 0 20px;
                text-align: center;
            }}
            QPushButton:hover {{ background: {ACCENT_HOVER}; }}
            QPushButton:pressed {{ background: #BF811A; }}
        """)
        self._start_btn.clicked.connect(self._start_custom)
        self._start_btn.setIcon(QIcon(_nav_icon("start", 14, "#1A1100")))
        self._start_btn.setIconSize(QSize(14, 14))
        input_layout.addWidget(self._start_btn)

        self._end_btn = QPushButton("End Session")
        self._end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._end_btn.setFixedHeight(44)
        self._end_btn.setStyleSheet(f"""
            QPushButton {{
                background: #E53935;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #C62828; }}
            QPushButton:pressed {{ background: #B71C1C; }}
        """)
        self._end_btn.clicked.connect(lambda: _send_command("end_session"))
        self._end_btn.hide()
        input_layout.addWidget(self._end_btn)

        center_wrap = QHBoxLayout()
        center_wrap.addStretch(1)
        center_wrap.addWidget(input_area, 0)
        center_wrap.addStretch(1)
        layout.addLayout(center_wrap)
        layout.addSpacing(24)

        # OR divider
        or_row = QHBoxLayout()
        l1 = QFrame(); l1.setFrameShape(QFrame.Shape.HLine)
        l1.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
        or_lbl = QLabel("OR")
        or_lbl.setFont(mono(9))
        or_lbl.setFixedWidth(28)
        or_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_lbl.setStyleSheet(f"color: {TEXT_LIGHT}; background: transparent; letter-spacing: 1px;")
        l2 = QFrame(); l2.setFrameShape(QFrame.Shape.HLine)
        l2.setStyleSheet(f"background: {BORDER}; max-height: 1px; border: none;")
        or_row.addWidget(l1); or_row.addWidget(or_lbl); or_row.addWidget(l2)

        or_wrap = QHBoxLayout()
        or_wrap.addStretch(1)
        or_w = QWidget(); or_w.setMaximumWidth(480)
        or_w.setLayout(or_row)
        or_wrap.addWidget(or_w, 0)
        or_wrap.addStretch(1)
        layout.addLayout(or_wrap)
        layout.addSpacing(20)

        # Events section
        events_wrap = QHBoxLayout()
        events_wrap.addStretch(1)
        self._events_widget = QWidget()
        self._events_widget.setMaximumWidth(480)
        self._events_layout = QVBoxLayout(self._events_widget)
        self._events_layout.setContentsMargins(0, 0, 0, 0)
        self._events_layout.setSpacing(0)
        events_wrap.addWidget(self._events_widget, 0)
        events_wrap.addStretch(1)
        layout.addLayout(events_wrap)

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _update_icon(self):
        color = "#E53935" if self._session_active else ACCENT
        circle_bg = "#FFEBEE" if self._session_active else ACCENT_MUTED

        size = 96
        lock_size = 44  # lock drawn inside circle with breathing room

        final = QPixmap(size, size)
        final.fill(Qt.GlobalColor.transparent)
        p = QPainter(final)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Circle background
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, size, size))
        p.fillPath(path, QBrush(QColor(circle_bg)))

        # Lock centered inside circle
        lock_px = _lock_pixmap(lock_size, self._session_active, color)
        lx = (size - lock_size) // 2
        ly = (size - lock_size) // 2
        p.drawPixmap(lx, ly, lock_px)
        p.end()

        self._icon_circle.setPixmap(final)

    def _populate_events(self):
        # Clear
        while self._events_layout.count():
            item = self._events_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._events:
            no_ev = QLabel("No upcoming assignments")
            no_ev.setStyleSheet(f"color: {TEXT_LIGHT}; background: transparent; font-size: 12px;")
            no_ev.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._events_layout.addWidget(no_ev)
            return

        # Group by date
        from collections import OrderedDict
        import datetime
        today = datetime.date.today().isoformat()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

        groups = OrderedDict()
        source_shown = set()

        for ev in self._events:
            date = ev.get("date", "")
            source = ev.get("source", "notion")

            # Section header for source
            source_key = f"source_{source}"
            if source_key not in source_shown:
                source_shown.add(source_key)
                src_lbl = QLabel("FROM NOTION" if source == "notion" else "FROM CALENDAR")
                src_lbl.setFont(mono(9, medium=True))
                src_lbl.setStyleSheet(f"color: {TEXT_LIGHT}; background: transparent; letter-spacing: 1px; margin-bottom: 6px;")
                self._events_layout.addWidget(src_lbl)

            if date not in groups:
                groups[date] = []
            groups[date].append(ev)

        for date, evs in groups.items():
            # Date header
            if date == today:
                date_str = "TODAY"
            elif date == tomorrow:
                date_str = "TOMORROW"
            else:
                try:
                    import datetime
                    d = datetime.date.fromisoformat(date)
                    date_str = d.strftime("%A, %b %-d").upper()
                except Exception:
                    date_str = date

            date_lbl = QLabel(date_str)
            date_lbl.setFont(mono(9, medium=True))
            date_lbl.setStyleSheet(f"color: {TEXT_SEC}; background: transparent; letter-spacing: 1px; margin-top: 10px; margin-bottom: 4px;")
            self._events_layout.addWidget(date_lbl)

            for ev in evs:
                # Card container
                card = QFrame()
                card.setStyleSheet(f"""
                    QFrame {{
                        background: {CARD};
                        border: 1px solid {BORDER};
                        border-radius: 10px;
                    }}
                """)
                card.setCursor(Qt.CursorShape.PointingHandCursor)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(12, 10, 12, 10)
                card_layout.setSpacing(4)

                title_lbl = QLabel(ev.get("title", "?"))
                title_lbl.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500; background: transparent; border: none;")
                card_layout.addWidget(title_lbl)

                bottom = QHBoxLayout()
                bottom.setSpacing(6)
                bottom.setContentsMargins(0, 0, 0, 0)

                class_name = ev.get("class_name", "")
                if class_name:
                    fg, bg = _tag_colors(class_name)
                    tag = QLabel(class_name.upper())
                    tag.setStyleSheet(f"""
                        color: {fg};
                        background: {bg};
                        border-radius: 4px;
                        padding: 1px 6px;
                        font-size: 10px;
                        font-weight: 600;
                        letter-spacing: 0.5px;
                        border: none;
                    """)
                    bottom.addWidget(tag)

                if ev.get("start_time"):
                    t_lbl = QLabel(ev["start_time"])
                    t_lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; background: transparent; border: none;")
                    bottom.addWidget(t_lbl)

                bottom.addStretch()
                card_layout.addLayout(bottom)

                # Click to start
                card.mousePressEvent = lambda e, ev=ev: _send_command("start_session", {
                    "title": ev.get("title", ""),
                    "date": ev.get("date", ""),
                })
                self._events_layout.addWidget(card)
                self._events_layout.addSpacing(5)

    def update_state(self, state: dict):
        self._events = state.get("events", [])
        self._session_info = state.get("session")
        self._session_active = self._session_info is not None

        self._update_icon()

        if self._session_active:
            name = self._session_info.get("display_name", "Session")
            self._title_lbl.setText(name)
            self._status_lbl.setText("Session active")
            self._start_btn.hide()
            self._end_btn.show()
            self._custom_input.setEnabled(False)
        else:
            self._title_lbl.setText("Locus")
            self._status_lbl.setText("Ready to focus")
            self._start_btn.show()
            self._end_btn.hide()
            self._custom_input.setEnabled(True)

        self._populate_events()

    def set_sidebar_width(self, sidebar_w: int):
        pass  # intentionally empty -- content stays centered, sidebar draws on top

    def _start_custom(self):
        title = self._custom_input.text().strip()
        if title:
            _send_command("start_custom_session", {"title": title})
            self._custom_input.clear()


# ── Placeholder panes ─────────────────────────────────────────────────────────

class PlaceholderPane(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel(title)
        t.setFont(serif(28))
        t.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        layout.addSpacing(6)

        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {TEXT_SEC}; background: transparent; font-size: 13px;")
        layout.addWidget(s)
        layout.addStretch()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
        p.end()


# ── Settings pane ─────────────────────────────────────────────────────────────

SETTINGS_PAGES = ["General", "Blocking", "Allowlists", "Notifications", "Advanced"]

def _settings_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("DM Mono", 9))
    lbl.setStyleSheet(f"color: {TEXT_LIGHT}; background: transparent; letter-spacing: 1px;")
    return lbl

def _settings_row_label(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500; background: transparent;")
    layout.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; background: transparent;")
        layout.addWidget(s)
    return w

def _settings_card() -> QFrame:
    card = QFrame()
    card.setStyleSheet(f"""
        QFrame {{
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
        QFrame QLineEdit {{
            background: {SURFACE};
            border: none;
            border-radius: 6px;
            padding: 4px 8px;
            color: {TEXT};
            font-size: 13px;
        }}
        QFrame QLineEdit:focus {{
            border: 1px solid {ACCENT};
        }}
        QFrame QLabel {{
            border: none;
            background: transparent;
        }}
        QFrame QWidget {{
            background: transparent;
            border: none;
        }}
    """)
    return card

def _save_btn() -> QPushButton:
    btn = QPushButton("Save Changes")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(40)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {ACCENT};
            color: #1A1100;
            border: none;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            padding: 0 24px;
        }}
        QPushButton:hover {{ background: {ACCENT_HOVER}; }}
        QPushButton:pressed {{ background: #BF811A; }}
    """)
    return btn


class SettingsPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self._build()
        self._load()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sub-sidebar
        sub = QWidget()
        sub.setFixedWidth(180)
        sub.setStyleSheet(f"background: {SETTINGS_SIDEBAR_BG}; border-right: 1px solid {BORDER};")
        sub_layout = QVBoxLayout(sub)
        sub_layout.setContentsMargins(12, 20, 12, 20)
        sub_layout.setSpacing(2)

        sec_lbl = _settings_label("SETTINGS")
        sec_lbl.setContentsMargins(4, 0, 0, 8)
        sub_layout.addWidget(sec_lbl)

        self._sub_btns = []
        for i, name in enumerate(SETTINGS_PAGES):
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            self._sub_btns.append(btn)
            sub_layout.addWidget(btn)
        sub_layout.addStretch()
        root.addWidget(sub)

        # Content stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {SURFACE};")
        self._stack.addWidget(self._build_general())
        self._stack.addWidget(self._build_blocking())
        self._stack.addWidget(self._build_allowlists())
        self._stack.addWidget(self._build_notifications())
        self._stack.addWidget(self._build_advanced())
        root.addWidget(self._stack)

        self._select(0)

    def _select(self, idx: int):
        self._current = idx
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._sub_btns):
            if i == idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {ACCENT_MUTED};
                        color: {TEXT};
                        border: none;
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 12px;
                        font-size: 13px;
                        font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {TEXT};
                        border: none;
                        border-radius: 8px;
                        text-align: left;
                        padding-left: 12px;
                        font-size: 13px;
                        font-weight: 400;
                    }}
                    QPushButton:hover {{ background: {CARD}; }}
                """)

    # ── General ───────────────────────────────────────────────────────────────

    def _build_general(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel("General")
        t.setFont(serif(28))
        t.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 28px; color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        s = QLabel("Appearance and global preferences.")
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; background: transparent;")
        layout.addWidget(s)
        layout.addSpacing(4)

        # Appearance card
        card = _settings_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(12)
        cl.addWidget(_settings_label("APPEARANCE"))

        # System / Light / Dark toggle
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        self._appearance_btns = {}
        for opt in ["System", "Light", "Dark"]:
            btn = QPushButton(opt)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, o=opt: self._set_appearance(o))
            self._appearance_btns[opt] = btn
            toggle_row.addWidget(btn)
        self._update_appearance_toggle("System")
        cl.addLayout(toggle_row)

        # Accent colour row
        accent_row = QFrame()
        accent_row.setStyleSheet(f"background: {SURFACE}; border-radius: 8px; border: none;")
        ar = QHBoxLayout(accent_row)
        ar.setContentsMargins(12, 10, 12, 10)
        swatch = QLabel()
        swatch.setFixedSize(32, 32)
        swatch.setStyleSheet(f"background: {ACCENT}; border-radius: 6px; border: none;")
        ar.addWidget(swatch)
        ar.addWidget(_settings_row_label("Accent colour", "Warm amber -- fixed"))
        ar.addStretch()
        cl.addWidget(accent_row)
        layout.addWidget(card)

        btn = _save_btn()
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()
        w.setWidget(inner)
        return w

    def _set_appearance(self, opt: str):
        self._update_appearance_toggle(opt)
        if opt == "Dark":
            set_dark_mode(True)
        elif opt == "Light":
            set_dark_mode(False)
        else:  # System
            set_dark_mode(_is_system_dark())

    def _update_appearance_toggle(self, active: str):
        for opt, btn in self._appearance_btns.items():
            if opt == active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {SURFACE};
                        color: {TEXT};
                        border: 1px solid {BORDER};
                        border-radius: 6px;
                        font-size: 13px;
                        font-weight: 600;
                        padding: 0 16px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {CARD};
                        color: {TEXT_SEC};
                        border: 1px solid {BORDER};
                        border-radius: 6px;
                        font-size: 13px;
                        padding: 0 16px;
                    }}
                    QPushButton:hover {{ background: {SURFACE}; color: {TEXT}; }}
                """)

    # ── Blocking ──────────────────────────────────────────────────────────────

    def _build_blocking(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel("Blocking")
        t.setFont(serif(28))
        t.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 28px; color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        s = QLabel("Timing, polling, and AI strictness.")
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; background: transparent;")
        layout.addWidget(s)
        layout.addSpacing(4)

        card = _settings_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(0)

        fields = [
            ("temporary_allow_minutes", "Temporary Allow Duration",
             "How long a temporary override lasts before the site/app is re-blocked.", "min"),
            ("schedule_refresh_minutes", "Schedule Refresh",
             "How often Notion events are re-fetched in the background.", "min"),
            ("url_poll_interval_seconds", "URL Poll Interval",
             "How often browser tabs are checked for blocked domains.", "s"),
            ("app_poll_interval_seconds", "App Poll Interval",
             "How often running apps are checked against the blocklist.", "s"),
        ]

        self._blocking_inputs = {}
        for i, (key, title, subtitle, unit) in enumerate(fields):
            if i > 0:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setFixedHeight(1)
                div.setStyleSheet(f"background: {BORDER}; border: none;")
                cl.addWidget(div)

            row = QHBoxLayout()
            row.setContentsMargins(0, 12, 0, 12)
            row.addWidget(_settings_row_label(title, subtitle), 1)
            inp = QLineEdit()
            inp.setFixedWidth(70)
            inp.setFixedHeight(32)
            inp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inp.setPlaceholderText("--")
            self._blocking_inputs[key] = inp
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet(f"color: {TEXT_SEC}; font-size: 12px; background: transparent;")
            row.addWidget(inp)
            row.addWidget(unit_lbl)
            cl.addLayout(row)

        # Override code row
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {BORDER}; border: none;")
        cl.addWidget(div)
        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 12)
        row.addWidget(_settings_row_label("Override Code", 'Typed to bypass the lock. Default is "bob".'), 1)
        self._override_input = QLineEdit()
        self._override_input.setFixedWidth(120)
        self._override_input.setFixedHeight(32)
        self._override_input.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self._override_input)
        cl.addLayout(row)

        # AI Harshness row
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {BORDER}; border: none;")
        cl.addWidget(div2)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 12, 0, 12)
        row2.addWidget(_settings_row_label("AI Harshness", "How strictly the AI judges reasons."), 1)
        toggle2 = QHBoxLayout()
        toggle2.setSpacing(0)
        self._harshness_btns = {}
        for opt in ["Lenient", "Standard", "Strict"]:
            btn = QPushButton(opt)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, o=opt: self._set_harshness(o))
            self._harshness_btns[opt] = btn
            toggle2.addWidget(btn)
        self._update_harshness_toggle("Standard")
        row2.addLayout(toggle2)
        cl.addLayout(row2)

        layout.addWidget(card)
        btn = _save_btn()
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()
        w.setWidget(inner)
        return w

    def _set_harshness(self, opt: str):
        self._update_harshness_toggle(opt)

    def _update_harshness_toggle(self, active: str):
        for opt, btn in self._harshness_btns.items():
            if opt == active:
                btn.setStyleSheet(f"""QPushButton {{
                    background: {SURFACE}; color: {TEXT};
                    border: 1px solid {BORDER}; border-radius: 6px;
                    font-size: 12px; font-weight: 600; padding: 0 12px;
                }}""")
            else:
                btn.setStyleSheet(f"""QPushButton {{
                    background: {CARD}; color: {TEXT_SEC};
                    border: 1px solid {BORDER}; border-radius: 6px;
                    font-size: 12px; padding: 0 12px;
                }}
                QPushButton:hover {{ background: {SURFACE}; color: {TEXT}; }}""")

    # ── Allowlists ────────────────────────────────────────────────────────────

    def _build_allowlists(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel("Allowlists")
        t.setFont(serif(28))
        t.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 28px; color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        s = QLabel("Always-allowed apps and domains, regardless of session.")
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; background: transparent;")
        layout.addWidget(s)
        layout.addSpacing(4)

        # Apps card
        apps_card = _settings_card()
        al = QVBoxLayout(apps_card)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(10)
        al.addWidget(_settings_label("ALWAYS-ALLOWED APPS"))
        sub = QLabel("These apps are never blocked even outside the session whitelist.")
        sub.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; background: transparent;")
        sub.setWordWrap(True)
        al.addWidget(sub)
        self._apps_tags = _TagEditor()
        al.addWidget(self._apps_tags)
        layout.addWidget(apps_card)

        # Domains card
        dom_card = _settings_card()
        dl = QVBoxLayout(dom_card)
        dl.setContentsMargins(20, 16, 20, 16)
        dl.setSpacing(10)
        dl.addWidget(_settings_label("ALWAYS-ALLOWED DOMAINS"))
        sub2 = QLabel("These domains are never blocked in the browser.")
        sub2.setStyleSheet(f"color: {TEXT_SEC}; font-size: 11px; background: transparent;")
        sub2.setWordWrap(True)
        dl.addWidget(sub2)
        self._domains_tags = _TagEditor()
        dl.addWidget(self._domains_tags)
        layout.addWidget(dom_card)

        btn = _save_btn()
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()
        w.setWidget(inner)
        return w

    # ── Notifications ─────────────────────────────────────────────────────────

    def _build_notifications(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel("Notifications")
        t.setFont(serif(28))
        t.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 28px; color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        s = QLabel("Control what notifications Locus sends.")
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; background: transparent;")
        layout.addWidget(s)
        layout.addSpacing(4)

        card = _settings_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(0)

        self._notif_toggles = {}
        rows = [
            ("show_notifications", "Show Notifications",
             'Displays banners like "Evaluating your reason..." and "Override accepted".'),
            ("play_sound_on_block", "Play Sound on Block",
             "Plays a system sound when a block is triggered."),
        ]
        for i, (key, title, subtitle) in enumerate(rows):
            if i > 0:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setFixedHeight(1)
                div.setStyleSheet(f"background: {BORDER}; border: none;")
                cl.addWidget(div)
            row = QHBoxLayout()
            row.setContentsMargins(0, 12, 0, 12)
            row.addWidget(_settings_row_label(title, subtitle), 1)
            toggle = _Toggle()
            self._notif_toggles[key] = toggle
            row.addWidget(toggle)
            cl.addLayout(row)

        layout.addWidget(card)
        btn = _save_btn()
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()
        w.setWidget(inner)
        return w

    # ── Advanced ──────────────────────────────────────────────────────────────

    def _build_advanced(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = QLabel("Advanced")
        t.setFont(serif(28))
        t.setStyleSheet(f"font-family: 'Instrument Serif'; font-size: 28px; color: {TEXT}; background: transparent;")
        layout.addWidget(t)
        s = QLabel("AI prompt overrides, polling, and debug options.")
        s.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px; background: transparent;")
        layout.addWidget(s)
        layout.addSpacing(4)

        # Debug logging toggle
        card = _settings_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        row = QHBoxLayout()
        row.addWidget(_settings_row_label("Debug Logging",
                      "Enables verbose print output in the Python backend."), 1)
        self._debug_toggle = _Toggle()
        row.addWidget(self._debug_toggle)
        cl.addLayout(row)
        layout.addWidget(card)

        # Prompt overrides
        prompts = [
            ("evaluate_reason", "Evaluate Reason Prompt",
             "Used when the user submits a justification for a blocked site/app.",
             "Placeholders: {session_name}, {subject_type}, {subject}, {reason}"),
            ("evaluate_site_relevance", "Evaluate Site Relevance Prompt",
             "Used to pre-screen whether a blocked domain is obviously relevant.",
             "Placeholders: {session_name}, {domain}, {title_hint}"),
        ]
        self._prompt_inputs = {}
        for key, title, subtitle, placeholder in prompts:
            pcard = _settings_card()
            pl = QVBoxLayout(pcard)
            pl.setContentsMargins(20, 16, 20, 16)
            pl.setSpacing(8)
            pl.addWidget(_settings_row_label(title, subtitle))
            hint = QLabel(placeholder)
            hint.setStyleSheet(f"color: {TEXT_LIGHT}; font-size: 10px; font-family: 'DM Mono'; background: transparent;")
            pl.addWidget(hint)
            from PyQt6.QtWidgets import QTextEdit
            ta = QTextEdit()
            ta.setFixedHeight(90)
            ta.setPlaceholderText("Leave empty to use the default prompt.")
            ta.setStyleSheet(f"""
                QTextEdit {{
                    background: {SURFACE};
                    border: 1px solid {BORDER};
                    border-radius: 8px;
                    padding: 8px;
                    color: {TEXT};
                    font-size: 12px;
                    font-family: 'DM Mono', 'Consolas', monospace;
                }}
                QTextEdit:focus {{ border-color: {ACCENT}; }}
            """)
            self._prompt_inputs[key] = ta
            pl.addWidget(ta)
            layout.addWidget(pcard)

        btn = _save_btn()
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()
        w.setWidget(inner)
        return w

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        for key, inp in self._blocking_inputs.items():
            val = cfg.get(key, "")
            inp.setText(str(val) if val != "" else "")

        self._override_input.setText(cfg.get("override_code", ""))

        harshness = cfg.get("harshness", "Standard")
        if harshness in self._harshness_btns:
            self._update_harshness_toggle(harshness)

        self._apps_tags.set_items(cfg.get("always_allowed_apps", []))
        self._domains_tags.set_items(cfg.get("always_allowed_domains", []))

        for key, toggle in self._notif_toggles.items():
            toggle.set_checked(bool(cfg.get(key, False)))

        self._debug_toggle.set_checked(bool(cfg.get("debug_logging", False)))

        prompts = cfg.get("prompts", {})
        for key, ta in self._prompt_inputs.items():
            ta.setPlainText(prompts.get(key, ""))

    def _save(self):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        for key, inp in self._blocking_inputs.items():
            txt = inp.text().strip()
            if txt:
                try:
                    cfg[key] = float(txt) if "." in txt else int(txt)
                except ValueError:
                    pass

        oc = self._override_input.text().strip()
        if oc:
            cfg["override_code"] = oc

        for opt, btn in self._harshness_btns.items():
            # find which one is selected by checking font-weight in stylesheet
            if "font-weight: 600" in btn.styleSheet():
                cfg["harshness"] = opt
                break

        cfg["always_allowed_apps"] = self._apps_tags.get_items()
        cfg["always_allowed_domains"] = self._domains_tags.get_items()

        for key, toggle in self._notif_toggles.items():
            cfg[key] = toggle.is_checked()

        cfg["debug_logging"] = self._debug_toggle.is_checked()

        if "prompts" not in cfg:
            cfg["prompts"] = {}
        for key, ta in self._prompt_inputs.items():
            cfg["prompts"][key] = ta.toPlainText().strip()

        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_PATH)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
        p.end()


# ── Toggle widget ─────────────────────────────────────────────────────────────

class _Toggle(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_checked(self, v: bool):
        self._checked = v
        self.update()

    def is_checked(self) -> bool:
        return self._checked

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_color = QColor(ACCENT) if self._checked else QColor(BORDER)
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 4, 44, 16, 8, 8)
        knob_x = 22 if self._checked else 2
        p.setBrush(QBrush(QColor("white")))
        p.drawEllipse(knob_x, 2, 20, 20)
        p.end()


# ── Tag editor widget ─────────────────────────────────────────────────────────

class _TagEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._layout = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._tags_widget = QWidget()
        self._tags_widget.setStyleSheet("background: transparent;")
        self._tags_layout = QHBoxLayout(self._tags_widget)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(6)
        self._tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self._tags_widget)

        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("Add...")
        self._add_input.setFixedHeight(30)
        self._add_input.returnPressed.connect(self._add_current)
        add_row.addWidget(self._add_input)
        add_btn = QPushButton("+")
        add_btn.setFixedSize(30, 30)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: #1A1100;
                border: none; border-radius: 6px;
                font-size: 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {ACCENT_HOVER}; }}
        """)
        add_btn.clicked.connect(self._add_current)
        add_row.addWidget(add_btn)
        outer.addLayout(add_row)

    def _refresh_tags(self):
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for item in self._items:
            tag = QWidget()
            tag.setStyleSheet(f"background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;")
            tl = QHBoxLayout(tag)
            tl.setContentsMargins(8, 3, 4, 3)
            tl.setSpacing(4)
            lbl = QLabel(item)
            lbl.setStyleSheet(f"color: {TEXT}; font-size: 12px; background: transparent; border: none;")
            tl.addWidget(lbl)
            x = QPushButton("×")
            x.setFixedSize(16, 16)
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.setStyleSheet(f"background: transparent; color: {TEXT_SEC}; border: none; font-size: 13px; padding: 0;")
            x.clicked.connect(lambda _, i=item: self._remove(i))
            tl.addWidget(x)
            self._tags_layout.addWidget(tag)

    def _add_current(self):
        val = self._add_input.text().strip()
        if val and val not in self._items:
            self._items.append(val)
            self._refresh_tags()
        self._add_input.clear()

    def _remove(self, item: str):
        if item in self._items:
            self._items.remove(item)
            self._refresh_tags()

    def set_items(self, items: list):
        self._items = list(items)
        self._refresh_tags()

    def get_items(self) -> list:
        return list(self._items)


# ── Main window ───────────────────────────────────────────────────────────────

class LocusWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Locus")
        self.setMinimumSize(680, 500)
        self.resize(720, 540)
        self.setWindowFlag(Qt.WindowType.Window)
        self.setStyleSheet(STYLESHEET)
        self._build()

    def _build(self):
        # Use a zero-margin layout with a single full-size container
        # so we can manually position children inside it
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Container fills the whole window -- children positioned manually
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {SURFACE};")
        root.addWidget(self._container)

        # Launcher spans full container width -- sidebar floats on top
        self._launcher = LauncherPane(self._container)

        # Other panes sit to the right of the sidebar
        self._other_stack = QStackedWidget(self._container)
        self._other_stack.setStyleSheet(f"background: {SURFACE};")
        self._other_stack.addWidget(PlaceholderPane(                   # 0
            "Connectors",
            "Connect Notion or paste a calendar URL (Google Calendar, Apple Calendar, Schoology) "
            "to pull upcoming assignments."
        ))
        self._other_stack.addWidget(PlaceholderPane(                   # 1
            "Analytics",
            "View your focus stats -- total time, sessions, most blocked apps and sites."
        ))
        self._other_stack.addWidget(SettingsPane())                    # 2
        self._other_stack.hide()

        # Sidebar floats on top of everything
        self._sidebar = Sidebar(self._container)
        self._sidebar.page_changed.connect(self._switch_page)
        self._sidebar.sidebar_toggled.connect(self._on_sidebar_toggled)
        self._sidebar.raise_()

        self._current_page = 0
        self._do_layout()

    def _do_layout(self):
        w = self._container.width()
        h = self._container.height()
        sw = self._sidebar.width() if self._sidebar.width() > 0 else SIDEBAR_EXPANDED

        # Sidebar always on left
        self._sidebar.setGeometry(0, 0, sw, h)

        # Launcher always full size -- content padding handles sidebar clearance
        self._launcher.setGeometry(0, 0, w, h)
        self._launcher.set_sidebar_width(sw)

        # Other panes fill remaining space to the right
        self._other_stack.setGeometry(sw, 0, max(0, w - sw), h)

        self._sidebar.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Container size updates automatically via layout, then we fix children
        QTimer.singleShot(0, self._do_layout)

    def _on_sidebar_toggled(self, collapsing: bool):
        if hasattr(self, "_layout_timer") and self._layout_timer.isActive():
            self._layout_timer.stop()
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(8)
        self._layout_timer.timeout.connect(self._do_layout)
        self._layout_timer.start()
        QTimer.singleShot(220, self._layout_timer.stop)

    def _switch_page(self, idx: int):
        self._current_page = idx
        if idx == 0:
            self._launcher.show()
            self._other_stack.hide()
        else:
            self._launcher.hide()
            self._other_stack.setCurrentIndex(idx - 1)
            self._other_stack.show()
        self._do_layout()
        self._sidebar.raise_()

    def update_state(self, state: dict):
        self._launcher.update_state(state)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
        p.end()


# ── Tray app ──────────────────────────────────────────────────────────────────

class LocusTrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        super().__init__(_tray_pixmap(False))
        self._app = app
        self._session_active = False
        self._events = []
        self._session_info = None
        self._window: Optional[LocusWindow] = None

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
            self._window.destroyed.connect(lambda: setattr(self, "_window", None))
        self._window.update_state({"events": self._events, "session": self._session_info})
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_state_changed(self, state: dict):
        self._events = state.get("events", [])
        self._session_info = state.get("session")
        self._session_active = self._session_info is not None

        if self._window:
            self._window.update_state(state)

        if self._session_active:
            name = self._session_info.get("display_name", "Session")
            self.setIcon(_tray_pixmap(True))
            self.setToolTip(f"Locus -- {name}")
            self._status_action.setText(f"  {name}")
            self._start_action.setEnabled(False)
            self._end_action.setEnabled(True)
        else:
            self.setIcon(_tray_pixmap(False))
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
    global _APP_REF
    app = QApplication(sys.argv)
    _APP_REF = app
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Locus")

    _load_fonts()

    # Auto-detect system dark mode
    if _is_system_dark():
        set_dark_mode(True)

    app.setStyleSheet(_make_stylesheet())

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
