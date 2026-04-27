"""Integration tests for the blocked-URL tab-tracking logic in app._on_blocked_url.

Simulates the three tab states at dialog time: active, background, gone.
Uses a fake ClaudeClient so no API calls happen, and monkey-patches the dialog
to never actually show. Verifies the right tab gets closed / redirected / left alone.
"""

import subprocess
import sys
import time
import types

sys.path.insert(0, ".")
from focuslock.url_monitor import URLMonitor
from focuslock import dialogs

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


def reset_chrome():
    """Close extra tabs, leave one about:blank tab."""
    run_apple("""
        tell application "Google Chrome" to activate
        delay 0.3
        tell application "Google Chrome"
            if (count of windows) = 0 then
                make new window
            end if
            set w to front window
            repeat while (count of tabs of w) > 1
                close last tab of w
            end repeat
            set URL of active tab of w to "about:blank"
        end tell
    """)
    time.sleep(0.8)


def open_tab(url):
    run_apple(f'''
        tell application "Google Chrome"
            tell front window to make new tab with properties {{URL:"{url}"}}
        end tell
    ''')
    time.sleep(0.6)


def switch_to_tab(tab_id):
    run_apple(f"""
        tell application "Google Chrome"
            set targetId to "{tab_id}"
            repeat with w in windows
                set idx to 0
                repeat with t in tabs of w
                    set idx to idx + 1
                    if (id of t) as text = targetId then
                        set active tab index of w to idx
                        return
                    end if
                end repeat
            end repeat
        end tell
    """)
    time.sleep(0.3)


# Build a minimal fake "app" that mimics _on_blocked_url without rumps/claude.
class FakeClaude:
    def __init__(self, auto_allow=False):
        self.auto_allow = auto_allow

    def evaluate_site_relevance(self, domain, session, title):
        return self.auto_allow, "fake reason"


class FakeApp:
    """Mirrors app._on_blocked_url logic exactly (copy from app.py)."""
    def __init__(self, url_monitor, claude):
        self.url_monitor = url_monitor
        self.claude = claude
        self.config = {"temporary_allow_minutes": 15}
        self.dialog_shown = False
        self.dialog_response = ("cancel", "")

    def fake_ask_reason(self, *a, **kw):
        self.dialog_shown = True
        return self.dialog_response

    def on_blocked_url(self, domain, original_url, tab_id):
        session_name = "Test"
        tab_title = self.url_monitor._get_chrome_title() or ""

        auto_allow, _ = self.claude.evaluate_site_relevance(domain, session_name, tab_title)
        if auto_allow:
            self.url_monitor.allow_domain_temporarily(domain, minutes=15)
            return

        if tab_id:
            status = self.url_monitor.check_tab_status(tab_id)
            if status == "gone":
                return
            if status == "background":
                self.url_monitor.close_tab_by_id(tab_id)
                return
            self.url_monitor.redirect_tab_by_id(tab_id)
        else:
            self.url_monitor.redirect_chrome()

        action, reason = self.fake_ask_reason(domain, "website", session_name)
        if action == "cancel":
            if tab_id:
                self.url_monitor.close_tab_by_id(tab_id)


print("\n=== Integration Tests ===\n")

mon = URLMonitor(on_blocked_url=lambda d, u, t: None)

# ── Test 1: user stays on blocked tab → redirected + dialog shown ────────

print("Test 1: active → blank + dialog")
reset_chrome()
# Open a "blocked" URL in the current tab (using example.com as stand-in)
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)
blocked_tab_id = mon.get_active_tab_id()

app = FakeApp(mon, FakeClaude(auto_allow=False))
app.dialog_response = ("cancel", "")
app.on_blocked_url("example.com", "https://example.com", blocked_tab_id)

url = mon._get_chrome_url() or ""
check("dialog shown", app.dialog_shown, True)
# After cancel, tab should be closed (set to about:blank since it was only tab)
check("tab redirected/closed", "about:blank" in url or mon.check_tab_status(blocked_tab_id) == "gone", True)

# ── Test 2: user switched to another tab → silent close, no dialog ───────

print("\nTest 2: background → silent close, no dialog")
reset_chrome()
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)
blocked_tab_id = mon.get_active_tab_id()

# User opens another tab
open_tab("about:blank")
spare_id = mon.get_active_tab_id()

app = FakeApp(mon, FakeClaude(auto_allow=False))
app.on_blocked_url("example.com", "https://example.com", blocked_tab_id)

check("no dialog", app.dialog_shown, False)
check("blocked tab gone", mon.check_tab_status(blocked_tab_id), "gone")
check("spare tab alive", mon.check_tab_status(spare_id) in ("active", "background"), True)

# ── Test 3: tab closed before handler runs → no-op ───────────────────────

print("\nTest 3: gone → no-op")
reset_chrome()
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)
blocked_tab_id = mon.get_active_tab_id()

# Open + close another tab to change state, then close the blocked tab
open_tab("about:blank")
alive_id = mon.get_active_tab_id()
mon.close_tab_by_id(blocked_tab_id)
time.sleep(0.4)

app = FakeApp(mon, FakeClaude(auto_allow=False))
app.on_blocked_url("example.com", "https://example.com", blocked_tab_id)

check("no dialog", app.dialog_shown, False)
check("alive tab untouched", mon.check_tab_status(alive_id) in ("active", "background"), True)
# Verify alive tab's URL is still about:blank (not blanked by any side effect)
url = mon._get_chrome_url() or ""
check("alive tab url preserved", "about:blank" in url, True)

# ── Test 4: innocent bystander tab is NOT blanked when user switches ────

print("\nTest 4: switching tabs doesn't blank bystander")
reset_chrome()
# Tab A: blocked
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)
blocked_tab_id = mon.get_active_tab_id()

# Tab B: user's work — put a distinctive URL
open_tab("https://www.iana.org/domains/example")
bystander_id = mon.get_active_tab_id()
bystander_url_before = mon._get_chrome_url()

# User stays on bystander while handler fires for blocked tab
app = FakeApp(mon, FakeClaude(auto_allow=False))
app.on_blocked_url("example.com", "https://example.com", blocked_tab_id)

bystander_url_after = mon._get_chrome_url()
check("bystander URL preserved", bystander_url_before, bystander_url_after)
check("bystander still active", mon.check_tab_status(bystander_id), "active")
check("blocked tab closed", mon.check_tab_status(blocked_tab_id), "gone")

# ── Test 5: auto_allow skips everything ──────────────────────────────────

print("\nTest 5: auto_allow path")
reset_chrome()
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)
blocked_tab_id = mon.get_active_tab_id()

app = FakeApp(mon, FakeClaude(auto_allow=True))
app.on_blocked_url("example.com", "https://example.com", blocked_tab_id)

check("no dialog on auto_allow", app.dialog_shown, False)
check("tab preserved", mon.check_tab_status(blocked_tab_id), "active")
check("domain temp-allowed", "example.com" in mon.temporarily_allowed, True)

# ── Test 6: no tab_id → fallback to redirect_chrome ──────────────────────

print("\nTest 6: missing tab_id falls back to redirect_chrome")
reset_chrome()
run_apple('tell application "Google Chrome" to set URL of active tab of front window to "https://example.com"')
time.sleep(0.8)

app = FakeApp(mon, FakeClaude(auto_allow=False))
app.dialog_response = ("cancel", "")
app.on_blocked_url("example.com", "https://example.com", None)
check("dialog shown in fallback", app.dialog_shown, True)

# ── Summary ──────────────────────────────────────────────────────────────

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
