# Individual Detectability

Individual Detectability is a beta reporting tool that creates one
participant-level topography and SNR panel per processed workbook. It helps you
see how consistently the selected FPVS response is detectable across
participants; it is not a replacement for the group statistical analysis.

## Inputs

Choose the processed Excel root, one or more conditions, an output folder, and
the participants to include. Each workbook must have compatible `FullFFT
Amplitude (uV)` and `FullSNR` data, stored in its NumPy companion for new
exports or its worksheets for older exports. Keep each workbook and companion
together; see [Spectral Data Files](../reference/spectral-data-files.md).

By default, the tool loads the project-wide selected-harmonic list saved
when processing completed. Condition selection and participant display
exclusions do not recalculate that list. If the saved selection is missing or
stale, the tool asks you to reprocess the project or recalculate harmonic
selection from Settings.

A custom fixed harmonic list remains available as an explicitly exploratory
advanced option and is identified as such in filenames and metadata. It does
not replace the project's saved harmonic selection.

## Participant-Level Detection

For each participant, condition, and electrode, the tool uses the uncorrected
FullFFT amplitude spectrum. Normal managed processing averages retained
repetitions in the time domain before computing the FFT, within each
recording-condition.

The selected target amplitudes are summed. Neighboring amplitudes are also
summed across harmonics **at matching offsets**: for example, every harmonic's
`-2` bin contributes to one background value and every `+2` bin to another.
The noise window uses offsets `-10` through `-2` and `+2` through `+10`,
excluding the target and immediately adjacent bins. It preserves 18 background
sums rather than concatenating neighboring bins or reducing them to one value.
One minimum and one maximum are removed **after summation**, normally leaving
16 values. The tool then calculates:

```text
Z = (summed target amplitude - mean of summed background)
    / population SD of summed background (ddof = 0)
```

This is a within-participant spectral Z-score, not standardization of stored
summed-BCA values across participants. A summed-BCA value does not retain the
background variability needed for this calculation. Trimming before versus
after harmonic summation can also change the baseline-corrected numerator.

An electrode is significant when `Z >=` the configured threshold (1.64 by
default) and, when enabled, it passes the one-tailed Benjamini–Hochberg
false-discovery-rate criterion across electrodes. FDR is enabled by default
at alpha 0.05. The current tool reports electrode results, not ROI-level
detectability results.

Each participant panel shows:

- a scalp topography of the summed-harmonic z-scores, with non-significant
  electrodes displayed at the white floor;
- `n`, the number of significant electrodes; and
- an SNR curve averaged across the significant electrodes and selected
  harmonics within the configured relative-frequency window.

The SNR curve uses stored FullSNR values; it is a descriptive display, not the
summed raw spectrum used to calculate Z. Its **Half window (Hz)** setting does
not change the composite-Z noise window. The SNR panel is blank when no
electrode meets the detection rule.

## Relationship to Published Methods

The **Input data** information button opens the calculation description and
linked references. The implementation follows the summed-spectrum approach,
with toolbox-specific harmonic selection, background geometry, and correction
settings; it is not an exact replication of every cited protocol.

- **David et al. (2025), Sections 2.6 and 3.2, Figure 5:** sums 25-bin
  harmonic-centered segments before baseline correction, retaining 20
  background values after adjacent-bin and min/max exclusions. Its
  FDR-corrected participant topographies, electrode counts, and SNR panels
  closely parallel this tool's presentation; the exact FDR variant and alpha
  are unspecified.
- **Yan et al. (2023):** uses five oddball components and 48 neighboring bins
  for individual left/right occipitotemporal ROI detection at `Z > 1.64`.
- **Hauk et al. (2025), Section 2.5.2:** explicitly sums harmonic-centered
  spectra before baseline correction and Z-scoring, with ten neighboring bins
  per side, a one-bin gap, and min/max removal. The authors' code uses population
  SD. The toolbox instead takes nine neighbors per side before trimming.
- **Lochy et al. (2024), Section 3.4:** describes individual ROI Z-scores from
  uncorrected summed harmonic amplitudes at `Z > 1.64`; this description is less
  explicit about the intermediate bin-summing operations.

The toolbox's default `Z >= 1.64` plus BH-FDR rule therefore differs from an
uncorrected strict `Z > 1.64` ROI rule. Study-specific harmonics, ROI definitions,
and noise windows must be considered when comparing results.

## Outputs

For each condition, the tool writes matching 600-DPI `.png` and `.pdf` grid
figures in a condition subfolder. It also writes a run log and JSON metadata
containing the selected conditions, exclusions, harmonic source and list,
thresholds, and display settings.

The tool may create an `_individual_detectability_cache` folder beside the
input workbooks to speed repeat runs. This cache is not an analysis result.

## Interpretation

Use these panels to inspect participant-level response consistency and data
quality. The number of significant electrodes depends on the harmonic list,
noise estimate, threshold, correction, montage coverage, and signal quality. It
should not be treated as a diagnosis or as an independent confirmatory test
without a prespecified analysis plan.

## References

- David, J., et al. (2025). [An objective and sensitive electrophysiological marker of word semantic categorization impairment in Alzheimer's disease](https://doi.org/10.1016/j.clinph.2024.12.018). *Clinical Neurophysiology, 170*, 98–109.
- Yan, X., Volfart, A., & Rossion, B. (2023). [A neural marker of the human face identity familiarity effect](https://doi.org/10.1038/s41598-023-40852-9). *Scientific Reports, 13*, 16294.
- Hauk, O., et al. (2025). [Word-selective EEG/MEG responses in the English language obtained with fast periodic visual stimulation (FPVS)](https://doi.org/10.1162/imag_a_00414). *Imaging Neuroscience, 3*. [Authors' analysis code](https://github.com/olafhauk/FPVS_WORDS).
- Lochy, A., et al. (2024). [Linguistic and attentional factors - Not statistical regularities - Contribute to word-selective neural responses with FPVS-oddball paradigms](https://doi.org/10.1016/j.cortex.2024.01.007). *Cortex, 173*, 339–354.
- Additional FPVS context: Vandenheever, D., et al. (2025). [Exploring facial expression processing with fast periodic visual stimulation and diverse stimuli](https://doi.org/10.1016/j.bandc.2025.106338). *Brain and Cognition, 189*, 106338.
- [Individual Detectability implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Individual_Detectability).
