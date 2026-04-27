"""Test script for tab-tracking functionality in URLMonitor.

Opens Chrome tabs and verifies get_active_tab_id, check_tab_status,
and close_tab_by_id behave correctly.

Usage: python test_tab_tracking.py
Requires: Google Chrome running (will open/close tabs).
"""

import subprocess
import time
import sys

sys.path.insert(0, ".")
from focuslock.url_monitor import URLMonitor

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


def run_apple(script):
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def ensure_chrome():
    """Make sure Chrome is running with at least one window."""
    run_apple("""
        tell application "Google Chrome" to activate
        delay 0.5
        tell application "Google Chrome"
            if (count of windows) = 0 then
                make new window
            end if
        end tell
    """)
    time.sleep(1)


# ── Setup ────────────────────────────────────────────────────────────────

print("\n=== Tab Tracking Tests ===\n")
ensure_chrome()

# ── Test 1: get_active_tab_id returns an integer ─────────────────────────

print("Test 1: get_active_tab_id returns an integer")
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "about:blank"')
time.sleep(0.5)
tab_id = mon.get_active_tab_id()
check("returns int", isinstance(tab_id, int), True)
check("positive", tab_id is not None and tab_id > 0, True)

# ── Test 2: active tab reports 'active' ──────────────────────────────────

print("\nTest 2: check_tab_status on active tab")
status = mon.check_tab_status(tab_id)
check("status is active", status, "active")

# ── Test 3: opening a new tab makes the old one 'background' ────────────

print("\nTest 3: old tab becomes 'background' after opening new tab")
run_apple("""
    tell application "Google Chrome"
        tell front window to make new tab with properties {URL:"about:blank"}
    end tell
""")
time.sleep(0.5)
status = mon.check_tab_status(tab_id)
check("old tab is background", status, "background")

new_tab_id = mon.get_active_tab_id()
check("new tab is different", new_tab_id != tab_id, True)
check("new tab is active", mon.check_tab_status(new_tab_id), "active")

# ── Test 4: close_tab_by_id closes the right tab ────────────────────────

print("\nTest 4: close_tab_by_id closes background tab, not active")
mon.close_tab_by_id(tab_id)
time.sleep(0.5)
check("closed tab is gone", mon.check_tab_status(tab_id), "gone")
check("active tab still exists", mon.check_tab_status(new_tab_id), "active")

# ── Test 5: close_tab_by_id on active tab ────────────────────────────────

print("\nTest 5: close_tab_by_id on the active tab")
# Open a second tab so closing the active one doesn't leave 0 tabs
run_apple("""
    tell application "Google Chrome"
        tell front window to make new tab with properties {URL:"about:blank"}
    end tell
""")
time.sleep(0.5)
spare_id = mon.get_active_tab_id()

# Switch back to new_tab_id and close it
run_apple(f"""
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if id of t = {new_tab_id} then
                    set active tab index of w to (index of t)
                    set index of w to 1
                    return
                end if
            end repeat
        end repeat
    end tell
""")
time.sleep(0.5)
mon.close_tab_by_id(new_tab_id)
time.sleep(0.5)
check("closed tab is gone", mon.check_tab_status(new_tab_id), "gone")
check("spare tab survived", mon.check_tab_status(spare_id) in ("active", "background"), True)

# ── Test 6: check_tab_status with bogus ID returns 'gone' ───────────────

print("\nTest 6: bogus tab ID returns 'gone'")
check("bogus id", mon.check_tab_status(999999999), "gone")

# ── Test 7: close_tab_by_id with last tab sets about:blank ──────────────

print("\nTest 7: closing the only tab in a window sets about:blank")
# Close all tabs except one
run_apple("""
    tell application "Google Chrome"
        set w to front window
        repeat while (count of tabs of w) > 1
            close last tab of w
        end repeat
        set URL of active tab of w to "https://example.com"
    end tell
""")
time.sleep(1)
only_tab_id = mon.get_active_tab_id()
mon.close_tab_by_id(only_tab_id)
time.sleep(0.5)
url = mon._get_chrome_url() or ""
check("tab set to about:blank", url, "about:blank")

# ── Summary ──────────────────────────────────────────────────────────────

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
