"""Block all apps except those on the whitelist."""

import threading
import time
import subprocess
from typing import Set, Dict, Callable, Optional, List

try:
    from .analytics import log_event as _log_event
except Exception:
    def _log_event(*a, **kw): pass


# Always allowed, regardless of session
ALWAYS_ALLOWED = {
    "Finder",
    "Google Chrome",
    "Terminal",
    "iTerm2",
    "iTerm",
    "FocusLock",
    "FocusLockApp",
    "System Preferences",
    "System Settings",
    "Activity Monitor",
    "Dock",
    "SystemUIServer",
    "loginwindow",
    "WindowServer",
    "python3",
    "Python",
    "bash",
    "zsh",
    "osascript",
    "Script Editor",
    "universalaccessd",
    "AXVisualSupportAgent",
    "TextInputMenuAgent",
    "UserNotificationCenter",
    "NotificationCenter",
    "ControlCenter",
    "Spotlight",
    "Alfred",
    "Raycast",
}

# Substrings — any app whose name contains one of these is always allowed
ALWAYS_ALLOWED_SUBSTRINGS = ("Helper", "Agent", "Daemon", "Service", "Extension")


class AppBlocker:
    def __init__(self, on_blocked: Callable[[str], None], poll_seconds: float = 2,
                 extra_always_allowed: Optional[List[str]] = None):
        self.session_allowed: Set[str] = set()
        self.temporarily_allowed: Dict[str, float] = {}
        self.user_always_allowed: Set[str] = set(extra_always_allowed or [])
        self.on_blocked = on_blocked
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._focus_thread: Optional[threading.Thread] = None
        self._handling: Set[str] = set()
        self._focus_app: Optional[str] = None
        self._focus_since: float = 0.0
        self.session_name: str = ""

    def set_session_allowed(self, apps: List[str]):
        self.session_allowed = set(apps)

    def allow_temporarily(self, app_name: str, minutes: int = 15):
        self.temporarily_allowed[app_name] = time.time() + minutes * 60
        self._handling.discard(app_name)

    def deny(self, app_name: str):
        self._handling.discard(app_name)

    def start(self):
        if self._running:
            return
        self._running = True
        self._focus_app = None
        self._focus_since = time.time()
        # Silent sweep: quit every disallowed app currently running, without
        # firing dialogs. Otherwise starting a session with 5 unrelated apps
        # open queues 5 modal prompts on top of each other.
        try:
            for app_name in self._get_running_gui_apps():
                if not self._is_allowed(app_name):
                    self._terminate_app(app_name)
        except Exception:
            pass
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._focus_thread = threading.Thread(target=self._focus_loop, daemon=True)
        self._focus_thread.start()

    def stop(self):
        self._flush_focus()
        self._running = False
        self.session_allowed.clear()
        self.temporarily_allowed.clear()
        self._handling.clear()
        self._focus_app = None

    def _is_allowed(self, app_name: str) -> bool:
        if app_name in ALWAYS_ALLOWED:
            return True
        if app_name in self.user_always_allowed:
            return True
        # Skip anything that looks like a system helper/agent/daemon
        if any(sub in app_name for sub in ALWAYS_ALLOWED_SUBSTRINGS):
            return True
        if app_name in self.session_allowed:
            return True
        if app_name in self.temporarily_allowed:
            if self.temporarily_allowed[app_name] > time.time():
                return True
            del self.temporarily_allowed[app_name]
        return False

    def _get_running_gui_apps(self) -> List[str]:
        """Use osascript to get names of all visible GUI apps."""
        script = 'tell application "System Events" to get name of every process whose background only is false'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        # Output is comma-separated: "Finder, Google Chrome, News, ..."
        return [a.strip() for a in result.stdout.strip().split(",") if a.strip()]

    def _terminate_app(self, app_name: str):
        """Gracefully quit, then force-kill if needed."""
        # Strip anything that could break AppleScript string parsing: quotes,
        # backslashes, backticks, the AS line-continuation char ¬, and
        # newlines. macOS app names don't contain these in practice.
        safe = app_name
        for ch in ('"', "\\", "`", "¬", "\n", "\r"):
            safe = safe.replace(ch, "")
        if safe.strip():
            subprocess.run(
                ["osascript", "-e", f'tell application "{safe}" to quit'],
                capture_output=True, timeout=3,
            )
            time.sleep(0.8)
        subprocess.run(["pkill", "-x", app_name], capture_output=True)

    def _loop(self):
        while self._running:
            try:
                running = self._get_running_gui_apps()
                for app_name in running:
                    if self._is_allowed(app_name):
                        continue
                    if app_name in self._handling:
                        # Already showing dialog — keep killing it if it reopens
                        subprocess.run(["pkill", "-x", app_name], capture_output=True)
                        continue
                    # New violation
                    self._handling.add(app_name)
                    self._terminate_app(app_name)
                    threading.Thread(
                        target=self._handle_violation,
                        args=(app_name,),
                        daemon=True,
                    ).start()
            except Exception as e:
                print(f"[Locus] App blocker error: {e}")
            time.sleep(self.poll_seconds)

    def _handle_violation(self, app_name: str):
        try:
            self.on_blocked(app_name)
        finally:
            self._handling.discard(app_name)

    def _get_frontmost_app(self) -> Optional[str]:
        script = "tell application \"System Events\" to get name of first application process whose frontmost is true"
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            name = result.stdout.strip()
            return name if name else None
        except Exception:
            return None

    def _flush_focus(self):
        app = self._focus_app
        if app and self._focus_since:
            dur = int(time.time() - self._focus_since)
            if dur >= 2:
                try:
                    _log_event("app_focus", app_name=app, duration_seconds=dur,
                               session_name=self.session_name)
                except Exception:
                    pass
        self._focus_app = None
        self._focus_since = 0.0

    def _focus_loop(self):
        while self._running:
            time.sleep(3)
            if not self._running:
                break
            try:
                current = self._get_frontmost_app()
                if current and current != self._focus_app:
                    self._flush_focus()
                    self._focus_app = current
                    self._focus_since = time.time()
            except Exception:
                pass

    def open_app(self, app_name: str):
        subprocess.Popen(["open", "-a", app_name])
