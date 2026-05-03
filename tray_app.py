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
)

from focuslock.paths import STATE_PATH, COMMAND_PATH, CONFIG_PATH


# ── Theme (light only) ────────────────────────────────────────────────────────

ACCENT        = "#E8A020"
ACCENT_HOVER  = "#D4901A"
ACCENT_MUTED  = "#FDF3E0"
SURFACE       = "#FDFAF5"
CARD          = "#F7F2E8"
BORDER        = "#E8DFC8"
TEXT          = "#1A1409"
TEXT_SEC      = "#7A6A4A"
TEXT_LIGHT    = "#B0A080"

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

def _tag_colors(class_name: str):
    key = class_name.lower().strip()
    for k, v in TAG_COLORS.items():
        if k in key:
            return v
    return TAG_COLORS["default"]


STYLESHEET = f"""
QWidget {{
    background-color: {SURFACE};
    color: {TEXT};
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}}
QLabel {{ background: transparent; color: {TEXT}; }}
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


# ── Font helpers ──────────────────────────────────────────────────────────────

def _load_fonts():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FocusLockApp", "Fonts")
    for fname in ["InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf",
                  "DMMono-Regular.ttf", "DMMono-Medium.ttf"]:
        path = os.path.join(base, fname)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def serif(size: int) -> QFont:
    f = QFont("Instrument Serif")
    if not f.exactMatch():
        f = QFont("Georgia")
    f.setPointSize(size)
    return f


def mono(size: int, medium: bool = False) -> QFont:
    f = QFont("DM Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSize(size)
    if medium:
        f.setWeight(QFont.Weight.Medium)
    return f


# ── Icon drawing ──────────────────────────────────────────────────────────────

def _lock_pixmap(size: int, locked: bool, color: str) -> QPixmap:
    """Outline-style lock icon -- no fill, just stroked shackle and body."""
    # Add padding so the stroke doesn't clip at the edges
    pad = int(size * 0.08)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    stroke = max(1.5, size * 0.085)

    pen = QPen(c, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Shackle (arc on top)
    sw = size * 0.42
    sh = size * 0.38
    sx = (size - sw) / 2
    sy = pad
    if locked:
        p.drawArc(QRectF(sx, sy, sw, sh), 0, 180 * 16)
    else:
        # Open -- arc lifted on right side
        p.drawArc(QRectF(sx, sy - size * 0.08, sw, sh), 25 * 16, 130 * 16)

    # Body (rounded rect, outline only)
    bw = size * 0.64
    bh = size * 0.42
    bx = (size - bw) / 2
    by = size * 0.50
    path = QPainterPath()
    path.addRoundedRect(bx, by, bw, bh, size * 0.09, size * 0.09)
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
        x = (self.width() - ICON_SIZE) // 2 if self._collapsed else 10
        y = (self.height() - ICON_SIZE) // 2
        p.drawPixmap(x, y, icon_px)
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
    collapse_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._current = 0
        self._rows = []
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 16)
        layout.setSpacing(0)

        # Header row -- lock icon + Locus title + collapse button
        hdr = QWidget()
        hdr.setFixedHeight(62)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 4, 0)
        hl.setSpacing(8)

        self._lock_lbl = QLabel()
        self._lock_lbl.setPixmap(_lock_pixmap(22, True, ACCENT))
        self._lock_lbl.setFixedSize(22, 22)
        hl.addWidget(self._lock_lbl)

        self._title_lbl = QLabel("Locus")
        self._title_lbl.setFont(serif(20))
        self._title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        hl.addWidget(self._title_lbl)
        hl.addStretch()

        # Collapse toggle button
        self._toggle_btn = QPushButton("‹")
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_SEC};
                border: none;
                font-size: 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{ background: {CARD}; }}
        """)
        self._toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self._toggle_btn)
        layout.addWidget(hdr)

        for label, icon_name, idx in PAGES:
            row = NavRow(label, icon_name)
            row.clicked.connect(lambda _, i=idx: self._select(i))
            self._rows.append(row)
            layout.addWidget(row)
            layout.addSpacing(2)

        layout.addStretch()
        self._rows[0].set_selected(True)

    def toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.setFixedWidth(SIDEBAR_COLLAPSED)
            self._title_lbl.hide()
            self._toggle_btn.setText("›")
        else:
            self.setFixedWidth(SIDEBAR_EXPANDED)
            self._title_lbl.show()
            self._toggle_btn.setText("‹")
        for row in self._rows:
            row.set_collapsed(self._collapsed)
        self.collapse_toggled.emit(self._collapsed)

    def _select(self, idx: int):
        for row in self._rows:
            row.set_selected(False)
        self._rows[idx].set_selected(True)
        self._current = idx
        self.page_changed.emit(idx)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
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
        self._title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
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
        center_wrap.addStretch()
        center_wrap.addWidget(input_area, 1)
        center_wrap.addStretch()
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
        or_wrap.addStretch()
        or_w = QWidget(); or_w.setMaximumWidth(440)
        or_w.setLayout(or_row)
        or_wrap.addWidget(or_w)
        or_wrap.addStretch()
        layout.addLayout(or_wrap)
        layout.addSpacing(20)

        # Events section
        events_wrap = QHBoxLayout()
        events_wrap.addStretch()
        self._events_widget = QWidget()
        self._events_widget.setMaximumWidth(440)
        self._events_layout = QVBoxLayout(self._events_widget)
        self._events_layout.setContentsMargins(0, 0, 0, 0)
        self._events_layout.setSpacing(0)
        events_wrap.addWidget(self._events_widget)
        events_wrap.addStretch()
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
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_changed.connect(self._switch_page)
        root.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {SURFACE};")

        self._launcher = LauncherPane()
        self._stack.addWidget(self._launcher)                          # 0

        self._stack.addWidget(PlaceholderPane(                         # 1
            "Connectors",
            "Connect Notion or paste a calendar URL (Google Calendar, Apple Calendar, Schoology) "
            "to pull upcoming assignments."
        ))
        self._stack.addWidget(PlaceholderPane(                         # 2
            "Analytics",
            "View your focus stats -- total time, sessions, most blocked apps and sites."
        ))
        self._stack.addWidget(PlaceholderPane(                         # 3
            "Settings",
            "Configure blocking behavior, override code, notification preferences, and appearance."
        ))

        root.addWidget(self._stack)

    def _switch_page(self, idx: int):
        self._stack.setCurrentIndex(idx)

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
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Locus")

    _load_fonts()
    app.setStyleSheet(STYLESHEET)

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
