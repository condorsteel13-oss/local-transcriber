# Local Transcriber 1.0.0

The first public release turns English and French audio or video into private,
timestamped transcripts on an Apple Silicon Mac. It supports batches, drag and
drop, resumable processing, progress estimates, readable result folders, and
optional anonymous speaker labels with pyannote Community-1.

## Installation

1. Download and extract `Local-Transcriber-1.0.0-macOS-arm64.zip`.
2. Control-click `Install Local Transcriber.command`, choose **Open**, and follow
   the setup prompts.
3. Open **Local Transcriber** from Applications.

The installer uses Homebrew to install FFmpeg and whisper.cpp, then downloads
and verifies the multilingual Whisper medium model. Speaker separation is an
optional setup step and requires a free Hugging Face account plus acceptance of
the Community-1 model conditions.

This build is ad-hoc signed rather than Apple-notarized. On first launch,
Control-click the app, choose **Open**, then confirm **Open** if macOS blocks it.

## Compatibility

- Apple Silicon Mac
- macOS 14 or later
- About 1.5 GB for the required Whisper model
- Additional disk space for optional speaker separation
