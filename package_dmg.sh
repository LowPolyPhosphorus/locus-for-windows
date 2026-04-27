#!/bin/bash
# One-shot release packager: builds the daemon, builds Locus.app, ad-hoc signs
# it, and produces a drag-to-install DMG at dist/Locus.dmg.
#
# Usage:
#   ./package_dmg.sh                 # default version "1.0"
#   ./package_dmg.sh 1.2             # version "1.2"
set -e
cd "$(dirname "$0")"

VERSION="${1:-1.0}"
APP_NAME="Locus"
APP_PATH="FocusLockApp/build/$APP_NAME.app"
DMG_NAME="Locus-$VERSION.dmg"
DMG_PATH="dist/$DMG_NAME"
STAGING="dist/dmg-staging"

echo "==> 1/4  Building Python daemon"
./build_daemon.sh

echo "==> 2/4  Building Locus.app"
(cd FocusLockApp && ./build.sh)

echo "==> 3/4  Ad-hoc signing the bundle"
# Ad-hoc sign so the OS treats it as a complete bundle. NOT notarized — users
# still need to right-click → Open the first time. For real distribution, swap
# the "-" identity for your Developer ID and add a notarization step.
codesign --force --deep --sign - "$APP_PATH"

echo "==> 4/4  Building DMG"
mkdir -p dist
rm -rf "$STAGING" "$DMG_PATH"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

# Build a read-write DMG first so we can set window + icon view options,
# then convert to a compressed read-only DMG for distribution.
TMP_DMG="dist/.tmp-$APP_NAME.dmg"
rm -f "$TMP_DMG"
hdiutil create \
    -volname "$APP_NAME $VERSION" \
    -srcfolder "$STAGING" \
    -ov -format UDRW \
    "$TMP_DMG" >/dev/null

MOUNT_DIR="/Volumes/$APP_NAME $VERSION"
hdiutil attach "$TMP_DMG" -readwrite -noautoopen >/dev/null

# AppleScript the Finder window so icons are big and centered, with Locus on
# the left and the Applications shortcut on the right (drag-to-install layout).
osascript <<EOF
tell application "Finder"
    tell disk "$APP_NAME $VERSION"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 740, 460}
        set theViewOptions to the icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to 128
        set position of item "$APP_NAME.app" of container window to {150, 170}
        set position of item "Applications" of container window to {390, 170}
        update without registering applications
        delay 1
        close
    end tell
end tell
EOF

sync
hdiutil detach "$MOUNT_DIR" >/dev/null

hdiutil convert "$TMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH" >/dev/null
rm -f "$TMP_DMG"
rm -rf "$STAGING"

SIZE=$(du -h "$DMG_PATH" | cut -f1)
echo ""
echo "Built: $DMG_PATH ($SIZE)"
echo ""
echo "Next: upload it as a GitHub Release asset so users can download + drag."
echo "  gh release create v$VERSION '$DMG_PATH' --title 'Locus $VERSION' --notes 'Drag Locus.app to Applications.'"
