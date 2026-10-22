#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h}"
BUILD="$ROOT/.build"
APP="$ROOT/dist/Local Transcriber.app"
CONTENTS="$APP/Contents"

mkdir -p "$BUILD" "$CONTENTS/MacOS" "$CONTENTS/Resources/backend"

if [[ ! -f "$ROOT/assets/AppIcon.icns" \
   || "$ROOT/mac/generate_icon.m" -nt "$ROOT/assets/AppIcon.icns" \
   || "$ROOT/generate_icon.sh" -nt "$ROOT/assets/AppIcon.icns" ]]; then
  "$ROOT/generate_icon.sh"
fi

CLANG_MODULE_CACHE_PATH="$BUILD/module-cache" clang \
  -fobjc-arc \
  -O2 \
  -framework Cocoa \
  -framework UniformTypeIdentifiers \
  "$ROOT/mac/main.m" \
  -o "$CONTENTS/MacOS/Local Transcriber"

cp "$ROOT/backend/"*.py "$CONTENTS/Resources/backend/"
cp "$ROOT/assets/AppIcon.icns" "$CONTENTS/Resources/AppIcon.icns"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleDisplayName</key><string>Local Transcriber</string>
  <key>CFBundleExecutable</key><string>Local Transcriber</string>
  <key>CFBundleIdentifier</key><string>com.canadaeurope.localtranscriber</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Local Transcriber</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleShortVersionString</key><string>1.1.0</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"
echo "$APP"

