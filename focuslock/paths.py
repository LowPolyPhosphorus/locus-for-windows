"""Canonical on-disk locations for Locus (Windows).

Everything lives under %APPDATA%\\Locus\\ so the app is install-ready:
no hardcoded Desktop paths, no temp files that don't survive reboot.

On first import we also migrate any data from legacy locations so users
don't lose their event history when upgrading from an older build.
"""

import os
import shutil

APP_SUPPORT_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Locus")

CONFIG_PATH    = os.path.join(APP_SUPPORT_DIR, "config.json")
STATE_PATH     = os.path.join(APP_SUPPORT_DIR, "state.json")
COMMAND_PATH   = os.path.join(APP_SUPPORT_DIR, "command.json")
ANALYTICS_PATH = os.path.join(APP_SUPPORT_DIR, "analytics.json")
EVENTS_PATH    = os.path.join(APP_SUPPORT_DIR, "events.jsonl")
LOCK_PATH      = os.path.join(APP_SUPPORT_DIR, "locusd.lock")
PROMPT_PATH    = os.path.join(APP_SUPPORT_DIR, "prompt.json")
RESPONSE_PATH  = os.path.join(APP_SUPPORT_DIR, "response.json")


def _legacy_candidates():
    """Old paths we migrate from. Ordered: check each, first hit wins."""
    home = os.path.expanduser("~")
    tmp  = os.environ.get("TEMP", os.path.join(home, "AppData", "Local", "Temp"))
    return {
        CONFIG_PATH: [
            os.path.join(home, "Desktop", "focus", "config.json"),
        ],
        STATE_PATH:     [os.path.join(tmp, "focuslock_state.json")],
        COMMAND_PATH:   [os.path.join(tmp, "focuslock_command.json")],
        ANALYTICS_PATH: [os.path.join(tmp, "focuslock_analytics.json")],
        EVENTS_PATH:    [os.path.join(tmp, "focuslock_events.jsonl")],
    }


def _migrate_once():
    """If the new location is empty, copy any old files into it."""
    try:
        os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    except Exception:
        return
    for new_path, old_candidates in _legacy_candidates().items():
        if os.path.exists(new_path):
            continue
        for old in old_candidates:
            if os.path.exists(old):
                try:
                    shutil.copy2(old, new_path)
                except Exception:
                    pass
                break


_migrate_once()
