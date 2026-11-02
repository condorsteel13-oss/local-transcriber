#!/usr/bin/env python3
"""Deterministic word↔speaker assignment for Local Transcriber.

Policy id: scoped-overlap-v1

Timeline
    Whisper token offsets are milliseconds from the start of the normalized
    recording. Alignment converts them with ``seconds = milliseconds / 1000``.
    Diarization rows already store ``source_start`` / ``source_end`` in seconds
    on that same timeline (clip time plus the diarization source offset).
    This module does not add the offset again and does not read clip times.
    ``through`` is the normalized duration in seconds. A token whose start is
    at or after ``through`` is excluded and counted, not dropped.

Turns
    ``overlap_aware_turns`` are used whenever that list is non-empty, including
    when every row is later rejected. Alignment does not fall back to
    ``exclusive_turns`` in that case. Exclusive turns are used only when no
    overlap-aware list was provided or the list is empty. Exclusive timing has
    already removed overlap, so the result is marked uncertain.

Assignment (collar 0.020 s, slack 0.020 s, long span 1.0 s)
    Overlap is the union of a speaker's turns inside the word, in seconds.
    It is coverage, not a probability.
    - Two or more speakers with overlap > 0.020 s: ambiguous, no winner.
    - One such speaker: that speaker. Speakers at or below 0.020 s are listed
      as below-collar contacts and do not take the word.
    - No speaker above 0.020 s, and two or more below it: ambiguous.
    - No speaker above 0.020 s, and exactly one below it: ``boundary`` when the
      word is at most 1.0 s, otherwise unassigned (``long_span_weak_contact``).
    - No overlap: one speaker within 0.020 s of the midpoint is ``boundary``;
      one speaker within the maximum gap (default 1.5 s) is ``nearest`` and
      uncertain; two or more inside the gap are ambiguous; otherwise unassigned.
    - A zero-length token uses containment. Two speakers containing the point
      are ambiguous. The first row does not win a tie.
    Invalid, reversed, negative, or nonfinite times are withheld. Missing
    offsets stay missing; they are not placed at 0 s.

Punctuation
    Non-lexical tokens keep an acoustic assignment. They inherit the previous
    stable speaker only when acoustics are unassigned, the previous lexical
    token was uniquely inside a turn (not nearest or ambiguous), and the gap
    is within the utterance gap.

Identity
    Display labels are the model's anonymous labels. ``speaker_id`` is
    ``{recording_id}/{diarization_revision}/{model_label}``. The recording id
    comes from the diarized audio hash. The revision mixes the diarization
    ``run_id`` (or the turns-file hash when no run id was stored) with the
    accepted turns. Equal labels or equal cluster numbers across revisions are
    not identities. This module does not map speakers across revisions.

Status
    ``review_required`` means every lexical token has a stable single-speaker
    assignment and overlap-aware turns were used. It does not mean the labels
    are correct. ``attribution_uncertain`` and ``partial_result`` are explicit.
    ``draft_ready`` is reserved for human review and is never emitted.
    Accuracy is ``UNMEASURED`` unless a separate scorer is given a reference.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from typing import Any


POLICY_ID = "scoped-overlap-v1"
BOUNDARY_COLLAR_SECONDS = 0.020
BOUNDARY_SLACK_SECONDS = 0.020
LONG_SPAN_SECONDS = 1.0
DEFAULT_MAXIMUM_GAP_SECONDS = 1.5
DEFAULT_UTTERANCE_GAP_SECONDS = 1.25

STABLE_METHODS = {"turn_overlap", "contained_point", "boundary"}
UNIQUE_METHODS = STABLE_METHODS | {"nearest", "punctuation"}
AMBIGUOUS_METHODS = {"ambiguous_overlap", "ambiguous_point", "ambiguous_gap"}
WITHHELD_METHODS = {"invalid", "missing_time", "excluded_after_through"}
PARTIAL_REASONS = (
    "rejected_turns",
    "invalid_word_times",
    "missing_word_times",
    "words_after_through",
)
UNCERTAIN_REASONS = (
    "no_speaker_turns",
    "no_words",
    "overlap_representation_unavailable",
    "recording_scope_unverified",
    "segment_time_fallback",
    "multiple_speakers_at_once",
    "multiple_speakers_within_gap",
    "nearest_turn_within_gap",
    "long_span_weak_contact",
    "speech_outside_turns",
)
RUN_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
BANNED_KEYS = {"assignment_value", "probability", "confidence", "score"}


class AlignmentError(Exception):
    """Base class for alignment failures that must not replace an output."""


class MissingInput(AlignmentError):
    """A required input file is absent."""


class MalformedInput(AlignmentError):
    """An input exists but cannot be aligned."""


class InputChanged(AlignmentError):
    """An input changed while it was being read."""


def policy_record() -> dict[str, Any]:
    return {
        "id": POLICY_ID,
        "boundary_collar_seconds": BOUNDARY_COLLAR_SECONDS,
        "boundary_slack_seconds": BOUNDARY_SLACK_SECONDS,
        "long_span_seconds": LONG_SPAN_SECONDS,
        "default_maximum_gap_seconds": DEFAULT_MAXIMUM_GAP_SECONDS,
        "default_utterance_gap_seconds": DEFAULT_UTTERANCE_GAP_SECONDS,
        "genuine_overlap": "union overlap strictly greater than boundary_collar_seconds",
        "coverage_is_probability": False,
    }


def exceeds_collar(duration: float) -> bool:
    """True when a measured overlap is large enough to count as competing speech."""
    return duration > BOUNDARY_COLLAR_SECONDS


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_stable_bytes(path: Any) -> bytes:
    """Read a file twice and refuse to continue if the bytes change."""
    file_path = path
    if not file_path.is_file():
        raise MissingInput(f"Required input is missing: {file_path}")
    first = file_path.read_bytes()
    if not file_path.is_file():
        raise InputChanged(f"Input disappeared while reading: {file_path}")
    second = file_path.read_bytes()
    if first != second:
        raise InputChanged(f"Input changed while reading: {file_path}")
    return first


def recording_identity(payload: dict[str, Any]) -> tuple[str, bool]:
    audio = payload.get("audio") if isinstance(payload, dict) else None
    digest = audio.get("sha256") if isinstance(audio, dict) else None
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return "rec_" + digest[:16].lower(), True
    return "rec_unknown", False


def run_discriminator(payload: dict[str, Any], turns_sha256: str) -> tuple[str, str]:
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    if isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id):
        return run_id.lower(), "run_id"
    return turns_sha256, "turns_file_sha256"


def revision_id(
    *,
    discriminator: str,
    discriminator_source: str,
    model: Any,
    source_offset: Any,
    turns_used: str,
    turns: list[dict[str, Any]],
) -> str:
    offset = round(float(source_offset), 3) if finite_number(source_offset) else None
    body = {
        "discriminator": discriminator,
        "discriminator_source": discriminator_source,
        "model": model if isinstance(model, str) else None,
        "source_offset_seconds": offset,
        "turns_used": turns_used,
        "turns": [
            {
                "speaker_id": turn["speaker_id"],
                "source_start": round(float(turn["source_start"]), 3),
                "source_end": round(float(turn["source_end"]), 3),
            }
            for turn in turns
        ],
    }
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return "dia_" + hashlib.sha256(encoded.encode()).hexdigest()[:16]


def scope_speaker(recording_id: str, diarization_revision: str, model_label: str) -> str:
    return f"{recording_id}/{diarization_revision}/{model_label}"


def turn_problem(row: Any) -> str | None:
    if not isinstance(row, dict):
        return "not_an_object"
    speaker = row.get("speaker_id")
    if (
        not isinstance(speaker, str)
        or not speaker.strip()
        or "/" in speaker
        or any(character.isspace() for character in speaker)
    ):
        return "invalid_speaker_id"
    start, end = row.get("source_start"), row.get("source_end")
    if not finite_number(start) or not finite_number(end):
        return "invalid_time"
    if float(start) < 0 or float(end) <= float(start):
        return "invalid_interval"
    return None


def classify_turns(rows: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        problem = turn_problem(row)
        if problem:
            rejected.append({"index": index, "reason": problem})
            continue
        accepted.append(
            {
                "speaker_id": str(row["speaker_id"]),
                "source_start": float(row["source_start"]),
                "source_end": float(row["source_end"]),
            }
        )
    return accepted, rejected


def select_turn_source(payload: dict[str, Any]) -> tuple[str, list[Any]]:
    if not isinstance(payload, dict):
        raise MalformedInput("Speaker turns must be a JSON object.")
    has_overlap = "overlap_aware_turns" in payload
    has_exclusive = "exclusive_turns" in payload
    if not has_overlap and not has_exclusive:
        raise MalformedInput(
            "Speaker turns contain neither overlap_aware_turns nor exclusive_turns."
        )
    overlap = payload.get("overlap_aware_turns")
    exclusive = payload.get("exclusive_turns")
    if has_overlap and not isinstance(overlap, list):
        raise MalformedInput("overlap_aware_turns is not a list.")
    if has_exclusive and not isinstance(exclusive, list):
        raise MalformedInput("exclusive_turns is not a list.")
    if isinstance(overlap, list) and len(overlap) > 0:
        return "overlap_aware_turns", overlap
    if isinstance(exclusive, list):
        return "exclusive_turns", exclusive
    return "overlap_aware_turns", []


def source_offset_seconds(payload: dict[str, Any]) -> float:
    audio = payload.get("audio")
    if isinstance(audio, dict) and finite_number(audio.get("source_offset_seconds")):
        return float(audio["source_offset_seconds"])
    return 0.0


def stamp_diarization(payload: dict[str, Any]) -> dict[str, Any]:
    """Add run scope and revision ids without changing raw turn rows."""
    stamped = json.loads(json.dumps(payload, allow_nan=False))
    if not isinstance(stamped.get("run_id"), str) or not RUN_ID_RE.fullmatch(stamped["run_id"]):
        stamped["run_id"] = str(uuid.uuid4())
    recording, verified = recording_identity(stamped)
    offset = source_offset_seconds(stamped)
    model = stamped.get("model")
    discriminator, discriminator_source = run_discriminator(stamped, "")
    provenance: dict[str, Any] = {
        "recording_id": recording,
        "recording_id_verified": verified,
        "run_id": stamped["run_id"],
        "labels_are_person_identities": False,
        "cross_revision_mapping": None,
    }
    for key, used_name, field in (
        ("exclusive_turns", "exclusive_turns", "exclusive_revision"),
        ("overlap_aware_turns", "overlap_aware_turns", "overlap_revision"),
    ):
        rows = stamped.get(key)
        if not isinstance(rows, list):
            provenance[field] = None
            provenance[f"rejected_{key}"] = None
            continue
        accepted, rejected = classify_turns(rows)
        provenance[field] = revision_id(
            discriminator=discriminator,
            discriminator_source=discriminator_source,
            model=model,
            source_offset=offset,
            turns_used=used_name,
            turns=accepted,
        )
        provenance[f"rejected_{key}"] = len(rejected)
    stamped["provenance"] = provenance
    return stamped


def overlap_union(
    start: float, end: float, turns: list[dict[str, Any]], speaker: str
) -> float:
    intervals: list[list[float]] = []
    for turn in turns:
        if turn["speaker_id"] != speaker:
            continue
        low = max(start, turn["source_start"])
        high = min(end, turn["source_end"])
        if high > low:
            intervals.append([low, high])
    intervals.sort()
    merged: list[list[float]] = []
    for low, high in intervals:
        if not merged or low > merged[-1][1]:
            merged.append([low, high])
        else:
            merged[-1][1] = max(merged[-1][1], high)
    return sum(high - low for low, high in merged)


def speaker_order(turns: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for turn in turns:
        if turn["speaker_id"] not in ordered:
            ordered.append(turn["speaker_id"])
    return ordered


def interval_distance(point: float, start: float, end: float) -> float:
    if point < start:
        return start - point
    if point > end:
        return point - end
    return 0.0


def _blank_assignment(start: float | None, end: float | None) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "native_end": end,
        "end_clamped": False,
        "assignment_method": "unassigned",
        "detail": None,
        "model_speaker": None,
        "speaker_id": None,
        "possible_model_speakers": [],
        "possible_speakers": [],
        "overlap_seconds": {},
        "distance_seconds": {},
        "below_collar_speakers": [],
        "acoustic_method": None,
    }


def _with_speaker(assignment: dict[str, Any], speaker: str, method: str) -> dict[str, Any]:
    assignment["assignment_method"] = method
    assignment["model_speaker"] = speaker
    assignment["possible_model_speakers"] = [speaker]
    return assignment


def _with_ambiguous(assignment: dict[str, Any], speakers: list[str], method: str) -> dict[str, Any]:
    ordered = sorted(speakers)
    assignment["assignment_method"] = method
    assignment["model_speaker"] = None
    assignment["possible_model_speakers"] = ordered
    return assignment


def _speaker_overlaps(
    start: float, end: float, turns: list[dict[str, Any]]
) -> dict[str, float]:
    measured: dict[str, float] = {}
    for speaker in speaker_order(turns):
        duration = overlap_union(start, end, turns, speaker)
        if duration > 0:
            measured[speaker] = duration
    return measured


def assign_gap(
    start: float,
    end: float,
    turns: list[dict[str, Any]],
    maximum_gap: float,
    assignment: dict[str, Any],
) -> dict[str, Any]:
    if not turns:
        assignment["assignment_method"] = "unassigned"
        return assignment
    if not finite_number(maximum_gap) or maximum_gap < 0:
        assignment["assignment_method"] = "unassigned"
        assignment["detail"] = "invalid_maximum_gap"
        return assignment
    midpoint = (start + end) / 2
    distances: dict[str, float] = {}
    for speaker in speaker_order(turns):
        distances[speaker] = min(
            interval_distance(midpoint, turn["source_start"], turn["source_end"])
            for turn in turns
            if turn["speaker_id"] == speaker
        )
    assignment["distance_seconds"] = {
        speaker: round(distance, 6) for speaker, distance in sorted(distances.items())
    }
    near = sorted(speaker for speaker, distance in distances.items() if distance <= maximum_gap)
    if len(near) == 1:
        method = "boundary" if distances[near[0]] <= BOUNDARY_SLACK_SECONDS else "nearest"
        return _with_speaker(assignment, near[0], method)
    if len(near) >= 2:
        return _with_ambiguous(assignment, near, "ambiguous_gap")
    assignment["assignment_method"] = "unassigned"
    return assignment


def assign_point(
    point: float,
    turns: list[dict[str, Any]],
    maximum_gap: float,
    assignment: dict[str, Any],
) -> dict[str, Any]:
    holders = [
        speaker
        for speaker in speaker_order(turns)
        if any(
            turn["speaker_id"] == speaker
            and turn["source_start"] <= point <= turn["source_end"]
            for turn in turns
        )
    ]
    if len(holders) == 1:
        return _with_speaker(assignment, holders[0], "contained_point")
    if len(holders) >= 2:
        return _with_ambiguous(assignment, holders, "ambiguous_point")
    return assign_gap(point, point, turns, maximum_gap, assignment)


def assign_interval(
    start: Any,
    end: Any,
    turns: list[dict[str, Any]],
    maximum_gap: float,
    through: float,
) -> dict[str, Any]:
    assignment = _blank_assignment(
        float(start) if finite_number(start) else None,
        float(end) if finite_number(end) else None,
    )
    if not finite_number(start) or not finite_number(end):
        assignment["assignment_method"] = "invalid"
        assignment["detail"] = "nonfinite"
        return assignment
    start = float(start)
    end = float(end)
    assignment["start"] = start
    assignment["end"] = end
    assignment["native_end"] = end
    if end < start:
        assignment["assignment_method"] = "invalid"
        assignment["detail"] = "reversed"
        return assignment
    if start < 0:
        assignment["assignment_method"] = "invalid"
        assignment["detail"] = "negative"
        return assignment
    if not finite_number(through) or through <= 0:
        assignment["assignment_method"] = "invalid"
        assignment["detail"] = "invalid_through"
        return assignment
    if start >= through:
        assignment["assignment_method"] = "excluded_after_through"
        return assignment
    if end > through:
        assignment["native_end"] = end
        assignment["end"] = through
        assignment["end_clamped"] = True
        end = through
    if end == start:
        return assign_point(start, turns, maximum_gap, assignment)

    measured = _speaker_overlaps(start, end, turns)
    assignment["overlap_seconds"] = {
        speaker: round(duration, 6) for speaker, duration in sorted(measured.items())
    }
    competing = sorted(
        speaker for speaker, duration in measured.items() if exceeds_collar(duration)
    )
    weak = sorted(
        speaker for speaker, duration in measured.items() if not exceeds_collar(duration)
    )
    if len(competing) >= 2:
        return _with_ambiguous(assignment, competing, "ambiguous_overlap")
    if len(competing) == 1:
        assignment["below_collar_speakers"] = weak
        return _with_speaker(assignment, competing[0], "turn_overlap")
    if len(weak) >= 2:
        return _with_ambiguous(assignment, weak, "ambiguous_overlap")
    if len(weak) == 1:
        if end - start > LONG_SPAN_SECONDS:
            assignment["assignment_method"] = "unassigned"
            assignment["detail"] = "long_span_weak_contact"
            assignment["below_collar_speakers"] = weak
            return assignment
        assignment["below_collar_speakers"] = []
        return _with_speaker(assignment, weak[0], "boundary")
    return assign_gap(start, end, turns, maximum_gap, assignment)


def _parse_offsets(offsets: Any) -> tuple[str, Any, Any]:
    if not isinstance(offsets, dict) or "from" not in offsets or "to" not in offsets:
        return "missing_time", None, None
    return "timed", offsets.get("from"), offsets.get("to")


def _skip_token(text: Any) -> bool:
    return not isinstance(text, str) or text == "" or text.startswith("[_")


def extract_items(whisper: dict[str, Any]) -> list[dict[str, Any]]:
    transcription = whisper.get("transcription") if isinstance(whisper, dict) else None
    if not isinstance(transcription, list):
        raise MalformedInput("Whisper JSON has no transcription list.")
    items: list[dict[str, Any]] = []
    for segment in transcription:
        if not isinstance(segment, dict):
            items.append(
                {
                    "text": "",
                    "time_basis": "segment",
                    "offset_state": "invalid",
                    "start": None,
                    "end": None,
                    "detail": "segment_not_object",
                }
            )
            continue
        tokens = segment.get("tokens")
        emitted = 0
        if isinstance(tokens, list):
            for token in tokens:
                if not isinstance(token, dict):
                    items.append(
                        {
                            "text": "",
                            "time_basis": "token",
                            "offset_state": "invalid",
                            "start": None,
                            "end": None,
                            "detail": "token_not_object",
                        }
                    )
                    emitted += 1
                    continue
                text = token.get("text")
                if _skip_token(text):
                    continue
                state, start, end = _parse_offsets(token.get("offsets"))
                if state == "timed" and finite_number(start) and finite_number(end):
                    start = float(start) / 1000.0
                    end = float(end) / 1000.0
                items.append(
                    {
                        "text": text,
                        "time_basis": "token",
                        "offset_state": state,
                        "start": start,
                        "end": end,
                        "detail": None,
                    }
                )
                emitted += 1
        elif tokens is not None:
            raise MalformedInput("Whisper segment tokens are not a list.")
        if emitted:
            continue
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        state, start, end = _parse_offsets(segment.get("offsets"))
        if state == "timed" and finite_number(start) and finite_number(end):
            start = float(start) / 1000.0
            end = float(end) / 1000.0
        items.append(
            {
                "text": text,
                "time_basis": "segment",
                "offset_state": state,
                "start": start,
                "end": end,
                "detail": "segment_without_word_times",
            }
        )
    return items


def _nonlexical(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and not any(character.isalnum() for character in stripped)


def apply_punctuation(words: list[dict[str, Any]], utterance_gap: float) -> None:
    previous: dict[str, Any] | None = None
    blocked = False
    for word in words:
        method = word["assignment_method"]
        if method in WITHHELD_METHODS:
            blocked = True
            continue
        if _nonlexical(word["text"]):
            if (
                method == "unassigned"
                and previous is not None
                and not blocked
                and finite_number(word.get("start"))
                and finite_number(previous.get("end"))
            ):
                gap = float(word["start"]) - float(previous["end"])
                if -BOUNDARY_COLLAR_SECONDS <= gap <= utterance_gap:
                    word["acoustic_method"] = method
                    word["assignment_method"] = "punctuation"
                    word["detail"] = "punctuation_inherited"
                    word["model_speaker"] = previous["model_speaker"]
                    word["speaker_id"] = previous["speaker_id"]
                    word["possible_model_speakers"] = [previous["model_speaker"]]
                    word["possible_speakers"] = [previous["speaker_id"]]
            continue
        if method in STABLE_METHODS and word.get("model_speaker"):
            previous = word
            blocked = False
        else:
            blocked = True


def display_label(word: dict[str, Any]) -> str:
    method = word["assignment_method"]
    speaker = word.get("model_speaker")
    possible = word.get("possible_model_speakers") or []
    if method in {"turn_overlap", "contained_point", "boundary", "punctuation"}:
        return str(speaker)
    if method == "nearest":
        return f"UNCERTAIN[{speaker}]"
    if method in AMBIGUOUS_METHODS:
        return "AMBIGUOUS[" + "|".join(possible) + "]"
    if method == "unassigned":
        return "UNASSIGNED"
    if method == "invalid":
        return "INVALID"
    if method == "missing_time":
        return "MISSING_TIME"
    if method == "excluded_after_through":
        return "EXCLUDED"
    return str(method)


def _identity(word: dict[str, Any]) -> tuple[Any, ...]:
    method = word["assignment_method"]
    if method in STABLE_METHODS or method == "punctuation":
        return ("assigned", word.get("model_speaker"))
    if method == "nearest":
        return ("nearest", word.get("model_speaker"))
    if method in AMBIGUOUS_METHODS:
        return (method, tuple(word.get("possible_model_speakers") or []))
    return (method, None)


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    if milliseconds < 0:
        milliseconds = 0
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def group_utterances(
    words: list[dict[str, Any]], utterance_gap: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    utterances: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish(utterance: dict[str, Any]) -> None:
        raw = "".join(words[index]["text"] for index in utterance["word_indexes"])
        utterance["text"] = raw.strip()
        utterance.pop("_key", None)
        if utterance["text"]:
            utterances.append(utterance)

    for index, word in enumerate(words):
        if word["assignment_method"] in WITHHELD_METHODS:
            if current is not None:
                finish(current)
                current = None
            if finite_number(word.get("start")) and finite_number(word.get("end")):
                when = f"{format_timestamp(word['start'])} --> {format_timestamp(word['end'])}"
            else:
                when = "-- --> --"
            withheld.append(
                {
                    "word_index": index,
                    "display_label": display_label(word),
                    "text": word["text"].strip(),
                    "time_label": when,
                    "assignment_method": word["assignment_method"],
                }
            )
            continue
        key = _identity(word)
        should_split = current is None or key != current["_key"]
        if (
            current is not None
            and finite_number(word.get("start"))
            and finite_number(current.get("end"))
            and float(word["start"]) - float(current["end"]) > utterance_gap
        ):
            should_split = True
        if should_split:
            if current is not None:
                finish(current)
            current = {
                "_key": key,
                "speaker_id": word.get("speaker_id"),
                "model_speaker": word.get("model_speaker"),
                "possible_speakers": list(word.get("possible_speakers") or []),
                "possible_model_speakers": list(word.get("possible_model_speakers") or []),
                "display_label": display_label(word),
                "start": word.get("start"),
                "end": word.get("end"),
                "word_indexes": [index],
                "methods": {word["assignment_method"]: 1},
            }
            continue
        current["end"] = word.get("end")
        current["word_indexes"].append(index)
        method = word["assignment_method"]
        current["methods"][method] = current["methods"].get(method, 0) + 1
    if current is not None:
        finish(current)
    for number, utterance in enumerate(utterances, start=1):
        utterance["id"] = f"utterance_{number:06d}"
        utterance["word_count"] = len(utterance["word_indexes"])
    return utterances, withheld


def decide_status(
    words: list[dict[str, Any]],
    rejected_turns: list[dict[str, Any]],
    turns_used: str,
    recording_verified: bool,
    accepted_turn_count: int,
) -> tuple[str, str, list[str]]:
    partial: list[str] = []
    uncertain: list[str] = []
    methods = [word["assignment_method"] for word in words]
    details = [word.get("detail") for word in words]
    if rejected_turns:
        partial.append("rejected_turns")
    if any(method == "invalid" for method in methods):
        partial.append("invalid_word_times")
    if any(method == "missing_time" for method in methods):
        partial.append("missing_word_times")
    if any(method == "excluded_after_through" for method in methods):
        partial.append("words_after_through")
    if accepted_turn_count == 0:
        uncertain.append("no_speaker_turns")
    if not words:
        uncertain.append("no_words")
    if turns_used == "exclusive_turns":
        uncertain.append("overlap_representation_unavailable")
    if not recording_verified:
        uncertain.append("recording_scope_unverified")
    if any(word.get("time_basis") == "segment" for word in words):
        uncertain.append("segment_time_fallback")
    if any(method in {"ambiguous_overlap", "ambiguous_point"} for method in methods):
        uncertain.append("multiple_speakers_at_once")
    if any(method == "ambiguous_gap" for method in methods):
        uncertain.append("multiple_speakers_within_gap")
    if any(method == "nearest" for method in methods):
        uncertain.append("nearest_turn_within_gap")
    if any(detail == "long_span_weak_contact" for detail in details):
        uncertain.append("long_span_weak_contact")
    if any(method == "unassigned" for method in methods):
        uncertain.append("speech_outside_turns")
    if partial:
        reasons = partial + [reason for reason in uncertain if reason not in partial]
        return "partial_result", reasons[0], reasons
    if uncertain:
        return "attribution_uncertain", uncertain[0], uncertain
    return "review_required", "model_labels_require_review", ["model_labels_require_review"]


def _lexical(text: str) -> bool:
    return any(character.isalnum() for character in text)


def coverage_counts(words: list[dict[str, Any]]) -> dict[str, Any]:
    lexical = [word for word in words if _lexical(word["text"])]
    unique = [word for word in lexical if word["assignment_method"] in UNIQUE_METHODS]
    ambiguous = [word for word in lexical if word["assignment_method"] in AMBIGUOUS_METHODS]
    unassigned = [word for word in lexical if word["assignment_method"] == "unassigned"]
    withheld = [word for word in words if word["assignment_method"] in WITHHELD_METHODS]
    nearest = [word for word in lexical if word["assignment_method"] == "nearest"]
    total = len(lexical)
    return {
        "tokens": len(words),
        "lexical_tokens": total,
        "unique_assignments": len(unique),
        "ambiguous_assignments": len(ambiguous),
        "unassigned_lexical_tokens": len(unassigned),
        "nearest_assignments": len(nearest),
        "withheld_tokens": len(withheld),
        "unique_assignment_rate": None if total == 0 else round(len(unique) / total, 6),
        "unique_assignment_rate_is_accuracy": False,
    }


def _attach_scope(
    assignment: dict[str, Any], recording: str, revision: str
) -> dict[str, Any]:
    speaker = assignment.get("model_speaker")
    assignment["speaker_id"] = (
        scope_speaker(recording, revision, speaker) if speaker else None
    )
    assignment["possible_speakers"] = [
        scope_speaker(recording, revision, label)
        for label in assignment.get("possible_model_speakers") or []
    ]
    return assignment


def build_alignment(
    whisper: dict[str, Any],
    diarization: dict[str, Any],
    *,
    through: float,
    maximum_gap: float = DEFAULT_MAXIMUM_GAP_SECONDS,
    utterance_gap: float = DEFAULT_UTTERANCE_GAP_SECONDS,
    whisper_sha256: str,
    turns_sha256: str,
    whisper_path: str,
    turns_path: str,
) -> dict[str, Any]:
    if not finite_number(through) or through <= 0:
        raise MalformedInput("--through must be a finite duration greater than zero.")
    if not finite_number(maximum_gap) or maximum_gap < 0:
        raise MalformedInput("--maximum-gap must be zero or greater.")
    if not finite_number(utterance_gap) or utterance_gap < 0:
        raise MalformedInput("--utterance-gap must be zero or greater.")
    turns_used, raw_rows = select_turn_source(diarization)
    accepted, rejected = classify_turns(raw_rows)
    recording, verified = recording_identity(diarization)
    offset = source_offset_seconds(diarization)
    discriminator, discriminator_source = run_discriminator(diarization, turns_sha256)
    revision = revision_id(
        discriminator=discriminator,
        discriminator_source=discriminator_source,
        model=diarization.get("model"),
        source_offset=offset,
        turns_used=turns_used,
        turns=accepted,
    )
    words: list[dict[str, Any]] = []
    for item in extract_items(whisper):
        if item["offset_state"] == "missing_time":
            assignment = _blank_assignment(None, None)
            assignment["assignment_method"] = "missing_time"
            assignment["detail"] = item.get("detail")
        elif item["offset_state"] == "invalid":
            assignment = _blank_assignment(None, None)
            assignment["assignment_method"] = "invalid"
            assignment["detail"] = item.get("detail") or "invalid_time"
        else:
            assignment = assign_interval(
                item["start"], item["end"], accepted, maximum_gap, through
            )
            if item.get("detail") and assignment.get("detail") is None:
                assignment["detail"] = item["detail"]
            _attach_scope(assignment, recording, revision)
        assignment["text"] = item["text"]
        assignment["time_basis"] = item["time_basis"]
        words.append(assignment)
    apply_punctuation(words, utterance_gap)
    utterances, withheld = group_utterances(words, utterance_gap)
    status, reason, reasons = decide_status(
        words, rejected, turns_used, verified, len(accepted)
    )
    speakers = [
        {
            "model_speaker": label,
            "speaker_id": scope_speaker(recording, revision, label),
            "recording_id": recording,
            "diarization_revision": revision,
            "is_person_identity": False,
        }
        for label in sorted({turn["speaker_id"] for turn in accepted})
    ]
    return {
        "schema_version": 2,
        "status": status,
        "status_reason": reason,
        "status_reasons": reasons,
        "accuracy": "UNMEASURED",
        "accuracy_reason": "This run has no human speaker reference.",
        "labels_are_person_identities": False,
        "cross_revision_mapping": None,
        "assignment_policy": policy_record(),
        "recording_id": recording,
        "recording_id_verified": verified,
        "diarization_revision": revision,
        "revision_discriminator_source": discriminator_source,
        "turns_used": turns_used,
        "timeline": {
            "word_unit": "seconds",
            "word_origin": "whisper token offsets in milliseconds divided by 1000",
            "turn_unit": "seconds",
            "turn_fields": ["source_start", "source_end"],
            "clip_times_used": False,
            "source_offset_seconds": offset,
            "offset_applied_in_align": False,
            "through_seconds": through,
        },
        "inputs": {
            "whisper_json": {"path": whisper_path, "sha256": whisper_sha256},
            "speaker_turns": {"path": turns_path, "sha256": turns_sha256},
            "model": diarization.get("model") if isinstance(diarization.get("model"), str) else None,
        },
        "rejected_turns": rejected,
        "speakers": speakers,
        "counts": coverage_counts(words),
        "alignment": {
            "maximum_gap_seconds": maximum_gap,
            "utterance_gap_seconds": utterance_gap,
            "boundary_collar_seconds": BOUNDARY_COLLAR_SECONDS,
            "boundary_slack_seconds": BOUNDARY_SLACK_SECONDS,
        },
        "words": words,
        "utterances": utterances,
        "withheld": withheld,
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"# status: {payload['status']}",
        f"# status_reason: {payload['status_reason']}",
        f"# assignment_policy: {payload['assignment_policy']['id']}",
        f"# recording_id: {payload['recording_id']}",
        f"# diarization_revision: {payload['diarization_revision']}",
        f"# turns_used: {payload['turns_used']}",
        "# Speaker labels are anonymous and scoped to this recording and diarization revision.",
        "# Equal labels in another file or revision are not the same person.",
        "# Overlap is left ambiguous. Listed durations are not probabilities.",
        "# Accuracy against a human reference is UNMEASURED.",
    ]
    for utterance in payload["utterances"]:
        if not utterance["text"]:
            continue
        lines.append(
            f"[{format_timestamp(utterance['start'])} --> {format_timestamp(utterance['end'])}] "
            f"{utterance['display_label']}: {utterance['text']}"
        )
    if payload["withheld"]:
        lines.append("# withheld")
        for item in payload["withheld"]:
            if not item["text"]:
                continue
            lines.append(f"[{item['time_label']}] {item['display_label']}: {item['text']}")
    return "\n".join(lines) + "\n"


def _banned_keys(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in BANNED_KEYS:
                found.add(key)
            _banned_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _banned_keys(item, found)


def validate_result(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 2:
        raise MalformedInput("Alignment result schema is not version 2.")
    if payload.get("status") not in {
        "review_required",
        "attribution_uncertain",
        "partial_result",
    }:
        raise MalformedInput(f"Alignment status is not publishable: {payload.get('status')}")
    if payload.get("accuracy") != "UNMEASURED":
        raise MalformedInput("Alignment must not claim a measured accuracy.")
    if payload.get("assignment_policy", {}).get("coverage_is_probability") is not False:
        raise MalformedInput("Coverage must not be described as a probability.")
    found: set[str] = set()
    _banned_keys(payload, found)
    if found:
        raise MalformedInput(f"Alignment contains banned fields: {sorted(found)}")
    recording = payload.get("recording_id")
    revision = payload.get("diarization_revision")
    words = payload.get("words")
    if not isinstance(words, list):
        raise MalformedInput("Alignment words are missing.")
    for word in words:
        speaker_id = word.get("speaker_id")
        if speaker_id is not None and not str(speaker_id).startswith(f"{recording}/{revision}/"):
            raise MalformedInput("Speaker id is not scoped to this recording and revision.")
        for scoped in word.get("possible_speakers") or []:
            if not str(scoped).startswith(f"{recording}/{revision}/"):
                raise MalformedInput("Possible speaker id is not revision-scoped.")
    for utterance in payload.get("utterances") or []:
        raw = "".join(words[index]["text"] for index in utterance["word_indexes"])
        if raw.strip() != utterance["text"]:
            raise MalformedInput("Utterance text does not match its tokens.")
    status, reason, reasons = decide_status(
        words,
        payload.get("rejected_turns") or [],
        payload.get("turns_used"),
        bool(payload.get("recording_id_verified")),
        len(payload.get("speakers") or []),
    )
    if (status, reason, reasons) != (
        payload.get("status"),
        payload.get("status_reason"),
        payload.get("status_reasons"),
    ):
        raise MalformedInput("Stored attribution status does not match the words.")
