# Statistics

The Statistics tool summarizes processed FPVS outputs and exports statistical results for single-group FPVS projects.

## What It Does

Use this page to document the supported statistical workflows and the basic outputs users should expect.

## When To Use It

Use the Statistics tool after FPVS Toolbox has generated processed Excel outputs for the conditions included in
the analysis.

## Basic Inputs

- Processed condition workbooks.
- Project condition and ROI settings.
- The selected dependent-variable policy.

## Basic Outputs

- Statistical result workbooks.
- Stats-ready export workbooks for downstream tools or external statistics software.
- A harmonic-selection summary workbook when the processing pipeline completes:
  `Quality Check/Harmonic_Selection_Summary.xlsx`.
- Plain-language summaries where supported.

## Harmonic Selection

By default, FPVS Toolbox detects significant oddball harmonics from the
grand-average `FullFFT Amplitude (uV)` spectrum over the union of the ROIs
defined in Settings. It uses a strict `z > 1.64` threshold and excludes
base-rate overlaps such as 6, 12, and 18 Hz.

For Summed BCA, the default summation rule includes all non-base oddball
harmonics up to the highest detected significant harmonic. For example, if
2.4, 4.8, and 7.2 Hz are detected as significant, the included summation list
also includes the lower non-base oddball harmonics through 7.2 Hz. The summary
workbooks distinguish the harmonics that were detected as significant from the
harmonics that were included in the final Summed BCA.

Fixed/predefined harmonic lists remain available as an alternate policy when a
study requires an explicit list.

## Notes To Fill In

- Document the supported analysis types.
- Add guidance for when users should export a stats-ready workbook.

## References

- Method references: Add during the manual content pass.
- Toolbox implementation reference: [src/Tools/Stats](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Stats).
