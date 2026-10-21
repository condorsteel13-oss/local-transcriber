#!/usr/bin/env python3
"""Align Whisper word timestamps with exclusive pyannote speaker turns."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def choose_speaker(
    start: float, end: float, turns: list[dict[str, Any]], maximum_gap: float
) -> tuple[str | None, str, float]:
    if end <= start:
        containing = [
            turn
            for turn in turns
            if float(turn["source_start"]) <= start <= float(turn["source_end"])
        ]
        if containing:
            return str(containing[0]["speaker_id"]), "contains", 0.0

    overlaps: list[tuple[float, dict[str, Any]]] = []
    for turn in turns:
        overlap = max(
            0.0,
            min(end, float(turn["source_end"]))
            - max(start, float(turn["source_start"])),
        )
        if overlap:
            overlaps.append((overlap, turn))
    if overlaps:
        overlap, turn = max(overlaps, key=lambda item: item[0])
        return str(turn["speaker_id"]), "overlap", overlap

    midpoint = (start + end) / 2
    if not turns:
        return None, "unassigned", 0.0
    closest = min(
        turns,
        key=lambda turn: min(
            abs(midpoint - float(turn["source_start"])),
            abs(midpoint - float(turn["source_end"])),
        ),
    )
    distance = min(
        abs(midpoint - float(closest["source_start"])),
        abs(midpoint - float(closest["source_end"])),
    )
    if distance <= maximum_gap:
        return str(closest["speaker_id"]), "nearest", distance
    return None, "unassigned", distance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper-json", type=Path, required=True)
    parser.add_argument("--speaker-turns", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", type=float, required=True)
    parser.add_argument("--maximum-gap", type=float, default=1.5)
    parser.add_argument("--utterance-gap", type=float, default=1.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    whisper_path = args.whisper_json.resolve()
    turns_path = args.speaker_turns.resolve()
    whisper = json.loads(whisper_path.read_text(encoding="utf-8"))
    diarization = json.loads(turns_path.read_text(encoding="utf-8"))
    turns = diarization["exclusive_turns"]

    words: list[dict[str, Any]] = []
    previous_lexical_speaker: str | None = None
    for segment in whisper["transcription"]:
        for token in segment.get("tokens", []):
            text = token.get("text", "")
            offsets = token.get("offsets") or {}
            if not text or text.startswith("[_"):
                continue
            start = float(offsets.get("from", 0)) / 1000
            end = float(offsets.get("to", offsets.get("from", 0))) / 1000
            if start >= args.through:
                continue
            end = min(end, args.through)
            speaker, method, score = choose_speaker(
                start, end, turns, args.maximum_gap
            )
            if text.strip() and not any(character.isalnum() for character in text):
                if previous_lexical_speaker is not None:
                    speaker, method, score = previous_lexical_speaker, "punctuation", 0.0
            elif speaker is not None:
                previous_lexical_speaker = speaker
            words.append(
                {
                    "text": text,
                    "start": start,
                    "end": end,
                    "speaker_id": speaker,
                    "assignment_method": method,
                    "assignment_value": round(score, 3),
                }
            )

    utterances: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for word in words:
        should_split = current is None or word["speaker_id"] != current["speaker_id"]
        if current is not None and word["start"] - current["end"] > args.utterance_gap:
            should_split = True
        if should_split:
            if current is not None:
                current["text"] = current["text"].strip()
                utterances.append(current)
            current = {
                "id": f"utterance_{len(utterances) + 1:06d}",
                "speaker_id": word["speaker_id"],
                "start": word["start"],
                "end": word["end"],
                "text": word["text"],
                "word_count": 1,
                "overlap_assigned_words": int(word["assignment_method"] == "overlap"),
                "contained_words": int(word["assignment_method"] == "contains"),
                "nearest_assigned_words": int(word["assignment_method"] == "nearest"),
                "punctuation_assigned_tokens": int(
                    word["assignment_method"] == "punctuation"
                ),
                "unassigned_words": int(word["assignment_method"] == "unassigned"),
            }
        else:
            current["end"] = max(current["end"], word["end"])
            current["text"] += word["text"]
            current["word_count"] += 1
            current["overlap_assigned_words"] += int(
                word["assignment_method"] == "overlap"
            )
            current["contained_words"] += int(word["assignment_method"] == "contains")
            current["nearest_assigned_words"] += int(
                word["assignment_method"] == "nearest"
            )
            current["punctuation_assigned_tokens"] += int(
                word["assignment_method"] == "punctuation"
            )
            current["unassigned_words"] += int(
                word["assignment_method"] == "unassigned"
            )
    if current is not None:
        current["text"] = current["text"].strip()
        utterances.append(current)

    payload = {
        "schema_version": 1,
        "status": "review_preview",
        "warning": "Speaker labels are anonymous model predictions and require validation.",
        "source_through_seconds": args.through,
        "whisper_json": {"path": str(whisper_path), "sha256": digest(whisper_path)},
        "speaker_turns": {"path": str(turns_path), "sha256": digest(turns_path)},
        "alignment": {
            "maximum_gap_seconds": args.maximum_gap,
            "utterance_gap_seconds": args.utterance_gap,
            "word_count": len(words),
            "utterance_count": len(utterances),
            "overlap_assigned_words": sum(
                item["overlap_assigned_words"] for item in utterances
            ),
            "nearest_assigned_words": sum(
                item["nearest_assigned_words"] for item in utterances
            ),
            "contained_words": sum(item["contained_words"] for item in utterances),
            "punctuation_assigned_tokens": sum(
                item["punctuation_assigned_tokens"] for item in utterances
            ),
            "unassigned_words": sum(item["unassigned_words"] for item in utterances),
        },
        "utterances": utterances,
    }

    output = args.output.resolve()
    atomic_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    text_path = output.with_suffix(".txt")
    lines = [
        f"[{timestamp(item['start'])} --> {timestamp(item['end'])}] "
        f"{item['speaker_id'] or 'UNASSIGNED'}: {item['text']}"
        for item in utterances
        if item["text"]
    ]
    atomic_text(text_path, "\n".join(lines) + "\n")
    print(json.dumps(payload["alignment"], indent=2))
    print(output)
    print(text_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
