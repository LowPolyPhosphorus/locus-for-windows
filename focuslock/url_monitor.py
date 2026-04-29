"""Block websites in Chrome except those on the session whitelist. (Windows)

Replaces all macOS osascript/AppleScript Chrome control with Chrome's
DevTools Protocol (CDP) over HTTP — more reliable, faster, and
cross-platform.

How it works:
    1. Chrome must be launched with --remote-debugging-port=9222
       (Locus does this automatically via open_chrome_with_debug()).
    2. We poll /json/list to get all open tabs and their URLs/titles.
    3. To close/redirect a tab we POST to its webSocketDebuggerUrl.

Dependencies:
    pip install requests websocket-client psutil

Chrome launch flag (add to your Chrome shortcut or launcher):
    chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
"""

import threading
import time
import subprocess
import re
import json
import os
from typing import Set, Dict, Callable, Optional, List

try:
    import requests as _requests
    _REQUESTS = True
except ImportError:
    _REQUESTS = False
    print("[Locus] WARNING: 'requests' not installed — URL monitoring disabled.")

try:
    import websocket  # websocket-client
    _WS = True
except ImportError:
    _WS = False
    print("[Locus] WARNING: 'websocket-client' not installed — tab control disabled.")

try:
    import psutil as _psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    from .analytics import log_event as _log_event
except Exception:
    def _log_event(*a, **kw): pass


# ── Constants ─────────────────────────────────────────────────────────────────

CDP_HOST = "http://localhost:9222"
CHROME_EXE_NAMES = ("chrome.exe", "chrome")

# Internal browser pages — never block these
INTERNAL_SCHEMES = {"chrome", "about", "data", "chrome-extension", "devtools"}

# Always allowed in any session
ALWAYS_ALLOWED_DOMAINS = {"notion.so", "notionusercontent.com", "music.youtube.com"}

# Tab titles too generic to check
TITLE_IGNORE = {"youtube", "youtube music", "google", "new tab", "claude", ""}


# ── Chrome launcher ───────────────────────────────────────────────────────────

def open_chrome_with_debug(url: str = "about:blank"):
    """Launch Chrome with the remote debugging port open.
    Safe to call if Chrome is already running — CDP is already available."""
    chrome_path = _find_chrome()
    if not chrome_path:
        print("[Locus] Chrome not found — cannot open with debug port.")
        return
    subprocess.Popen([
        chrome_path,
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        url,
    ])


def _find_chrome() -> Optional[str]:
    """Find the Chrome executable on Windows."""
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ── CDP helpers ───────────────────────────────────────────────────────────────

def _cdp_tabs() -> List[dict]:
    """Return a list of tab dicts from Chrome's /json/list endpoint."""
    if not _REQUESTS:
        return []
    try:
        resp = _requests.get(f"{CDP_HOST}/json/list", timeout=2)
        if resp.status_code == 200:
            return [t for t in resp.json() if t.get("type") == "page"]
    except Exception:
        pass
    return []


def _cdp_send(ws_url: str, method: str, params: dict = None, timeout: float = 3.0):
    """Open a WebSocket to the tab's debugger URL, send one command, close."""
    if not _WS:
        return None
    try:
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        result = json.loads(ws.recv())
        ws.close()
        return result
    except Exception:
        return None


def _navigate_tab(ws_url: str, url: str):
    _cdp_send(ws_url, "Page.navigate", {"url": url})


def _close_tab(ws_url: str):
    _cdp_send(ws_url, "Page.close")


def _get_tab_url(ws_url: str) -> Optional[str]:
    """Fetch the live URL of a tab via CDP (more accurate than /json/list cache)."""
    result = _cdp_send(ws_url, "Runtime.evaluate", {
        "expression": "window.location.href",
        "returnByValue": True,
    })
    try:
        return result["result"]["result"]["value"]
    except Exception:
        return None


# ── Monitor ───────────────────────────────────────────────────────────────────

class URLMonitor:
    def __init__(
        self,
        on_blocked_url: Callable[[str, str, Optional[str], str], None],
        on_off_topic: Optional[Callable[[str, str, Optional[str]], None]] = None,
        poll_seconds: float = 2,
        extra_always_allowed: Optional[List[str]] = None,
    ):
        self.session_allowed_domains: Set[str] = set()
        self.temporarily_allowed: Dict[str, float] = {}
        self.user_always_allowed: Set[str] = set(extra_always_allowed or [])
        self.on_blocked_url = on_blocked_url
        self.on_off_topic = on_off_topic
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._title_thread: Optional[threading.Thread] = None
        # domain -> set of tab IDs currently being handled
        self._handling: Set[str] = set()
        self._handling_origin: Dict[str, str] = {}   # domain -> ws_url of origin tab
        self._last_url_by_tab: Dict[str, str] = {}   # ws_url -> last seen url
        self._last_title_by_tab: Dict[str, str] = {} # ws_url -> last seen title
        self._title_cooldown_until: Dict[str, float] = {}
        self.session_name: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    def set_session_allowed_domains(self, domains: List[str]):
        self.session_allowed_domains = set(domains)

    def allow_domain_temporarily(self, domain: str, minutes: int = 15):
        self.temporarily_allowed[domain] = time.time() + minutes * 60
        self._handling.discard(domain)
        self._handling_origin.pop(domain, None)

    def set_title_cooldown(self, domain: str, seconds: int = 120):
        self._title_cooldown_until[domain] = time.time() + seconds

    def deny_domain(self, domain: str, ws_url: Optional[str] = None, close_tab: bool = True):
        if close_tab and ws_url:
            self.close_tab(ws_url)
        elif close_tab:
            self.close_active_tab()
        self._handling.discard(domain)

    def revoke_domain(self, domain: str, ws_url: Optional[str] = None):
        self.temporarily_allowed.pop(domain, None)
        self._last_url_by_tab.pop(ws_url, None) if ws_url else None
        if ws_url:
            self.close_tab(ws_url)
        else:
            self.close_active_tab()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._title_thread = threading.Thread(target=self._title_loop, daemon=True)
        self._title_thread.start()

    def stop(self):
        self._running = False
        self.session_allowed_domains.clear()
        self.temporarily_allowed.clear()
        self._handling.clear()
        self._handling_origin.clear()
        self._last_checked_title = ""
        self._title_cooldown_until.clear()

    # ── Tab control (replaces all osascript) ──────────────────────────────

    def close_tab(self, ws_url: str):
        """Close a specific tab by its WebSocket debugger URL."""
        tabs = _cdp_tabs()
        # If it's the only tab in its window, navigate to blank instead
        tab = next((t for t in tabs if t.get("webSocketDebuggerUrl") == ws_url), None)
        if tab:
            _close_tab(ws_url)

    def close_active_tab(self):
        """Close (or blank) the frontmost Chrome tab."""
        tabs = _cdp_tabs()
        if tabs:
            ws_url = tabs[0].get("webSocketDebuggerUrl", "")
            if len(tabs) > 1:
                _close_tab(ws_url)
            else:
                _navigate_tab(ws_url, "about:blank")

    def redirect_tab(self, ws_url: str, url: str = "about:blank"):
        _navigate_tab(ws_url, url)

    def navigate_chrome_to(self, url: str):
        tabs = _cdp_tabs()
        if tabs:
            _navigate_tab(tabs[0]["webSocketDebuggerUrl"], url)

    def open_url_in_new_tab(self, url: str):
        """Open a URL in a new Chrome tab via CDP."""
        if not _REQUESTS:
            return
        try:
            resp = _requests.get(f"{CDP_HOST}/json/new?{url}", timeout=2)
        except Exception:
            pass

    def pin_tab_to_blank(self, ws_url: str):
        """Return a stop callable. Background thread keeps the tab on about:blank,
        snapping back if the user presses back/forward to escape."""
        stop = threading.Event()

        def watcher():
            while not stop.wait(0.4):
                try:
                    live_url = _get_tab_url(ws_url)
                    if live_url and live_url != "about:blank":
                        _navigate_tab(ws_url, "about:blank")
                except Exception:
                    pass

        t = threading.Thread(target=watcher, daemon=True)
        t.start()
        return stop.set

    # ── Allow checking ────────────────────────────────────────────────────

    def _is_allowed(self, domain: str) -> bool:
        candidate = domain[4:] if domain.startswith("www.") else domain
        for allowed in ALWAYS_ALLOWED_DOMAINS | self.user_always_allowed:
            if candidate == allowed or candidate.endswith("." + allowed):
                return True
        for allowed in self.session_allowed_domains:
            if candidate == allowed or candidate.endswith("." + allowed):
                return True
        if domain in self.temporarily_allowed:
            if self.temporarily_allowed[domain] > time.time():
                return True
            del self.temporarily_allowed[domain]
        return False

    def _is_temp_allowed(self, domain: str) -> bool:
        if domain in self.temporarily_allowed:
            return self.temporarily_allowed[domain] > time.time()
        return False

    def _extract_domain(self, url: str) -> Optional[str]:
        match = re.match(r'(\w+)://', url)
        if match and match.group(1) in INTERNAL_SCHEMES:
            return None
        match = re.search(r'https?://(?:www\.)?([^/?\s#]+)', url)
        return match.group(1).lower() if match else None

    # ── URL monitoring loop ───────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                tabs = _cdp_tabs()
                live_ws = {t["webSocketDebuggerUrl"] for t in tabs if "webSocketDebuggerUrl" in t}

                # Drop stale cache entries
                for stale in list(self._last_url_by_tab):
                    if stale not in live_ws:
                        self._last_url_by_tab.pop(stale, None)

                for tab in tabs:
                    ws_url = tab.get("webSocketDebuggerUrl", "")
                    url = tab.get("url", "")
                    title = tab.get("title", "")
                    if not url or not ws_url:
                        continue
                    if self._last_url_by_tab.get(ws_url) == url:
                        continue

                    domain = self._extract_domain(url)
                    if not domain:
                        self._last_url_by_tab[ws_url] = url
                        continue

                    if not self._is_allowed(domain):
                        self._last_url_by_tab.pop(ws_url, None)

                        if domain in self._handling:
                            # Dialog already running; block bypass attempts
                            if self._handling_origin.get(domain) != ws_url:
                                _navigate_tab(ws_url, "about:blank")
                            continue

                        self._handling.add(domain)
                        self._handling_origin[domain] = ws_url

                        try:
                            _log_event("url_blocked", domain=domain, url=url,
                                       session_name=self.session_name)
                        except Exception:
                            pass

                        threading.Thread(
                            target=self._handle_violation,
                            args=(domain, url, ws_url, title),
                            daemon=True,
                        ).start()
                    else:
                        self._last_url_by_tab[ws_url] = url
                        try:
                            _log_event("tab_visit", domain=domain,
                                       session_name=self.session_name)
                        except Exception:
                            pass

            except Exception:
                pass

            time.sleep(self.poll_seconds)

    def _handle_violation(self, domain: str, original_url: str,
                           ws_url: Optional[str], tab_title: str):
        try:
            self.on_blocked_url(domain, original_url, ws_url, tab_title)
        finally:
            self._handling.discard(domain)
            self._handling_origin.pop(domain, None)

    # ── Title monitoring loop ─────────────────────────────────────────────

    def _title_loop(self):
        time.sleep(2)
        while self._running:
            try:
                tabs = _cdp_tabs()
                live_ws = {t["webSocketDebuggerUrl"] for t in tabs if "webSocketDebuggerUrl" in t}
                for stale in list(self._last_title_by_tab):
                    if stale not in live_ws:
                        self._last_title_by_tab.pop(stale, None)

                now = time.time()
                for d in list(self._title_cooldown_until):
                    if self._title_cooldown_until[d] <= now:
                        self._title_cooldown_until.pop(d, None)

                for tab in tabs:
                    ws_url = tab.get("webSocketDebuggerUrl", "")
                    url = tab.get("url", "")
                    title = tab.get("title", "")
                    if not url or not ws_url:
                        continue
                    domain = self._extract_domain(url)
                    if not domain or not self._is_temp_allowed(domain):
                        continue
                    if not title or title.lower().strip() in TITLE_IGNORE:
                        continue
                    if self._title_cooldown_until.get(domain, 0) > now:
                        continue
                    if self._last_title_by_tab.get(ws_url) == title:
                        continue
                    self._last_title_by_tab[ws_url] = title

                    if domain in self._handling:
                        continue

                    if self.on_off_topic:
                        self._handling.add(domain)
                        threading.Thread(
                            target=self._handle_title_check,
                            args=(domain, title, ws_url),
                            daemon=True,
                        ).start()

            except Exception:
                pass

            time.sleep(8)

    def _handle_title_check(self, domain: str, title: str, ws_url: Optional[str]):
        try:
            if self.on_off_topic:
                self.on_off_topic(domain, title, ws_url)
        finally:
            self._handling.discard(domain)
