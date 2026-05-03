"""User-facing prompts and notifications. (Windows)

Dialogs match the Swift UI style: serif headline, gold accent button,
cream card surface, DM Mono labels. All dialogs run on Qt's main thread
via the request queue bridge.

Dependencies:
    pip install PyQt6 win10toast
"""

import queue
import threading
from typing import Tuple, Callable, Any

# ── Inter-thread dialog bridge ────────────────────────────────────────────────

_REQUEST_QUEUE: queue.Queue = queue.Queue()
_dialog_lock = threading.Lock()


def _run_on_main_thread(fn: Callable) -> Any:
    done = threading.Event()
    result = [None]

    def _wrapped():
        try:
            result[0] = fn()
        except Exception as e:
            print(f"[Locus] Dialog error: {e}")
        finally:
            done.set()

    _REQUEST_QUEUE.put(_wrapped)
    done.wait()
    return result[0]


def _run_qt_dialog(fn: Callable) -> Any:
    with _dialog_lock:
        return _run_on_main_thread(fn)


# ── Theme ─────────────────────────────────────────────────────────────────────

_ACCENT       = "#E8A020"
_ACCENT_MUTED = "#FDF3E0"
_SURFACE      = "#FDFAF5"
_CARD         = "#F7F2E8"
_BORDER       = "#E8DFC8"
_TEXT         = "#1A1409"
_TEXT_SEC     = "#7A6A4A"

_SURFACE_DARK = "#151009"
_CARD_DARK    = "#211A0B"
_BORDER_DARK  = "#FFFFFF17"
_TEXT_DARK    = "#F5EDD8"
_TEXT_SEC_DARK = "#9A8A6A"

_dark = False


def _sync_theme():
    global _dark
    try:
        from tray_app import Theme
        _dark = Theme._dark
    except Exception:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as k:
                val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
                _dark = (val == 0)
        except Exception:
            _dark = False


def _s(): return _SURFACE_DARK if _dark else _SURFACE
def _c(): return _CARD_DARK if _dark else _CARD
def _b(): return _BORDER_DARK if _dark else _BORDER
def _t(): return _TEXT_DARK if _dark else _TEXT
def _ts(): return _TEXT_SEC_DARK if _dark else _TEXT_SEC


def _dialog_style() -> str:
    return f"""
    QDialog, QWidget {{
        background: {_s()};
        color: {_t()};
        font-family: 'Segoe UI', sans-serif;
        font-size: 13px;
        border: none;
    }}
    QLabel {{ background: transparent; color: {_t()}; }}
    QLineEdit {{
        background: {_c()};
        border: 1px solid {_b()};
        border-radius: 8px;
        padding: 8px 12px;
        color: {_t()};
        font-size: 13px;
    }}
    QLineEdit:focus {{ border-color: {_ACCENT}; }}
    QPushButton#primary {{
        background: {_ACCENT};
        color: #1A1409;
        font-weight: 600;
        font-size: 13px;
        border-radius: 8px;
        padding: 8px 20px;
        border: none;
        min-width: 80px;
    }}
    QPushButton#primary:hover {{ background: #D4911C; }}
    QPushButton#primary:pressed {{ background: #C07F10; }}
    QPushButton#secondary_btn {{
        background: transparent;
        color: {_t()};
        font-size: 13px;
        border: 1px solid {_b()};
        border-radius: 8px;
        padding: 8px 16px;
        min-width: 70px;
    }}
    QPushButton#secondary_btn:hover {{ border-color: {_ACCENT}; color: {_ACCENT}; }}
    QPushButton#ghost {{
        background: transparent;
        color: {_ts()};
        font-size: 12px;
        border: none;
        padding: 8px 12px;
    }}
    QPushButton#ghost:hover {{ color: {_t()}; }}
    """


def _serif_font(size: int):
    from PyQt6.QtGui import QFont
    f = QFont("Instrument Serif")
    if not f.exactMatch():
        f = QFont("Georgia")
    f.setPointSize(size)
    return f


def _mono_font(size: int):
    from PyQt6.QtGui import QFont
    f = QFont("DM Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSize(size)
    return f


def _draw_icon_circle(icon_char: str, bg: str, fg: str, size: int = 52):
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPainterPath, QBrush
    from PyQt6.QtCore import Qt, QRectF
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    p.fillPath(path, QBrush(QColor(bg)))
    f = QFont("Segoe UI Emoji")
    f.setPointSize(int(size * 0.36))
    p.setFont(f)
    p.setPen(QColor(fg))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, icon_char)
    p.end()
    return px


def _make_base_dialog(title: str, icon_char: str, icon_bg: str, icon_fg: str, width: int = 440):
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QWidget
    )
    from PyQt6.QtCore import Qt

    _sync_theme()

    dlg = QDialog()
    dlg.setWindowTitle("Locus")
    dlg.setMinimumWidth(width)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    dlg.setStyleSheet(_dialog_style())

    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    # Header -- card background
    header_widget = QWidget()
    header_widget.setStyleSheet(f"background: {_c()}; border: none;")
    header_layout = QVBoxLayout(header_widget)
    header_layout.setContentsMargins(28, 24, 28, 20)
    header_layout.setSpacing(8)
    header_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    icon_lbl = QLabel()
    icon_lbl.setPixmap(_draw_icon_circle(icon_char, icon_bg, icon_fg))
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    header_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

    title_lbl = QLabel(title)
    title_lbl.setFont(_serif_font(20))
    title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_lbl.setWordWrap(True)
    title_lbl.setStyleSheet(f"color: {_t()}; background: transparent;")
    header_layout.addWidget(title_lbl)

    outer.addWidget(header_widget)

    # Divider
    div = QFrame()
    div.setFrameShape(QFrame.Shape.HLine)
    div.setFixedHeight(1)
    div.setStyleSheet(f"background: {_b()}; border: none;")
    outer.addWidget(div)

    # Body
    body_widget = QWidget()
    body_widget.setStyleSheet(f"background: {_s()}; border: none;")
    body_layout = QVBoxLayout(body_widget)
    body_layout.setContentsMargins(28, 20, 28, 0)
    body_layout.setSpacing(12)
    outer.addWidget(body_widget)

    # Footer
    footer_widget = QWidget()
    footer_widget.setStyleSheet(f"background: {_s()}; border: none;")
    footer_layout = QHBoxLayout(footer_widget)
    footer_layout.setContentsMargins(28, 16, 28, 24)
    footer_layout.setSpacing(8)
    outer.addWidget(footer_widget)

    return dlg, body_layout, footer_layout, title_lbl


# ── Toast notifications ───────────────────────────────────────────────────────

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


# ── Browser relaunch warning ──────────────────────────────────────────────────

def ask_browser_relaunch(browser_name: str) -> bool:
    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton
        dlg, body, footer, _ = _make_base_dialog(
            f"Restart {browser_name}?", "↻", _ACCENT_MUTED, _ACCENT,
        )
        result = [False]

        lbl = QLabel(
            f"To block websites, Locus needs to relaunch {browser_name} "
            f"in a special mode. Your tabs will restore automatically.\n\n"
            f"Save any unsaved work before continuing."
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {_t()}; background: transparent;")
        body.addWidget(lbl)

        def _go():
            result[0] = True
            dlg.accept()

        cx = QPushButton("Cancel"); cx.setObjectName("secondary_btn")
        cx.clicked.connect(dlg.reject)
        ok = QPushButton("Continue"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(_go)
        footer.addStretch(); footer.addWidget(cx); footer.addWidget(ok)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


# ── Ask reason ────────────────────────────────────────────────────────────────

def ask_reason(
    blocked_name: str,
    blocked_type: str,
    session_name: str,
) -> Tuple[str, str]:
    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton, QLineEdit
        from PyQt6.QtCore import Qt

        icon = "🔒" if blocked_type == "app" else "🌐"
        dlg, body, footer, title_lbl = _make_base_dialog(
            blocked_name, icon, _ACCENT_MUTED, _ACCENT,
        )
        result = ["cancel", ""]

        session_lbl = QLabel(f"Blocked during  {session_name}")
        session_lbl.setFont(_mono_font(10))
        session_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        session_lbl.setStyleSheet(
            f"color: {_ts()}; background: {_c()}; letter-spacing: 0.5px; padding-bottom: 4px;"
        )
        # Insert into header area (index 1 in outer layout = header widget)
        dlg.layout().itemAt(0).widget().layout().addWidget(session_lbl)

        prompt = QLabel(f"Why do you need this {blocked_type}?")
        prompt.setStyleSheet(f"color: {_ts()}; background: transparent; font-size: 12px;")
        body.addWidget(prompt)

        inp = QLineEdit()
        inp.setPlaceholderText("Enter your reason...")
        body.addWidget(inp)

        def _submit():
            result[0] = "submit"; result[1] = inp.text().strip(); dlg.accept()

        def _override():
            result[0] = "override"; dlg.accept()

        def _cancel():
            result[0] = "cancel"; dlg.reject()

        inp.returnPressed.connect(_submit)

        ov = QPushButton("Override"); ov.setObjectName("ghost"); ov.clicked.connect(_override)
        cx = QPushButton("Cancel"); cx.setObjectName("secondary_btn"); cx.clicked.connect(_cancel)
        ok = QPushButton("Submit"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(_submit)

        footer.addWidget(ov); footer.addStretch()
        footer.addWidget(cx); footer.addWidget(ok)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")


# ── Override code ─────────────────────────────────────────────────────────────

def ask_override_code(expected: str) -> bool:
    if not expected or not expected.strip():
        show_override_wrong()
        return False

    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton, QLineEdit
        dlg, body, footer, _ = _make_base_dialog(
            "Override Code", "🔑", _ACCENT_MUTED, _ACCENT, width=360
        )
        result = [False]

        lbl = QLabel("Enter your override code:")
        lbl.setStyleSheet(f"color: {_ts()}; background: transparent; font-size: 12px;")
        body.addWidget(lbl)

        inp = QLineEdit()
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setPlaceholderText("••••••••")
        body.addWidget(inp)

        def _ok():
            entered = inp.text().strip()
            if expected.startswith("3141592653589") or expected.isdigit():
                cleaned = "".join(c for c in entered if c.isdigit())
                result[0] = cleaned == expected
            else:
                result[0] = entered == expected.strip()
            dlg.accept()

        inp.returnPressed.connect(_ok)
        cx = QPushButton("Cancel"); cx.setObjectName("secondary_btn"); cx.clicked.connect(dlg.reject)
        ok = QPushButton("Unlock"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(_ok)
        footer.addStretch(); footer.addWidget(cx); footer.addWidget(ok)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


# ── Show result ───────────────────────────────────────────────────────────────

def show_result(approved: bool, explanation: str, target_name: str, minutes: int = 15):
    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton
        from PyQt6.QtCore import Qt

        if approved:
            if minutes == -1:
                title = "Allowed for this session"
            elif minutes >= 60:
                h = minutes // 60
                title = f"Allowed for {h} hour{'s' if h > 1 else ''}"
            else:
                title = f"Allowed for {minutes} minutes"
            icon, bg, fg = "✓", "#E8F5E9", "#2E7D32"
        else:
            title = "Access Denied"
            icon, bg, fg = "✕", "#FFEBEE", "#C62828"

        dlg, body, footer, _ = _make_base_dialog(title, icon, bg, fg, width=400)

        name_lbl = QLabel(f"<b>{target_name}</b>")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"color: {_t()}; background: transparent;")
        body.addWidget(name_lbl)

        if explanation:
            exp = QLabel(explanation)
            exp.setWordWrap(True)
            exp.setStyleSheet(f"color: {_ts()}; background: transparent; font-size: 12px;")
            body.addWidget(exp)

        ok = QPushButton("OK"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(dlg.accept)
        footer.addStretch(); footer.addWidget(ok)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()

    _run_qt_dialog(_build)


# ── Override wrong ────────────────────────────────────────────────────────────

def show_override_wrong():
    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton
        dlg, body, footer, _ = _make_base_dialog(
            "Wrong Code", "✕", "#FFEBEE", "#C62828", width=340
        )
        lbl = QLabel("Incorrect override code.")
        lbl.setStyleSheet(f"color: {_ts()}; background: transparent; font-size: 12px;")
        body.addWidget(lbl)
        ok = QPushButton("OK"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(dlg.accept)
        footer.addStretch(); footer.addWidget(ok)
        dlg.raise_(); dlg.activateWindow(); dlg.exec()

    _run_qt_dialog(_build)


# ── Off-topic reason ──────────────────────────────────────────────────────────

def ask_off_topic_reason(
    domain: str,
    tab_title: str,
    session_name: str,
    ai_reason: str,
) -> Tuple[str, str]:
    def _build():
        from PyQt6.QtWidgets import QLabel, QPushButton, QLineEdit
        dlg, body, footer, title_lbl = _make_base_dialog(
            domain, "⚠", "#FFF8E1", "#F57F17"
        )
        result = ["cancel", ""]

        if tab_title:
            tl = QLabel(tab_title)
            tl.setFont(_mono_font(10))
            tl.setWordWrap(True)
            tl.setStyleSheet(f"color: {_ts()}; background: {_c()}; padding-bottom: 2px;")
            dlg.layout().itemAt(0).widget().layout().addWidget(tl)

        if ai_reason:
            ai = QLabel(f"AI: {ai_reason}")
            ai.setWordWrap(True)
            ai.setStyleSheet(
                f"color: {_ts()}; background: transparent; font-size: 12px; font-style: italic;"
            )
            body.addWidget(ai)

        prompt = QLabel("Why is this relevant to your session?")
        prompt.setStyleSheet(f"color: {_ts()}; background: transparent; font-size: 12px;")
        body.addWidget(prompt)

        inp = QLineEdit()
        inp.setPlaceholderText("Enter your reason...")
        body.addWidget(inp)

        def _submit():
            result[0] = "submit"; result[1] = inp.text().strip(); dlg.accept()

        inp.returnPressed.connect(_submit)
        cx = QPushButton("Cancel"); cx.setObjectName("secondary_btn"); cx.clicked.connect(dlg.reject)
        ok = QPushButton("Submit"); ok.setObjectName("primary")
        ok.setDefault(True); ok.clicked.connect(_submit)
        footer.addStretch(); footer.addWidget(cx); footer.addWidget(ok)

        dlg.raise_(); dlg.activateWindow(); dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")
