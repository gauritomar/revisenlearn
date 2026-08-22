#!/usr/bin/env bash
#
# Build "Revise & Learn.app" — a bundle whose executable is a two-line shell
# script calling run.sh (spec §17). Gives a Dock icon and Spotlight launch with
# no packaging framework.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Revise & Learn"
DEST="${1:-$REPO_ROOT/dist}"
APP="$DEST/$APP_NAME.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Icon (spec §14.3)
if [ ! -f "$REPO_ROOT/assets/AppIcon.icns" ]; then
  echo "Generating icon..."
  "$REPO_ROOT/scripts/make_icon.sh"
fi
cp "$REPO_ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>       <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>        <string>local.revisenlearn</string>
  <key>CFBundleVersion</key>           <string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleExecutable</key>        <string>revisenlearn</string>
  <key>CFBundleIconFile</key>          <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>    <string>13.0</string>
  <key>NSHighResolutionCapable</key>   <true/>
</dict>
</plist>
PLIST

# The two-line executable, per spec.
cat > "$APP/Contents/MacOS/revisenlearn" <<LAUNCHER
#!/bin/bash
exec "$REPO_ROOT/run.sh"
LAUNCHER
chmod +x "$APP/Contents/MacOS/revisenlearn"

# Refresh the icon cache so Finder picks it up immediately.
touch "$APP"

echo "Built $APP"
echo "Drag it to /Applications or your Dock. It launches $REPO_ROOT/run.sh."
