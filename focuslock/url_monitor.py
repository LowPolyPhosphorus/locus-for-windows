"""Block all websites in Chrome except those on the session whitelist."""

import threading
import time
import subprocess
import re
from typing import Set, Dict, Callable, Optional, List

try:
    from .analytics import log_event as _log_event
except Exception:
    def _log_event(*a, **kw): pass


# Internal browser pages — never block these
INTERNAL_SCHEMES = {"chrome", "about", "data", "chrome-extension", "devtools"}

# Always allowed in any session (core school tools)
ALWAYS_ALLOWED_DOMAINS = {"notion.so", "notionusercontent.com", "music.youtube.com"}

# Tab titles too generic to bother checking
TITLE_IGNORE = {"youtube", "youtube music", "google", "new tab", "claude", ""}


class URLMonitor:
    def __init__(
        self,
        on_blocked_url: Callable[[str, str, Optional[int], str], None],
        on_off_topic: Optional[Callable[[str, str, Optional[int]], None]] = None,
        poll_seconds: float = 2,
        extra_always_allowed: Optional[List[str]] = None,
    ):
        self.session_allowed_domains: Set[str] = set()
        self.temporarily_allowed: Dict[str, float] = {}  # domain -> expiry
        self.user_always_allowed: Set[str] = set(extra_always_allowed or [])
        self.on_blocked_url = on_blocked_url
        self.on_off_topic = on_off_topic
        self.poll_seconds = max(0.5, float(poll_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._title_thread: Optional[threading.Thread] = None
        self._handling: Set[str] = set()
        # Tab that kicked off each in-flight handler. The bypass guard must
        # NOT redirect this tab while its pre-screen is running, or an
        # auto-allow ends up landing on about:blank.
        self._handling_origin: Dict[str, int] = {}
        self._last_url: str = ""
        self._last_url_by_tab: Dict[int, str] = {}
        self._last_checked_title: str = ""
        self._last_title_by_tab: Dict[int, str] = {}
        # Per-domain cooldown for title-based off-topic checks. Prevents a
        # re-flag loop right after the user explicitly approved a reason —
        # the AI can flip-flop on ambiguous titles/homepages.
        self._title_cooldown_until: Dict[str, float] = {}
        self.session_name: str = ""

    def set_session_allowed_domains(self, domains: List[str]):
        self.session_allowed_domains = set(domains)

    def allow_domain_temporarily(self, domain: str, minutes: int = 15):
        self.temporarily_allowed[domain] = time.time() + minutes * 60
        self._handling.discard(domain)
        self._handling_origin.pop(domain, None)

    def set_title_cooldown(self, domain: str, seconds: int = 120):
        """After user-approves a reason, suppress title-based off-topic checks
        for this domain for `seconds`. Prevents AI flip-flop re-flag loops."""
        self._title_cooldown_until[domain] = time.time() + seconds

    def deny_domain(self, domain: str, close_tab: bool = True):
        if close_tab:
            self.close_chrome_tab()
        self._handling.discard(domain)

    def revoke_domain(self, domain: str, tab_id: Optional[int] = None):
        """Remove from temporarily allowed and close the specific tab (or active if unknown)."""
        self.temporarily_allowed.pop(domain, None)
        self._last_url = ""
        if tab_id:
            self.close_tab_by_id(tab_id)
        else:
            self.close_chrome_tab()

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

    def _is_allowed(self, domain: str) -> bool:
        # Strip a leading "www." from the candidate so "www.youtube.com" matches
        # an allowlist entry of "youtube.com". Only www — not www2, m, etc.
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
        """True only if allowed via temporary grant (not session whitelist)."""
        if domain in self.temporarily_allowed:
            return self.temporarily_allowed[domain] > time.time()
        return False

    def _get_chrome_url(self) -> Optional[str]:
        script = """
try
    tell application "Google Chrome"
        if (count of windows) > 0 then
            set w to front window
            if (count of tabs of w) > 0 then
                return URL of active tab of w
            end if
        end if
    end tell
on error
    return ""
end try
"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            url = result.stdout.strip()
            return url if url else None
        except Exception:
            return None

    def _get_chrome_title(self) -> Optional[str]:
        script = """
try
    tell application "Google Chrome"
        if (count of windows) > 0 then
            set w to front window
            if (count of tabs of w) > 0 then
                return title of active tab of w
            end if
        end if
    end tell
on error
    return ""
end try
"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            t = result.stdout.strip()
            return t if t else None
        except Exception:
            return None

    def _get_active_tabs(self) -> List[tuple]:
        """Return (tab_id, url, title) for the active tab of every Chrome window."""
        script = """
try
    set out to ""
    tell application "Google Chrome"
        repeat with w in windows
            try
                set t to active tab of w
                set out to out & (id of t) & "|~|" & (URL of t) & "|~|" & (title of t) & "<<END>>"
            end try
        end repeat
    end tell
    return out
on error
    return ""
end try
"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            tabs: List[tuple] = []
            for entry in result.stdout.split("<<END>>"):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split("|~|", 2)
                if len(parts) < 3:
                    continue
                try:
                    tab_id = int(parts[0])
                except ValueError:
                    continue
                tabs.append((tab_id, parts[1], parts[2]))
            return tabs
        except Exception:
            return []

    def _extract_domain(self, url: str) -> Optional[str]:
        match = re.match(r'(\w+)://', url)
        if match and match.group(1) in INTERNAL_SCHEMES:
            return None
        match = re.search(r'https?://(?:www\.)?([^/?\s#]+)', url)
        return match.group(1).lower() if match else None

    def get_active_tab_id(self) -> Optional[int]:
        """Return the Chrome tab ID of the current active tab."""
        script = """
try
    tell application "Google Chrome"
        if (count of windows) > 0 then
            return id of active tab of front window
        end if
    end tell
on error
    return ""
end try
"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            val = result.stdout.strip()
            return int(val) if val else None
        except Exception:
            return None

    def check_tab_status(self, tab_id: int) -> str:
        """Check if a tab is 'active', 'background', or 'gone'."""
        script = f"""
try
    tell application "Google Chrome"
        set targetId to "{tab_id}"
        repeat with w in windows
            repeat with t in tabs of w
                if (id of t) as text = targetId then
                    if (id of active tab of w) as text = targetId then
                        return "active"
                    else
                        return "background"
                    end if
                end if
            end repeat
        end repeat
        return "gone"
    end tell
on error
    return "active"
end try
"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            out = result.stdout.strip()
            # On any failure, assume "active" so we don't silently close a
            # tab the user is actually on. "gone" is only returned when
            # Chrome definitively reports the tab doesn't exist.
            if out in ("active", "background", "gone"):
                return out
            return "active"
        except Exception:
            return "active"

    def close_tab_by_id(self, tab_id: int):
        """Close a specific Chrome tab by its ID."""
        script = f"""
tell application "Google Chrome"
    set targetId to "{tab_id}"
    repeat with w in windows
        set tabList to tabs of w
        repeat with i from (count of tabList) to 1 by -1
            set t to item i of tabList
            if (id of t) as text = targetId then
                if (count of tabList) > 1 then
                    close t
                else
                    set URL of t to "about:blank"
                end if
                return
            end if
        end repeat
    end repeat
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def close_chrome_tab(self):
        script = """
tell application "Google Chrome"
    if (count of windows) > 0 then
        set w to front window
        if (count of tabs of w) > 1 then
            close active tab of w
        else
            set URL of active tab of w to "about:blank"
        end if
    end if
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def redirect_chrome(self):
        script = """
tell application "Google Chrome"
    if (count of windows) > 0 then
        set URL of active tab of front window to "about:blank"
    end if
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def redirect_tab_by_id(self, tab_id: int):
        """Redirect a specific Chrome tab to about:blank without closing it."""
        script = f"""
tell application "Google Chrome"
    set targetId to "{tab_id}"
    repeat with w in windows
        repeat with t in tabs of w
            if (id of t) as text = targetId then
                set URL of t to "about:blank"
                return
            end if
        end repeat
    end repeat
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def pin_tab_to_blank(self, tab_id: int):
        """Returns a (stop) callable. Spawns a background thread that keeps
        the given tab on about:blank — if the user presses back/forward to
        navigate to a non-blank URL, snap it back. Used to prevent the user
        from escaping a blocked-site dialog via Chrome's back button."""
        import threading
        stop = threading.Event()

        def watcher():
            check = f"""
tell application "Google Chrome"
    set targetId to "{tab_id}"
    repeat with w in windows
        repeat with t in tabs of w
            if (id of t) as text = targetId then
                return URL of t
            end if
        end repeat
    end repeat
    return ""
end tell
"""
            while not stop.wait(0.4):
                try:
                    out = subprocess.run(
                        ["osascript", "-e", check],
                        capture_output=True, text=True, timeout=3,
                    )
                    url = (out.stdout or "").strip()
                    if url and url != "about:blank":
                        self.redirect_tab_by_id(tab_id)
                except Exception:
                    pass

        t = threading.Thread(target=watcher, daemon=True)
        t.start()
        return stop.set

    def navigate_tab_by_id(self, tab_id: int, url: str):
        """Navigate a specific Chrome tab to a URL."""
        escaped = url.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""
tell application "Google Chrome"
    set targetId to "{tab_id}"
    repeat with w in windows
        repeat with t in tabs of w
            if (id of t) as text = targetId then
                set URL of t to "{escaped}"
                return
            end if
        end repeat
    end repeat
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def open_url_in_new_tab(self, url: str):
        """Open the URL in a new Chrome tab in the front window (or create a window)."""
        escaped = url.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""
tell application "Google Chrome"
    activate
    if (count of windows) = 0 then
        make new window
        set URL of active tab of front window to "{escaped}"
    else
        tell front window
            make new tab with properties {{URL:"{escaped}"}}
        end tell
    end if
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def navigate_chrome_to(self, url: str):
        escaped = url.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""
tell application "Google Chrome"
    if (count of windows) > 0 then
        set URL of active tab of front window to "{escaped}"
    end if
end tell
"""
        subprocess.run(["osascript", "-e", script], capture_output=True)

    # ── URL monitoring loop ───────────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                tabs = self._get_active_tabs()
                live_ids = {tid for tid, _, _ in tabs}
                # Drop cached URLs for tabs that no longer exist
                for stale in list(self._last_url_by_tab.keys()):
                    if stale not in live_ids:
                        self._last_url_by_tab.pop(stale, None)

                for tab_id, url, title in tabs:
                    if not url or self._last_url_by_tab.get(tab_id) == url:
                        continue

                    domain = self._extract_domain(url)
                    if not domain:
                        self._last_url_by_tab[tab_id] = url
                        continue

                    if not self._is_allowed(domain):
                        # Don't cache blocked URLs — if the user navigates
                        # back we want to re-evaluate.
                        self._last_url_by_tab.pop(tab_id, None)

                        if domain in self._handling:
                            # Dialog/pre-screen already running for this domain.
                            # Exempt the originating tab — redirecting it now
                            # would blank a page that may still be auto-allowed.
                            # Other tabs are bypass attempts; redirect those.
                            if self._handling_origin.get(domain) != tab_id:
                                self.redirect_tab_by_id(tab_id)
                            continue

                        # First sighting: let the handler run the auto-allow
                        # pre-screen before we touch the tab. If the AI
                        # approves (e.g. khanacademy.org for a school
                        # session), the tab keeps loading with no flicker.
                        # If the AI denies, the handler redirects to blank
                        # and prompts. The 1-2s pre-screen window is the
                        # cost of avoiding a visible about:blank bounce.
                        self._handling.add(domain)
                        self._handling_origin[domain] = tab_id

                        try:
                            _log_event("url_blocked", domain=domain, url=url,
                                       session_name=self.session_name)
                        except Exception:
                            pass

                        threading.Thread(
                            target=self._handle_violation,
                            args=(domain, url, tab_id, title or ""),
                            daemon=True,
                        ).start()
                    else:
                        self._last_url_by_tab[tab_id] = url
                        try:
                            _log_event("tab_visit", domain=domain,
                                       session_name=self.session_name)
                        except Exception:
                            pass

            except Exception:
                pass

            time.sleep(self.poll_seconds)

    def _handle_violation(self, domain: str, original_url: str, tab_id: Optional[int], tab_title: str):
        try:
            self.on_blocked_url(domain, original_url, tab_id, tab_title)
        finally:
            self._handling.discard(domain)
            self._handling_origin.pop(domain, None)

    # ── Title monitoring loop ─────────────────────────────────────────────

    def _title_loop(self):
        """Every 8s, check the tab title if on a temporarily-allowed video site."""
        # Small cold-start delay so we don't hammer Chrome right as the
        # session begins, but not so long that the first off-topic content
        # goes unchecked for 8s.
        time.sleep(2)
        while self._running:
            try:
                tabs = self._get_active_tabs()
                live_ids = {tid for tid, _, _ in tabs}
                for stale in list(self._last_title_by_tab.keys()):
                    if stale not in live_ids:
                        self._last_title_by_tab.pop(stale, None)

                now = time.time()
                # Drop expired title cooldowns so the dict doesn't grow forever.
                for d in list(self._title_cooldown_until.keys()):
                    if self._title_cooldown_until[d] <= now:
                        self._title_cooldown_until.pop(d, None)

                for tab_id, url, title in tabs:
                    if not url:
                        continue
                    domain = self._extract_domain(url)
                    if not domain or not self._is_temp_allowed(domain):
                        continue
                    if not title or title.lower().strip() in TITLE_IGNORE:
                        continue
                    # Respect post-approval cooldown — prevents the re-flag
                    # loop where the AI keeps flagging a site right after
                    # the user got it approved. Crucially, do NOT update the
                    # title cache during cooldown: if we did, a title the
                    # user navigated to mid-cooldown would be treated as
                    # already-checked once cooldown lifts, and stay invisible
                    # to the off-topic detector forever.
                    if self._title_cooldown_until.get(domain, 0) > now:
                        continue
                    if self._last_title_by_tab.get(tab_id) == title:
                        continue
                    self._last_title_by_tab[tab_id] = title

                    if domain in self._handling:
                        continue

                    if self.on_off_topic:
                        self._handling.add(domain)
                        threading.Thread(
                            target=self._handle_title_check,
                            args=(domain, title, tab_id),
                            daemon=True,
                        ).start()

            except Exception:
                pass

            time.sleep(8)

    def _handle_title_check(self, domain: str, title: str, tab_id: Optional[int]):
        try:
            if self.on_off_topic:
                self.on_off_topic(domain, title, tab_id)
        finally:
            self._handling.discard(domain)
