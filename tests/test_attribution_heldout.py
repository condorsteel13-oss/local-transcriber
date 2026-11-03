import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from attribution_cases import HELDOUT_CASES
from attribution_runner import assert_case, run_case


class HeldOutStructuralTests(unittest.TestCase):
    def test_heldout_cases(self):
        for case in HELDOUT_CASES:
            with self.subTest(case=case["id"]):
                assert_case(self, case)

    def test_same_display_label_is_not_cross_recording_identity(self):
        left = run_case(next(case for case in HELDOUT_CASES if case["id"] == "recording_a"))
        right = run_case(next(case for case in HELDOUT_CASES if case["id"] == "recording_b"))
        self.assertEqual(left["utterances"][0]["display_label"], right["utterances"][0]["display_label"])
        self.assertNotEqual(left["words"][0]["speaker_id"], right["words"][0]["speaker_id"])
        self.assertIsNone(left["cross_revision_mapping"])
        self.assertIsNone(right["cross_revision_mapping"])


if __name__ == "__main__":
    unittest.main()
