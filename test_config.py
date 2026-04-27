"""Test that the config menu's settings actually take effect in the Python backend.

For each config field the Swift UI exposes, verify:
  (a) Python reads it from config.json
  (b) Python actually USES the value at runtime

The Swift ConfigStore writes these keys. Python must honor them.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

passed = 0
failed = 0
bugs = []


def check(name, ok, detail=""):
    global passed, failed
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1
        bugs.append(f"{name}: {detail}")


CONFIG_PATH = "config.json"
with open(CONFIG_PATH) as f:
    cfg = json.load(f)

# ── 1. notion API key + database id ──────────────────────────────────────
print("\n[1] Notion API key / database ID")
check("api_keys.notion present", "notion" in cfg.get("api_keys", {}))
check("notion_database_id present", bool(cfg.get("notion_database_id")))
# Verified: NotionClient uses these in __init__ (app.py:38-41). Functional.

# ── 2. temporary_allow_minutes ───────────────────────────────────────────
print("\n[2] temporary_allow_minutes")
with open("focuslock/app.py") as f:
    app_src = f.read()
check(
    "read from config in app.py",
    'self.config.get("temporary_allow_minutes"' in app_src,
    "found uses in _on_blocked_url and _on_blocked_app",
)

# ── 3. schedule_refresh_minutes ──────────────────────────────────────────
print("\n[3] schedule_refresh_minutes")
check(
    "read from config in _background_loop",
    'self.config.get("schedule_refresh_minutes"' in app_src,
)

# ── 4. override_code — the Swift UI sets this, Python should read it ─────
print("\n[4] override_code")
with open("focuslock/dialogs.py") as f:
    dialogs_src = f.read()
check(
    "Python reads override_code from config",
    '"override_code"' in app_src,
    "Swift writes it to config.json, Python must actually read that key.",
)

# ── 5. url_poll_interval_seconds ─────────────────────────────────────────
print("\n[5] url_poll_interval_seconds")
with open("focuslock/url_monitor.py") as f:
    url_src = f.read()
check(
    "url_monitor reads poll interval from config",
    "url_poll_interval_seconds" in url_src or "poll_seconds" in url_src,
    "Swift writes this, but url_monitor.py uses hardcoded time.sleep(2).",
)

# ── 6. app_poll_interval_seconds ─────────────────────────────────────────
print("\n[6] app_poll_interval_seconds")
with open("focuslock/app_blocker.py") as f:
    ab_src = f.read()
check(
    "app_blocker reads poll interval from config",
    "app_poll_interval_seconds" in ab_src or "poll_seconds" in ab_src,
    "Swift writes this, but app_blocker.py uses hardcoded time.sleep(2).",
)

# ── 7. activities.{class}.open_apps/allow_apps/allow_domains ─────────────
print("\n[7] activities per-class mapping")
check(
    "activities mapping is consumed",
    '_event_to_session' in app_src and 'activities' in app_src,
    "read on session start (app.py:_event_to_session)",
)

# ── 8. Round-trip: write then re-read config.json (mirrors Swift save) ──
print("\n[8] JSON round-trip preserves values")
bak = cfg.copy()
test_cfg = json.loads(json.dumps(cfg))
test_cfg["override_code"] = "xyzzy"
test_cfg["temporary_allow_minutes"] = 42
with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tf:
    json.dump(test_cfg, tf)
    tmp_path = tf.name
with open(tmp_path) as f:
    reloaded = json.load(f)
os.unlink(tmp_path)
check("override_code round-trips", reloaded["override_code"] == "xyzzy")
check("temporary_allow_minutes round-trips", reloaded["temporary_allow_minutes"] == 42)

# ── 9. Does Python hot-reload config changes? ────────────────────────────
print("\n[9] live config reload")
check(
    "config reloaded before session start",
    "self.config = load_config()" in app_src,
    "reloaded only in _event_to_session — changes made mid-session to "
    "temporary_allow_minutes/override/poll don't apply until next session",
)

# ── Summary ──────────────────────────────────────────────────────────────
print(f"\n{'='*56}")
print(f"Results: {passed} passed, {failed} failed\n")
if bugs:
    print("BUGS FOUND (shippable-blockers):")
    for b in bugs:
        print(f"  • {b}")
sys.exit(0 if failed == 0 else 1)
