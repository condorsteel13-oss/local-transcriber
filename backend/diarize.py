#!/usr/bin/env python3
"""Run pyannote Community-1 and preserve timestamped diarization artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_ID = "pyannote/speaker-diarization-community-1"


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def version(name: str) -> str | None:
    try:
        from importlib.metadata import version as package_version

        return package_version(name)
    except Exception:
        return None


def load_pcm16_mono(path: Path, torch: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load normalized PCM audio without relying on TorchCodec/FFmpeg linkage."""
    import numpy as np

    with wave.open(str(path), "rb") as source:
        metadata = {
            "channels": source.getnchannels(),
            "sample_width_bytes": source.getsampwidth(),
            "sample_rate": source.getframerate(),
            "frame_count": source.getnframes(),
            "compression": source.getcomptype(),
        }
        if metadata["channels"] != 1:
            raise SystemExit(f"Expected mono WAV, found {metadata['channels']} channels")
        if metadata["sample_width_bytes"] != 2:
            raise SystemExit("Expected 16-bit PCM WAV")
        if metadata["compression"] != "NONE":
            raise SystemExit("Expected uncompressed PCM WAV")
        frames = source.readframes(source.getnframes())

    # Copy makes the NumPy buffer writable before Torch adopts it.
    samples = np.frombuffer(frames, dtype="<i2").copy()
    waveform = torch.from_numpy(samples).to(dtype=torch.float32).div_(32768.0)
    return {
        "waveform": waveform.unsqueeze(0),
        "sample_rate": metadata["sample_rate"],
        "uri": path.stem,
    }, metadata


def turn_rows(annotation: Any, offset: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (turn, _, speaker) in enumerate(
        annotation.itertracks(yield_label=True), start=1
    ):
        rows.append(
            {
                "id": f"turn_{index:06d}",
                "speaker_id": str(speaker),
                "clip_start": round(float(turn.start), 3),
                "clip_end": round(float(turn.end), 3),
                "source_start": round(float(turn.start) + offset, 3),
                "source_end": round(float(turn.end) + offset, 3),
            }
        )
    return rows


def rttm_text(rows: list[dict[str, Any]], uri: str) -> str:
    lines = []
    for row in rows:
        start = float(row["source_start"])
        duration = float(row["source_end"]) - start
        lines.append(
            f"SPEAKER {uri} 1 {start:.3f} {duration:.3f} <NA> <NA> "
            f"{row['speaker_id']} <NA> <NA>"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-offset", type=float, default=0.0)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--num-speakers", type=int)
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audio = args.audio.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not audio.is_file():
        raise SystemExit(f"Audio file does not exist: {audio}")
    if args.source_offset < 0:
        raise SystemExit("--source-offset must be zero or greater")

    token = os.environ.get("HF_TOKEN")
    cached_token = Path.home() / ".cache" / "huggingface" / "token"
    if not token and not cached_token.is_file():
        raise SystemExit(
            "Community-1 access is not configured. Accept the model conditions at "
            "https://hf.co/pyannote/speaker-diarization-community-1 and run "
            "`hf auth login`, or set HF_TOKEN in your shell. Do not put the token in "
            "a project file."
        )

    # Disable optional anonymous usage telemetry for this local proof.
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    # Community-1 has already been downloaded during setup. Keep routine audio
    # processing offline so a transcription never depends on network access.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    matplotlib_cache = output / ".cache" / "matplotlib"
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache))

    import torch
    from pyannote.audio import Pipeline

    started = datetime.now(timezone.utc)
    pipeline = Pipeline.from_pretrained(MODEL_ID, token=token or True)
    pipeline.to(torch.device(args.device))

    inference: dict[str, int] = {}
    for name in ("num_speakers", "min_speakers", "max_speakers"):
        value = getattr(args, name)
        if value is not None:
            inference[name] = value

    audio_input, wav_metadata = load_pcm16_mono(audio, torch)
    result = pipeline(audio_input, **inference)
    standard = turn_rows(result.speaker_diarization, args.source_offset)
    exclusive = turn_rows(result.exclusive_speaker_diarization, args.source_offset)
    speakers = sorted({row["speaker_id"] for row in exclusive})
    finished = datetime.now(timezone.utc)

    payload = {
        "schema_version": 1,
        "model": MODEL_ID,
        "audio": {
            "path": str(audio),
            "sha256": sha256(audio),
            "source_offset_seconds": args.source_offset,
            "wav": wav_metadata,
        },
        "configuration": {
            "device": args.device,
            "speaker_constraints": inference,
            "telemetry_enabled": os.environ.get("PYANNOTE_METRICS_ENABLED") != "0",
        },
        "speakers": speakers,
        "speaker_count": len(speakers),
        "exclusive_turns": exclusive,
        "overlap_aware_turns": standard,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "runtime_seconds": round((finished - started).total_seconds(), 3),
        "software": {
            "python": platform.python_version(),
            "pyannote.audio": version("pyannote.audio"),
            "torch": version("torch"),
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    atomic_text(
        output / "speaker-turns.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    atomic_text(output / "speaker-turns.rttm", rttm_text(exclusive, audio.stem))
    atomic_text(
        output / "run-summary.json",
        json.dumps(
            {
                "status": "completed",
                "speaker_count": len(speakers),
                "exclusive_turn_count": len(exclusive),
                "output": str(output / "speaker-turns.json"),
            },
            indent=2,
        )
        + "\n",
    )
    print(f"Detected {len(speakers)} speakers in {len(exclusive)} exclusive turns.")
    print(output / "speaker-turns.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
