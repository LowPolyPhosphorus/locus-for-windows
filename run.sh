#!/bin/bash
# FocusLock launcher — installs deps if needed, then runs the app

set -e
cd "$(dirname "$0")"

VENV_DIR=".venv"

# Check Python 3.10+
python3 --version | grep -qE "3\.(1[0-9]|[2-9][0-9])" || {
    echo "Error: Python 3.10+ required"
    exit 1
}

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install deps into venv if needed
if ! python3 -c "import rumps" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

echo "Starting FocusLock..."
python3 -m focuslock.app