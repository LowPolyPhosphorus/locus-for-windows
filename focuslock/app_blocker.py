"""Block all apps except those on the whitelist. (Windows)

Replaces macOS osascript/pkill calls with psutil + pywin32.

Dependencies:
    pip install psutil pywin32
"""

import threading
import time
import subprocess
from typing import Set, Dict, Callable, Optional, List

import psutil

try:
    import win32gui
    import win32process
    import win32con
    import win32api
    _WIN32 = True
except ImportError:
    _WIN32 = False
    print("[Locus] WARNING: pywin32 not installed — frontmost-app tracking disabled.")

try:
    from .analytics import log_event as _log_event
except Exception:
    def _log_event(*a, **kw): pass


# Always allowed, regardless of session
ALWAYS_ALLOWED = {
    "explorer",          # Windows Explorer / Finder equivalent
    "chrome",            # Google Chrome
    "cmd",               # Command Prompt
    "powershell",        # PowerShell
    "WindowsTerminal",   # Windows Terminal
    "wt",                # Windows Terminal (alternate)
    "FocusLock",
    "FocusLockApp",
    "python",
    "python3",
    "pythonw",
    "taskmgr",           # Task Manager (Activity Monitor equivalent)
    "SystemSettings",    # Settings (System Preferences equivalent)
    "Taskmgr",
    "dwm",               # Desktop Window Manager
    "csrss",             # Client/Server Runtime
    "winlogon",
    "services",
    "svchost",
    "lsass",
    "spoolsv",
    "SearchHost",
    "SearchIndexer",
    "ShellExperienceHost",
    "StartMenuExperienceHost",
    "TextInputHost",
    "ctfmon",            # Input method / accessibility
    "sihost",            # Shell infrastructure
    "fontdrvhost",
}

# Substrings — any process whose name contains one of these is always allowed
ALWAYS_ALLOWED_SUBSTRINGS = (
    "helper", "agent", "daemon", "service", "extension",
    "update", "crash", "runtime",
)


def _proc_name(proc: psutil.Process) -> str:
    """Return process name without the .exe extension, lowercased."""
    try:
        name = proc.name()
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _get_window_title(proc: psutil.Process) -> str:
    """Return the window title of the main window for a process, or ''."""
    if not _WIN32:
        return ""
    pid = proc.pid
    titles: list[str] = []

    def _cb(hwnd, _):
        try:
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid and win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if t:
                    titles.append(t)
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return titles[0] if titles else ""


class AppBlocker:
    def __init__(
        self,
        on_blocked: Callable[[str], None],
        poll_seconds: float = 2,
        extra_always_allowed: Optional[List[str]] = None,
    ):
        self.session_allowed: Set[str] = set()
        self.temporarily_allowed: Dict[str, float] = {}
        self.user_always_allowed: Set[str] = set(
            (n.lower() for n in (extra_always_allowed or []))
        )
        self.on_blocked = on_blocked
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._focus_thread: Optional[threading.Thread] = None
        self._handling: Set[str] = set()
        self._focus_app: Optional[str] = None
        self._focus_since: float = 0.0
        self.session_name: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    def set_session_allowed(self, apps: List[str]):
        """Set the list of apps allowed during this session (by display name or exe name)."""
        self.session_allowed = {a.lower() for a in apps}

    def allow_temporarily(self, app_name: str, minutes: int = 15):
        self.temporarily_allowed[app_name.lower()] = time.time() + minutes * 60
        self._handling.discard(app_name.lower())

    def deny(self, app_name: str):
        self._handling.discard(app_name.lower())

    def start(self):
        if self._running:
            return
        self._running = True
        self._focus_app = None
        self._focus_since = time.time()
        # Silent sweep: kill every disallowed GUI app currently running so we
        # don't queue a stack of modal prompts the moment a session starts.
        try:
            for name, proc in self._get_running_gui_apps():
                if not self._is_allowed(name):
                    self._terminate_app(name, proc)
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

    def open_app(self, app_name: str):
        """Launch an application by name (uses Windows 'start' command)."""
        subprocess.Popen(["start", "", app_name], shell=True)

    # ── Allow checking ────────────────────────────────────────────────────

    def _is_allowed(self, name: str) -> bool:
        """name is already lowercased."""
        if name in {a.lower() for a in ALWAYS_ALLOWED}:
            return True
        if name in self.user_always_allowed:
            return True
        if any(sub in name for sub in ALWAYS_ALLOWED_SUBSTRINGS):
            return True
        if name in self.session_allowed:
            return True
        if name in self.temporarily_allowed:
            if self.temporarily_allowed[name] > time.time():
                return True
            del self.temporarily_allowed[name]
        return False

    # ── Process enumeration ───────────────────────────────────────────────

    def _get_running_gui_apps(self) -> List[tuple]:
        """Return (lowercased_name, proc) for every process that owns a visible window."""
        if not _WIN32:
            # Fallback: return all non-system processes
            results = []
            for proc in psutil.process_iter(["pid", "name"]):
                name = _proc_name(proc).lower()
                if name:
                    results.append((name, proc))
            return results

        # Collect PIDs that own at least one visible, non-minimised window
        gui_pids: Set[int] = set()

        def _cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    gui_pids.add(pid)
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            pass

        results = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.pid in gui_pids:
                    name = _proc_name(proc).lower()
                    if name:
                        results.append((name, proc))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return results

    # ── Termination ───────────────────────────────────────────────────────

    def _terminate_app(self, name: str, proc: Optional[psutil.Process] = None):
        """Gracefully close, then force-kill if needed."""
        # 1. Try graceful close via taskkill /IM (sends WM_CLOSE)
        exe = name if name.endswith(".exe") else name + ".exe"
        subprocess.run(
            ["taskkill", "/IM", exe, "/T"],
            capture_output=True,
        )
        time.sleep(0.8)
        # 2. Force-kill if still alive
        if proc is not None:
            try:
                if proc.is_running():
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        else:
            subprocess.run(
                ["taskkill", "/F", "/IM", exe, "/T"],
                capture_output=True,
            )

    # ── Main loop ─────────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                for name, proc in self._get_running_gui_apps():
                    if self._is_allowed(name):
                        continue
                    if name in self._handling:
                        # Already showing dialog — keep killing if it respawns
                        self._terminate_app(name, proc)
                        continue
                    # New violation
                    self._handling.add(name)
                    self._terminate_app(name, proc)
                    threading.Thread(
                        target=self._handle_violation,
                        args=(name,),
                        daemon=True,
                    ).start()
            except Exception as e:
                print(f"[Locus] App blocker error: {e}")
            time.sleep(self.poll_seconds)

    def _handle_violation(self, name: str):
        try:
            self.on_blocked(name)
        finally:
            self._handling.discard(name)

    # ── Focus tracking ────────────────────────────────────────────────────

    def _get_frontmost_app(self) -> Optional[str]:
        """Return the exe name (no extension) of the foreground window's process."""
        if not _WIN32:
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            return _proc_name(proc).lower() or None
        except Exception:
            return None

    def _flush_focus(self):
        app = self._focus_app
        if app and self._focus_since:
            dur = int(time.time() - self._focus_since)
            if dur >= 2:
                try:
                    _log_event(
                        "app_focus",
                        app_name=app,
                        duration_seconds=dur,
                        session_name=self.session_name,
                    )
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
