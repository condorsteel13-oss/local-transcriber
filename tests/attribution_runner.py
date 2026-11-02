"""Run a structural attribution case through the pure aligner."""

from __future__ import annotations

import json

from attribution import build_alignment, digest_bytes, render_text, validate_result


def whisper_from_case(case: dict) -> dict:
    if "segments" in case:
        return {"transcription": case["segments"]}
    tokens = []
    for token in case["tokens"]:
        item = {"text": token["text"]}
        if "from" in token and "to" in token:
            item["offsets"] = {"from": token["from"], "to": token["to"]}
        tokens.append(item)
    text = "".join(token["text"] for token in case["tokens"])
    return {
        "transcription": [
            {
                "text": text,
                "offsets": {"from": 0, "to": 100000},
                "tokens": tokens,
            }
        ]
    }


def turns_from_case(case: dict) -> dict:
    payload = {
        "model": "pyannote/speaker-diarization-community-1",
        "run_id": case["run_id"],
        "audio": {
            "path": "/tmp/example.wav",
            "sha256": case["sha256"],
            "source_offset_seconds": case.get("source_offset_seconds", 0.0),
        },
        "exclusive_turns": case.get("exclusive_turns", []),
    }
    if not case.get("omit_overlap", False):
        payload["overlap_aware_turns"] = case.get("overlap_aware_turns", [])
    if case.get("omit_run_id"):
        payload.pop("run_id")
    if case.get("omit_sha"):
        payload["audio"].pop("sha256", None)
    return payload


def run_case(case: dict) -> dict:
    whisper = whisper_from_case(case)
    turns = turns_from_case(case)
    result = build_alignment(
        whisper,
        turns,
        through=case["through"],
        maximum_gap=case.get("maximum_gap", 1.5),
        utterance_gap=case.get("utterance_gap", 1.25),
        whisper_sha256=digest_bytes(json.dumps(whisper).encode()),
        turns_sha256=digest_bytes(json.dumps(turns).encode()),
        whisper_path=f"memory://{case['id']}/whisper.json",
        turns_path=f"memory://{case['id']}/turns.json",
    )
    validate_result(result)
    return result


def assert_case(test, case: dict) -> dict:
    result = run_case(case)
    expect = case["expect"]
    test.assertEqual(result["status"], expect["status"], case["id"])
    test.assertEqual(result["accuracy"], "UNMEASURED", case["id"])
    test.assertNotEqual(result["status"], "draft_ready", case["id"])
    test.assertIsNone(result["cross_revision_mapping"], case["id"])
    for reason in expect.get("reasons_include", []):
        test.assertIn(reason, result["status_reasons"], case["id"])
    if "turns_used" in expect:
        test.assertEqual(result["turns_used"], expect["turns_used"], case["id"])
    if "timeline_offset" in expect:
        test.assertEqual(result["timeline"]["source_offset_seconds"], expect["timeline_offset"])
        test.assertFalse(result["timeline"]["offset_applied_in_align"])
        test.assertFalse(result["timeline"]["clip_times_used"])
    words = result["words"]
    test.assertEqual(len(words), len(expect["words"]), case["id"])
    for got, expected in zip(words, expect["words"]):
        test.assertEqual(got["text"], expected["text"], case["id"])
        test.assertEqual(got["assignment_method"], expected["method"], case["id"])
        test.assertEqual(got["model_speaker"], expected["model_speaker"], case["id"])
        test.assertEqual(got["possible_model_speakers"], expected["possible"], case["id"])
        if "detail" in expected:
            test.assertEqual(got["detail"], expected["detail"], case["id"])
        if "below_collar" in expected:
            test.assertEqual(got["below_collar_speakers"], expected["below_collar"], case["id"])
        if "time_basis" in expected:
            test.assertEqual(got["time_basis"], expected["time_basis"], case["id"])
        if got["speaker_id"] is not None:
            test.assertTrue(
                got["speaker_id"].startswith(f"{result['recording_id']}/{result['diarization_revision']}/"),
                got["speaker_id"],
            )
    test.assertEqual(
        [(item["display_label"], item["text"]) for item in result["utterances"]],
        [(item["display"], item["text"]) for item in expect["utterances"]],
        case["id"],
    )
    if expect.get("same_scoped_speaker"):
        identities = {word["speaker_id"] for word in words}
        test.assertEqual(len(identities), 1, case["id"])
        test.assertIsNotNone(next(iter(identities)), case["id"])
    rendered = render_text(result)
    for utterance in expect["utterances"]:
        test.assertIn(utterance["text"], rendered, case["id"])
        test.assertIn(utterance["display"], rendered, case["id"])
    test.assertIn("UNMEASURED", rendered, case["id"])
    return result
