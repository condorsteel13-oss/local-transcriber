#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h}"
VERSION="1.1.0"
NAME="Local-Transcriber-$VERSION-macOS-arm64"
RELEASE="$ROOT/release"
STAGING="$RELEASE/$NAME"
ARCHIVE="$RELEASE/$NAME.zip"

"$ROOT/build_app.sh"
rm -rf "$RELEASE"
mkdir -p "$STAGING"
ditto "$ROOT/dist/Local Transcriber.app" "$STAGING/Local Transcriber.app"
cp "$ROOT/Install Local Transcriber.command" "$STAGING/Install Local Transcriber.command"
cp "$ROOT/README.md" "$STAGING/README.md"
chmod +x "$STAGING/Install Local Transcriber.command"

ditto -c -k --sequesterRsrc --keepParent "$STAGING" "$ARCHIVE"
(
  cd "$RELEASE"
  shasum -a 256 "${NAME}.zip" > SHA256SUMS.txt
)

codesign --verify --deep --strict "$STAGING/Local Transcriber.app"
print "$ARCHIVE"
