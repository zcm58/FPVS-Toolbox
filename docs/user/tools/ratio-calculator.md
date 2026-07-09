# Ratio Calculator

Ratio Calculator is a beta exploratory tool for paired condition comparisons.
For each participant and ROI, it computes condition A divided by condition B for
summed BCA, summed SNR, and summed z-score values.

## When To Use It

Use this tool only when a condition ratio is part of a planned descriptive or
exploratory analysis. Both conditions must contain processed workbooks for the
same participants.

A ratio is not automatically a normalized or better outcome. Values can become
unstable when the denominator is small, and the resulting distributions may be
skewed. Inspect the underlying condition values and report the numerator,
denominator, and harmonic rule alongside any ratio.

## Inputs

Choose different condition A and condition B folders. The tool pairs
participants by the participant ID parsed from each workbook filename and lets
you manually exclude paired participants from the `USED` summaries.

Each workbook must contain:

- `BCA (uV)`;
- `SNR`; and
- `Z Score`.

The tool loads the current ROI definitions from Settings. Advanced controls set
the oddball frequency, upper summation frequency, excluded frequencies, color
palette, output DPI, and optional y-axis limits.

## Calculation

For every participant, condition, and ROI, the tool averages each selected
harmonic across the ROI electrodes and then sums those harmonic means. It uses
the configured oddball-frequency series through the upper frequency limit after
removing the configured excluded frequencies.

For each paired participant and ROI, it calculates:

- `ratio_Z = sum_Z_A / sum_Z_B`;
- `ratio_SNR = sum_SNR_A / sum_SNR_B`; and
- `ratio_BCA = sum_BCA_A / sum_BCA_B`.

If a denominator is non-finite or effectively zero, the ratio is saved as a
missing value and marked in `ratio_notes`.

## Outputs

The default project output folder is `5 - Ratio Summaries`. A run writes:

- `Metrics_<run label>.xlsx`, with parameters, exclusions, all and used
  participant sums, all and used ratios, and group summaries;
- matching `.png` and `.pdf` raincloud-style plots for the three raw summed
  metrics and the three ratios; and
- `Log_<run label>.txt`, which records the participant pairing, harmonic list,
  exclusions, and output settings.

Manual exclusions remain visible in the `ALL` tables and are omitted from the
`USED` tables and group summaries.

## Interpretation

Ratio Calculator does not run inferential statistics or establish a clinically
meaningful cutoff. Treat its output as a transparent transformation of two
condition measurements and examine the raw condition plots before interpreting
the ratio plots.

## References

- See [Methods and References](../reference/index.md) for the FPVS processing studies that inform the source metrics.
- [Ratio Calculator implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Ratio_Calculator).
