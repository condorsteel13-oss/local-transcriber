#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h}"
BUILD="$ROOT/.build/icon"
ICONSET="$BUILD/AppIcon.iconset"
BASE="$BUILD/AppIcon-1024.png"
TIFF_DIR="$BUILD/tiff"

rm -rf "$BUILD"
mkdir -p "$ICONSET" "$TIFF_DIR" "$ROOT/assets"

CLANG_MODULE_CACHE_PATH="$ROOT/.build/module-cache" clang \
  -fobjc-arc -O2 -framework Cocoa \
  "$ROOT/mac/generate_icon.m" -o "$BUILD/generate-icon"
"$BUILD/generate-icon" "$BASE"

for spec in \
  '16 icon_16x16.png' \
  '32 icon_16x16@2x.png' \
  '32 icon_32x32.png' \
  '64 icon_32x32@2x.png' \
  '128 icon_128x128.png' \
  '256 icon_128x128@2x.png' \
  '256 icon_256x256.png' \
  '512 icon_256x256@2x.png' \
  '512 icon_512x512.png' \
  '1024 icon_512x512@2x.png'; do
  pixels="${spec%% *}"
  name="${spec#* }"
  sips -z "$pixels" "$pixels" "$BASE" --out "$ICONSET/$name" >/dev/null
done

# iconutil rejects otherwise valid iconsets on some macOS releases. A
# multi-representation TIFF converted by Apple's tiff2icns is reliable across
# the macOS versions supported by this app.
for pixels in 16 32 48 128 256 512 1024; do
  sips -z "$pixels" "$pixels" -s format tiff "$BASE" \
    --out "$TIFF_DIR/icon-$pixels.tiff" >/dev/null
done
tiffutil -cat \
  "$TIFF_DIR/icon-16.tiff" \
  "$TIFF_DIR/icon-32.tiff" \
  "$TIFF_DIR/icon-48.tiff" \
  "$TIFF_DIR/icon-128.tiff" \
  "$TIFF_DIR/icon-256.tiff" \
  "$TIFF_DIR/icon-512.tiff" \
  "$TIFF_DIR/icon-1024.tiff" \
  -out "$BUILD/AppIcon.tiff" >/dev/null
tiff2icns "$BUILD/AppIcon.tiff" "$ROOT/assets/AppIcon.icns"
cp "$BASE" "$ROOT/assets/AppIcon-1024.png"
echo "$ROOT/assets/AppIcon.icns"

\n