import json
import stat
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from align import main
from attribution import (
    BOUNDARY_COLLAR_SECONDS,
    InputChanged,
    exceeds_collar,
    policy_record,
    read_stable_bytes,
    stamp_diarization,
)
from attribution_cases import DEV_CASES, SHA, SHA_B
from attribution_runner import assert_case, run_case
from core import read_json
from diarize import publish_diarization
from score_attribution import ScoringError, score_speaker_time, score_words
from transcribe import process


PLAN = json.loads((ROOT / "tests/attribution_data/evaluation_plan.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "tests/attribution_data/baseline_behavior.json").read_text(encoding="utf-8"))


class PolicyTests(unittest.TestCase):
    def test_plan_constants_match_the_implementation(self):
        code = policy_record()
        for key, value in PLAN["policy"].items():
            self.assertEqual(code[key], value)

    def test_collar_is_strict(self):
        self.assertFalse(exceeds_collar(BOUNDARY_COLLAR_SECONDS))
        self.assertFalse(exceeds_collar(0.519 - 0.5))
        self.assertTrue(exceeds_collar(0.525 - 0.5))

    def test_development_cases(self):
        for case in DEV_CASES:
            with self.subTest(case=case["id"]):
                assert_case(self, case)

    def test_baseline_forced_the_failures_this_policy_abstains_on(self):
        forced = {
            "equal_overlap": "SPEAKER_00",
            "point_double_contain": "SPEAKER_00",
            "gap_both_near": "SPEAKER_00",
            "missing_offsets": "SPEAKER_00",
            "punctuation_crosses": "SPEAKER_00",
        }
        for name, speaker in forced.items():
            self.assertEqual(BASELINE["cases"][name]["utterances"][0]["speaker_id"], speaker)
            self.assertEqual(BASELINE["cases"][name]["status"], "review_preview")
        candidate = {case["id"]: case for case in DEV_CASES}
        self.assertEqual(
            run_case(candidate["equal_overlap"])["words"][0]["assignment_method"],
            "ambiguous_overlap",
        )
        self.assertNotEqual(
            run_case(candidate["punctuation_crosses"])["utterances"][0]["text"],
            "Hello.",
        )
        missing = run_case(candidate["missing_offsets"])
        self.assertEqual(missing["words"][0]["assignment_method"], "missing_time")
        self.assertIsNone(missing["words"][0]["start"])

    def test_same_run_is_stable_and_another_run_is_not_the_same_speaker(self):
        case = next(item for item in DEV_CASES if item["id"] == "unique_overlap")
        first = run_case(case)
        second = run_case(case)
        self.assertEqual(first["words"][0]["speaker_id"], second["words"][0]["speaker_id"])
        other = dict(case)
        other["run_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        third = run_case(other)
        self.assertEqual(first["words"][0]["model_speaker"], third["words"][0]["model_speaker"])
        self.assertNotEqual(first["words"][0]["speaker_id"], third["words"][0]["speaker_id"])
        self.assertNotEqual(first["diarization_revision"], third["diarization_revision"])

    def test_diarization_stamp_revision_matches_alignment(self):
        case = next(item for item in DEV_CASES if item["id"] == "unique_overlap")
        from attribution_runner import turns_from_case

        payload = turns_from_case(case)
        stamped = stamp_diarization(payload)
        aligned = run_case(case)
        self.assertEqual(
            aligned["diarization_revision"],
            stamped["provenance"]["overlap_revision"],
        )
        self.assertIsNone(stamped["provenance"]["cross_revision_mapping"])
        self.assertEqual(stamped["overlap_aware_turns"], payload["overlap_aware_turns"])


class ExecutionTests(unittest.TestCase):
    def test_changed_input_is_rejected(self):
        class Flip:
            def __init__(self):
                self.calls = 0

            def is_file(self):
                return True

            def read_bytes(self):
                self.calls += 1
                return b"one" if self.calls == 1 else b"two"

        with self.assertRaises(InputChanged):
            read_stable_bytes(Flip())

    def test_missing_input_does_not_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "transcript-with-speakers.json"
            output.write_text("KEEP", encoding="utf-8")
            code = main(
                [
                    "--whisper-json",
                    str(root / "missing-whisper.json"),
                    "--speaker-turns",
                    str(root / "missing-turns.json"),
                    "--output",
                    str(output),
                    "--through",
                    "1",
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "KEEP")

    def test_malformed_input_does_not_replace_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            whisper = root / "whisper.json"
            turns = root / "turns.json"
            whisper.write_text("{", encoding="utf-8")
            turns.write_text("[]", encoding="utf-8")
            output = root / "transcript-with-speakers.json"
            output.write_text("KEEP", encoding="utf-8")
            (output.with_suffix(".txt")).write_text("KEEP", encoding="utf-8")
            code = main(
                [
                    "--whisper-json",
                    str(whisper),
                    "--speaker-turns",
                    str(turns),
                    "--output",
                    str(output),
                    "--through",
                    "1",
                ]
            )
            self.assertEqual(code, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "KEEP")
            self.assertEqual(output.with_suffix(".txt").read_text(encoding="utf-8"), "KEEP")

    def test_cli_commits_a_validated_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            whisper = root / "whisper.json"
            turns = root / "turns.json"
            whisper.write_text(
                json.dumps(
                    {
                        "transcription": [
                            {
                                "text": " yes",
                                "tokens": [{"text": " yes", "offsets": {"from": 100, "to": 400}}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            turns.write_text(
                json.dumps(
                    {
                        "model": "pyannote/speaker-diarization-community-1",
                        "run_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                        "audio": {"sha256": SHA, "source_offset_seconds": 0},
                        "overlap_aware_turns": [
                            {"speaker_id": "SPEAKER_00", "source_start": 0, "source_end": 1}
                        ],
                        "exclusive_turns": [
                            {"speaker_id": "SPEAKER_00", "source_start": 0, "source_end": 1}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "transcript-with-speakers.json"
            code = main(
                [
                    "--whisper-json",
                    str(whisper),
                    "--speaker-turns",
                    str(turns),
                    "--output",
                    str(output),
                    "--through",
                    "4",
                ]
            )
            self.assertEqual(code, 0)
            payload = read_json(output)
            self.assertEqual(payload["status"], "review_required")
            self.assertEqual(payload["accuracy"], "UNMEASURED")
            self.assertIn("SPEAKER_00", output.with_suffix(".txt").read_text(encoding="utf-8"))
            attempts = list((root / "attempts").glob("align_*"))
            self.assertEqual(len(attempts), 1)
            self.assertEqual(read_json(attempts[0] / "status.json")["state"], "committed")

    def test_publish_diarization_keeps_raw_labels_and_does_not_claim_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            existing = output / "speaker-turns.json"
            existing.write_text("KEEP", encoding="utf-8")
            with self.assertRaises(SystemExit):
                publish_diarization(output, {"exclusive_turns": []})
            self.assertEqual(existing.read_text(encoding="utf-8"), "KEEP")
            payload = {
                "model": "pyannote/speaker-diarization-community-1",
                "audio": {"path": "/tmp/example.wav", "sha256": SHA, "source_offset_seconds": 0},
                "exclusive_turns": [
                    {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
                ],
                "overlap_aware_turns": [
                    {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.2},
                    {"speaker_id": "SPEAKER_01", "source_start": 1.0, "source_end": 1.2},
                ],
            }
            summary = publish_diarization(output, payload)
            stored = read_json(output / "speaker-turns.json")
            self.assertEqual(stored["exclusive_turns"][0]["speaker_id"], "SPEAKER_00")
            self.assertEqual(stored["overlap_aware_turns"][1]["speaker_id"], "SPEAKER_01")
            self.assertFalse(stored["provenance"]["labels_are_person_identities"])
            self.assertIsNone(stored["provenance"]["cross_revision_mapping"])
            self.assertEqual(summary["status"], "outputs_written")
            self.assertFalse(summary["attribution_assessed"])
            self.assertFalse(summary["process_exit_means_attribution_correct"])
            self.assertIn("SPEAKER_01", (output / "speaker-turns-overlap.rttm").read_text(encoding="utf-8"))

    def test_nonfinite_diarization_does_not_replace_a_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            existing = output / "speaker-turns.json"
            existing.write_text("KEEP", encoding="utf-8")
            with self.assertRaises(SystemExit):
                publish_diarization(
                    output,
                    {
                        "audio": {"path": "/tmp/example.wav"},
                        "exclusive_turns": [
                            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": float("inf")}
                        ],
                        "overlap_aware_turns": [],
                    },
                )
            self.assertEqual(existing.read_text(encoding="utf-8"), "KEEP")


class ScoreTests(unittest.TestCase):
    def test_missing_reference_is_unmeasured(self):
        result = score_words(None, [])
        self.assertEqual(result["status"], "UNMEASURED")
        self.assertNotIn("accuracy_on_answered", result)
        timed = score_speaker_time(None, [])
        self.assertEqual(timed["status"], "UNMEASURED")
        self.assertNotIn("speaker_time_error_ratio", timed)

    def test_word_score_matches_hand_counts(self):
        reference = [
            {"start": 0.0, "end": 1.0, "speakers": ["SPEAKER_00"]},
            {"start": 1.0, "end": 2.0, "speakers": ["SPEAKER_00", "SPEAKER_01"]},
        ]
        hypothesis = [
            {
                "start": 0.0,
                "end": 1.0,
                "assignment_method": "turn_overlap",
                "model_speaker": "SPEAKER_00",
                "possible_model_speakers": ["SPEAKER_00"],
            },
            {
                "start": 1.0,
                "end": 2.0,
                "assignment_method": "ambiguous_overlap",
                "model_speaker": None,
                "possible_model_speakers": ["SPEAKER_00", "SPEAKER_01"],
            },
        ]
        mapping = {"SPEAKER_00": "SPEAKER_00", "SPEAKER_01": "SPEAKER_01"}
        scored = score_words(reference, hypothesis, mapping)
        self.assertEqual(scored["answered"], 1)
        self.assertEqual(scored["correct_answered"], 1)
        self.assertEqual(scored["abstained"], 1)
        self.assertEqual(scored["unique_assignment_rate"], 0.5)
        self.assertEqual(scored["accuracy_on_answered"], 1.0)
        self.assertEqual(scored["overlap_preserved"], 1)
        self.assertEqual(scored["overlap_collapsed"], 0)

        collapsed = dict(hypothesis[1])
        collapsed["assignment_method"] = "turn_overlap"
        collapsed["model_speaker"] = "SPEAKER_00"
        collapsed["possible_model_speakers"] = ["SPEAKER_00"]
        forced = score_words(reference, [hypothesis[0], collapsed], mapping)
        self.assertEqual(forced["overlap_collapsed"], 1)
        self.assertEqual(forced["correct_answered"], 1)
        self.assertEqual(forced["answered"], 2)
        self.assertEqual(forced["accuracy_on_answered"], 0.5)

    def test_word_score_refuses_unsupported_cases(self):
        reference = [{"start": 0.0, "end": 1.0, "speakers": ["Alice"]}]
        hypothesis = [
            {
                "start": 0.0,
                "end": 1.0,
                "assignment_method": "turn_overlap",
                "model_speaker": "SPEAKER_00",
                "possible_model_speakers": ["SPEAKER_00"],
            }
        ]
        with self.assertRaises(ScoringError):
            score_words(reference, hypothesis, None)
        with self.assertRaises(ScoringError):
            score_words(reference, hypothesis, {})
        with self.assertRaises(ScoringError):
            score_words(reference, [{**hypothesis[0], "end": 1.5}], {"SPEAKER_00": "Alice"})
        empty = score_words(
            [{"start": 0.0, "end": 1.0, "speakers": ["UNKNOWN"]}],
            hypothesis,
            {"SPEAKER_00": "UNKNOWN"},
        )
        self.assertEqual(empty["status"], "UNMEASURED")
        self.assertNotIn("accuracy_on_answered", empty)

    def test_speaker_time_ratio_matches_hand_counts(self):
        reference = [
            {"speaker": "A", "start": 0.0, "end": 1.0},
            {"speaker": "B", "start": 1.0, "end": 2.0},
        ]
        mapping = {"A": "A", "B": "B", "C": None}
        perfect = score_speaker_time(reference, reference, {"A": "A", "B": "B"})
        self.assertEqual(perfect["speaker_time_error_ratio"], 0.0)
        confused = score_speaker_time(
            reference,
            [{"speaker": "A", "start": 0.0, "end": 2.0}],
            {"A": "A", "B": "B"},
        )
        self.assertEqual(confused["speaker_time_error_ratio"], 0.5)
        missed = score_speaker_time(
            reference,
            [{"speaker": "A", "start": 0.0, "end": 1.0}],
            {"A": "A", "B": "B"},
        )
        self.assertEqual(missed["speaker_time_error_ratio"], 0.5)
        alarm = score_speaker_time(
            reference,
            [
                {"speaker": "A", "start": 0.0, "end": 1.0},
                {"speaker": "B", "start": 1.0, "end": 2.0},
                {"speaker": "C", "start": 2.0, "end": 3.0},
            ],
            mapping,
        )
        self.assertEqual(alarm["false_alarm_seconds"], 1.0)
        self.assertEqual(alarm["speaker_time_error_ratio"], 0.5)
        collar = score_speaker_time(
            reference,
            [
                {"speaker": "A", "start": 0.0, "end": 1.1},
                {"speaker": "B", "start": 1.1, "end": 2.0},
            ],
            {"A": "A", "B": "B"},
            collar=0.25,
        )
        self.assertEqual(collar["speaker_time_error_ratio"], 0.0)
        bare = score_speaker_time(
            reference,
            [
                {"speaker": "A", "start": 0.0, "end": 1.1},
                {"speaker": "B", "start": 1.1, "end": 2.0},
            ],
            {"A": "A", "B": "B"},
            collar=0.0,
        )
        self.assertEqual(bare["speaker_time_error_ratio"], 0.05)

    def test_speaker_time_refuses_overlap_and_missing_mapping(self):
        reference = [
            {"speaker": "A", "start": 0.0, "end": 2.0},
            {"speaker": "B", "start": 1.0, "end": 2.0},
        ]
        hypothesis = [{"speaker": "A", "start": 0.0, "end": 2.0}]
        with self.assertRaises(ScoringError):
            score_speaker_time(reference, hypothesis, {"A": "A", "B": "B"})
        with self.assertRaises(ScoringError):
            score_speaker_time(
                [{"speaker": "A", "start": 0.0, "end": 1.0}],
                [{"speaker": "A", "start": 0.0, "end": 1.0}],
                None,
            )


class PipelineTests(unittest.TestCase):
    def test_speaker_pipeline_preserves_wording_and_records_uncertainty(self):
        ffmpeg = "/usr/bin/ffmpeg"
        ffprobe = "/usr/bin/ffprobe"
        if not Path(ffmpeg).is_file() or not Path(ffprobe).is_file():
            self.skipTest("ffmpeg is not available")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "fixture.wav"
            with wave.open(str(audio), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\0\0" * 16000)
            model = root / "ggml-medium.bin"
            model.write_bytes(b"multilingual-test-model")
            payload = {
                "model": {"type": "medium", "multilingual": True},
                "result": {"language": "fr"},
                "transcription": [
                    {
                        "timestamps": {"from": "00:00:00,000", "to": "00:00:00,900"},
                        "offsets": {"from": 0, "to": 900},
                        "text": " Bonjour toi",
                        "tokens": [
                            {"text": " Bonjour", "offsets": {"from": 0, "to": 400}, "p": 0.91},
                            {"text": " toi", "offsets": {"from": 500, "to": 800}, "p": 0.93},
                        ],
                    }
                ],
            }
            whisper = root / "fake-whisper-cli"
            whisper.write_text(
                """#!/usr/bin/env python3
import json, pathlib, sys
if '--version' in sys.argv:
    print('whisper.cpp version: test')
    raise SystemExit(0)
base = pathlib.Path(sys.argv[sys.argv.index('-of') + 1])
payload = %s
base.with_suffix('.json').write_text(json.dumps(payload), encoding='utf-8')
base.with_suffix('.txt').write_text('Bonjour toi\\n', encoding='utf-8')
base.with_suffix('.srt').write_text('1\\n00:00:00,000 --> 00:00:00,900\\nBonjour toi\\n', encoding='utf-8')
"""
                % repr(payload),
                encoding="utf-8",
            )
            whisper.chmod(whisper.stat().st_mode | stat.S_IXUSR)
            diarize = root / "fake-diarize-python"
            diarize.write_text(
                f"""#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path
audio = Path(sys.argv[sys.argv.index('--audio') + 1])
output = Path(sys.argv[sys.argv.index('--output') + 1])
output.mkdir(parents=True, exist_ok=True)
digest = hashlib.sha256(audio.read_bytes()).hexdigest()
payload = {{
    "model": "pyannote/speaker-diarization-community-1",
    "run_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    "audio": {{"path": str(audio), "sha256": digest, "source_offset_seconds": 0}},
    "exclusive_turns": [
        {{"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.45}},
        {{"speaker_id": "SPEAKER_01", "source_start": 0.45, "source_end": 0.9}},
    ],
    "overlap_aware_turns": [
        {{"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}},
        {{"speaker_id": "SPEAKER_01", "source_start": 0.45, "source_end": 0.9}},
    ],
}}
(output / "speaker-turns.json").write_text(json.dumps(payload), encoding="utf-8")
(output / "speaker-turns.rttm").write_text("SPEAKER fixture 1 0.000 0.450 <NA> <NA> SPEAKER_00 <NA> <NA>\\n", encoding="utf-8")
(output / "speaker-turns-overlap.rttm").write_text("SPEAKER fixture 1 0.000 1.000 <NA> <NA> SPEAKER_00 <NA> <NA>\\n", encoding="utf-8")
(output / "run-summary.json").write_text(json.dumps({{"status": "outputs_written", "turn_validation": "ok", "attribution_assessed": False}}), encoding="utf-8")
""",
                encoding="utf-8",
            )
            diarize.chmod(diarize.stat().st_mode | stat.S_IXUSR)
            config = {
                "source": str(audio),
                "output_root": str(root / "output"),
                "model": str(model),
                "language": "auto",
                "speakers": True,
                "min_speakers": None,
                "max_speakers": None,
                "threads": 4,
                "whisper": str(whisper),
                "ffmpeg": ffmpeg,
                "ffprobe": ffprobe,
                "diarization_python": str(diarize),
            }
            job = process(dict(config))
            technical = job / "Technical Files"
            manifest = read_json(technical / "job.json")
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["recipe"]["assignment_policy"]["id"], "scoped-overlap-v1")
            raw = (technical / "raw-transcript.json").read_bytes()
            self.assertEqual((technical / "raw-transcript.txt").read_text(encoding="utf-8"), "Bonjour toi\n")
            transcript = (job / "Transcript.txt").read_text(encoding="utf-8")
            self.assertIn("Bonjour", transcript)
            self.assertIn("toi", transcript)
            self.assertIn("AMBIGUOUS[SPEAKER_00|SPEAKER_01]", transcript)
            self.assertIn("UNMEASURED", transcript)
            alignment = read_json(technical / "transcript-with-speakers.json")
            self.assertEqual(alignment["status"], "attribution_uncertain")
            self.assertEqual(alignment["accuracy"], "UNMEASURED")
            self.assertEqual(alignment["words"][0]["text"], " Bonjour")
            self.assertEqual(alignment["words"][1]["text"], " toi")
            warning = next(item for item in manifest["warnings"] if item["code"] == "speaker_attribution")
            self.assertTrue(warning["review_required"])
            self.assertEqual(warning["accuracy"], "UNMEASURED")
            resumed = process(dict(config))
            self.assertEqual(resumed, job)
            self.assertEqual((technical / "raw-transcript.json").read_bytes(), raw)


class IdentityScopeTests(unittest.TestCase):
    def test_recording_hashes_do_not_share_a_speaker_id(self):
        self.assertNotEqual(SHA, SHA_B)
        from attribution_cases import HELDOUT_CASES

        left = run_case(next(case for case in HELDOUT_CASES if case["id"] == "recording_a"))
        right = run_case(next(case for case in HELDOUT_CASES if case["id"] == "recording_b"))
        self.assertEqual(left["words"][0]["model_speaker"], right["words"][0]["model_speaker"])
        self.assertNotEqual(left["recording_id"], right["recording_id"])
        self.assertNotEqual(left["words"][0]["speaker_id"], right["words"][0]["speaker_id"])
        self.assertIsNone(left["cross_revision_mapping"])


if __name__ == "__main__":
    unittest.main()
