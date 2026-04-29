"""User-facing prompts and notifications. (Windows)

Replaces the macOS version which wrote prompt.json and waited for the
Swift app to respond via response.json. On Windows there is no Swift app —
dialogs are PyQt6 windows spawned directly from the daemon thread.

Dependencies:
    pip install PyQt6 win10toast
"""

import threading
from typing import Tuple

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


# ── Qt helpers ────────────────────────────────────────────────────────────────

def _run_qt_dialog(fn):
    """Run a Qt dialog safely from any thread.

    If the tray UI's QApplication already exists we schedule onto it via
    QTimer and block the calling thread until the dialog closes.
    If we're running headless (no QApplication yet) we create one,
    run the dialog, then exit it.
    """
    import sys
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer

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

    QTimer.singleShot(0, _run)
    if _created:
        app.exec()
    else:
        done.wait(timeout=600)   # same ceiling as the old Swift IPC timeout

    return result.get("value")


# ── Dialogs ───────────────────────────────────────────────────────────────────

def ask_reason(
    blocked_name: str,
    blocked_type: str,   # "app" or "website"
    session_name: str,
) -> Tuple[str, str]:
    """Show the reason prompt. Returns (action, reason).
    action ∈ {"submit", "override", "cancel"}
    """
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    )
    from PyQt6.QtCore import Qt

    def _build():
        dlg = QDialog()
        dlg.setWindowTitle("Locus — Access Request")
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
        ok = QPushButton("Submit");    ok.setDefault(True); ok.clicked.connect(_submit)
        cx = QPushButton("Cancel");    cx.clicked.connect(_cancel)
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
        dlg.setWindowTitle("Locus — Off-Topic Content")
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
        inp.setPlaceholderText("Enter your reason…")
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
