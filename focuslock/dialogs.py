"""User-facing prompts and notifications. (Windows)

Dialogs must run on Qt's main thread. The daemon's queue worker runs on a
background thread. We bridge this with a simple request/response queue:

  - Background thread calls ask_reason() etc. as normal
  - ask_reason() pushes a request onto _REQUEST_QUEUE and blocks on an Event
  - The tray app's main thread drains _REQUEST_QUEUE every 100ms via a QTimer
  - Main thread builds and shows the dialog, puts the result in the Event
  - Background thread unblocks and returns the result

This is the only reliable way to show Qt dialogs from non-main threads.

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
    """Push fn onto the main thread queue and block until it completes."""
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
    """Serialize and run a Qt dialog on the main thread."""
    with _dialog_lock:
        return _run_on_main_thread(fn)


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
    """Warn the user that their browser will be relaunched.

    Returns True if the user clicks Continue, False if they click Cancel.
    """
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    )
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Locus -- Browser Restart Required")
        dlg.setMinimumWidth(420)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = [False]

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>Locus needs to restart {browser_name}.</b>")
        header.setWordWrap(True)
        layout.addWidget(header)

        body = QLabel(
            "To block websites, Locus needs to relaunch your browser in "
            "a special mode. Your tabs will be restored automatically when "
            "it reopens.\n\n"
            "Save any unsaved work (forms, drafts, etc.) before continuing."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        btn_row = QHBoxLayout()

        def _continue():
            result[0] = True
            dlg.accept()

        def _cancel():
            result[0] = False
            dlg.reject()

        ok = QPushButton("Continue -- Restart Browser")
        ok.setDefault(True)
        ok.clicked.connect(_continue)
        cx = QPushButton("Cancel")
        cx.clicked.connect(_cancel)

        btn_row.addStretch()
        btn_row.addWidget(cx)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


# ── Dialogs ───────────────────────────────────────────────────────────────────

def ask_reason(
    blocked_name: str,
    blocked_type: str,
    session_name: str,
) -> Tuple[str, str]:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    )
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Locus -- Access Request")
        dlg.setMinimumWidth(420)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = ["cancel", ""]

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{blocked_name}</b> is blocked during <i>{session_name}</i>.")
        header.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(QLabel(f"Why do you need this {blocked_type}?"))

        inp = QLineEdit()
        inp.setPlaceholderText("Enter your reason...")
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
        ov = QPushButton("Override..."); ov.clicked.connect(_override)
        ok = QPushButton("Submit");      ok.setDefault(True); ok.clicked.connect(_submit)
        cx = QPushButton("Cancel");      cx.clicked.connect(_cancel)
        btn_row.addWidget(ov)
        btn_row.addStretch()
        btn_row.addWidget(cx)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")


def ask_override_code(expected: str) -> bool:
    if not expected or not expected.strip():
        show_override_wrong()
        return False

    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    )
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Override Code")
        dlg.setMinimumWidth(300)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = [False]

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Enter override code:"))

        inp = QLineEdit()
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(inp)

        btn_row = QHBoxLayout()

        def _ok():
            entered = inp.text().strip()
            if expected.startswith("3141592653589") or expected.isdigit():
                cleaned = "".join(c for c in entered if c.isdigit())
                result[0] = cleaned == expected
            else:
                result[0] = entered == expected.strip()
            dlg.accept()

        inp.returnPressed.connect(_ok)
        ok = QPushButton("OK"); ok.setDefault(True); ok.clicked.connect(_ok)
        cx = QPushButton("Cancel"); cx.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(cx)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return result[0]

    return _run_qt_dialog(_build) or False


def show_result(approved: bool, explanation: str, target_name: str, minutes: int = 15):
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtCore import Qt

    def _build():
        msg = QMessageBox()
        msg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        if approved:
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Access Granted")
            msg.setText(f"<b>{target_name}</b> allowed for {minutes} min.\n\n{explanation}")
        else:
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Access Denied")
            msg.setText(f"<b>{target_name}</b> blocked.\n\n{explanation}")
        msg.exec()

    _run_qt_dialog(_build)


def show_override_wrong():
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtCore import Qt

    def _build():
        msg = QMessageBox()
        msg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Wrong Code")
        msg.setText("Incorrect override code.")
        msg.exec()

    _run_qt_dialog(_build)


def ask_off_topic_reason(
    domain: str,
    tab_title: str,
    session_name: str,
    ai_reason: str,
) -> Tuple[str, str]:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    )
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Locus -- Off-Topic Content")
        dlg.setMinimumWidth(440)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        result = ["cancel", ""]

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(
            f"<b>{domain}</b> looks off-topic during <i>{session_name}</i>.<br>"
            f"<small>{tab_title}</small>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        if ai_reason:
            reason_label = QLabel(f"<i>AI: {ai_reason}</i>")
            reason_label.setWordWrap(True)
            layout.addWidget(reason_label)

        layout.addWidget(QLabel("Why is this relevant to your session?"))
        inp = QLineEdit()
        inp.setPlaceholderText("Enter your reason...")
        layout.addWidget(inp)

        btn_row = QHBoxLayout()

        def _submit():
            result[0] = "submit"
            result[1] = inp.text().strip()
            dlg.accept()

        def _cancel():
            result[0] = "cancel"
            dlg.reject()

        inp.returnPressed.connect(_submit)
        ok = QPushButton("Submit"); ok.setDefault(True); ok.clicked.connect(_submit)
        cx = QPushButton("Cancel"); cx.clicked.connect(_cancel)
        btn_row.addStretch()
        btn_row.addWidget(cx)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        dlg.raise_()
        dlg.activateWindow()
        dlg.exec()
        return tuple(result)

    return _run_qt_dialog(_build) or ("cancel", "")
