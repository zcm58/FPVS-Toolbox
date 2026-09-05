# FFT Crop Method

This page documents the current FFT crop method now owned by `Main_App.Shared.fft_crop_utils`. Refactors must preserve these decisions, warning strings, result fields, and caller behavior unless a future task explicitly changes the processing method.

## Purpose

The FFT crop helper chooses per-condition repetition windows that put the
project's exact oddball frequency on an FFT bin when possible. The active
processing runner passes the immutable project protocol; post-processing
verifies the resulting grid before producing frequency-domain values. The old
`ProcessingMixin` export is compatibility-only and is not in the active Main
App window's method-resolution order.

## Locked Invariant

The normal processing pipeline must preserve exact oddball-bin locking for
`55_onbin` crops. This is not a presentation detail or a tunable epoch-length
preference: the crop length `N` must make the oddball bin index
`k = f_oddball * N / fs` an integer before downstream FFT, SNR, BCA, FullFFT,
Plot Generator, or Stats code consumes the workbook.

For the default project protocol, `f_oddball = 6/5 Hz = 1.2 Hz`.
With the supported integer sampling rates that are multiples of 256 Hz, this
means the crop length advances in 3-oddball-cycle units:

| Sampling rate | `n_step` samples | Step duration | Oddball cycles per step |
| --- | ---: | ---: | ---: |
| 256 Hz | 640 | 2.5 s | 3 |
| 512 Hz | 1280 | 2.5 s | 3 |
| 1024 Hz | 2560 | 2.5 s | 3 |
| 2048 Hz | 5120 | 2.5 s | 3 |

Do not assume that an arbitrary integer number of oddball cycles is FFT-safe at
these sampling rates. A crop "around 146 cycles" must use an on-bin neighbor
such as 144 or 147 cycles, because 146 cycles places 1.2 Hz between FFT bins
for 256/512/1024/2048 Hz data.

This behavior is owned by `Main_App.Shared.fft_crop_utils` and the active
normal processing route through `Main_App.Performance.process_runner`. Do not
try to repair normal processing FFT leakage by changing unrelated workbook
readers unless the user explicitly scopes that separate workflow.

## Inputs

- `events`: MNE-style event rows where column 0 is sample index and column 2 is event id.
- `fs`: sampling frequency in Hz.
- `onset_ids`: condition onset event ids supplied by the event map.
- `oddball_id`: oddball trigger id or a per-condition mapping of condition
  onset code to oddball marker code. Standard projects use global marker `55`.
  Some task variants encode oddball markers as `50 + condition_id`, for
  example condition starts `1, 2, 3, 4, 5` with oddball markers
  `51, 52, 53, 54, 55`.
- `stream_end_sample`: optional sample index used as the end boundary for the final repetition block.

- `f_oddball`: the exact rational oddball rate from the ready project
  frequency protocol. `6/5` Hz remains the compatibility default of the pure
  helper, but active processing must pass the project value explicitly.
- `expected_analyzed_oddball_cycles`: the project-wide intended FFT-cycle
  count. Managed-project processing checks each repetition against this target;
  longer usable spans are capped and shorter spans are reported as protocol
  mismatches.

## On-Bin Length Rule

`compute_onbin_step(fs, f_oddball)` rounds `fs` to an integer and rejects
non-integer sampling rates when `abs(fs - round(fs)) >= 1e-6`. Active callers
pass the exact project rate; the function's `6/5` default exists only for
legacy/direct compatibility.

For integer sampling rates, the required FFT-compatible sample step is:

```text
den_fs = f_oddball.denominator * round(fs)
n_step = den_fs / gcd(f_oddball.numerator, den_fs)
```

`compute_onbin_N(available_samples, n_step)` returns the largest multiple of `n_step` that fits in the available interval. Non-positive inputs return `0`.

The returned `N` is intentionally allowed to be shorter than the full available
marker-to-marker interval so that `N % n_step == 0`. Do not replace this with "use all
available samples", "use the nearest second count", or a fixed epoch duration;
those changes can leak oddball power into neighboring FFT bins.

## Repetition Blocks

For each onset event whose id is in `onset_ids`:

- The block starts at that onset sample.
- The block ends at the next onset sample, or `stream_end_sample`, or `events[-1][0] + 1` for the final block.
- Repetition indexes are tracked separately per condition id, starting at `0`.
- The result key is `(condition_id, repetition_index)`.

Within each block, only rows whose event id matches the resolved oddball marker
for that condition are treated as oddball events. The normal processing runner
resolves this explicitly from the event stream: if a block contains at least
two condition-specific oddball markers (`50 + condition_id`), that marker is
used for the condition; otherwise the standard global marker `55` is used.

## Oddball-Marker Deduplication And Gap Warnings

The expected oddball-marker interval is `fs / f_oddball`, evaluated from the
exact project rate and represented on the source sample grid.

- An oddball marker is dropped as a duplicate when it occurs less than half the expected interval after the previous retained marker.
- A missing-gap warning is counted when a retained marker occurs more than 1.5 times the expected interval after the previous retained marker.
- Per-block warning strings are exactly `dedup_dropped:{count}` and `missing_55_gaps:{count}`.

## Crop Result Behavior

For each repetition, `CropResult` records:

- crop start sample and length;
- resolved oddball marker id;
- raw and deduplicated oddball-marker counts;
- cycle count as `max(0, len(dedup_55) - 1)`;
- block start/end samples;
- first and last deduplicated oddball-marker samples;
- available samples as `last55 - first55`;
- dedup and missing-gap counts;
- fallback flag, fallback reason, and warning strings.

When at least two deduplicated oddball markers exist and `n_step` is available,
the crop starts at the first deduplicated oddball marker and uses
`compute_onbin_N(last55 - first55, n_step)`. The metadata field names
`crop_mode == "55_onbin"`, `n55`, `first55_samp`, and `last55_samp` are
retained for workbook compatibility, but in condition-specific projects they
refer to the resolved marker such as 51 or 52. Any caller that stamps
`crop_mode == "55_onbin"` must preserve the condition `N % n_step == 0`.

The helper still records fallback diagnostics for invalid repetition blocks:

- `n_step is None`: fallback, reason is the non-integer sampling-rate warning.
- fewer than two deduplicated oddball markers: fallback, reason
  `insufficient_<marker>`, for example `insufficient_55` or `insufficient_51`.
- computed `n_samples <= 0`: fallback, reason `nonpositive_N`.

These fallback flags are diagnostic only. `Main_App.Performance.process_runner`
must hard-fail when any selected condition repetition falls back, when
`n_step` is unavailable, or when no common on-bin `N` can be computed. Do not
convert these diagnostics into `fixed_epoch_fallback` epochs, skip
repetitions, use fixed epoch windows, or let post-processing choose nearest
FFT bins.

## Shared Condition Span Plan

`plan_condition_fft_spans(crop_results, condition_id, n_step)` is the public
owner of repetition ordering, the shortest valid common on-bin length, aligned
`[start, stop)` spans, and fallback-repetition diagnostics for one condition.
The normal process runner consumes this plan and retains its existing hard-fail
messages and behavior.

Condition-aware preflight QC also consumes this exact plan at the raw source
sampling rate. Its time-domain and spectral checks use the same locked span that
normal processing will analyze. A present condition without a valid locked span
fails preflight explicitly; preflight must not invent an onset-based or fixed-
duration interval, use the whole arbitrary condition block, or duplicate the
common-length calculation. This reuse keeps preflight aligned with the FPVS crop
contract without changing the later 256 Hz preprocessing/downsample path.
The preflight scan and crop-grid audit carry the resolved project oddball rate
and frequency-protocol fingerprint; reference duration and cycle calculations
must not import the 1.2-Hz compatibility constant.

For managed single-segment BDF processing, `analysis_spans.py` preserves the
v3 release's post-resampling stimulus-marker alignment. It locates the MNE
stimulus sampling window containing the approved source onset, verifies the
actual target oddball onset, and retains the exact project-declared sample
count from that start. Nearest-target-sample rounding must not shift the crop.
Missing boundary markers cannot be repaired by snapping to another event.
The source and observed target origins remain separate, so nonzero
`first_samp` is not accidentally applied twice. Existing source timestamps are
preserved; the lower-rate grid still has the timing quantization present in v3.
Timing-version changes invalidate processed caches and incremental completion
records before the corrected windows can be reused downstream.

Normal condition workbooks report the realized grid in `FFT Metadata` and the
exact protocol/grid/filter identity in `Spectral Eligibility`. `FFT Bin Width
(Hz)` is `fs / N`; the existing `df_hz` field in `FFT and neighbors` remains
available for machine-readable compatibility. For managed projects, FullFFT
grid QC uses the declared expected oddball-cycle count as the reference and
validates displayed headers against the exact rational oddball spacing. A
cohort majority may describe legacy/corruption evidence but cannot redefine
the project duration. Rounded header collisions are invalid rather than a
license to select a nearby bin. The project protocol and spectral-eligibility
fingerprints invalidate old harmonic caches.

Run-level warnings are exactly `empty_events`, `no_onsets`, or `non_integer_fs:{fs}` where applicable.

## Refactor Constraints

- Preserve `CropResult`, fallback reasons, warning strings, result keys, and
  exact sample arithmetic. `ODDBALL_FREQ` is a compatibility default only;
  never use it as an active fallback when a managed project protocol is
  missing or invalid.
- Do not change the preprocessing order except through the locked
  `preprocessing-contract.md` behavior-change process. Do not change epoch
  metadata fields, FFT crop diagnostics, output filenames, Excel sheets, or
  exported values.
- Do not downgrade an entire condition or any repetition to fixed-epoch
  fallback. If a selected repetition cannot produce a valid `55_onbin` crop,
  fail the normal processing run before export.
- Do not make downstream Stats, Plot Generator, or workbook code compensate for
  off-bin workbooks by silently using nearest oddball-frequency bins. Exact
  oddball columns in `FullFFT Amplitude (uV)` are expected from valid
  `55_onbin` processing.
- Legacy compatibility wrappers have been deleted; runtime imports should use the current-app owner.
