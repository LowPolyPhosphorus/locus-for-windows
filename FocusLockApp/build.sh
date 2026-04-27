#!/bin/bash
# Compile the SwiftUI app into a .app bundle without needing Xcode.
set -e
cd "$(dirname "$0")"

APP_NAME="Locus"
BIN_NAME="FocusLockApp"
BUILD_DIR="build"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
SRC_DIR="FocusLockApp"

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    TARGET="arm64-apple-macos13.0"
else
    TARGET="x86_64-apple-macos13.0"
fi

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

SOURCES=$(find "$SRC_DIR" -name "*.swift")

echo "Compiling for $TARGET..."
swiftc -O \
    -target "$TARGET" \
    -parse-as-library \
    -o "$APP_BUNDLE/Contents/MacOS/$BIN_NAME" \
    $SOURCES

cp "$SRC_DIR/Info.plist" "$APP_BUNDLE/Contents/Info.plist"

# Bundle custom fonts (Instrument Serif, DM Mono) — registered via
# ATSApplicationFontsPath in Info.plist.
if [ -d "$SRC_DIR/Fonts" ]; then
    mkdir -p "$APP_BUNDLE/Contents/Resources/Fonts"
    cp "$SRC_DIR/Fonts/"*.ttf "$APP_BUNDLE/Contents/Resources/Fonts/" 2>/dev/null || true
fi

# Bundle the frozen Python daemon (locusd) so users don't need Python installed.
# Built separately via `pyinstaller` at repo root — see build_daemon.sh.
LOCUSD_SRC="../dist/locusd"
if [ -f "$LOCUSD_SRC" ]; then
    cp "$LOCUSD_SRC" "$APP_BUNDLE/Contents/Resources/locusd"
    chmod +x "$APP_BUNDLE/Contents/Resources/locusd"
    echo "Bundled daemon: $LOCUSD_SRC → $APP_BUNDLE/Contents/Resources/locusd"
else
    echo "WARNING: $LOCUSD_SRC not found — app will have no backend. Run build_daemon.sh first."
fi

echo ""
echo "Built: $APP_BUNDLE"
echo "Run:   open '$APP_BUNDLE'"
