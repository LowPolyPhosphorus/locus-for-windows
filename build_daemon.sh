#!/bin/bash
# Freeze the Python backend into a single-file binary (dist/locusd) that
# FocusLockApp/build.sh embeds inside Locus.app/Contents/Resources/.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

pyinstaller --noconfirm --onefile --name locusd \
    --hidden-import focuslock.app \
    --hidden-import focuslock.paths \
    --hidden-import focuslock.analytics \
    --hidden-import focuslock.session \
    --hidden-import focuslock.dialogs \
    --hidden-import focuslock.notion_client \
    --hidden-import focuslock.ical_client \
    --hidden-import focuslock.claude_client \
    --hidden-import focuslock.url_monitor \
    --hidden-import focuslock.app_blocker \
    locusd_entry.py

echo "Built: dist/locusd"
