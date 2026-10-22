#!/usr/bin/env python3
"""Local English/French transcription with optional speaker diarization."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from core import (
    artifact,
    atomic_bytes,
    atomic_json,
    exclusive_lock,
    now,
    read_json,
    sha256,
    signature,
    verified,
)

SUPPORTED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".mkv", ".webm",
}
STAGES = ("inspect", "normalize", "whisper", "canonical", "diarization", "align")


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def command_version(executable: str, flag: str) -> str:
    result = subprocess.run(
        [executable, flag], capture_output=True, text=True, check=True
    )
    lines = (result.stdout + result.stderr).splitlines()
    if "whisper" in Path(executable).name:
        matches = [line.strip() for line in lines if line.startswith("whisper.cpp version:")]
        return matches[0] if matches else "unknown"
    return lines[0].strip() if lines else "unknown"


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    if not data.get("streams") or not data.get("format"):
        raise ValueError("ffprobe returned no usable media metadata.")
    return data


def inspect_source(source: Path, ffprobe: str, source_hash: str) -> dict:
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {source.suffix or '(none)'}")
    data = probe(source, ffprobe)
    streams = [stream for stream in data["streams"] if stream.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise ValueError("The file must contain exactly one audio stream.")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The recording duration is invalid.")
    return {
        "schema_version": 1,
        "source": {
            "path": str(source),
            "name": source.name,
            "sha256": source_hash,
            "bytes": source.stat().st_size,
            "duration_seconds": duration,
        },
        "selected_audio_stream": streams[0]["index"],
        "ffprobe": data,
    }


def normalize(source: Path, work: Path, metadata: dict, ffmpeg: str, ffprobe: str) -> list[Path]:
    partial = work / "normalized-audio.partial.wav"
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-y",
        "-i", str(source), "-map", f"0:{metadata['selected_audio_stream']}", "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(partial),
    ]
    log = work / "ffmpeg.stderr.log"
    with log.open("wb") as error_log:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=error_log, check=True)
    decoded = probe(partial, ffprobe)
    track = decoded["streams"][0]
    duration = float(decoded["format"]["duration"])
    if (
        track.get("codec_name") != "pcm_s16le"
        or int(track.get("sample_rate", 0)) != 16000
        or int(track.get("channels", 0)) != 1
    ):
        raise ValueError("Normalized audio is not mono 16 kHz PCM.")
    if abs(duration - metadata["source"]["duration_seconds"]) > 0.3:
        raise ValueError("Normalized audio duration differs from the source.")
    os.replace(partial, work / "normalized-audio.wav")
    audio = work / "normalized-audio.wav"
    details = {
        "command": command,
        "duration_seconds": duration,
        "sha256": sha256(audio),
        "format": "mono 16 kHz signed 16-bit PCM WAV",
        "timeline_changed": False,
    }
    atomic_json(work / "audio-metadata.json", details)
    return [audio, work / "audio-metadata.json", log]


def run_whisper(work: Path, config: dict) -> list[Path]:
    attempt = work / "attempts" / f"whisper_{uuid4().hex}"
    attempt.mkdir(parents=True)
    base = attempt / "raw-transcript"
    command = [
        config["whisper"], "-m", config["model"], "-f", str(work / "normalized-audio.wav"),
        "-l", config["language"], "-t", str(config["threads"]), "-p", "1",
        "-bo", "5", "-bs", "5", "-tp", "0", "-tpi", "0.2", "-et", "2.4",
        "-lpt", "-1", "-nth", "0.6", "-fa", "-otxt", "-osrt", "-oj", "-ojf",
        "-of", str(base),
    ]
    attempts = [{"device": "metal", "argv": command}]
    with (attempt / "stdout.log").open("wb") as output, (attempt / "stderr.log").open("wb") as error:
        result = subprocess.run(command, stdout=output, stderr=error)
    gpu_used = True
    if result.returncode != 0:
        diagnostic = (attempt / "stderr.log").read_text(encoding="utf-8", errors="replace")
        metal_failure = "failed to allocate Metal buffer" in diagnostic or "MTL0_Private buffer" in diagnostic
        if not metal_failure:
            raise subprocess.CalledProcessError(result.returncode, command)
        # Keep the failed accelerated diagnostic and retry reliably on CPU.
        os.replace(attempt / "stdout.log", attempt / "stdout-metal-failed.log")
        os.replace(attempt / "stderr.log", attempt / "stderr-metal-failed.log")
        for extension in ("txt", "srt", "json"):
            base.with_suffix(f".{extension}").unlink(missing_ok=True)
        command = [*command, "-ng"]
        attempts.append({"device": "cpu_fallback", "argv": command})
        with (attempt / "stdout.log").open("wb") as output, (attempt / "stderr.log").open("wb") as error:
            subprocess.run(command, stdout=output, stderr=error, check=True)
        gpu_used = False
    atomic_json(
        attempt / "command.json",
        {"attempts": attempts, "translate": False, "model_sha256": config["model_sha256"]},
    )
    paths = []
    for extension in ("txt", "srt", "json"):
        source = base.with_suffix(f".{extension}")
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"Whisper did not produce raw {extension.upper()} output.")
        target = work / f"raw-transcript.{extension}"
        atomic_bytes(target, source.read_bytes())
        paths.append(target)
    native = read_json(work / "raw-transcript.json")
    if not native.get("transcription"):
        raise ValueError("Whisper returned no transcription segments.")
    settings = {
        "implementation": "whisper.cpp",
        "version": config["whisper_version"],
        "model": config["model"],
        "model_sha256": config["model_sha256"],
        "language_requested": config["language"],
        "language_detected": native.get("result", {}).get("language"),
        "multilingual_model": native.get("model", {}).get("multilingual"),
        "translate": False,
        "threads": config["threads"],
        "gpu_used": gpu_used,
        "metal_fallback_used": not gpu_used,
        "native_attempt": str(attempt.relative_to(work)),
        "argv": command,
    }
    if settings["multilingual_model"] is not True:
        raise ValueError("The selected Whisper model is not multilingual.")
    atomic_json(work / "whisper-settings.json", settings)
    return paths + [work / "whisper-settings.json"]


def timestamp_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})", value)
    if not match:
        raise ValueError(f"Invalid timestamp: {value}")
    hours, minutes, seconds, millis = map(int, match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError("Invalid timestamp components.")
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_segments(data: dict, duration: float) -> tuple[list[dict], list[dict]]:
    records = data.get("transcription")
    if not isinstance(records, list) or not records:
        raise ValueError("Native Whisper JSON has no segments.")
    segments, warnings = [], []
    previous = -1.0
    for index, item in enumerate(records, 1):
        offsets = item.get("offsets", {})
        begin, end = offsets.get("from"), offsets.get("to")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in (begin, end)
        ):
            raise ValueError("Whisper offsets must be finite milliseconds.")
        start, stop = begin / 1000, end / 1000
        displayed = item.get("timestamps", {})
        if any(
            abs(timestamp_seconds(displayed[key]) - value) > 0.0011
            for key, value in (("from", start), ("to", stop))
        ):
            raise ValueError("Whisper numeric and formatted timestamps disagree.")
        if stop > duration:
            if index != len(records) or stop - duration > 2 or start >= duration:
                raise ValueError("Whisper segment is outside the recording.")
            warnings.append(
                {
                    "code": "terminal_timestamp_clamped",
                    "segment": index,
                    "native_end": stop,
                    "recording_end": duration,
                }
            )
        if not 0 <= start < stop or start < previous or start >= duration:
            raise ValueError("Whisper segments are not valid chronological intervals.")
        previous = start
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("Whisper segment text must be a string.")
        probabilities = [
            token["p"]
            for token in item.get("tokens", [])
            if isinstance(token, dict)
            and isinstance(token.get("p"), (int, float))
            and not isinstance(token.get("p"), bool)
        ]
        mean = sum(probabilities) / len(probabilities) if probabilities else None
        if mean is not None and mean < 0.45:
            warnings.append(
                {"code": "low_mean_token_probability", "segment": index, "mean": round(mean, 4)}
            )
        segments.append(
            {
                "id": f"seg_{index:06d}",
                "start": round(start, 3),
                "end": round(min(stop, duration), 3),
                "native_end": stop,
                "text": text,
                "speaker_id": None,
                "mean_token_probability": mean,
            }
        )
    if not any(segment["text"].strip() for segment in segments):
        raise ValueError("Whisper returned an empty transcript.")
    for left, right in zip(segments, segments[1:]):
        if left["text"].strip().casefold() == right["text"].strip().casefold():
            warnings.append(
                {"code": "consecutive_identical_segments", "segments": [left["id"], right["id"]]}
            )
    return segments, warnings


def format_time(value: float) -> str:
    millis = round(value * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def canonicalize(work: Path) -> list[Path]:
    native = read_json(work / "raw-transcript.json")
    audio = read_json(work / "audio-metadata.json")
    settings = read_json(work / "whisper-settings.json")
    segments, warnings = parse_segments(native, audio["duration_seconds"])
    transcript = {
        "schema_version": 1,
        "source": read_json(work / "source-metadata.json")["source"],
        "timestamp_reference": "seconds from recording start",
        "language": {
            "requested": settings["language_requested"],
            "detected": settings["language_detected"],
        },
        "segments": segments,
        "metrics": {
            "segment_count": len(segments),
            "duration_seconds": audio["duration_seconds"],
            "first_segment_start": segments[0]["start"],
            "last_segment_end": segments[-1]["end"],
        },
        "warnings": warnings,
        "raw_whisper_json_sha256": sha256(work / "raw-transcript.json"),
    }
    atomic_json(work / "transcript.json", transcript)
    lines = [
        f"[{format_time(segment['start'])} --> {format_time(segment['end'])}] {segment['text'].strip()}"
        for segment in segments
    ]
    atomic_bytes(work / "transcript.txt", ("\n".join(lines) + "\n").encode())
    atomic_json(
        work / "transcription-checks.json",
        {
            "metrics": transcript["metrics"],
            "warning_counts": dict(Counter(item["code"] for item in warnings)),
            "warnings": warnings,
        },
    )
    return [work / "transcript.json", work / "transcript.txt", work / "transcription-checks.json"]


def diarization_python(config: dict) -> Path:
    candidates = []
    if config.get("diarization_python"):
        candidates.append(Path(config["diarization_python"]))
    candidates.extend(
        [
            Path.home() / "Library/Application Support/Local Transcriber/pyannote-env/bin/python",
            Path(__file__).resolve().parents[1] / "pyannote-env/bin/python",
            Path(__file__).resolve().parents[2] / "speaker-diarization/.venv/bin/python",
        ]
    )
    for candidate in candidates:
        candidate = candidate.expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.is_file():
            # Do not resolve the venv's python symlink: invoking the resolved
            # base interpreter would discard the virtual environment.
            return candidate.absolute()
    raise ValueError("Speaker separation environment is not installed.")


def run_diarization(work: Path, config: dict) -> list[Path]:
    python = diarization_python(config)
    script = Path(__file__).with_name("diarize.py")
    output = work / "diarization"
    command = [
        str(python), str(script), "--audio", str(work / "normalized-audio.wav"),
        "--output", str(output), "--device", "cpu",
    ]
    if config.get("min_speakers") is not None:
        command += ["--min-speakers", str(config["min_speakers"])]
    if config.get("max_speakers") is not None:
        command += ["--max-speakers", str(config["max_speakers"])]
    with (work / "diarization.stdout.log").open("wb") as stdout, (work / "diarization.stderr.log").open("wb") as stderr:
        subprocess.run(command, stdout=stdout, stderr=stderr, check=True)
    paths = [
        output / "speaker-turns.json",
        output / "speaker-turns.rttm",
        output / "run-summary.json",
        work / "diarization.stdout.log",
        work / "diarization.stderr.log",
    ]
    if not all(path.is_file() for path in paths):
        raise ValueError("Speaker separation did not produce all expected files.")
    return paths


def align_speakers(work: Path, config: dict) -> list[Path]:
    script = Path(__file__).with_name("align.py")
    output = work / "transcript-with-speakers.json"
    duration = read_json(work / "audio-metadata.json")["duration_seconds"]
    command = [
        sys.executable, str(script), "--whisper-json", str(work / "raw-transcript.json"),
        "--speaker-turns", str(work / "diarization/speaker-turns.json"),
        "--output", str(output), "--through", str(duration),
    ]
    subprocess.run(command, check=True)
    text = output.with_suffix(".txt")
    if not output.is_file() or not text.is_file():
        raise ValueError("Speaker alignment did not produce expected files.")
    return [output, text]


def mark_stage(job: Path, work: Path, manifest: dict, stage: str, started: float, paths: list[Path]) -> None:
    manifest["stages"][stage] = {
        "status": "succeeded",
        "ended_at": now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "artifacts": [artifact(path, job) for path in paths],
    }
    atomic_json(work / "job.json", manifest)


def select_job_folder(output_root: Path, source: Path, recipe: dict) -> Path:
    """Choose a readable, stable folder while keeping colliding jobs separate."""
    safe_stem = re.sub(r"[/:\\]+", "-", source.stem)
    safe_stem = re.sub(r"\s+", " ", safe_stem).strip(" .-")[:100] or "Recording"
    base = output_root / f"{safe_stem} - Transcript"
    recipe_id = signature(recipe)
    candidates = [
        base,
        output_root / f"{safe_stem} - Transcript ({recipe['source_sha256'][:6]}-{recipe_id[:6]})",
        output_root / f"{safe_stem} - Transcript ({recipe['source_sha256'][:12]}-{recipe_id[:10]})",
    ]
    for candidate in candidates:
        manifest_path = candidate / "Technical Files" / "job.json"
        if manifest_path.is_file() and read_json(manifest_path).get("recipe") == recipe:
            return candidate
        if not candidate.exists():
            return candidate
    raise ValueError("Could not choose a unique output folder for this recording.")


def publish_final_files(job: Path, work: Path, speakers: bool) -> list[Path]:
    transcript = work / ("transcript-with-speakers.txt" if speakers else "transcript.txt")
    subtitles = work / "raw-transcript.srt"
    if not transcript.is_file() or not subtitles.is_file():
        raise ValueError("Final transcript or subtitles are missing.")
    final_transcript = job / "Transcript.txt"
    final_subtitles = job / "Subtitles.srt"
    atomic_bytes(final_transcript, transcript.read_bytes())
    atomic_bytes(final_subtitles, subtitles.read_bytes())
    return [final_transcript, final_subtitles]


def process(config: dict) -> Path:
    source = Path(config["source"]).expanduser().resolve()
    output_root = Path(config["output_root"]).expanduser().resolve()
    model = Path(config["model"]).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Recording does not exist: {source}")
    if not model.is_file():
        raise ValueError(f"Multilingual Whisper model is missing: {model}")
    output_root.mkdir(parents=True, exist_ok=True)
    for name in ("whisper", "ffmpeg", "ffprobe"):
        config[name] = shutil.which(config[name]) or config[name]
        if not Path(config[name]).is_file():
            raise ValueError(f"Required executable is missing: {config[name]}")
    config["whisper_version"] = command_version(config["whisper"], "--version")
    config["ffmpeg_version"] = command_version(config["ffmpeg"], "-version")
    config["ffprobe_version"] = command_version(config["ffprobe"], "-version")
    backend_files = [Path(__file__), Path(__file__).with_name("core.py")]
    if config["speakers"]:
        backend_files += [Path(__file__).with_name("diarize.py"), Path(__file__).with_name("align.py")]
    code_sha256 = signature({path.name: sha256(path) for path in backend_files})
    source_hash = sha256(source)
    recipe = {
        "source_sha256": source_hash,
        "model": str(model),
        "model_sha256": sha256(model),
        "language": config["language"],
        "speakers": config["speakers"],
        "min_speakers": config.get("min_speakers"),
        "max_speakers": config.get("max_speakers"),
        "threads": config["threads"],
        "whisper_version": config["whisper_version"],
        "ffmpeg_version": config["ffmpeg_version"],
        "ffprobe_version": config["ffprobe_version"],
        "code_sha256": code_sha256,
    }
    job_id = f"{source_hash[:12]}_{signature(recipe)[:10]}"

    with exclusive_lock(output_root, job_id):
        job = select_job_folder(output_root, source, recipe)
        job.mkdir(parents=True, exist_ok=True)
        work = job / "Technical Files"
        work.mkdir(parents=True, exist_ok=True)
        manifest_path = work / "job.json"
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            if manifest.get("recipe") != recipe:
                raise ValueError("Existing job settings do not match this run.")
        else:
            manifest = {
                "schema_version": 1,
                "job_id": job_id,
                "status": "running",
                "created_at": now(),
                "source": str(source),
                "recipe": recipe,
                "stages": {},
                "warnings": [],
            }
        manifest["status"] = "running"
        atomic_json(manifest_path, manifest)
        config.update({"model": str(model), "model_sha256": recipe["model_sha256"]})

        try:
            for stage in STAGES:
                if not config["speakers"] and stage in ("diarization", "align"):
                    manifest["stages"][stage] = {"status": "skipped", "reason": "speaker separation disabled"}
                    atomic_json(manifest_path, manifest)
                    continue
                if verified(job, manifest["stages"].get(stage, {})):
                    emit("stage", stage=stage, status="cached")
                    continue
                emit("stage", stage=stage, status="running")
                started = time.monotonic()
                if stage == "inspect":
                    metadata = inspect_source(source, config["ffprobe"], source_hash)
                    atomic_json(work / "source-metadata.json", metadata)
                    paths = [work / "source-metadata.json"]
                elif stage == "normalize":
                    paths = normalize(source, work, read_json(work / "source-metadata.json"), config["ffmpeg"], config["ffprobe"])
                elif stage == "whisper":
                    paths = run_whisper(work, config)
                elif stage == "canonical":
                    paths = canonicalize(work)
                elif stage == "diarization":
                    paths = run_diarization(work, config)
                else:
                    paths = align_speakers(work, config)
                mark_stage(job, work, manifest, stage, started, paths)
                emit("stage", stage=stage, status="succeeded")
            publish_final_files(job, work, config["speakers"])
            manifest["status"] = "completed"
            manifest["completed_at"] = now()
            atomic_json(manifest_path, manifest)
            emit("completed", output_directory=str(job), speakers=config["speakers"])
            return job
        except BaseException as error:
            manifest["status"] = "failed"
            manifest["error"] = str(error)
            manifest["failed_at"] = now()
            atomic_json(manifest_path, manifest)
            emit("failed", message=str(error), output_directory=str(job))
            raise


def default_model() -> Path:
    candidates = [
        Path.home() / "Library/Application Support/Local Transcriber/models/ggml-medium.bin",
        Path.home() / "whisper-models/ggml-medium.bin",
        Path(__file__).resolve().parents[1] / "models/ggml-medium.bin",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local English/French audio transcription")
    parser.add_argument("source")
    parser.add_argument("--output-root", default=str(Path.home() / "Documents/Local Transcriber"))
    parser.add_argument("--model", default=str(default_model()))
    parser.add_argument("--language", choices=("auto", "en", "fr"), default="auto")
    parser.add_argument("--speakers", action="store_true")
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    parser.add_argument("--threads", type=int, default=max(4, min(8, os.cpu_count() or 4)))
    parser.add_argument("--whisper", default="whisper-cli")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--diarization-python")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_speakers is not None and args.min_speakers < 1:
        print("Minimum speakers must be at least one.", file=sys.stderr)
        return 2
    if args.max_speakers is not None and args.max_speakers < 1:
        print("Maximum speakers must be at least one.", file=sys.stderr)
        return 2
    if args.min_speakers and args.max_speakers and args.min_speakers > args.max_speakers:
        print("Minimum speakers cannot exceed maximum speakers.", file=sys.stderr)
        return 2
    try:
        process(vars(args))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
