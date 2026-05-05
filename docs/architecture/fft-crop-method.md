# FFT Crop Method

This page documents the current FFT crop method before ownership is moved out of `Legacy_App`. Refactors must preserve these decisions, warning strings, result fields, and caller behavior unless a future task explicitly changes the processing method.

## Purpose

The FFT crop helper chooses per-condition repetition windows that put the oddball frequency exactly on an FFT bin when possible. It is used by the processing runner, legacy processing bridge, and post-processing bridge to keep epoch lengths compatible with oddball-frequency analysis.

## Inputs

- `events`: MNE-style event rows where column 0 is sample index and column 2 is event id.
- `fs`: sampling frequency in Hz.
- `onset_ids`: condition onset event ids supplied by the event map.
- `oddball_id`: oddball trigger id, currently `55`.
- `stream_end_sample`: optional sample index used as the end boundary for the final repetition block.

The oddball frequency constant is `6/5` Hz, equivalent to `1.2` Hz.

## On-Bin Length Rule

`compute_onbin_step(fs, f_oddball=6/5)` rounds `fs` to an integer and rejects non-integer sampling rates when `abs(fs - round(fs)) >= 1e-6`.

For integer sampling rates, the required FFT-compatible sample step is:

```text
den_fs = f_oddball.denominator * round(fs)
n_step = den_fs / gcd(f_oddball.numerator, den_fs)
```

`compute_onbin_N(available_samples, n_step)` returns the largest multiple of `n_step` that fits in the available interval. Non-positive inputs return `0`.

## Repetition Blocks

For each onset event whose id is in `onset_ids`:

- The block starts at that onset sample.
- The block ends at the next onset sample, or `stream_end_sample`, or `events[-1][0] + 1` for the final block.
- Repetition indexes are tracked separately per condition id, starting at `0`.
- The result key is `(condition_id, repetition_index)`.

Within each block, only rows whose event id is `55` are treated as oddball events.

## 55 Deduplication And Gap Warnings

The expected 55 interval is `round(fs / 1.2)` samples.

- A 55 event is dropped as a duplicate when it occurs less than half the expected interval after the previous retained 55.
- A missing-gap warning is counted when a retained 55 occurs more than 1.5 times the expected interval after the previous retained 55.
- Per-block warning strings are exactly `dedup_dropped:{count}` and `missing_55_gaps:{count}`.

## Crop Result Behavior

For each repetition, `CropResult` records:

- crop start sample and length;
- raw and deduplicated 55 counts;
- cycle count as `max(0, len(dedup_55) - 1)`;
- block start/end samples;
- first and last deduplicated 55 samples;
- available samples as `last55 - first55`;
- dedup and missing-gap counts;
- fallback flag, fallback reason, and warning strings.

When at least two deduplicated 55 events exist and `n_step` is available, the crop starts at the first deduplicated 55 and uses `compute_onbin_N(last55 - first55, n_step)`.

Fallback behavior is unchanged:

- `n_step is None`: fallback, reason is the non-integer sampling-rate warning.
- fewer than two deduplicated 55 events: fallback, reason `insufficient_55`.
- computed `n_samples <= 0`: fallback, reason `nonpositive_N`.

Run-level warnings are exactly `empty_events`, `no_onsets`, or `non_integer_fs:{fs}` where applicable.

## Refactor Constraints

- Do not change `ODDBALL_FREQ`, `CropResult`, function signatures, fallback reasons, warning strings, result keys, or sample arithmetic.
- Do not change processing order, epoch metadata fields, FFT crop diagnostics, output filenames, Excel sheets, or exported values.
- Compatibility wrappers may remain temporarily under `Legacy_App`, but new runtime imports should prefer the current-app owner.
