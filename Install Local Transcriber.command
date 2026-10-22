#!/bin/zsh
set -euo pipefail

APP_NAME="Local Transcriber.app"
ROOT="${0:A:h}"
APP_SOURCE="$ROOT/$APP_NAME"
SUPPORT="$HOME/Library/Application Support/Local Transcriber"
MODEL_DIR="$SUPPORT/models"
MODEL="$MODEL_DIR/ggml-medium.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
MODEL_SHA256="6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"

print "Local Transcriber 1.1.0 setup"
print "=============================="
print

if [[ "$(uname -m)" != "arm64" ]]; then
  print -u2 "This release requires an Apple Silicon Mac."
  exit 1
fi

if [[ ! -d "$APP_SOURCE" ]]; then
  print -u2 "Keep this installer beside $APP_NAME and run it from the extracted release folder."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  print -u2 "Homebrew is required to install FFmpeg and whisper.cpp."
  print -u2 "Install it from https://brew.sh, then run this installer again."
  exit 1
fi

print "Installing required command-line tools with Homebrew…"
brew install ffmpeg whisper.cpp python@3.13

mkdir -p "$MODEL_DIR"
if [[ -f "$MODEL" ]] && [[ "$(shasum -a 256 "$MODEL" | awk '{print $1}')" == "$MODEL_SHA256" ]]; then
  print "The multilingual Whisper model is already installed and verified."
else
  partial="$MODEL.partial"
  rm -f "$partial"
  print "Downloading the multilingual Whisper medium model (about 1.5 GB)…"
  curl --fail --location --progress-bar "$MODEL_URL" --output "$partial"
  actual="$(shasum -a 256 "$partial" | awk '{print $1}')"
  if [[ "$actual" != "$MODEL_SHA256" ]]; then
    rm -f "$partial"
    print -u2 "Model verification failed. Expected $MODEL_SHA256 but received $actual."
    exit 1
  fi
  mv "$partial" "$MODEL"
  print "Whisper model downloaded and verified."
fi

print
print "Speaker separation is optional and adds a large Python environment."
print "It also requires a free Hugging Face account and acceptance of the Community-1 conditions."
printf "Install speaker separation now? [y/N] "
read -r install_speakers
if [[ "$install_speakers" == [yY] || "$install_speakers" == [yY][eE][sS] ]]; then
  print
  print "First accept the Community-1 conditions in your browser:"
  print "https://huggingface.co/pyannote/speaker-diarization-community-1"
  printf "Press Return after you have accepted them…"
  read -r
  python_bin="$(brew --prefix python@3.13)/bin/python3.13"
  env_dir="$SUPPORT/pyannote-env"
  if [[ ! -x "$env_dir/bin/python" ]]; then
    "$python_bin" -m venv "$env_dir"
  fi
  "$env_dir/bin/python" -m pip install --upgrade pip
  "$env_dir/bin/python" -m pip install "pyannote.audio==4.0.4"
  print
  print "Hugging Face will now ask for your access token. The token stays in your user account."
  "$env_dir/bin/hf" auth login
  HF_HUB_OFFLINE=0 "$env_dir/bin/python" -c \
    'from pyannote.audio import Pipeline; Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=True); print("Community-1 downloaded successfully.")'
fi

if [[ -w "/Applications" ]]; then
  INSTALL_DIR="/Applications"
else
  INSTALL_DIR="$HOME/Applications"
  mkdir -p "$INSTALL_DIR"
fi
APP_TARGET="$INSTALL_DIR/$APP_NAME"
APP_STAGING="$INSTALL_DIR/$APP_NAME.installing"
rm -rf "$APP_STAGING"
ditto "$APP_SOURCE" "$APP_STAGING"
codesign --verify --deep --strict "$APP_STAGING"
rm -rf "$APP_TARGET"
mv "$APP_STAGING" "$APP_TARGET"

print
print "Installed: $APP_TARGET"
print "Setup is complete. Open Local Transcriber from Applications."
print "If macOS blocks the first launch, Control-click the app, choose Open, then confirm Open."
print
printf "Press Return to close this window…"
read -r
