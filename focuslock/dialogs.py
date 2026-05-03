"""User-facing prompts and notifications. (Windows)

Dialogs must run on Qt's main thread. The daemon's queue worker runs on a
background thread. We bridge this with a simple request/response queue:

  - Background thread calls ask_reason() etc. as normal
  - ask_reason() pushes a request onto _REQUEST_QUEUE and blocks on an Event
  - The tray app's main thread drains _REQUEST_QUEUE every 100ms via a QTimer
  - Main thread builds and shows the dialog, puts the result in the Event
  - Background thread unblocks and returns the result

This is the only reliable way to show Qt dialogs from non-main threads.
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


# ── Theme constants ───────────────────────────────────────────────────────────

# Mirrors Theme.swift exactly
ACCENT        = "#E8A020"
ACCENT_MUTED  = "#FDF3E0"
SURFACE       = "#FDFAF5"
CARD          = "#F7F2E8"
BORDER        = "#E8DFC8"
TEXT_PRIMARY  = "#1A1A1A"
TEXT_SECONDARY = "#6B6B6B"

# Dark mode variants
SURFACE_DARK  = "#151108"
CARD_DARK     = "#211C12"
BORDER_DARK   = "#FFFFFF17"

STYLESHEET = f"""
QDialog {{
    background-color: {SURFACE};
    font-family: 'Segoe UI', sans-serif;
}}

/* ── Field label (DM Mono uppercase style) ── */
QLabel#field_label {{
    font-family: 'Consolas', monospace;
    font-size: 10px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
    letter-spacing: 1px;
    text-transform: uppercase;
}}

/* ── Body / secondary text ── */
QLabel#secondary {{
    font-size: 11px;
    color: {TEXT_SECONDARY};
}}

/* ── Serif heading ── */
QLabel#heading {{
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 22px;
    color: {TEXT_PRIMARY};
}}

QLabel#subheading {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

/* ── Card ── */
QFrame#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ── Icon circle ── */
QFrame#icon_circle_accent {{
    background-color: {ACCENT_MUTED};
    border-radius: 28px;
}}
QFrame#icon_circle_red {{
    background-color: rgba(229,57,53,18);
    border-radius: 28px;
}}
QFrame#icon_circle_green {{
    background-color: rgba(67,160,71,18);
    border-radius: 28px;
}}
QFrame#icon_circle_orange {{
    background-color: rgba(251,140,0,18);
    border-radius: 28px;
}}

/* ── AI reason box ── */
QLabel#ai_reason_box {{
    background-color: {ACCENT_MUTED};
    border-radius: 8px;
    padding: 10px;
    font-size: 12px;
    color: {TEXT_PRIMARY};
}}

/* ── Input ── */
QLineEdit, QTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_MUTED};
}}
QLineEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ── Primary button (gold) ── */
QPushButton#primary {{
    background-color: {ACCENT};
    color: #1A1100;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background-color: #D4901A; }}
QPushButton#primary:pressed {{ background-color: #BF811A; }}
QPushButton#primary:disabled {{ background-color: {ACCENT}; opacity: 0.45; }}

/* ── Secondary button (outlined) ── */
QPushButton#secondary {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#secondary:hover {{ background-color: {BORDER}; }}
QPushButton#secondary:pressed {{ background-color: {CARD}; }}

/* ── Footer separator ── */
QFrame#footer_sep {{
    background-color: {BORDER};
    max-height: 1px;
    border: none;
}}

/* ── Status pill ── */
QLabel#status_pill {{
    background-color: {ACCENT_MUTED};
    color: {ACCENT};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}}
"""


# ── Shared dialog builder helpers ─────────────────────────────────────────────

def _apply_style(widget):
    widget.setStyleSheet(STYLESHEET)


def _make_label(text, object_name=None, word_wrap=True):
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setWordWrap(word_wrap)
    if object_name:
        lbl.setObjectName(object_name)
    return lbl


def _make_icon_circle(icon_char: str, circle_name: str, icon_color: str, size=56):
    """Returns a QFrame containing a centered emoji/unicode icon in a colored circle."""
    from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
    from PyQt6.QtCore import Qt

    frame = QFrame()
    frame.setObjectName(circle_name)
    frame.setFixedSize(size, size)
    frame.setStyleSheet(f"""
        QFrame#{circle_name} {{
            border-radius: {size // 2}px;
        }}
    """)

    inner = QVBoxLayout(frame)
    inner.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(icon_char)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f"font-size: 22px; color: {icon_color}; background: transparent;")
    inner.addWidget(lbl)
    return frame


def _prompt_header(icon_char: str, circle_obj: str, icon_color: str,
                   circle_bg: str, title: str, subtitle: str = ""):
    """Returns a QVBoxLayout with the centered icon + serif title + subtitle."""
    from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QFrame
    from PyQt6.QtCore import Qt

    layout = QVBoxLayout()
    layout.setSpacing(10)
    layout.setContentsMargins(22, 28, 22, 18)

    # Icon circle
    circle = QFrame()
    circle.setFixedSize(56, 56)
    circle.setStyleSheet(f"""
        QFrame {{
            background-color: {circle_bg};
            border-radius: 28px;
        }}
    """)
    icon_lbl = QLabel(icon_char)
    icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_lbl.setStyleSheet(f"font-size: 22px; color: {icon_color}; background: transparent;")
    il = QVBoxLayout(circle)
    il.setContentsMargins(0, 0, 0, 0)
    il.addWidget(icon_lbl)

    icon_row = QHBoxLayout()
    icon_row.addStretch()
    icon_row.addWidget(circle)
    icon_row.addStretch()
    layout.addLayout(icon_row)

    title_lbl = QLabel(title)
    title_lbl.setObjectName("heading")
    title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_lbl.setWordWrap(True)
    layout.addWidget(title_lbl)

    if subtitle:
        sub_lbl = QLabel(subtitle)
        sub_lbl.setObjectName("subheading")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setWordWrap(True)
        layout.addWidget(sub_lbl)

    return layout


def _footer_layout(*buttons):
    """Returns a styled footer QVBoxLayout with a top separator and right-aligned buttons."""
    from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame

    outer = QVBoxLayout()
    outer.setSpacing(0)
    outer.setContentsMargins(0, 0, 0, 0)

    sep = QFrame()
    sep.setObjectName("footer_sep")
    sep.setFixedHeight(1)
    sep.setStyleSheet(f"background-color: {BORDER}; border: none;")
    outer.addWidget(sep)

    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(18, 14, 18, 14)
    btn_row.setSpacing(10)
    btn_row.addStretch()
    for btn in buttons:
        btn_row.addWidget(btn)
    outer.addLayout(btn_row)

    return outer


def _base_dialog(title="Locus", width=460):
    from PyQt6.QtWidgets import QDialog
    from PyQt6.QtCore import Qt
    dlg = QDialog()
    dlg.setWindowTitle(title)
    dlg.setFixedWidth(width)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    dlg.setStyleSheet(STYLESHEET)
    return dlg


def _primary_btn(text):
    from PyQt6.QtWidgets import QPushButton
    btn = QPushButton(text)
    btn.setObjectName("primary")
    return btn


def _secondary_btn(text):
    from PyQt6.QtWidgets import QPushButton
    btn = QPushButton(text)
    btn.setObjectName("secondary")
    return btn


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
        from PyQt6.QtWidgets import QVBoxLayout

        dlg = _base_dialog("Locus")
        result = [False]

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = _prompt_header(
            "🔄", "icon_circle_accent", ACCENT, ACCENT_MUTED,
            "Browser Restart Required",
            f"Locus needs to relaunch {browser_name} to enable website blocking."
        )
        root.addLayout(hdr)

        # Body
        from PyQt6.QtWidgets import QLabel
        body_lbl = QLabel(
            "Your tabs will be restored automatically when it reopens.\n\n"
            "Save any unsaved work (forms, drafts, etc.) before continuing."
        )
        body_lbl.setWordWrap(True)
        body_lbl.setObjectName("secondary")
        body_lbl.setContentsMargins(22, 0, 22, 20)
        root.addWidget(body_lbl)

        # Footer
        cx = _secondary_btn("Cancel")
        ok = _primary_btn("Continue — Restart Browser")
        ok.setDefault(True)

        def _continue():
            result[0] = True
            dlg.accept()

        ok.clicked.connect(_continue)
        cx.clicked.connect(dlg.reject)

        root.addLayout(_footer_layout(cx, ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


# ── ask_reason ────────────────────────────────────────────────────────────────

def ask_reason(
    blocked_name: str,
    blocked_type: str,
    session_name: str,
) -> Tuple[str, str]:
    def _build():
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QLineEdit

        dlg = _base_dialog("Locus")
        result = ["cancel", ""]

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        icon = "🌐" if blocked_type == "website" else "🔒"
        hdr = _prompt_header(
            icon, "icon_circle_red", "#E53935", "rgba(229,57,53,0.10)",
            blocked_name,
            f"Blocked during {session_name}"
        )
        root.addLayout(hdr)

        # Body
        from PyQt6.QtWidgets import QFrame
        body_frame = QFrame()
        body_layout = QVBoxLayout(body_frame)
        body_layout.setSpacing(8)
        body_layout.setContentsMargins(22, 4, 22, 18)

        q_lbl = QLabel("Why do you need access?")
        q_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT_PRIMARY};")
        body_layout.addWidget(q_lbl)

        hint = QLabel("Be specific — AI will evaluate your reason.")
        hint.setObjectName("secondary")
        body_layout.addWidget(hint)

        inp = QLineEdit()
        inp.setPlaceholderText("e.g. Looking up the formula for kinetic energy")
        body_layout.addWidget(inp)

        root.addWidget(body_frame)

        # Footer
        cx = _secondary_btn("Cancel")
        ov = _secondary_btn("Override")
        ok = _primary_btn("Submit")
        ok.setDefault(True)
        ok.setEnabled(False)

        inp.textChanged.connect(lambda t: ok.setEnabled(bool(t.strip())))

        def _submit():
            result[0] = "submit"
            result[1] = inp.text().strip()
            dlg.accept()

        def _override():
            result[0] = "override"
            dlg.accept()

        inp.returnPressed.connect(_submit)
        ok.clicked.connect(_submit)
        ov.clicked.connect(_override)
        cx.clicked.connect(dlg.reject)

        root.addLayout(_footer_layout(cx, ov, ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")


# ── ask_override_code ─────────────────────────────────────────────────────────

def ask_override_code(expected: str) -> bool:
    if not expected or not expected.strip():
        show_override_wrong()
        return False

    def _build():
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QFrame

        dlg = _base_dialog("Locus")
        result = [False]

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = _prompt_header(
            "🔑", "icon_circle_accent", ACCENT, ACCENT_MUTED,
            "Enter Override Code",
            "Bypass Locus for this session"
        )
        root.addLayout(hdr)

        body_frame = QFrame()
        body_layout = QVBoxLayout(body_frame)
        body_layout.setSpacing(8)
        body_layout.setContentsMargins(22, 4, 22, 18)

        if expected.startswith("3141592653589"):
            hint = QLabel("Hint: it's the first 100 digits of π")
            hint.setObjectName("secondary")
            body_layout.addWidget(hint)

        inp = QLineEdit()
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setPlaceholderText("override code")
        inp.setStyleSheet(inp.styleSheet() + "font-family: Consolas, monospace;")
        body_layout.addWidget(inp)

        root.addWidget(body_frame)

        cx = _secondary_btn("Cancel")
        ok = _primary_btn("Unlock")
        ok.setDefault(True)
        ok.setEnabled(False)

        inp.textChanged.connect(lambda t: ok.setEnabled(bool(t.strip())))

        def _ok():
            entered = inp.text().strip()
            if expected.startswith("3141592653589") or expected.isdigit():
                cleaned = "".join(c for c in entered if c.isdigit())
                result[0] = cleaned == expected
            else:
                result[0] = entered == expected.strip()
            dlg.accept()

        inp.returnPressed.connect(_ok)
        ok.clicked.connect(_ok)
        cx.clicked.connect(dlg.reject)

        root.addLayout(_footer_layout(cx, ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


# ── show_result ───────────────────────────────────────────────────────────────

def show_result(approved: bool, explanation: str, target_name: str, minutes: int = 15):
    def _build():
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QFrame

        dlg = _base_dialog("Locus")

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        if approved:
            hdr = _prompt_header(
                "✅", "icon_circle_green", "#43A047", "rgba(67,160,71,0.10)",
                "Access Granted", target_name
            )
        else:
            hdr = _prompt_header(
                "❌", "icon_circle_red", "#E53935", "rgba(229,57,53,0.10)",
                "Access Denied", target_name
            )
        root.addLayout(hdr)

        body_frame = QFrame()
        body_layout = QVBoxLayout(body_frame)
        body_layout.setSpacing(10)
        body_layout.setContentsMargins(22, 4, 22, 18)

        exp_lbl = QLabel(explanation)
        exp_lbl.setWordWrap(True)
        exp_lbl.setStyleSheet(f"font-size: 13px; color: {TEXT_PRIMARY};")
        body_layout.addWidget(exp_lbl)

        if approved and minutes > 0:
            pill = QLabel(f"⏱  Allowed for {minutes} minutes")
            pill.setStyleSheet(f"""
                background-color: {ACCENT_MUTED};
                color: {ACCENT};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 600;
            """)
            body_layout.addWidget(pill)

        root.addWidget(body_frame)

        ok = _primary_btn("OK")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)

        root.addLayout(_footer_layout(ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()

    _run_qt_dialog(_build)


# ── show_override_wrong ───────────────────────────────────────────────────────

def show_override_wrong():
    def _build():
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QFrame

        dlg = _base_dialog("Locus", width=380)

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = _prompt_header(
            "🚫", "icon_circle_red", "#E53935", "rgba(229,57,53,0.10)",
            "Wrong Code",
            "Incorrect override code."
        )
        root.addLayout(hdr)

        ok = _primary_btn("OK")
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        root.addLayout(_footer_layout(ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()

    _run_qt_dialog(_build)


# ── ask_off_topic_reason ──────────────────────────────────────────────────────

def ask_off_topic_reason(
    domain: str,
    tab_title: str,
    session_name: str,
    ai_reason: str,
) -> Tuple[str, str]:
    def _build():
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QFrame

        dlg = _base_dialog("Locus")
        result = ["cancel", ""]

        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = _prompt_header(
            "⚠️", "icon_circle_orange", "#FB8C00", "rgba(251,140,0,0.10)",
            "Off-topic detected",
            domain
        )
        root.addLayout(hdr)

        body_frame = QFrame()
        body_layout = QVBoxLayout(body_frame)
        body_layout.setSpacing(10)
        body_layout.setContentsMargins(22, 4, 22, 18)

        if tab_title:
            tab_lbl = QLabel(f"📄  {tab_title}")
            tab_lbl.setWordWrap(True)
            tab_lbl.setObjectName("secondary")
            body_layout.addWidget(tab_lbl)

        if ai_reason:
            ai_lbl = QLabel(ai_reason)
            ai_lbl.setWordWrap(True)
            ai_lbl.setObjectName("ai_reason_box")
            ai_lbl.setStyleSheet(f"""
                background-color: {ACCENT_MUTED};
                border-radius: 8px;
                padding: 10px;
                font-size: 12px;
                color: {TEXT_PRIMARY};
            """)
            body_layout.addWidget(ai_lbl)

        q_lbl = QLabel("Why are you viewing this?")
        q_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT_PRIMARY}; margin-top: 4px;")
        body_layout.addWidget(q_lbl)

        inp = QLineEdit()
        inp.setPlaceholderText("e.g. The video covers mitosis stages")
        body_layout.addWidget(inp)

        root.addWidget(body_frame)

        cx = _secondary_btn("Cancel")
        ok = _primary_btn("Submit")
        ok.setDefault(True)
        ok.setEnabled(False)

        inp.textChanged.connect(lambda t: ok.setEnabled(bool(t.strip())))

        def _submit():
            result[0] = "submit"
            result[1] = inp.text().strip()
            dlg.accept()

        inp.returnPressed.connect(_submit)
        ok.clicked.connect(_submit)
        cx.clicked.connect(dlg.reject)

        root.addLayout(_footer_layout(cx, ok))

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")
