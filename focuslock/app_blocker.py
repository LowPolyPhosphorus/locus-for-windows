"""Block all apps except those on the whitelist. (Windows)

Replaces macOS osascript/pkill calls with psutil + pywin32.

Dependencies:
    pip install psutil pywin32
"""

import threading
import time
import subprocess
import queue
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
    "claude",            # Claude desktop app
    "vivaldi",           # Vivaldi browser
    "explorer",          # Windows Explorer
    "chrome",            # Google Chrome
    "cmd",               # Command Prompt
    "powershell",        # PowerShell
    "windowsterminal",   # Windows Terminal
    "wt",                # Windows Terminal (alternate)
    "focuslock",
    "focuslockapp",
    "python",
    "python3",
    "pythonw",
    "taskmgr",           # Task Manager
    "systemsettings",    # Settings
    "dwm",               # Desktop Window Manager
    "csrss",             # Client/Server Runtime
    "winlogon",
    "services",
    "svchost",
    "lsass",
    "spoolsv",
    "searchhost",
    "searchindexer",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "textinputhost",
    "ctfmon",
    "sihost",
    "fontdrvhost",
}

# Substrings — any process whose name contains one of these is always allowed
ALWAYS_ALLOWED_SUBSTRINGS = (
    "agent", "daemon", "service", "extension",
    "update", "crash", "runtime",
)


def _proc_name(proc: psutil.Process) -> str:
    """Return process name without the .exe extension, lowercased."""
    try:
        name = proc.name()
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name.lower()
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
            n.lower() for n in (extra_always_allowed or [])
        )
        self.on_blocked = on_blocked
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._queue_thread: Optional[threading.Thread] = None
        self._focus_thread: Optional[threading.Thread] = None
        self._handling: Set[str] = set()          # names currently in queue or being shown
        self._violation_queue: queue.Queue = queue.Queue()  # (name, proc) tuples
        self._focus_app: Optional[str] = None
        self._focus_since: float = 0.0
        self.session_name: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    def set_session_allowed(self, apps: List[str]):
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
        # Drain any stale queue entries from a previous session
        while not self._violation_queue.empty():
            try:
                self._violation_queue.get_nowait()
            except queue.Empty:
                break
        self._handling.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self._queue_thread.start()
        self._focus_thread = threading.Thread(target=self._focus_loop, daemon=True)
        self._focus_thread.start()

    def stop(self):
        self._flush_focus()
        self._running = False
        self.session_allowed.clear()
        self.temporarily_allowed.clear()
        self._handling.clear()
        self._focus_app = None
        # Unblock the queue worker so it can exit
        self._violation_queue.put(None)

    def open_app(self, app_name: str):
        subprocess.Popen(["start", "", app_name], shell=True)

    # ── Allow checking ────────────────────────────────────────────────────

    def _is_allowed(self, name: str) -> bool:
        """name must already be lowercased."""
        if name in ALWAYS_ALLOWED:
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
            results = []
            for proc in psutil.process_iter(["pid", "name"]):
                name = _proc_name(proc)
                if name:
                    results.append((name, proc))
            return results

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
                    name = _proc_name(proc)
                    if name:
                        results.append((name, proc))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return results

    # ── Termination ───────────────────────────────────────────────────────

    def _terminate_app(self, name: str, proc: Optional[psutil.Process] = None):
        """Gracefully close, then force-kill if needed."""
        # Steam's visible window is owned by steamwebhelper — kill the full tree
        if "steam" in name:
            subprocess.run(["taskkill", "/IM", "steamservice.exe", "/F", "/T"], capture_output=True)
            subprocess.run(["taskkill", "/IM", "steam.exe", "/F", "/T"], capture_output=True)
            subprocess.run(["taskkill", "/IM", "steamwebhelper.exe", "/F", "/T"], capture_output=True)
            return
        exe = name if name.endswith(".exe") else name + ".exe"
        subprocess.run(["taskkill", "/IM", exe, "/T"], capture_output=True)
        time.sleep(0.8)
        if proc is not None:
            try:
                if proc.is_running():
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        else:
            subprocess.run(["taskkill", "/F", "/IM", exe, "/T"], capture_output=True)

    # ── Name remapping — map subprocess names to their parent app ────────

    def _remap_name(self, name: str) -> str:
        """Map subprocess-only process names to their logical parent app name."""
        if "steam" in name:
            return "steam"
        return name

    # ── Main poll loop ────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                for name, proc in self._get_running_gui_apps():
                    if self._is_allowed(name):
                        continue
                    display_name = self._remap_name(name)
                    if display_name in self._handling:
                        self._terminate_app(display_name, proc)
                        continue
                    self._handling.add(display_name)
                    self._violation_queue.put((display_name, proc))
                    print(f"[Locus] Queued violation: {display_name}")
            except Exception as e:
                print(f"[Locus] App blocker error: {e}")
            time.sleep(self.poll_seconds)

    # ── Queue worker — shows dialogs one at a time ────────────────────────

    def _queue_worker(self):
        """Single thread that processes violations one at a time, in order."""
        while self._running:
            try:
                item = self._violation_queue.get(timeout=1)
            except queue.Empty:
                continue

            if item is None:  # stop sentinel
                break

            name, proc = item
            try:
                # Check if still not allowed (user may have whitelisted it while queued)
                if self._is_allowed(name):
                    print(f"[Locus] {name} now allowed, skipping dialog")
                    continue
                # Show dialog — blocks until user responds
                self.on_blocked(name)
                # After dialog: if still not allowed, kill it
                if not self._is_allowed(name):
                    self._terminate_app(name, proc)
            except Exception as e:
                print(f"[Locus] Queue worker error for {name}: {e}")
            finally:
                self._handling.discard(name)

    # ── Focus tracking ────────────────────────────────────────────────────

    def _get_frontmost_app(self) -> Optional[str]:
        if not _WIN32:
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            return _proc_name(proc) or None
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
