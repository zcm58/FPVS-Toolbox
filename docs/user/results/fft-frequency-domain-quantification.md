# FFT and Frequency-Domain Quantification (FPVS)

Use this page when you want to understand how FPVS Toolbox turns EEG responses into frequency-domain measures.

This Toolbox quantifies Fast Periodic Visual Stimulation (FPVS) responses in the **frequency domain**. In FPVS, images are presented at a fixed "base" rate (for example, 6 Hz). Every Nth image is an "oddball," so the oddball events occur at a lower fixed rate (for example, **1.2 Hz** when every 5th image is an oddball). If the brain is tracking these periodic events, the EEG spectrum shows peaks at the stimulation frequencies and their harmonics.

## What is an FFT "bin"?

When we compute a Fast Fourier Transform (FFT) on a finite time segment, the spectrum is evaluated at a discrete set of frequencies called **bins**. The spacing between bins is the **frequency resolution**:

- **T** = length of the analyzed time segment (seconds)
- **fs** = sampling rate (Hz)
- **N** = number of samples in the analyzed segment
- **T = N / fs**
- **df = 1 / T = fs / N** (Hz per bin)

Each FFT bin corresponds to a frequency:
- bin k corresponds to frequency **f(k) = k * df**.

So if df is 0.00833 Hz, then bin k=144 corresponds exactly to 144 x 0.00833 ~ **1.2 Hz**.

## Why FPVS needs "bin-locked" segment lengths (integer-cycle cropping)

FPVS analysis often focuses on the amplitude at the **oddball frequency** (e.g., 1.2 Hz) and its harmonics (2.4 Hz, 3.6 Hz, ...). This works best when the oddball frequency lands **exactly on an FFT bin**.

If the analyzed segment length does *not* contain an integer number of oddball cycles, the oddball energy does not fall cleanly into a single bin. Instead, it spreads into neighboring bins. This is commonly called **spectral leakage**. Leakage makes the "target bin amplitude" smaller than it should be and can inflate or distort noise estimates around that bin.

The key requirement for bin-locking is:

- The segment must contain an **integer number of oddball cycles**.

Equivalently:
- **f_oddball x T** must be an integer
- or **f_oddball = k x df** for some integer bin k

This Toolbox enforces this rule by cropping the segment used for FFT to a sample count **N** that guarantees oddball bin alignment.

## How the Toolbox defines the FFT segment using oddball triggers

During acquisition, the start of a condition is marked by a condition code
(e.g., 1, 2, 3, ...). Every time an oddball stimulus is shown, an oddball event
code is emitted. In standard projects this code is **55**. Some projects encode
the oddball marker by condition, such as condition codes **1, 2, 3, 4, 5** with
oddball markers **51, 52, 53, 54, 55**.

This creates a structure like:

- condition start trigger (e.g., "1")
- short blank / lead-in
- oddball markers such as 55, or 51 for condition 1, one per oddball at 1.2 Hz
- condition ends (no special "last oddball" trigger; the last marker in the series is effectively the last oddball)

To define a "steady stimulation" analysis window, the Toolbox can use the first
and last oddball markers for each condition repetition:

1) Resolve the oddball marker for the condition.
2) Find all matching oddball marker events within the condition repetition.
3) Identify the first and last matching oddball markers.
4) Use this region as the basis for selecting the FFT segment.

This avoids relying on a fixed "tmin/tmax in seconds" window that might include non-steady periods (e.g., lead-in blank screens) and it naturally adapts across sampling rates because everything is based on sample indices and event timing.

### Why "n55 - 1" matters

If there are **n55** oddball triggers in a repetition, there are **n55 - 1 intervals** between them. Those intervals represent complete oddball periods. Using the intervals between the first and last oddball events is the most conservative way to guarantee an integer number of oddball cycles without needing to assume extra time after the last oddball trigger.

In plain terms:
- **n55** = number of oddballs observed
- **n55 - 1** = number of full oddball cycles between the first and last oddball

This is a safe choice when you want the FFT segment to be based on confirmed, fully observed cycles.

## Enforcing an on-bin sample count (works across sampling rates)

The oddball rate in this project is currently **1.2 Hz**, which equals **6/5 Hz**. To be exactly on-bin, we need a sample count **N** such that:

- oddball cycles in the segment = **f_oddball x (N/fs)** is an integer

For f_oddball = 6/5, that means we need:

- (6 x N) / (5 x fs) is an integer

In practice, the Toolbox computes an "on-bin step size" in samples for the current sampling rate (fs). For example:
- If fs = 256 Hz, a valid on-bin step is **640 samples** (2.5 seconds).
  That guarantees that 1.2 Hz aligns to an FFT bin (because df = fs/N becomes a divisor that places 1.2 exactly on a bin).

Then the Toolbox snaps the usable sample length down to the largest multiple of this step:

- **N = floor(available_samples / step) x step**

This guarantees:
- N is a clean multiple of the on-bin step
- df = fs / N yields a bin exactly at 1.2 Hz (and therefore also at integer harmonics of 1.2)

### Common N across repetitions

When a condition has multiple repetitions, each repetition may have slightly different available lengths (missing triggers, dropped samples, etc.). To avoid mixing spectra with different df values, the Toolbox enforces a **common N per condition**, chosen as:

- take the minimum usable N across repetitions
- snap it down to the nearest on-bin multiple

This ensures that within a condition, all repetitions share the same:
- sampling rate fs
- FFT length N
- frequency resolution df
- bin index for the oddball frequency (k0)

## What the "FFT and neighbors" sheet means

Some exports include a sheet (for example, "FFT and neighbors") that stores amplitudes not only at the target bin, but also at neighboring bins around the target. These columns help diagnose leakage, noise floor structure, and whether the peak is cleanly centered.

Key columns:

- **fs**: sampling rate (Hz)
- **N**: number of samples in the FFT segment
- **T_sec**: segment duration in seconds (N / fs)
- **df_hz**: frequency resolution (fs / N)
- **k0**: bin index used for the target (nearest or exact)
- **f_bin_hz**: actual bin frequency at k0 (k0 x df)
- **crop_mode**:
  - **55_onbin** means the segment was derived from oddball triggers and snapped to an on-bin N. The name is retained for compatibility even when the actual marker was condition-specific, such as 51 or 52.
  - **fixed_epoch_fallback** means the system could not apply marker-based cropping and used the legacy fixed window (tmin/tmax) instead. Normal Stats-bound processing treats this as invalid and fails before export.
- **n55**, **first55_samp**, **last55_samp**: oddball trigger count and indices used to define the crop region. These field names are historical; in condition-specific projects they refer to the resolved oddball marker.
- **N_step**: the on-bin step size in samples for this fs
- **N_mod_step**: N % N_step (should be 0 in on-bin mode)
- **fallback_reason**: why marker-based cropping was not used (e.g., missing triggers)

Neighbor amplitude columns:
- **amp_m11 ... amp_m1** are the amplitudes at bins below the target (k0-11 ... k0-1)
- **amp_p1 ... amp_p11** are the amplitudes at bins above the target (k0+1 ... k0+11)

If the segment is perfectly bin-locked and the signal is stable, you typically expect a strong peak at the target bin with relatively smaller neighbors (though real EEG and harmonics can complicate this). If the target energy spreads across multiple bins, that suggests leakage or non-stationarity.

## Notes about SNR / noise estimation

Many FPVS pipelines estimate a local noise floor using bins around the target frequency while excluding the immediately adjacent bins. This reduces contamination from leakage into neighboring bins. The Toolbox follows this same general idea: a target bin is compared against nearby bins to estimate noise, and then SNR- or z-like metrics can be computed from that local baseline.

## Summary

- FFT bins are spaced by df = fs/N.
- FPVS amplitude estimates at 1.2 Hz work best when 1.2 Hz lands exactly on a bin.
- If the segment does not contain an integer number of oddball cycles, energy leaks into neighboring bins (spectral leakage).
- The Toolbox avoids this by using oddball triggers to define the stimulation segment and snapping N to an on-bin multiple for the current sampling rate.
- The "FFT and neighbors" export is a diagnostic view that shows amplitudes around the target bin to confirm bin-locking and evaluate leakage/noise.
