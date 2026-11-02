#!/usr/bin/env python3
"""Fixture-checked attribution scores.

These helpers do not claim acoustic accuracy. They return ``UNMEASURED`` when
no reference is supplied, and they raise ``ScoringError`` when a caller asks
for a number the inputs cannot support. Overlap-aware speaker-time scoring is
unsupported: pyannote.metrics is not used, and a homemade overlap DER would
look more authoritative than it is. Word scoring is defined below and checked
against hand-computed fixtures.

Word attribution
    Reference and hypothesis must contain the same words in the same order.
    Each pair of endpoints must agree within 0.001 s. No forced alignment is
    attempted. An explicit ``mapping`` from every hypothesis model label to a
    reference label is required. Missing labels raise instead of being guessed.

    A hypothesis word is answered only when it names one speaker. Ambiguous,
    unassigned, invalid, missing, and excluded words are abstentions.
    ``accuracy_on_answered`` uses answered words as the denominator.
    ``unique_assignment_rate`` uses every decidable reference word, so extra
    abstention cannot raise the accuracy figure. Reference entries with no
    speaker, or with ``UNKNOWN``, are reference abstentions and are not scored.
    If nothing decidable remains, the result is ``UNMEASURED``.

    When the reference lists more than one speaker, a hypothesis that names
    exactly that set (after mapping) counts as overlap preserved and as an
    abstention, not as a correct unique answer. A single hypothesis speaker
    on that word counts as overlap collapsed and as an incorrect answer.

Speaker-time error ratio
    Non-overlapping reference and hypothesis turns only. ``mapping`` must name
    every speaker on both sides. A mapping value of ``None`` means the
    hypothesis speaker matches nobody. Regions within ``collar`` seconds of a
    reference boundary are unscored. The ratio is
    ``(miss + false_alarm + confusion) / scored_reference_speech``.
    Zero scored reference speech raises instead of returning 0 or 1.
"""

from __future__ import annotations

import math
from typing import Any


class ScoringError(Exception):
    """The requested score is undefined for these inputs."""


UNIQUE_METHODS = {"turn_overlap", "contained_point", "boundary", "nearest", "punctuation"}
ABSTAIN_METHODS = {
    "ambiguous_overlap",
    "ambiguous_point",
    "ambiguous_gap",
    "unassigned",
    "invalid",
    "missing_time",
    "excluded_after_through",
}
TIME_TOLERANCE_SECONDS = 0.001


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _unmeasured(reason: str, **fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "UNMEASURED", "reason": reason}
    result.update(fields)
    return result


def _require_mapping(mapping: dict[str, Any] | None, labels: set[str]) -> dict[str, str]:
    if mapping is None:
        raise ScoringError("explicit speaker mapping required")
    if not isinstance(mapping, dict):
        raise ScoringError("speaker mapping must be an object")
    resolved: dict[str, str] = {}
    for label in labels:
        if label not in mapping or mapping[label] is None or mapping[label] == "":
            raise ScoringError(f"hypothesis label has no reference mapping: {label}")
        if not isinstance(mapping[label], str):
            raise ScoringError(f"mapping for {label} is not a speaker label")
        resolved[label] = mapping[label]
    return resolved


def _endpoints(item: dict[str, Any], *, what: str) -> tuple[float, float]:
    start, end = item.get("start"), item.get("end")
    if not _finite(start) or not _finite(end) or float(end) < float(start):
        raise ScoringError(f"{what} has an invalid interval")
    return float(start), float(end)


def score_words(
    reference: list[dict[str, Any]] | None,
    hypothesis: list[dict[str, Any]] | None,
    mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if reference is None or hypothesis is None:
        return _unmeasured("no_reference")
    if not isinstance(reference, list) or not isinstance(hypothesis, list):
        raise ScoringError("reference and hypothesis must be lists")
    if len(reference) != len(hypothesis):
        raise ScoringError("word count mismatch; refusing to realign")

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reference_abstentions = 0
    for index, (ref, hyp) in enumerate(zip(reference, hypothesis)):
        if not isinstance(ref, dict) or not isinstance(hyp, dict):
            raise ScoringError("word entries must be objects")
        ref_start, ref_end = _endpoints(ref, what=f"reference word {index}")
        hyp_start, hyp_end = _endpoints(hyp, what=f"hypothesis word {index}")
        if abs(ref_start - hyp_start) > TIME_TOLERANCE_SECONDS or abs(ref_end - hyp_end) > TIME_TOLERANCE_SECONDS:
            raise ScoringError("timestamp mismatch; refusing to shift words")
        speakers = ref.get("speakers")
        if not isinstance(speakers, list) or any(not isinstance(label, str) for label in speakers):
            raise ScoringError("reference speakers must be a list of labels")
        if not speakers or any(label in {"", "UNKNOWN"} for label in speakers):
            reference_abstentions += 1
            continue
        pairs.append((ref, hyp))

    if not pairs:
        return _unmeasured(
            "no_decidable_reference_words",
            reference_abstentions=reference_abstentions,
        )

    labels: set[str] = set()
    for _ref, hyp in pairs:
        method = hyp.get("assignment_method")
        if method in UNIQUE_METHODS:
            speaker = hyp.get("model_speaker")
            if not isinstance(speaker, str) or not speaker:
                raise ScoringError("unique assignment is missing model_speaker")
            labels.add(speaker)
        elif method in {"ambiguous_overlap", "ambiguous_point", "ambiguous_gap"}:
            possible = hyp.get("possible_model_speakers")
            if not isinstance(possible, list) or not possible:
                raise ScoringError("ambiguous assignment is missing possible speakers")
            labels.update(possible)
        elif method in ABSTAIN_METHODS:
            continue
        else:
            raise ScoringError(f"unsupported assignment method: {method}")
    resolved = _require_mapping(mapping, labels)

    answered = correct = uncertain_answered = stable_answered = stable_correct = 0
    abstained = overlap_reference_words = overlap_preserved = overlap_collapsed = 0
    for ref, hyp in pairs:
        reference_speakers = set(ref["speakers"])
        method = hyp["assignment_method"]
        hypothesis_speakers: set[str] = set()
        if method in UNIQUE_METHODS:
            hypothesis_speakers = {resolved[hyp["model_speaker"]]}
        elif method in {"ambiguous_overlap", "ambiguous_point", "ambiguous_gap"}:
            hypothesis_speakers = {resolved[label] for label in hyp["possible_model_speakers"]}

        if len(reference_speakers) > 1:
            overlap_reference_words += 1
            if hypothesis_speakers == reference_speakers and method not in UNIQUE_METHODS:
                overlap_preserved += 1
                abstained += 1
                continue
            if method in UNIQUE_METHODS:
                overlap_collapsed += 1
                answered += 1
                if method == "nearest":
                    uncertain_answered += 1
                else:
                    stable_answered += 1
                continue
            abstained += 1
            continue

        reference_speaker = next(iter(reference_speakers))
        if method in UNIQUE_METHODS:
            answered += 1
            match = hypothesis_speakers == {reference_speaker}
            if match:
                correct += 1
            if method == "nearest":
                uncertain_answered += 1
            else:
                stable_answered += 1
                if match:
                    stable_correct += 1
            continue
        abstained += 1

    decidable = len(pairs)
    return {
        "status": "scored",
        "mapping": "explicit",
        "decidable_words": decidable,
        "reference_abstentions": reference_abstentions,
        "answered": answered,
        "correct_answered": correct,
        "abstained": abstained,
        "uncertain_answered": uncertain_answered,
        "stable_answered": stable_answered,
        "stable_correct": stable_correct,
        "unique_assignment_rate": round(answered / decidable, 6),
        "accuracy_on_answered": None if answered == 0 else round(correct / answered, 6),
        "accuracy_on_stable": None if stable_answered == 0 else round(stable_correct / stable_answered, 6),
        "overlap_reference_words": overlap_reference_words,
        "overlap_preserved": overlap_preserved,
        "overlap_collapsed": overlap_collapsed,
        "definitions": {
            "unique_assignment_rate": "answered / decidable reference words",
            "accuracy_on_answered": "correct unique answers / answered words; null when none were answered",
            "overlap_preserved": "multi-speaker reference whose hypothesis set matches and is not a single speaker",
        },
    }


def _overlaps(rows: list[dict[str, Any]]) -> bool:
    ordered = sorted(rows, key=lambda row: (float(row["start"]), float(row["end"])))
    previous_end = None
    for row in ordered:
        if previous_end is not None and float(row["start"]) < previous_end:
            return True
        previous_end = float(row["end"])
    return False


def score_speaker_time(
    reference: list[dict[str, Any]] | None,
    hypothesis: list[dict[str, Any]] | None,
    mapping: dict[str, Any] | None = None,
    collar: float = 0.0,
) -> dict[str, Any]:
    if reference is None or hypothesis is None:
        return _unmeasured("no_reference")
    if not isinstance(reference, list) or not isinstance(hypothesis, list):
        raise ScoringError("reference and hypothesis must be lists")
    if not _finite(collar) or collar < 0:
        raise ScoringError("collar must be zero or greater")
    for index, row in enumerate(reference + hypothesis):
        if not isinstance(row, dict) or not isinstance(row.get("speaker"), str) or not row["speaker"]:
            raise ScoringError(f"turn {index} is missing a speaker")
        _endpoints(row, what=f"turn {index}")
    if _overlaps(reference) or _overlaps(hypothesis):
        raise ScoringError("overlap scoring is unsupported without an independent implementation")

    labels = {row["speaker"] for row in hypothesis}
    reference_labels = {row["speaker"] for row in reference}
    if mapping is None:
        raise ScoringError("explicit speaker mapping required")
    missing = (labels | reference_labels) - set(mapping)
    if missing:
        raise ScoringError(f"mapping is missing speakers: {sorted(missing)}")
    resolved: dict[str, str | None] = {}
    for label, target in mapping.items():
        if target is not None and not isinstance(target, str):
            raise ScoringError(f"mapping for {label} is not a speaker label or null")
        resolved[label] = target

    boundaries = [float(row["start"]) for row in reference] + [float(row["end"]) for row in reference]
    points = set(boundaries)
    for row in reference + hypothesis:
        points.add(float(row["start"]))
        points.add(float(row["end"]))
    for boundary in boundaries:
        points.add(boundary - collar)
        points.add(boundary + collar)
    ordered = sorted(points)
    miss = false_alarm = confusion = correct = reference_speech = 0.0
    for left, right in zip(ordered, ordered[1:]):
        if right <= left:
            continue
        midpoint = (left + right) / 2
        if any(abs(midpoint - boundary) <= collar for boundary in boundaries):
            continue
        duration = right - left
        ref_speaker = None
        raw_hypothesis = None
        mapped_hypothesis = None
        for row in reference:
            if float(row["start"]) <= left and right <= float(row["end"]):
                ref_speaker = row["speaker"]
                break
        for row in hypothesis:
            if float(row["start"]) <= left and right <= float(row["end"]):
                raw_hypothesis = row["speaker"]
                mapped_hypothesis = resolved[row["speaker"]]
                break
        if ref_speaker is not None:
            reference_speech += duration
        if ref_speaker is not None and raw_hypothesis is None:
            miss += duration
        elif ref_speaker is None and raw_hypothesis is not None:
            false_alarm += duration
        elif (
            ref_speaker is not None
            and raw_hypothesis is not None
            and mapped_hypothesis != ref_speaker
        ):
            confusion += duration
        elif ref_speaker is not None and mapped_hypothesis == ref_speaker:
            correct += duration
    if reference_speech == 0:
        raise ScoringError("no scored reference speech")
    error = miss + false_alarm + confusion
    return {
        "status": "scored",
        "collar_seconds": collar,
        "overlap_supported": False,
        "independent_implementation": None,
        "scored_reference_speech_seconds": round(reference_speech, 6),
        "miss_seconds": round(miss, 6),
        "false_alarm_seconds": round(false_alarm, 6),
        "confusion_seconds": round(confusion, 6),
        "correct_seconds": round(correct, 6),
        "speaker_time_error_ratio": round(error / reference_speech, 6),
    }
