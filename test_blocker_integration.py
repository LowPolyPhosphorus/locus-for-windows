"""Integration tests for the blocked-URL tab-tracking logic in app._on_blocked_url.

Windows version — replaces all AppleScript/osascript calls with CDP
(Chrome DevTools Protocol) via the url_monitor helpers.

Prerequisites:
    1. Chrome must be running with --remote-debugging-port=9222
       e.g.  chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
    2. pip install requests websocket-client

Run:
    python test_blocker_integration.py
"""

import sys
import time

sys.path.insert(0, ".")

from focuslock.url_monitor import URLMonitor, _cdp_tabs, _navigate_tab, _close_tab

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    ok = got == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}: got={got!r}, expected={expected!r}")
    if ok:
        passed += 1
    else:
        failed += 1


# ── CDP helpers used only in tests ────────────────────────────────────────────

def _get_tab_url_by_ws(ws_url: str) -> str:
    """Return current URL of a tab by its ws URL, or '' if gone."""
    for t in _cdp_tabs():
        if t.get("webSocketDebuggerUrl") == ws_url:
            return t.get("url", "")
    return ""


def _tab_exists(ws_url: str) -> bool:
    return any(t.get("webSocketDebuggerUrl") == ws_url for t in _cdp_tabs())


def _open_tab(url: str) -> str:
    """Open a new Chrome tab at url, return its ws_url. Returns '' on failure."""
    import requests as _req
    try:
        resp = _req.get(f"http://localhost:9222/json/new?{url}", timeout=3)
        tab = resp.json()
        ws = tab.get("webSocketDebuggerUrl", "")
        time.sleep(0.6)
        return ws
    except Exception as e:
        print(f"  [ERROR] _open_tab failed: {e}")
        return ""


def _close_tab_by_ws(ws_url: str):
    _close_tab(ws_url)
    time.sleep(0.3)


def reset_chrome():
    """Leave exactly one about:blank tab open."""
    tabs = _cdp_tabs()
    if not tabs:
        _open_tab("about:blank")
        time.sleep(0.5)
        return
    # Keep the first tab, close the rest
    keep = tabs[0]["webSocketDebuggerUrl"]
    _navigate_tab(keep, "about:blank")
    for t in tabs[1:]:
        ws = t.get("webSocketDebuggerUrl", "")
        if ws:
            _close_tab(ws)
    time.sleep(0.5)


# ── Fake classes (identical logic to macOS version) ───────────────────────────

class FakeClaude:
    def __init__(self, auto_allow=False):
        self.auto_allow = auto_allow

    def evaluate_site_relevance(self, domain, session, title):
        return self.auto_allow, "fake reason"


class FakeApp:
    """Mirrors app._on_blocked_url logic with CDP tab IDs (ws_url strings)."""
    def __init__(self, url_monitor, claude):
        self.url_monitor = url_monitor
        self.claude = claude
        self.config = {"temporary_allow_minutes": 15}
        self.dialog_shown = False
        self.dialog_response = ("cancel", "")

    def fake_ask_reason(self, *a, **kw):
        self.dialog_shown = True
        return self.dialog_response

    def on_blocked_url(self, domain, original_url, ws_url):
        session_name = "Test"
        tab_title = ""
        tabs = _cdp_tabs()
        for t in tabs:
            if t.get("webSocketDebuggerUrl") == ws_url:
                tab_title = t.get("title", "")
                break

        auto_allow, _ = self.claude.evaluate_site_relevance(domain, session_name, tab_title)
        if auto_allow:
            self.url_monitor.allow_domain_temporarily(domain, minutes=15)
            return

        if ws_url:
            # Check if tab is still alive and active
            live_ws = {t.get("webSocketDebuggerUrl") for t in _cdp_tabs()}
            if ws_url not in live_ws:
                return  # gone → no-op
            # Check if it's active (frontmost) or background
            # In CDP, we can't easily tell which tab is "active" across windows,
            # so we check if the ws_url is the first tab in the list (heuristic)
            # A proper check would use the Browser.getWindowForTarget CDP call.
            # For testing purposes we track which tab we designated as "background".
            status = self._tab_status(ws_url)
            if status == "background":
                self.url_monitor.close_tab(ws_url)
                return
            self.url_monitor.redirect_tab(ws_url, "about:blank")
        else:
            self.url_monitor.close_active_tab()

        action, reason = self.fake_ask_reason(domain, "website", session_name)
        if action == "cancel" and ws_url:
            self.url_monitor.close_tab(ws_url)

    def _tab_status(self, ws_url: str) -> str:
        """Simplified status: uses _background_tabs set injected by test."""
        if ws_url in getattr(self, "_background_tabs", set()):
            return "background"
        return "active" if _tab_exists(ws_url) else "gone"


# ── Tests ─────────────────────────────────────────────────────────────────────

print("\n=== Integration Tests (Windows/CDP) ===\n")

mon = URLMonitor(on_blocked_url=lambda d, u, t: None)

# Check Chrome is reachable
tabs = _cdp_tabs()
if not tabs:
    print("ERROR: Cannot reach Chrome on localhost:9222.")
    print("Launch Chrome with:  chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*")
    sys.exit(1)

# ── Test 1: active tab → redirected to blank + dialog shown ──────────────────

print("Test 1: active → blank + dialog")
reset_chrome()
blocked_ws = _open_tab("https://example.com")
if not blocked_ws:
    print("  [SKIP] Could not open tab")
else:
    app = FakeApp(mon, FakeClaude(auto_allow=False))
    app.dialog_response = ("cancel", "")
    app.on_blocked_url("example.com", "https://example.com", blocked_ws)

    check("dialog shown", app.dialog_shown, True)
    url_after = _get_tab_url_by_ws(blocked_ws)
    tab_gone = not _tab_exists(blocked_ws)
    check("tab redirected or closed", "about:blank" in url_after or tab_gone, True)

# ── Test 2: background tab → silent close, no dialog ─────────────────────────

print("\nTest 2: background → silent close, no dialog")
reset_chrome()
blocked_ws = _open_tab("https://example.com")
spare_ws   = _open_tab("about:blank")   # user switches to this

if not blocked_ws or not spare_ws:
    print("  [SKIP] Could not open tabs")
else:
    app = FakeApp(mon, FakeClaude(auto_allow=False))
    app._background_tabs = {blocked_ws}   # tell FakeApp this tab is background
    app.on_blocked_url("example.com", "https://example.com", blocked_ws)

    check("no dialog", app.dialog_shown, False)
    check("blocked tab gone", not _tab_exists(blocked_ws), True)
    check("spare tab alive", _tab_exists(spare_ws), True)

# ── Test 3: tab already closed → no-op ───────────────────────────────────────

print("\nTest 3: gone → no-op")
reset_chrome()
blocked_ws = _open_tab("https://example.com")
alive_ws   = _open_tab("about:blank")

if not blocked_ws or not alive_ws:
    print("  [SKIP] Could not open tabs")
else:
    _close_tab_by_ws(blocked_ws)   # close it before handler runs

    app = FakeApp(mon, FakeClaude(auto_allow=False))
    app.on_blocked_url("example.com", "https://example.com", blocked_ws)

    check("no dialog", app.dialog_shown, False)
    check("alive tab untouched", _tab_exists(alive_ws), True)
    check("alive tab url preserved", "about:blank" in _get_tab_url_by_ws(alive_ws), True)

# ── Test 4: bystander tab not blanked when user switches ─────────────────────

print("\nTest 4: switching tabs doesn't blank bystander")
reset_chrome()
blocked_ws    = _open_tab("https://example.com")
bystander_ws  = _open_tab("https://www.iana.org/domains/example")
time.sleep(0.8)  # let iana.org start loading

if not blocked_ws or not bystander_ws:
    print("  [SKIP] Could not open tabs")
else:
    url_before = _get_tab_url_by_ws(bystander_ws)

    app = FakeApp(mon, FakeClaude(auto_allow=False))
    app._background_tabs = {blocked_ws}
    app.on_blocked_url("example.com", "https://example.com", blocked_ws)

    url_after = _get_tab_url_by_ws(bystander_ws)
    check("bystander URL preserved", url_before, url_after)
    check("bystander still alive", _tab_exists(bystander_ws), True)
    check("blocked tab closed", not _tab_exists(blocked_ws), True)

# ── Test 5: auto_allow skips everything ──────────────────────────────────────

print("\nTest 5: auto_allow path")
reset_chrome()
blocked_ws = _open_tab("https://example.com")

if not blocked_ws:
    print("  [SKIP] Could not open tab")
else:
    app = FakeApp(mon, FakeClaude(auto_allow=True))
    app.on_blocked_url("example.com", "https://example.com", blocked_ws)

    check("no dialog on auto_allow", app.dialog_shown, False)
    check("tab preserved", _tab_exists(blocked_ws), True)
    check("domain temp-allowed", "example.com" in mon.temporarily_allowed, True)

# ── Test 6: no ws_url → fallback to close_active_tab ────────────────────────

print("\nTest 6: missing ws_url falls back to close_active_tab")
reset_chrome()
_open_tab("https://example.com")
time.sleep(0.5)

app = FakeApp(mon, FakeClaude(auto_allow=False))
app.dialog_response = ("cancel", "")
app.on_blocked_url("example.com", "https://example.com", None)
check("dialog shown in fallback", app.dialog_shown, True)

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
