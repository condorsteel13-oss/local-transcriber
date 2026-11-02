# Speaker attribution report

Recommendation: **reviewed drafts only**.

Acoustic accuracy on real recordings is **UNMEASURED**. This change is not a
bounded pilot and it is not ready for unreviewed production use. Downstream
meeting work should treat `Transcript.txt` speaker labels as a draft that still
needs a person.

## Current stack

Local Transcriber transcribes with multilingual whisper.cpp, optionally
diarizes the full normalized WAV with pyannote Community-1
(`pyannote/speaker-diarization-community-1`), and aligns words in
`backend/align.py`. Those are three different jobs. A correct transcript does
not make the speaker labels correct, and an anonymous `SPEAKER_00` is not a
person's name.

The production path does not chunk. `backend/transcribe.py` passes the whole
normalized file to `diarize.py` and does not set `--source-offset` (the default
is 0). `diarize.py` already stores both `exclusive_turns` and
`overlap_aware_turns`, with `source_start` / `source_end` equal to clip time
plus the offset. Before this change, alignment ignored `overlap_aware_turns`.

Whisper token offsets are milliseconds. Diarization times are seconds on the
normalized-recording timeline. Alignment now converts token offsets with
`seconds = milliseconds / 1000` and reads only `source_start` / `source_end`.
It does not add `source_offset` again and it does not treat clip times as
source times.

This VM has Python 3.12, ffmpeg, and ffprobe. It does not have whisper.cpp,
pyannote, Community-1 weights, a Hugging Face token, or any recording. No human
listener labeled speech for this change. Nothing here was confirmed by ear.

## Baseline (before any edit)

Code at git `343b548f039e945eab66dd1c15ea9a3d57e5fa5c`:

| File | SHA-256 |
| --- | --- |
| `backend/align.py` | `0426f6e5e3b45eb56a9bd458e0584933b844110651f29a16b8e23fd704233cee` |
| `backend/diarize.py` | `29a213d05dfc8daea5534dec0684b954cf170829f5d3ff388fa28c7780044514` |
| `backend/transcribe.py` | `4dda6a6b8a064fb319f7142dbf4a0dfb276ebc441c75001025ed8c585c54fa9a` |
| `backend/core.py` | `6b6e3f8528bb9ea9b7e160a4fc190e6b4d34ac66dad889f3bb4314801a03d262` |

The old aligner was run on synthetic JSON under `/tmp/diarization-baseline`
before the policy changed. Those raw files embed absolute paths, so the
normalized behavior is what is kept: `tests/attribution_data/baseline_behavior.json`.
Original recordings were not present and were not overwritten.

Confirmed by executing that aligner, not by listening:

| Case | Baseline result |
| --- | --- |
| Equal overlap, overlap-aware turns present | Ignored overlap-aware turns. Exclusive tie awarded to the first label, `SPEAKER_00`. Status `review_preview`. |
| Point on a shared boundary | First containing speaker, `SPEAKER_00`. |
| Word in a gap within 1.5 s of two speakers | Nearer speaker, `SPEAKER_00`, method `nearest`. |
| Token with no offsets | Placed at 0 ms and merged into the speaker active there (`ghost real`). |
| `.` inside the next speaker | Overwritten with the previous speaker (`Hello.` as `SPEAKER_00`). |
| Token starting after `--through` | Dropped. Word count omitted it. |
| Reversed token | Treated as a point at its start and assigned. |
| No turns, or a far gap | `UNASSIGNED`, but status still `review_preview`. |

`assignment_value` was an overlap duration or a distance. The status string did
not say that a finished process is not a correct attribution. Speaker ids were
the raw model labels, with no recording or diarization-run scope.

## What was implemented

Policy id `scoped-overlap-v1` in `backend/attribution.py`. Constants were
written into `tests/attribution_data/evaluation_plan.json` before the candidate
was accepted. They were not retuned after the held-out run.

- Use `overlap_aware_turns` whenever that list is non-empty. Do not fall back
  to exclusive turns after rejecting bad overlap rows. Exclusive turns are used
  only when overlap-aware turns are missing or empty, and that result is marked
  uncertain because overlap was already removed.
- Two speakers with union overlap **strictly greater than 0.020 s** stay
  ambiguous. There is no "larger overlap wins" rule.
- A single speaker above 0.020 s gets the word. Contacts at or below 0.020 s
  are listed in `below_collar_speakers` and do not take the word.
- A gap within 0.020 s of exactly one speaker is `boundary`. A gap within the
  existing 1.5 s maximum of exactly one speaker is `nearest` and uncertain.
  Two speakers inside that window stay ambiguous, including a tie.
- A span longer than 1.0 s with only a sub-collar contact is unassigned
  (`long_span_weak_contact`).
- Missing offsets stay missing. Reversed, negative, and nonfinite times are
  withheld. Tokens at or after `--through` are counted as excluded, not dropped.
- Punctuation keeps an acoustic assignment. It inherits the previous stable
  speaker only when acoustics are unassigned and the gap is inside the
  utterance gap.
- `speaker_id` is `{recording_id}/{diarization_revision}/{model_label}`.
  Display text still uses `SPEAKER_00`. Another file or another `run_id` does
  not share that id. No cross-revision mapping is created.
- Publishable statuses are `review_required`, `attribution_uncertain`, and
  `partial_result`. `draft_ready` is not emitted. `accuracy` is `UNMEASURED`.
  Overlap seconds are durations. The JSON does not carry probability,
  confidence, score, or `assignment_value` fields.
- Alignment writes an attempt directory and replaces the committed files only
  after validation. Missing or malformed input leaves an existing output in
  place. Inputs are read twice and rejected if the bytes change.
- The pipeline refuses to align when the turns file does not carry the
  normalized audio hash, re-checks that hash and the source hash, and records a
  job warning that review is required and accuracy is unmeasured.
- Diarization writes `speaker-turns-overlap.rttm`, stamps `run_id` and revision
  ids, and labels its summary `outputs_written` with
  `attribution_assessed: false`. Raw turn rows keep the model labels.

`backend/score_attribution.py` scores only when a reference and an explicit
label mapping are supplied. It returns `UNMEASURED` with no accuracy field when
the reference is missing. It raises on word-count or timestamp mismatch, on a
missing mapping, and on overlapping turns for the time ratio. Overlap-aware
diarization error is unsupported. `pyannote.metrics` was not installed.

## Before / after

Synthetic tokens. Times are seconds on the source timeline. Wording is the
token text with only the surrounding whitespace stripped in the utterance line.

Equal overlap (`tests/attribution_cases.py`, case `equal_overlap`):

- Turns: `SPEAKER_00` 0.0–2.0 and `SPEAKER_01` 1.0–3.0 (overlap-aware).
- Token: ` hello` at 1.000–2.000.
- Baseline: `SPEAKER_00: hello`, one forced speaker.
- Candidate: `AMBIGUOUS[SPEAKER_00|SPEAKER_01]: hello`. Scoped `speaker_id` is
  null. Status `attribution_uncertain`. On a synthetic reference that lists
  both speakers, the baseline score is overlap collapsed, answered 1/1,
  accuracy_on_answered 0. The candidate abstains: unique assignment rate 0,
  accuracy_on_answered null, overlap preserved 1. The coverage drop is the
  point of the change, not a hidden accuracy gain.

Missing time (`missing_offsets`):

- Baseline merged `ghost real` onto the speaker at 0 s.
- Candidate withholds `ghost` as `MISSING_TIME` and assigns only ` real`.

Punctuation (`punctuation_crosses`):

- ` Hello` 0.000–0.400 in `SPEAKER_00`; `.` 0.800–0.900 in `SPEAKER_01`.
- Baseline: `SPEAKER_00: Hello.`
- Candidate: two lines, `SPEAKER_00: Hello` and `SPEAKER_01: .`

Held-out overlap (`overlapping_interruption`), not used to choose the collar:

- `SPEAKER_00` 0–4 and `SPEAKER_01` 1.5–2.5; token ` both` at 1.600–2.200.
- Candidate: `AMBIGUOUS[SPEAKER_00|SPEAKER_01]`, unique assignment rate 0.

Held-out separated interjection, where the turns themselves do not overlap:

- ` yes` at 2.050–2.300 is `SPEAKER_01`; the neighboring words stay `SPEAKER_00`.
- Status `review_required`. That still means a person must check it.

Same display label, two recordings (`recording_a`, `recording_b`): both render
`SPEAKER_00`, and their scoped ids differ. There is no mapping between them.

The excerpt case uses source times 10–12 s with `source_offset_seconds` 10.
The word at 10.2–10.8 s follows the source turn. The word at 0.2–0.8 s does
not, which is what would happen if clip time were mistaken for source time.
The case duration is 20 s. The first held-out run used the default 10 s, so the
10.2 s word was excluded by `--through`; the duration was corrected and the
expected assignment was not edited. The second held-out run passed.

## Evaluation

Plan: `tests/attribution_data/evaluation_plan.json`.

| Split | What it is | Result |
| --- | --- | --- |
| Development, 18 synthetic cases | Regressions for the baseline failures above | Passed |
| Held-out, 14 synthetic cases | Structural checks written with the policy | Passed after the excerpt duration correction described above |
| Hand word-score fixtures | Defined in `backend/score_attribution.py` | Passed, including refusal when the mapping or the reference is missing |
| Hand speaker-time fixtures, collar 0 and 0.25, no overlap | Ratio `(miss + false alarm + confusion) / scored reference speech` | 0, 0.5, 0.5, 0.5, 0.0 with collar, 0.05 without. Overlap input raises |
| Pipeline on a 1-second silent WAV plus fake whisper and fake diarization | Wording, ambiguity, resume, raw file preserved | Passed |
| Real Community-1 audio | Not available | **UNMEASURED** |
| Human reference | Not collected | **UNMEASURED** |
| `pyannote.metrics` | Not installed | Not used |

`unique_assignment_rate` is the share of lexical tokens given exactly one
speaker. It is not accuracy. Ambiguous overlap lowers it on purpose.

No corpus accuracy, throughput, cache-hit rate, or reviewer-time number is
claimed. The unit suite finished in under a second and does not include model
load, decoding, or human review. One corrected synthetic pair does not
generalize.

Full-recording diarization was not compared with chunked diarization on audio.
The current product already diarizes the full normalized file. Chunking was
not added.

## Claim boundaries

Implemented and covered by tests: the assignment policy, revision-scoped ids,
statuses, attempt commits, hash checks, overlap RTTM publication, and the
scorer's refusal behavior.

Measured: structural counts on the synthetic cases, and the hand-computed
scores above. The equal-overlap synthetic reference shows preserved overlap
with lower coverage, not a higher accuracy.

Not measured: diarization error, word error rate, named-person identification,
and any real recording.

Still proposed, and not done:

- A listening set collected before the listener sees model output.
- Scoring that set with the existing word scorer and an explicit mapping.
- Checking that installed Community-1 builds actually contain
  `overlap_aware_turns`.
- Any comparison of chunked diarization against the full file.
- Cross-revision identity, real names, and calibrated probabilities.

## Next experiment

Do not retune the 0.020 s collar on the result.

1. Choose three short two-speaker recordings that stay on disk.
2. Have a person mark words or turns, including overlap and "unsure", before
   seeing Community-1 or this aligner.
3. Run the existing full-file diarization and `align.py` into a new attempt
   directory. Do not replace the current transcript folder.
4. Score with `score_words` and a mapping written down before scoring. Report
   unique assignment rate, accuracy on answered words, overlap preserved, and
   overlap collapsed.
5. If the model file has no `overlap_aware_turns`, stop and record that. Do
   not invent overlap from exclusive turns.

Until that experiment exists, ship these labels as reviewed drafts only.
