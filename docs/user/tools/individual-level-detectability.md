# Individual Detectability

Individual Detectability is a beta reporting tool that creates one
participant-level topography and SNR panel per processed workbook. It helps you
see how consistently the selected FPVS response is detectable across
participants; it is not a replacement for the group statistical analysis.

## Inputs

Choose the processed Excel root, one or more conditions, an output folder, and
the participants to include. Each workbook must contain `FullFFT Amplitude
(uV)` and `FullSNR` sheets with compatible electrode and frequency columns.

By default, the tool obtains one common harmonic list using the same
group-significant selection policy as Statistical Analysis. The selected
conditions, project ROIs, and included participants therefore affect the common
list. A custom fixed harmonic list is available as an explicitly exploratory
advanced option and is identified as such in filenames and metadata.

## Participant-Level Detection

For each electrode, the tool sums the selected FullFFT target amplitudes and
compares that sum with neighboring-bin sums. The noise window uses ±10 FFT bins
around each target, excludes the target and immediately adjacent bins, and
removes one minimum and one maximum noise value before calculating a z-score.

An electrode is significant when it meets the configured z threshold (1.64 by
default) and, when enabled, the one-tailed Benjamini–Hochberg false-discovery-rate
criterion (alpha 0.05 by default) across electrodes.

Each participant panel shows:

- a scalp topography of the summed-harmonic z-scores, with non-significant
  electrodes displayed at the white floor;
- `n`, the number of significant electrodes; and
- an SNR curve averaged across the significant electrodes and selected
  harmonics within the configured relative-frequency window.

The SNR panel is blank when no electrode meets the detection rule.

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
- Vandenheever, D., et al. (2025). [Exploring facial expression processing with fast periodic visual stimulation and diverse stimuli](https://doi.org/10.1016/j.bandc.2025.106338). *Brain and Cognition, 189*, 106338.
- [Individual Detectability implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Individual_Detectability).
