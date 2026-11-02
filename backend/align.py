#!/usr/bin/env python3
"""Align Whisper words with pyannote turns, preserving overlap and uncertainty.

The assignment rules live in ``attribution.py`` (policy ``scoped-overlap-v1``).
A successful process exit means the alignment file was validated and committed.
It does not mean the speaker labels are correct.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from attribution import (
    AlignmentError,
    InputChanged,
    MalformedInput,
    MissingInput,
    build_alignment,
    digest_bytes,
    read_stable_bytes,
    render_text,
    validate_result,
)
from core import atomic_json, exclusive_lock, read_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper-json", type=Path, required=True)
    parser.add_argument("--speaker-turns", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", type=float, required=True)
    parser.add_argument("--maximum-gap", type=float, default=1.5)
    parser.add_argument("--utterance-gap", type=float, default=1.25)
    return parser.parse_args(argv)


def _load_pair(whisper_path: Path, turns_path: Path) -> tuple[dict, dict, str, str]:
    whisper_bytes = read_stable_bytes(whisper_path)
    turns_bytes = read_stable_bytes(turns_path)
    try:
        whisper = read_json(whisper_path)
        turns = read_json(turns_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise MalformedInput(f"Could not parse alignment input: {error}") from error
    if read_stable_bytes(whisper_path) != whisper_bytes or read_stable_bytes(turns_path) != turns_bytes:
        raise InputChanged("Alignment input changed during parsing.")
    if not isinstance(whisper, dict) or not isinstance(turns, dict):
        raise MalformedInput("Alignment inputs must be JSON objects.")
    return whisper, turns, digest_bytes(whisper_bytes), digest_bytes(turns_bytes)


def commit_alignment(output: Path, payload: dict, text: str) -> Path:
    """Validate, then publish. A failed attempt leaves any existing output in place."""
    attempt = output.parent / "attempts" / f"align_{uuid.uuid4().hex}"
    attempt.mkdir(parents=True, exist_ok=False)
    status: dict = {"state": "writing", "output": str(output)}
    atomic_json(attempt / "status.json", status)
    try:
        validate_result(payload)
        body = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        json_path = attempt / "transcript-with-speakers.json"
        text_path = attempt / "transcript-with-speakers.txt"
        json_path.write_text(body, encoding="utf-8")
        text_path.write_text(text, encoding="utf-8")
        if json_path.read_text(encoding="utf-8") != body or text_path.read_text(encoding="utf-8") != text:
            raise MalformedInput("Attempt files did not round-trip.")
        status = {
            "state": "validated",
            "result_sha256": digest_bytes(body.encode()),
            "text_sha256": digest_bytes(text.encode()),
        }
        atomic_json(attempt / "status.json", status)
        output.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(output.parent, f"align-{output.name}"):
            temporary_json = output.with_suffix(".json.committing")
            temporary_text = output.with_suffix(".txt.committing")
            temporary_json.write_text(body, encoding="utf-8")
            temporary_text.write_text(text, encoding="utf-8")
            temporary_json.replace(output)
            temporary_text.replace(output.with_suffix(".txt"))
            if output.read_text(encoding="utf-8") != body or output.with_suffix(".txt").read_text(
                encoding="utf-8"
            ) != text:
                status = {"state": "commit_mismatch", "output": str(output)}
                atomic_json(attempt / "status.json", status)
                raise MalformedInput("Committed alignment did not match the validated attempt.")
        status = {"state": "committed", "output": str(output), "attempt": str(attempt)}
        atomic_json(attempt / "status.json", status)
        return attempt
    except Exception:
        status = {"state": "failed", "output": str(output)}
        atomic_json(attempt / "status.json", status)
        raise


def run(args: argparse.Namespace) -> int:
    whisper_path = args.whisper_json.expanduser().resolve()
    turns_path = args.speaker_turns.expanduser().resolve()
    output = args.output.expanduser().resolve()
    whisper, turns, whisper_sha, turns_sha = _load_pair(whisper_path, turns_path)
    payload = build_alignment(
        whisper,
        turns,
        through=args.through,
        maximum_gap=args.maximum_gap,
        utterance_gap=args.utterance_gap,
        whisper_sha256=whisper_sha,
        turns_sha256=turns_sha,
        whisper_path=str(whisper_path),
        turns_path=str(turns_path),
    )
    text = render_text(payload)
    attempt = commit_alignment(output, payload, text)
    summary = {
        "status": payload["status"],
        "status_reason": payload["status_reason"],
        "accuracy": payload["accuracy"],
        "counts": payload["counts"],
        "attempt": str(attempt),
        "output": str(output),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except MissingInput as error:
        print(json.dumps({"status": "missing_input", "reason": str(error)}), file=sys.stderr)
        return 2
    except AlignmentError as error:
        print(json.dumps({"status": "processing_failed", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
