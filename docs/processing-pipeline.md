# Processing Pipeline

This page describes the **single-file processing pipeline** used by FPVS Toolbox.
It is written for end users who need manuscript-ready Methods text and verified
implementation details.

---

## Manuscript-ready summary (copy/paste)

FPVS Toolbox (Windows desktop app) processes EEG recordings stored as BioSemi .bdf
or EEGLAB .set files using MNE-Python for loading, channel typing, and preprocessing.
For each recording, the toolbox loads data with disk-backed memory mapping when
available, assigns channel types (including a configured stimulus/trigger channel),
and applies a standard 10–20 montage. Preprocessing follows a fixed sequence:
initial re-reference to a user-specified EXG pair, removal of those EXG channels,
optional channel-count limiting, optional downsampling, zero-phase FIR bandpass
filtering, kurtosis-based bad-channel detection with interpolation, and a final
average reference. Events are extracted from the stim channel (or annotations if
stim extraction fails), then epochs are created for each user-defined condition
label using a configured time window without baseline correction. The time-domain
data are averaged across epochs per condition, transformed with an FFT, and
frequency-domain metrics are computed at the target oddball harmonics (SNR,
baseline-corrected amplitude, and Z-score). Results are exported to per-condition
Excel files (electrode-level metrics and a full-spectrum SNR sheet), which serve
as inputs for ROI aggregation and statistical analyses in the Stats tool.

**Parameter placeholders:** Use the processing log and project settings/manifest
(exported from the UI) to fill in your actual values for reference channels,
filters, epoch window, and oddball frequency settings.

---

## Single-file pipeline (verified order)

The steps below reflect the linear processing order for **one recording file**
as implemented in the current codebase. “Implementation verified in:” notes point
you to the exact modules that define each step.

### 1) Data import / file loading

**What happens**

- **Supported input types:** `.bdf` (BioSemi) and `.set` (EEGLAB). Other formats
  are rejected. (Implementation verified in: `src/Main_App/PySide6_App/Backend/loader.py`.)
- **Disk-backed memory mapping:** the loader requests a disk-backed `preload` path
  for `.bdf` and (when supported) `.set` files, then materializes the memmap with
  `raw.load_data()` to keep RAM use bounded. (Implementation verified in:
  `src/Main_App/PySide6_App/Backend/loader.py`.)
- **Channel typing policy:**
  - The **stimulus/trigger channel** is explicitly typed as `stim`.
  - The **reference pair** (e.g., EXG1/EXG2) is preserved as `eeg` so it can be
    used for re-referencing.
  - Other EXG channels (EXG1–EXG8 not in the reference pair) are demoted to
    `misc`.
  (Implementation verified in: `src/Main_App/PySide6_App/Backend/loader.py`.)
- **Montage:** a standard 10–20 montage (`standard_1020`) is applied with
  `on_missing="warn"` and case-insensitive matching. (Implementation verified in:
  `src/Main_App/PySide6_App/Backend/loader.py`.)

**Key parameters**

| Parameter | Default | Source | Notes |
|---|---:|---|---|
| `stim_channel` | `Status` | Project settings / global settings | Used for event detection and typed as `stim`. |
| `ref_channel1`, `ref_channel2` | `EXG1`, `EXG2` | Project settings / global settings | Kept as `eeg` during loading. |

(Defaults verified in: `src/Main_App/PySide6_App/Backend/loader.py`,
`src/Main_App/PySide6_App/Backend/preprocessing_settings.py`.)

---

### 2) Preprocessing (fixed order)

Preprocessing is applied in a fixed sequence. Each operation is optional only if
its parameter is unset/disabled.

**Fixed order** (implementation verified in
`src/Main_App/PySide6_App/Backend/preprocess.py`):

1. **Initial re-reference** to the user-selected EXG pair (if both channels are
   present). The reference pair is applied using `raw.set_eeg_reference(...)`.
2. **Drop reference channels**: the two reference channels are removed from the
   data after re-referencing.
3. **Optional channel limit**: if `max_idx_keep` is set and smaller than the
   current channel count, only the first N channels are retained **plus** the
   stim channel (if present).
4. **Optional downsampling**: if `downsample_rate` is set and lower than the
   current sampling rate, the data are resampled with a Hann window.
5. **FIR bandpass filter** (zero-phase, forward/backward):
   - Method: `fir` with `firwin` design, `hamming` window, `phase="zero-double"`.
   - Transition bandwidths: 0.1 Hz (low and high).
   - Fixed filter length: 8449 points.
6. **Kurtosis-based bad-channel detection & interpolation**:
   - Kurtosis (Fisher, `bias=False`) is computed per EEG channel.
   - A **trimmed mean/std** is computed by removing 10% of the highest and lowest
     kurtosis values.
   - Channels with `|z| > rejection_z` are marked bad.
   - If a montage is present, bad channels are interpolated
     (`reset_bads=True`, `mode="accurate"`).
7. **Final average reference**: average reference is applied via projection and
   immediately applied (`apply_proj`).

**Key parameters (defaults)**

| Parameter | Default | Purpose |
|---|---:|---|
| `high_pass` | 0.1 Hz | High-pass cutoff (HPF) |
| `low_pass` | 50.0 Hz | Low-pass cutoff (LPF) |
| `downsample` / `downsample_rate` | 256 Hz | Target sampling rate |
| `rejection_z` / `reject_thresh` | 5.0 | Kurtosis Z threshold |
| `max_idx_keep` | 64 | Max channel index to keep |
| `ref_channel1`, `ref_channel2` | EXG1 / EXG2 | Initial reference pair |

(Defaults verified in: `src/Main_App/PySide6_App/Backend/preprocessing_settings.py`.)

**Logged/audited items**

- A preprocessing fingerprint string (HP/LP/downsample/reject/ref/stim).
- Filter snapshot (computed cutoffs and sampling rate).
- Number of bad channels rejected by kurtosis.
- Final sampling rate and channel count.

(Logging verified in: `src/Main_App/PySide6_App/Backend/preprocess.py`.)

---

### 3) Event detection and condition mapping

**Event detection (single-file pipeline)**

- The toolbox attempts to read events from the configured **stim channel** using
  `mne.find_events(...)`.
- If stim-based extraction fails, it falls back to
  `mne.events_from_annotations(...)`.

(Implementation verified in: `src/Main_App/Performance/process_runner.py`.)

**Condition mapping**

- Your **Event Map** supplies `label → integer code` pairs.
- For each label, events are included only if that integer code is present in
  the extracted events.
- If a label has zero matching events, the pipeline logs a warning and skips
  that label for the file.

(Implementation verified in: `src/Main_App/Performance/process_runner.py`.)

---

### 4) Epoching

- Epochs are created per label with:
  - `tmin = epoch_start` and `tmax = epoch_end` (seconds)
  - `baseline = None` (no baseline correction at epoch stage)
  - `preload = False`
  - `decim = 1`
- After creation, `epochs.drop_bad()` is called.

(Implementation verified in: `src/Main_App/Performance/process_runner.py`.)

**Not found in code; user-configurable / unknown**

- **Epoch rejection thresholds (e.g., voltage limits):** no explicit `reject`
  or `flat` criteria are passed to `mne.Epochs`. Search locations:
  - `src/Main_App/Performance/process_runner.py` (keywords: `Epochs`, `reject`, `flat`)
  - `src/Main_App/Legacy_App/processing_utils.py` (keywords: `Epochs`, `reject`, `flat`)

---

### 5) Frequency-domain analysis (FFT)

- For each condition, epochs are **averaged in the time domain** and the FFT is
  computed on the averaged signal (not per-epoch).
- FFT uses `np.fft.fft` with no explicit windowing, detrending, or zero-padding.
- The amplitude spectrum is computed as:
  `abs(FFT) / N * 2` for bins from 0 to Nyquist.
- Frequency bins are linearly spaced from 0 to `sfreq / 2`.

(Implementation verified in: `src/Main_App/Legacy_App/post_process.py`.)

---

### 6) Metric computation (SNR, BCA, Z-score)

**Target frequencies**

- The toolbox computes metrics at **oddball harmonics** defined by
  `TARGET_FREQUENCIES`.
- These are calculated as: `oddball_freq × 1..K`, where
  `K = round(bca_upper_limit / oddball_freq)`.
- `oddball_freq` and `bca_upper_limit` come from project settings.

(Implementation verified in: `src/config.py`.)

**Noise window and baseline definition (used by SNR, BCA, Z)**

For each target frequency, the toolbox finds the **nearest FFT bin** and defines
noise bins as follows:

- Window: ±10 bins around the target bin.
- Exclusions: target bin and its immediate neighbors (−1 and +1) are excluded.
- Minimum bins: if fewer than 4 candidate bins remain, noise mean/std are set
  to 0.0.
- Trimming: one maximum and one minimum value are removed before computing the
  mean and standard deviation.
- Standard deviation uses population variance (`ddof=0`).

(Implementation verified in: `src/Tools/Stats/Legacy/noise_utils.py` and
`src/Main_App/Legacy_App/post_process.py`.)

**Formulas (applied per channel × harmonic)**

Let:
- `A` = amplitude at the target FFT bin (µV)
- `noise_mean` = mean of the noise bins
- `noise_std` = standard deviation of the noise bins

Then:

- **SNR** = `A / noise_mean` (set to 0 when `noise_mean <= 1e-12`)
- **BCA** = `A - noise_mean`
- **Z-score** = `(A - noise_mean) / noise_std` (set to 0 when `noise_std <= 1e-12`)

(Implementation verified in: `src/Main_App/Legacy_App/post_process.py`.)

**Full-spectrum SNR**

A separate full-spectrum SNR matrix is computed for **all FFT bins** using the
same noise-bin logic and is exported as the `FullSNR` sheet.

(Implementation verified in: `src/Tools/Stats/Legacy/full_snr.py` and
`src/Main_App/Legacy_App/post_process.py`.)

**Background (not necessarily the toolbox implementation)**

FPVS studies often describe SNR based on a local noise window around each target
frequency; always report the **implementation actually used by the toolbox**
above.

---

### 7) ROI aggregation

**Important:** The core processing/export step writes **electrode-level**
metrics. ROI aggregation happens later (e.g., in the Stats tool) by reading the
exported Excel files.

**Verified ROI aggregation behavior (Stats tool)**

- ROI definitions are stored in settings as `roi_name → list of electrodes`,
  with electrode names uppercased and trimmed for matching.
- For Summed BCA analyses, the toolbox:
  - Reads the `BCA (uV)` sheet.
  - Sums BCA across selected harmonics per electrode.
  - Averages the summed values across electrodes in the ROI.
  - Ignores ROI electrodes that are missing from the Excel file.

(Implementation verified in: `src/Main_App/Legacy_App/settings_manager.py`,
`src/Tools/Stats/PySide6/dv_policies.py`.)

If you perform ROI aggregation outside the Stats tool (e.g., in a custom script),
report the exact aggregation rule you used.

---

### 8) Exports

**Output location**

- The export root is the project’s **Excel results folder** (default:
  `1 - Excel Data Files` under the project’s results directory).
- A subfolder is created per condition label (label is sanitized for filenames).

(Implementation verified in: `src/Main_App/PySide6_App/Backend/project.py`,
`src/Main_App/Legacy_App/post_process.py`.)

**Excel file names**

- **Single-file processing:** `PID_<Condition>_Results.xlsx`
- `PID` is extracted from the raw filename using `P\d+`, `Sub\d+`, or `S\d+`
  patterns; otherwise a cleaned filename stem is used.

(Implementation verified in: `src/Main_App/Legacy_App/post_process.py`.)

**Excel sheet names and contents**

| Sheet name | Contents | Columns |
|---|---|---|
| `FFT Amplitude (uV)` | Amplitude spectrum at target harmonics | `Electrode`, `<freq>_Hz` |
| `SNR` | Signal-to-noise ratio at target harmonics | `Electrode`, `<freq>_Hz` |
| `Z Score` | Z-scores at target harmonics | `Electrode`, `<freq>_Hz` |
| `BCA (uV)` | Baseline-corrected amplitudes at target harmonics | `Electrode`, `<freq>_Hz` |
| `FullSNR` | Full-spectrum SNR (interpolated) | `Electrode`, `<freq>_Hz` |

Target-harmonic columns are formatted as `"{freq:.4f}_Hz"`.
The `FullSNR` sheet is interpolated from 0.5 Hz up to the configured
`bca_upper_limit` in 0.01 Hz steps.

(Implementation verified in: `src/Main_App/Legacy_App/post_process.py`.)

---

### 9) Logging / reproducibility

The pipeline writes structured log messages during preprocessing and processing.
Key log entries you can cite for reproducibility include:

- Preprocessing fingerprint and filter snapshot (cutoffs, sampling rate).
- Number of channels rejected by kurtosis.
- Event source (stim vs. annotations) and number of events.
- Warnings for labels with zero events or zero epochs.
- Confirmation of Excel export completion.

(Implementation verified in: `src/Main_App/PySide6_App/Backend/preprocess.py`,
`src/Main_App/Performance/process_runner.py`,
`src/Main_App/Legacy_App/post_process.py`.)

For manuscript archiving, keep:
- The project settings/manifest (event map, preprocessing settings, ROI list).
- The per-condition Excel outputs.
- The processing log file or log window export.

---

## What to report in your manuscript (checklist)

Fill in the values in brackets with your project’s actual settings.

- **Recording format and sampling rate:** [e.g., BioSemi .bdf, 512 Hz]
- **Stim/trigger channel:** [e.g., Status]
- **Initial reference:** [e.g., EXG1/EXG2]
- **Final reference:** [average reference]
- **Filter settings:** [HPF = __ Hz, LPF = __ Hz]
- **Downsampling:** [target Hz or “not applied”]
- **Bad-channel handling:** [kurtosis Z threshold __; interpolation on/off]
- **Epoch window:** [tmin = __ s, tmax = __ s; baseline = none]
- **Event mapping:** [list labels and integer codes]
- **FFT method:** [FFT of averaged epochs; amplitude = abs(FFT)/N*2]
- **Frequency resolution:** [N = samples per epoch → resolution = sfreq/N]
- **Noise window for SNR/Z/BCA:** [±10 bins; exclude target ±1; drop max/min]
- **Oddball harmonics analyzed:** [oddball_freq, upper limit, resulting list]
- **ROI definitions:** [ROI name → electrode list; uppercased channel matching]
- **Exported metrics and units:** [SNR, Z, BCA (µV), FFT amplitude (µV)]

---

## Implementation details not found in code

If you need any of the following details for your manuscript, they are **not
verified in code** and should be reported explicitly as user-configurable or
unknown:

- **Epoch rejection thresholds (amplitude/flat criteria)**
  - Searched in:
    - `src/Main_App/Performance/process_runner.py` (keywords: `Epochs`, `reject`, `flat`)
    - `src/Main_App/Legacy_App/processing_utils.py` (keywords: `Epochs`, `reject`, `flat`)

If you know where these are configured in your local deployment, add them to
this documentation and cite the exact configuration source.
