# FFT Crop Method

This page documents the current FFT crop method now owned by `Main_App.Shared.fft_crop_utils`. Refactors must preserve these decisions, warning strings, result fields, and caller behavior unless a future task explicitly changes the processing method.

## Purpose

The FFT crop helper chooses per-condition repetition windows that put the oddball frequency exactly on an FFT bin when possible. It is used by the processing runner, compatibility processing bridge, and post-processing bridge to keep epoch lengths compatible with oddball-frequency analysis.

## Locked Invariant

The normal processing pipeline must preserve exact oddball-bin locking for
`55_onbin` crops. This is not a presentation detail or a tunable epoch-length
preference: the crop length `N` must make the oddball bin index
`k = f_oddball * N / fs` an integer before downstream FFT, SNR, BCA, FullFFT,
Plot Generator, or Stats code consumes the workbook.

For the toolbox default oddball frequency, `f_oddball = 6/5 Hz = 1.2 Hz`.
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
try to repair normal processing FFT leakage by changing Average Preprocessing,
advanced averaging, or unrelated workbook readers unless the user explicitly
scopes that separate workflow.

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

The oddball frequency constant is `6/5` Hz, equivalent to `1.2` Hz.

## On-Bin Length Rule

`compute_onbin_step(fs, f_oddball=6/5)` rounds `fs` to an integer and rejects non-integer sampling rates when `abs(fs - round(fs)) >= 1e-6`.

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

The expected oddball-marker interval is `round(fs / 1.2)` samples.

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

These fallback flags are diagnostic only for the active normal processing
pipeline. `Main_App.Performance.process_runner` must hard-fail when any selected
condition repetition falls back, when `n_step` is unavailable, or when no common
on-bin `N` can be computed. Do not convert these diagnostics into
`fixed_epoch_fallback` epochs, skip repetitions, use fixed epoch windows, or let
post-processing choose nearest FFT bins.

Run-level warnings are exactly `empty_events`, `no_onsets`, or `non_integer_fs:{fs}` where applicable.

## Refactor Constraints

- Do not change `ODDBALL_FREQ`, `CropResult`, function signatures, fallback reasons, warning strings, result keys, or sample arithmetic.
- Do not change processing order, epoch metadata fields, FFT crop diagnostics, output filenames, Excel sheets, or exported values.
- Do not downgrade an entire condition or any repetition to fixed-epoch
  fallback. If a selected repetition cannot produce a valid `55_onbin` crop,
  fail the normal processing run before export.
- Do not make downstream Stats, Plot Generator, or workbook code compensate for
  off-bin workbooks by silently using nearest oddball-frequency bins. Exact
  oddball columns in `FullFFT Amplitude (uV)` are expected from valid
  `55_onbin` processing.
- Legacy compatibility wrappers have been deleted; runtime imports should use the current-app owner.
