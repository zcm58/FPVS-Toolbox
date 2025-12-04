# Processing Pipeline

This page describes how the FPVS Toolbox processes EEG data from raw
recordings to frequency-domain metrics and ROI-level summaries.

The pipeline is designed to mirror a standard processing pipeline using MATLAB and EEGLab. Please see the relevant 
publications for more information on this methodology. 

---

## Overview

At a high level, the FPVS Toolbox:

1. Loads a raw FPVS recording (BioSemi `.bdf`) using
   a disk-backed memory map.
2. Applies a standardized preprocessing pipeline (referencing, filtering,
   artifact handling, final average reference).
3. Extracts events for user-defined conditions and creates epochs around
   each stimulus type.
4. Computes frequency-domain spectra and FPVS metrics (e.g., SNR, baseline-
   corrected amplitudes) at the tag frequency and harmonics.
5. Aggregates results within user-defined ROIs and exports per-condition,
   per-ROI summaries to Excel for downstream statistics.

Each step is logged to the FPVS Toolbox log window and log file so users
can reconstruct the full processing history for a given project.

---

## 1. Loading recordings

When you select a single file or a batch folder, the loader:

- Resolves the **stimulus channel**  
  The toolbox chooses the stim channel specified in project settings
  (default: `Status`) and assigns it the MNE `stim` type.

- Resolves the **initial reference pair**  
  A pair of EXG channels (default: `EXG1` / `EXG2`) is treated as the
  initial EEG reference. These channels are kept as EEG during loading.

- Reads the recording with MNE  
  - BioSemi recordings are loaded with `mne.io.read_raw_bdf`.
  - EEGLAB files are loaded via MNE’s EEGLAB reader.  
  In both cases, a disk-backed memory map is used when possible to limit
  RAM usage on large datasets.

- Applies a standard montage  
  After loading, a standard 10–20 montage is applied to EEG channels so
  channel locations are available for interpolation and ROI aggregation.
  Any non-EEG auxiliary channels are typed appropriately (e.g., EXG → `misc`
  after referencing, stim → `stim`).

---

## 2. Preprocessing pipeline

The preprocessing pipeline is applied in a fixed order to keep behavior
consistent across projects.

### 2.1 Initial referencing

- The user-selected reference pair (by default, `EXG1` / `EXG2`) is
  coerced to EEG type if needed.
- MNE’s `set_eeg_reference` is used to subtract the average of these two
  reference channels from all EEG channels.
- Audit flags are recorded so that the log reflects whether referencing
  succeeded and which channels were used.

### 2.2 Drop reference channels

After re-referencing:

- The two reference channels are removed from the dataset, so they do not
  contribute to later average-reference and ROI computations.

### 2.3 Optional channel limit

If a maximum EEG channel count is configured in project settings:

- Channels beyond that index are dropped to keep a consistent subset of
  sensors across recordings.
- The stim channel is preserved even if it would otherwise be outside
  the limit.

### 2.4 Downsampling (optional)

If downsampling is enabled and the original sampling rate is higher than
the chosen target:

- Data are resampled using MNE’s resampling routines with a Hann window.
- Downsampling occurs **before** filtering to reduce computation and
  keep filter design consistent.

### 2.5 FIR filtering

A zero-phase FIR filter is applied to the (possibly downsampled) data:

- Legacy parameters are mirrored:
  - The GUI “high-pass” setting maps to the filter’s `l_freq`.
  - The GUI “low-pass” setting maps to `h_freq`.
  - Fixed transition bandwidths and filter lengths are chosen to match
    the original toolbox behavior as closely as possible.
- Filtering is applied in a way that avoids phase distortion
  (forward-and-backward filtering).

### 2.6 Kurtosis-based artifact handling

To identify noisy channels:

- EEG channels (excluding previously marked bads and non-EEG/stim
  channels) are scored using a kurtosis-based metric.
- Channels whose kurtosis exceeds a configurable Z-score threshold are:
  - Marked as bad (added to `raw.info["bads"]`).
  - Interpolated when a montage is available, using neighboring
    electrodes to estimate the signal.

### 2.7 Final average reference

After bad-channel handling:

- Remaining good EEG channels are re-referenced to the average.
- Any pending projections are applied.
- Preprocessing completes with logging of:
  - Final channel count (total and bads).
  - Final sampling rate.
  - Filter settings, artifact thresholds, and reference choices.

---

## 3. Event extraction and epoching

The event and epoching step mirrors the legacy flow but is configured via
the PySide6 GUI.

### 3.1 Event detection

Events are derived in one of two ways:

1. **From annotations**  
   If the recording contains MNE annotations that correspond to your
   condition IDs, they are mapped directly using the IDs and labels you
   configure in the Event Map. 

2. **From the stim channel**  
   If annotations are not available, events are detected from the stim
   channel (e.g., `Status`) using `mne.find_events`.  
   - The IDs you configure in the Event Map (e.g., '21' for
     “Condition ABC”) are matched to codes on the stim channel.
   - Empty event sets (no events found for a given ID) are logged as
     warnings.

### 3.2 Epoch creation

For each label/ID pair defined in the Event Map:

- MNE `Epochs` objects are created with user-specified start and end
  times relative to each event (e.g., from −0.5 s to +5.0 s). In FPVS Experiments, `Epochs` refer to one 
experimental condition. Each condition must be analyzed separately. 

- Successful epoch sets are stored per condition label and used for
  downstream spectral analysis and metric computation.

---

## 4. Frequency-domain analysis

Once epochs are defined, the FPVS Toolbox computes frequency-domain
responses for each condition.

In brief:

1. **FFT per epoch and channel**  
   - A Fourier transform is applied to each epoch to obtain amplitude
     spectra at frequencies of interest.

2. **Tag frequency and harmonics**  
   - The fundamental FPVS stimulation frequency and a configurable number
     of harmonics are selected for metric computation.

3. **Baseline regions**  
   - Surrounding “noise” frequency bins (excluding the signal bin and
     its immediate neighbors) define a baseline used for SNR and
     baseline-corrected measures.

---

## 5. FPVS metrics (SNR, baseline-corrected amplitude)

For each channel, condition, and harmonic, the toolbox computes the following metrics: 

--- 
- **SNR (Signal-to-Noise Ratio)**  

In frequency-domain analyses of fast periodic visual stimulation (FPVS) with electroencephalography (EEG), signal-to-noise ratio (SNR) is a core metric for quantifying neural responses at stimulation frequencies. Within oddball paradigms where deviant stimuli are periodically included among a stream of base images, SNR provides a robust, objective estimate of response strength at the oddball frequency and its harmonics. The standard method for calculating SNR involves dividing the amplitude at the frequency of interest by the mean amplitude of surrounding frequency bins, assumed to reflect background noise (Rossion et al., 2015; Zimmermann et al., 2019).
A methodological consensus has emerged around the use of a 20-bin local noise window—10 bins on either side of the target frequency—with specific exclusions to ensure a clean estimate. First, the immediately adjacent frequency bins are systematically excluded to mitigate contamination from spectral leakage of the target response (Stothart et al., 2017; Georges et al., 2020). Second, many studies further discard the two most extreme amplitude values among the noise bins (i.e., the highest and lowest), which can otherwise inflate or deflate the average due to unrelated spectral artifacts or narrowband EEG noise (Dzhelyova & Rossion, 2014a; Poncet et al., 2019).
For example, Georges et al. (2020) and Zimmermann et al. (2019) both implemented this 20-bin ±10 approach, excluding the neighboring bins as well as the extreme values to derive a robust noise floor. This practice, introduced in foundational studies (e.g., Liu-Shuang et al., 2014), ensures the SNR reflects genuine periodic neural responses rather than local noise fluctuations or harmonics from unrelated sources.
The resulting SNR values are used not only for individual participant-level inference but also for generating z-scores and evaluating signal strength across scalp topographies. Because the frequency bins used for noise estimation are drawn from the same power spectrum and close in frequency to the signal bin, this method yields a locally normalized, frequency-specific measure that is highly sensitive to subtle categorical effects in the EEG signal (Rossion et al., 2015; Poncet et al., 2019).

**References**

- Dzhelyova, M., & Rossion, B. (2014a). The effect of parametric stimulus variation on individual face discrimination indexed by fast periodic visual stimulation. Journal of Vision, 14(12), 1–18. https://doi.org/10.1167/14.12.22
- Georges, C., Retter, T. L., & Rossion, B. (2020). Face-selective responses in the human brain: A periodic stimulation approach. NeuroImage, 214, 116703. https://doi.org/10.1016/j.neuroimage.2020.116703
- Liu-Shuang, J., Norcia, A. M., & Rossion, B. (2014). An objective index of individual face discrimination in the right occipito-temporal cortex by means of fast periodic oddball stimulation. Neuropsychologia, 52, 57–72. https://doi.org/10.1016/j.neuropsychologia.2013.10.022
- Poncet, F., Rossion, B., & Jacques, C. (2019). Evidence for the existence of a face-selective neural response in the human brain with fast periodic visual stimulation. NeuroImage, 189, 150–162. https://doi.org/10.1016/j.neuroimage.2019.01.021
- Rossion, B., Torfs, K., Jacques, C., & Liu-Shuang, J. (2015). Fast periodic presentation of natural images reveals a robust face-selective electrophysiological response in the human brain. Journal of Vision, 15(1), 1–18. https://doi.org/10.1167/15.1.15
- Stothart, G., Quadflieg, S., & Kazanina, N. (2017). Semantic processing in the human brain: Electrophysiological evidence from fast periodic visual stimulation. Neuropsychologia, 100, 57–63. https://doi.org/10.1016/j.neuropsychologia.2017.03.006
- Zimmermann, J. F., Groh-Bordin, C., & Roesler, F. (2019). Familiarity and identity-specificity of face representations in fast periodic visual stimulation. NeuroImage, 193, 162–171. https://doi.org/10.1016/j.neuroimage.2019.03.026

--- 

**Baseline-corrected amplitude (BCA)**  

  Amplitude at the target bin minus the baseline estimate.

--- 
**Z-Scores (placeholder)**

Need to include some information regarding Z-Scores here. 


--- 
These metrics are then aggregated:

- Across epochs for each subject and condition.
- Across channels belonging to each user-defined ROI.

The resulting ROI-level SNR and BCA values form the basis of the
statistical analyses run in the Stats tool.

---

## 6. ROI aggregation and exports

The final steps of the processing pipeline are:

1. **ROI aggregation**  
   - Channels are grouped into ROIs defined in project settings
     (e.g., left occipital, right occipital, frontal, parietal).
   - Metrics are averaged within each ROI for each subject, condition,
     and harmonic.

2. **Excel exports**  
   - Per-subject, per-condition, and per-ROI summaries are written to
     Excel files in the project’s Results folder.
   - These Excel outputs are used directly by the **Statistical Analysis**
     module for single-group and between-group models.

3. **Logging and audit trail**  
   - Each successfully processed file contributes to a batch summary
     (number of files, rejected channels, etc.).
   - The logs provide a full audit trail of the processing settings used
     for a given project and batch.

---

## Notes and best practices

- Keep preprocessing settings consistent within a project so that metrics
  are comparable across subjects and sessions.
- Verify event IDs and epoch time windows before running large batch
  jobs; incorrect event mappings can silently produce empty conditions.
- When publishing results, include key pipeline settings (reference,
  filter bands, artifact thresholds, and epoch windows) in the Methods
  section, ideally referencing this documentation for additional detail.
