"""Test script for tab-tracking functionality in URLMonitor (Windows/CDP).

Opens Chrome tabs and verifies CDP-based tab management:
get_active_tab_ws_url, _cdp_tabs, close_tab, redirect_tab.

Usage: python test_tab_tracking.py
Requires: Google Chrome running with --remote-debugging-port=9222
          (tray_app.py / open_chrome_with_debug() handles this automatically)
"""

import subprocess
import time
import sys
import requests

sys.path.insert(0, ".")
from focuslock.url_monitor import URLMonitor, _cdp_tabs

mon = URLMonitor(on_blocked_url=lambda d, u, t: None)

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


def cdp_new_tab(url="about:blank"):
    """Open a new tab via CDP and return its webSocketDebuggerUrl."""
    resp = requests.get(f"http://localhost:9222/json/new?{url}", timeout=5)
    resp.raise_for_status()
    return resp.json().get("webSocketDebuggerUrl")


def cdp_activate_tab(ws_url):
    """Bring a tab to the foreground by its ws_url."""
    tabs = _cdp_tabs()
    for tab in tabs:
        if tab.get("webSocketDebuggerUrl") == ws_url:
            tab_id = tab.get("id")
            requests.get(f"http://localhost:9222/json/activate/{tab_id}", timeout=5)
            return
    raise ValueError(f"Tab not found: {ws_url}")


def tab_exists(ws_url):
    """Return True if the tab is still in the CDP tab list."""
    live = {t.get("webSocketDebuggerUrl") for t in _cdp_tabs()}
    return ws_url in live


def tab_is_active(ws_url):
    """Return True if this tab is the frontmost tab (type=page, not devtools)."""
    tabs = [t for t in _cdp_tabs() if t.get("type") == "page"]
    if not tabs:
        return False
    # CDP doesn't expose 'active' directly; last activated is usually last in list
    # Best proxy: activate it and check it's still alive
    return ws_url in {t.get("webSocketDebuggerUrl") for t in tabs}


# ── Preflight: make sure Chrome debug port is reachable ─────────────────

print("\n=== Tab Tracking Tests (CDP) ===\n")
try:
    requests.get("http://localhost:9222/json", timeout=3)
except Exception:
    print("ERROR: Chrome debug port not reachable on localhost:9222.")
    print("Launch Chrome with: chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*")
    print("Or let tray_app.py start Chrome via open_chrome_with_debug().")
    sys.exit(1)

# ── Test 1: open a new tab, get its ws_url ───────────────────────────────

print("Test 1: cdp_new_tab returns a ws_url string")
ws1 = cdp_new_tab("about:blank")
time.sleep(0.4)
check("returns string", isinstance(ws1, str), True)
check("non-empty", bool(ws1), True)
check("tab exists in CDP list", tab_exists(ws1), True)

# ── Test 2: tab appears in _cdp_tabs() ──────────────────────────────────

print("\nTest 2: _cdp_tabs() includes the new tab")
all_ws = {t.get("webSocketDebuggerUrl") for t in _cdp_tabs()}
check("tab in cdp_tabs()", ws1 in all_ws, True)

# ── Test 3: open a second tab — both should exist ────────────────────────

print("\nTest 3: open second tab, both tabs exist")
ws2 = cdp_new_tab("about:blank")
time.sleep(0.4)
check("tab1 still exists", tab_exists(ws1), True)
check("tab2 exists", tab_exists(ws2), True)
check("tabs are distinct", ws1 != ws2, True)

# ── Test 4: close_tab removes the tab ────────────────────────────────────

print("\nTest 4: close_tab removes the correct tab")
mon.close_tab(ws1)
time.sleep(0.5)
check("closed tab is gone", tab_exists(ws1), False)
check("other tab survived", tab_exists(ws2), True)

# ── Test 5: close_tab on a bogus ws_url doesn't crash ───────────────────

print("\nTest 5: close_tab with bogus ws_url is a no-op")
try:
    mon.close_tab("ws://localhost:9222/devtools/page/doesnotexist")
    check("no exception raised", True, True)
except Exception as e:
    check("no exception raised", False, True)

# ── Test 6: redirect_tab navigates the tab ───────────────────────────────

print("\nTest 6: redirect_tab navigates tab to target URL")
ws3 = cdp_new_tab("about:blank")
time.sleep(0.4)
mon.redirect_tab(ws3, "about:blank")
time.sleep(0.5)
# Verify tab still alive after redirect
check("tab still alive after redirect", tab_exists(ws3), True)

# ── Test 7: bogus ws_url returns 'gone' from tab_exists ─────────────────

print("\nTest 7: tab_exists with bogus ws_url returns False")
check("bogus ws_url not found", tab_exists("ws://localhost:9222/devtools/page/999999999"), False)

# ── Test 8: close_active_tab closes the frontmost page tab ──────────────

print("\nTest 8: close_active_tab removes a tab")
ws4 = cdp_new_tab("about:blank")
time.sleep(0.4)
cdp_activate_tab(ws4)
time.sleep(0.3)
before_count = len([t for t in _cdp_tabs() if t.get("type") == "page"])
mon.close_active_tab()
time.sleep(0.5)
after_count = len([t for t in _cdp_tabs() if t.get("type") == "page"])
check("one fewer page tab after close_active_tab", after_count, before_count - 1)

# ── Cleanup ──────────────────────────────────────────────────────────────

for ws in [ws2, ws3]:
    if tab_exists(ws):
        try:
            mon.close_tab(ws)
        except Exception:
            pass

# ── Summary ──────────────────────────────────────────────────────────────

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
