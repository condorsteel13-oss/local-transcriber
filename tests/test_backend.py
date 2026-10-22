import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from core import artifact, atomic_bytes, read_json, verified
from transcribe import parse_segments, process


def native_payload(language="fr"):
    return {
        "model": {"type": "medium", "multilingual": True},
        "params": {"language": "auto", "translate": False},
        "result": {"language": language},
        "transcription": [
            {
                "timestamps": {"from": "00:00:00,000", "to": "00:00:01,000"},
                "offsets": {"from": 0, "to": 1000},
                "text": " Bonjour, ça va?",
                "tokens": [{"text": " Bonjour", "offsets": {"from": 0, "to": 600}, "p": 0.92}],
            }
        ],
    }


class BackendTests(unittest.TestCase):
    def test_french_unicode_and_millisecond_times_are_preserved(self):
        segments, warnings = parse_segments(native_payload(), 1.0)
        self.assertEqual(segments[0]["text"], " Bonjour, ça va?")
        self.assertEqual((segments[0]["start"], segments[0]["end"]), (0.0, 1.0))
        self.assertEqual(warnings, [])

    def test_non_millisecond_timestamp_mapping_is_rejected(self):
        payload = native_payload()
        payload["transcription"][0]["offsets"]["to"] = 100
        with self.assertRaises(ValueError):
            parse_segments(payload, 1.0)

    def test_artifact_hash_verification_detects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "artifact.txt"
            atomic_bytes(target, b"first")
            stage = {"status": "succeeded", "artifacts": [artifact(target, root)]}
            self.assertTrue(verified(root, stage))
            atomic_bytes(target, b"other")
            self.assertFalse(verified(root, stage))

    def test_pipeline_preserves_raw_outputs_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "fixture.wav"
            with wave.open(str(audio), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\0\0" * 16000)
            model = root / "ggml-medium.bin"
            model.write_bytes(b"multilingual-test-model")
            whisper = root / "fake-whisper-cli"
            whisper.write_text(
                """#!/usr/bin/env python3
import json, pathlib, sys
if '--version' in sys.argv:
    print('whisper.cpp version: test')
    raise SystemExit(0)
base = pathlib.Path(sys.argv[sys.argv.index('-of') + 1])
payload = %s
base.with_suffix('.json').write_text(json.dumps(payload))
base.with_suffix('.txt').write_text('Bonjour, ça va?\\n')
base.with_suffix('.srt').write_text('1\\n00:00:00,000 --> 00:00:01,000\\nBonjour, ça va?\\n')
""" % repr(native_payload())
            )
            whisper.chmod(whisper.stat().st_mode | stat.S_IXUSR)
            config = {
                "source": str(audio),
                "output_root": str(root / "output"),
                "model": str(model),
                "language": "auto",
                "speakers": False,
                "min_speakers": None,
                "max_speakers": None,
                "threads": 4,
                "whisper": str(whisper),
                "ffmpeg": "/opt/homebrew/bin/ffmpeg",
                "ffprobe": "/opt/homebrew/bin/ffprobe",
                "diarization_python": None,
            }
            job = process(dict(config))
            technical = job / "Technical Files"
            self.assertEqual(read_json(technical / "job.json")["status"], "completed")
            self.assertEqual(read_json(technical / "whisper-settings.json")["language_detected"], "fr")
            self.assertEqual((technical / "raw-transcript.txt").read_text(), "Bonjour, ça va?\n")
            self.assertIn("Bonjour, ça va?", (job / "Transcript.txt").read_text())
            self.assertTrue((job / "Subtitles.srt").is_file())
            self.assertEqual(
                sorted(path.name for path in job.iterdir()),
                ["Subtitles.srt", "Technical Files", "Transcript.txt"],
            )
            raw_hash = (technical / "raw-transcript.json").read_bytes()
            resumed = process(dict(config))
            self.assertEqual(resumed, job)
            self.assertEqual((technical / "raw-transcript.json").read_bytes(), raw_hash)


if __name__ == "__main__":
    unittest.main()
