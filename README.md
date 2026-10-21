# Local Transcriber for macOS

![Local Transcriber icon](assets/AppIcon-1024.png)

Local Transcriber converts audio or video recordings into timestamped English
or French transcripts on an Apple Silicon Mac. It uses multilingual whisper.cpp for speech
recognition and can optionally use pyannote Community-1 to label anonymous
speakers.

You can drag one or several recordings onto the Recording panel, or select them
with the file picker. A batch is processed sequentially so Whisper and speaker
detection do not compete for memory. Each recording still receives its own
resumable output folder, and one failure does not prevent the remaining selected
recordings from running.

## Outputs

`Show Results` opens a simple, dated results folder. Each recording has a
clearly named subfolder containing only `Transcript.txt` and `Subtitles.srt`.
When speaker separation is enabled, `Transcript.txt` is the speaker-labelled
version.

Each recording gets a separate content-addressed job folder containing:

- `raw-transcript.txt`, `.srt`, and `.json`: untouched whisper.cpp outputs
- `transcript.txt` and `transcript.json`: normalized timestamped transcript
- `source-metadata.json`, `audio-metadata.json`, settings, checks, and logs
- `transcript-with-speakers.txt` and `.json` when speaker separation is enabled
- `diarization/speaker-turns.json` and `.rttm` for raw speaker timing

The source recording is read-only. Processing is resumable: verified completed
stages are reused if the same recording and settings are run again.

## Language behavior

The default `Auto-detect` mode asks multilingual Whisper to choose English or
French. Explicit English and French options are available. A recording that
switches repeatedly between languages can still require review because a single
Whisper run chooses one primary decoding language.

Québec French is supported as French speech; the model does not convert the
accent or expressions into European French. Proper names, local expressions,
and poor audio can still be transcribed incorrectly.

## Speaker behavior

Community-1 predicts anonymous labels such as `SPEAKER_00`. It does not know
real names. Short interruptions, overlapping speech, and similar voices may
produce imperfect boundaries. The app preserves the raw transcript and raw
speaker turns so alignment can be improved without retranscribing the audio.
The installed Community-1 model is used in offline mode during routine jobs.

## Install the release

Requirements: an Apple Silicon Mac running macOS 14 or later, an internet
connection for initial setup, and [Homebrew](https://brew.sh). Routine
transcription runs locally after setup.

1. Download and extract the ZIP from the latest GitHub release.
2. Control-click `Install Local Transcriber.command`, choose **Open**, and follow
   the prompts.
3. Open Local Transcriber from Applications. If macOS blocks the first launch,
   Control-click the app, choose **Open**, then confirm **Open**.

The installer downloads and verifies the multilingual Whisper medium model
(about 1.5 GB). Speaker separation is optional and installs additional Python
packages. Community-1 requires a free Hugging Face account and acceptance of
the [model conditions](https://huggingface.co/pyannote/speaker-diarization-community-1).
No Hugging Face token is stored in this repository.

Version 1.0.0 is ad-hoc signed and is not Apple-notarized. That is why macOS may
require the Control-click Open step. A future Developer ID release can remove
that extra first-launch step.

## Build

```sh
chmod +x build_app.sh
./build_app.sh
```

The resulting application is `dist/Local Transcriber.app`.

Run `./package_release.sh` to build the distributable ZIP and its SHA-256 file
under `release/`.

Public release users should use `Install Local Transcriber.command`. Development
builds use the same support directory under `~/Library/Application Support/Local
Transcriber`.
