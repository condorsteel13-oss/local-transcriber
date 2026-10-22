# Local Transcriber 1.1.0

Version 1.1.0 reorganizes every transcription into one readable folder named
after the source recording. `Transcript.txt` and `Subtitles.srt` are the only
files at the top level. Raw Whisper output, normalized audio, speaker timing,
metadata, logs, checks, and resume information are kept together under
`Technical Files`.

The new structure preserves verified resume behavior and automatically adds a
short identifier only when two recordings or setting combinations would
otherwise use the same folder name.

## Included application

Local Transcriber turns English and French audio or video into private,
timestamped transcripts on an Apple Silicon Mac. It supports batches, drag and
drop, resumable processing, progress estimates, readable result folders, and
optional anonymous speaker labels with pyannote Community-1.

## Installation

1. Download and extract `Local-Transcriber-1.1.0-macOS-arm64.zip`.
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
