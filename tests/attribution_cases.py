"""Frozen structural cases for scoped-overlap-v1.

Development cases cover failures observed in the baseline aligner. Held-out
cases were specified with the policy and are not a tuning set. None of these
are human listening references.
"""

SHA = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SHA_B = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
RUN = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
RUN_B = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _case(case_id, **fields):
    fields.setdefault("sha256", SHA)
    fields.setdefault("run_id", RUN)
    fields.setdefault("through", 10.0)
    fields["id"] = case_id
    return fields


DEV_CASES = [
    _case(
        "equal_overlap",
        exclusive_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.5},
            {"speaker_id": "SPEAKER_01", "source_start": 1.5, "source_end": 3.0},
        ],
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.0, "source_end": 3.0},
        ],
        tokens=[{"text": " hello", "from": 1000, "to": 2000}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_at_once"],
            "turns_used": "overlap_aware_turns",
            "words": [
                {
                    "text": " hello",
                    "method": "ambiguous_overlap",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "hello"}],
        },
    ),
    _case(
        "point_double_contain",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.0, "source_end": 2.0},
        ],
        tokens=[{"text": " ah", "from": 1000, "to": 1000}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_at_once"],
            "words": [
                {
                    "text": " ah",
                    "method": "ambiguous_point",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "ah"}],
        },
    ),
    _case(
        "gap_both_near",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.4, "source_end": 2.4},
        ],
        tokens=[{"text": " wait", "from": 1050, "to": 1250}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_within_gap"],
            "words": [
                {
                    "text": " wait",
                    "method": "ambiguous_gap",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "wait"}],
        },
    ),
    _case(
        "gap_tie_within_slack",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.02, "source_end": 2.0},
        ],
        tokens=[{"text": " um", "from": 1000, "to": 1020}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_within_gap"],
            "words": [
                {
                    "text": " um",
                    "method": "ambiguous_gap",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "um"}],
        },
    ),
    _case(
        "missing_offsets",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0}
        ],
        tokens=[{"text": " ghost"}, {"text": " real", "from": 0, "to": 500}],
        expect={
            "status": "partial_result",
            "reasons_include": ["missing_word_times"],
            "words": [
                {"text": " ghost", "method": "missing_time", "model_speaker": None, "possible": []},
                {
                    "text": " real",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                },
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "real"}],
        },
    ),
    _case(
        "punctuation_crosses",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.5},
            {"speaker_id": "SPEAKER_01", "source_start": 0.5, "source_end": 1.5},
        ],
        tokens=[
            {"text": " Hello", "from": 0, "to": 400},
            {"text": ".", "from": 800, "to": 900},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " Hello",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                },
                {
                    "text": ".",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_01",
                    "possible": ["SPEAKER_01"],
                },
            ],
            "utterances": [
                {"display": "SPEAKER_00", "text": "Hello"},
                {"display": "SPEAKER_01", "text": "."},
            ],
        },
    ),
    _case(
        "punctuation_inherits",
        maximum_gap=0.0,
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.4}
        ],
        tokens=[
            {"text": " Hello", "from": 0, "to": 300},
            {"text": ".", "from": 450, "to": 500},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " Hello",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                },
                {
                    "text": ".",
                    "method": "punctuation",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                    "detail": "punctuation_inherited",
                },
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "Hello."}],
        },
    ),
    _case(
        "after_through",
        through=4.0,
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 6.0}
        ],
        tokens=[
            {"text": " late", "from": 5000, "to": 5500},
            {"text": " early", "from": 0, "to": 400},
        ],
        expect={
            "status": "partial_result",
            "reasons_include": ["words_after_through"],
            "words": [
                {
                    "text": " late",
                    "method": "excluded_after_through",
                    "model_speaker": None,
                    "possible": [],
                },
                {
                    "text": " early",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                },
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "early"}],
        },
    ),
    _case(
        "reversed_token",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0}
        ],
        tokens=[{"text": " bad", "from": 800, "to": 200}],
        expect={
            "status": "partial_result",
            "reasons_include": ["invalid_word_times"],
            "words": [
                {"text": " bad", "method": "invalid", "model_speaker": None, "possible": [], "detail": "reversed"}
            ],
            "utterances": [],
        },
    ),
    _case(
        "no_turns",
        overlap_aware_turns=[],
        exclusive_turns=[],
        tokens=[{"text": " alone", "from": 0, "to": 400}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["no_speaker_turns"],
            "words": [
                {"text": " alone", "method": "unassigned", "model_speaker": None, "possible": []}
            ],
            "utterances": [{"display": "UNASSIGNED", "text": "alone"}],
        },
    ),
    _case(
        "unique_overlap",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        tokens=[{"text": " yes", "from": 100, "to": 400}],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " yes",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "yes"}],
        },
    ),
    _case(
        "far_gap",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        tokens=[{"text": " echo", "from": 5000, "to": 5400}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["speech_outside_turns"],
            "words": [
                {"text": " echo", "method": "unassigned", "model_speaker": None, "possible": []}
            ],
            "utterances": [{"display": "UNASSIGNED", "text": "echo"}],
        },
    ),
    _case(
        "exclusive_only",
        omit_overlap=True,
        exclusive_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        tokens=[{"text": " yes", "from": 100, "to": 400}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["overlap_representation_unavailable"],
            "turns_used": "exclusive_turns",
            "words": [
                {
                    "text": " yes",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "yes"}],
        },
    ),
    _case(
        "wording_french",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0}
        ],
        tokens=[
            {"text": " Bonjour", "from": 0, "to": 300},
            {"text": ",", "from": 300, "to": 400},
            {"text": " ça", "from": 400, "to": 700},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {"text": " Bonjour", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": ",", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": " ça", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "Bonjour, ça"}],
        },
    ),
    _case(
        "long_span_weak_contact",
        through=12.0,
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.015}
        ],
        tokens=[{"text": " long", "from": 0, "to": 10500}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["long_span_weak_contact"],
            "words": [
                {
                    "text": " long",
                    "method": "unassigned",
                    "model_speaker": None,
                    "possible": [],
                    "detail": "long_span_weak_contact",
                    "below_collar": ["SPEAKER_00"],
                }
            ],
            "utterances": [{"display": "UNASSIGNED", "text": "long"}],
        },
    ),
    _case(
        "short_subcollar_boundary",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.015}
        ],
        tokens=[{"text": " hi", "from": 0, "to": 300}],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " hi",
                    "method": "boundary",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "hi"}],
        },
    ),
    _case(
        "clip_times_are_not_source",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "clip_start": 0.0, "clip_end": 1.0}
        ],
        tokens=[{"text": " no", "from": 100, "to": 400}],
        expect={
            "status": "partial_result",
            "reasons_include": ["rejected_turns"],
            "words": [
                {"text": " no", "method": "unassigned", "model_speaker": None, "possible": []}
            ],
            "utterances": [{"display": "UNASSIGNED", "text": "no"}],
        },
    ),
    _case(
        "segment_fallback",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 3.0}
        ],
        segments=[
            {
                "text": " Bonjour tout le monde",
                "offsets": {"from": 0, "to": 2000},
                "tokens": [],
            }
        ],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["segment_time_fallback"],
            "words": [
                {
                    "text": " Bonjour tout le monde",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                    "time_basis": "segment",
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "Bonjour tout le monde"}],
        },
    ),
]

HELDOUT_CASES = [
    _case(
        "separated_interjection",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0},
            {"speaker_id": "SPEAKER_01", "source_start": 2.0, "source_end": 2.4},
            {"speaker_id": "SPEAKER_00", "source_start": 2.4, "source_end": 5.0},
        ],
        tokens=[
            {"text": " main", "from": 200, "to": 800},
            {"text": " yes", "from": 2050, "to": 2300},
            {"text": " later", "from": 3000, "to": 3400},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {"text": " main", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": " yes", "method": "turn_overlap", "model_speaker": "SPEAKER_01", "possible": ["SPEAKER_01"]},
                {"text": " later", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
            ],
            "utterances": [
                {"display": "SPEAKER_00", "text": "main"},
                {"display": "SPEAKER_01", "text": "yes"},
                {"display": "SPEAKER_00", "text": "later"},
            ],
        },
    ),
    _case(
        "overlapping_interruption",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 4.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.5, "source_end": 2.5},
        ],
        tokens=[{"text": " both", "from": 1600, "to": 2200}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_at_once"],
            "words": [
                {
                    "text": " both",
                    "method": "ambiguous_overlap",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "both"}],
        },
    ),
    _case(
        "recording_a",
        tokens=[{"text": " same", "from": 100, "to": 400}],
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {"text": " same", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]}
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "same"}],
        },
    ),
    _case(
        "recording_b",
        sha256=SHA_B,
        run_id=RUN_B,
        tokens=[{"text": " same", "from": 100, "to": 400}],
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {"text": " same", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]}
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "same"}],
        },
    ),
    _case(
        "speaker_returns",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_00", "source_start": 4.0, "source_end": 5.0},
        ],
        tokens=[
            {"text": " one", "from": 100, "to": 400},
            {"text": " two", "from": 4200, "to": 4600},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "same_scoped_speaker": True,
            "words": [
                {"text": " one", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": " two", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
            ],
            "utterances": [
                {"display": "SPEAKER_00", "text": "one"},
                {"display": "SPEAKER_00", "text": "two"},
            ],
        },
    ),
    _case(
        "long_silence",
        through=20.0,
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        tokens=[{"text": " echo", "from": 10000, "to": 10400}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["speech_outside_turns"],
            "words": [
                {"text": " echo", "method": "unassigned", "model_speaker": None, "possible": []}
            ],
            "utterances": [{"display": "UNASSIGNED", "text": "echo"}],
        },
    ),
    _case(
        "glancing_second_speaker",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.5},
            {"speaker_id": "SPEAKER_01", "source_start": 0.5, "source_end": 0.515},
        ],
        tokens=[{"text": " word", "from": 0, "to": 1000}],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " word",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                    "below_collar": ["SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "word"}],
        },
    ),
    _case(
        "subcollar_not_competing",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 0.5},
            {"speaker_id": "SPEAKER_01", "source_start": 0.5, "source_end": 0.519},
        ],
        tokens=[{"text": " word", "from": 0, "to": 1000}],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {
                    "text": " word",
                    "method": "turn_overlap",
                    "model_speaker": "SPEAKER_00",
                    "possible": ["SPEAKER_00"],
                    "below_collar": ["SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "word"}],
        },
    ),
    _case(
        "point_on_shared_boundary",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_01", "source_start": 1.0, "source_end": 2.0},
        ],
        tokens=[{"text": " edge", "from": 1000, "to": 1000}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["multiple_speakers_at_once"],
            "words": [
                {
                    "text": " edge",
                    "method": "ambiguous_point",
                    "model_speaker": None,
                    "possible": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
            "utterances": [{"display": "AMBIGUOUS[SPEAKER_00|SPEAKER_01]", "text": "edge"}],
        },
    ),
    _case(
        "excerpt_offset",
        through=20.0,
        source_offset_seconds=10.0,
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 10.0, "source_end": 12.0}
        ],
        tokens=[
            {"text": " inside", "from": 10200, "to": 10800},
            {"text": " clip", "from": 200, "to": 800},
        ],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["speech_outside_turns"],
            "timeline_offset": 10.0,
            "words": [
                {"text": " inside", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": " clip", "method": "unassigned", "model_speaker": None, "possible": []},
            ],
            "utterances": [
                {"display": "SPEAKER_00", "text": "inside"},
                {"display": "UNASSIGNED", "text": "clip"},
            ],
        },
    ),
    _case(
        "rejected_turn_kept_separate",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 1.0, "source_end": 0.2},
            {"speaker_id": "SPEAKER_01", "source_start": 0.0, "source_end": 1.0},
        ],
        tokens=[{"text": " kept", "from": 100, "to": 400}],
        expect={
            "status": "partial_result",
            "reasons_include": ["rejected_turns"],
            "words": [
                {"text": " kept", "method": "turn_overlap", "model_speaker": "SPEAKER_01", "possible": ["SPEAKER_01"]}
            ],
            "utterances": [{"display": "SPEAKER_01", "text": "kept"}],
        },
    ),
    _case(
        "nearest_unique",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0},
            {"speaker_id": "SPEAKER_01", "source_start": 5.0, "source_end": 6.0},
        ],
        tokens=[{"text": " after", "from": 1100, "to": 1300}],
        expect={
            "status": "attribution_uncertain",
            "reasons_include": ["nearest_turn_within_gap"],
            "words": [
                {"text": " after", "method": "nearest", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]}
            ],
            "utterances": [{"display": "UNCERTAIN[SPEAKER_00]", "text": "after"}],
        },
    ),
    _case(
        "boundary_slack_unique",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 1.0}
        ],
        tokens=[{"text": " edge", "from": 1000, "to": 1030}],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "words": [
                {"text": " edge", "method": "boundary", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]}
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "edge"}],
        },
    ),
    _case(
        "language_mix_same_turn",
        overlap_aware_turns=[
            {"speaker_id": "SPEAKER_00", "source_start": 0.0, "source_end": 2.0}
        ],
        tokens=[
            {"text": " Bonjour", "from": 0, "to": 400},
            {"text": " Hello", "from": 500, "to": 900},
        ],
        expect={
            "status": "review_required",
            "reasons_include": ["model_labels_require_review"],
            "same_scoped_speaker": True,
            "words": [
                {"text": " Bonjour", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
                {"text": " Hello", "method": "turn_overlap", "model_speaker": "SPEAKER_00", "possible": ["SPEAKER_00"]},
            ],
            "utterances": [{"display": "SPEAKER_00", "text": "Bonjour Hello"}],
        },
    ),
]
