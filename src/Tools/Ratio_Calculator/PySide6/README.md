# Ratio Calculator (PySide6)

## Purpose
The Ratio Calculator compares two experimental conditions (Condition A vs Condition B) for each ROI and participant. It computes summary metrics per condition and then reports a ratio:

- **Ratio** = SummaryA / SummaryB
- **LogRatio** = ln(Ratio)
- **RatioPercent** = (exp(LogRatio) - 1) × 100

A ratio above 1 (or LogRatio above 0) indicates Condition A is higher than Condition B. A ratio below 1 (or LogRatio below 0) indicates Condition A is lower than Condition B.

## Inputs
The tool expects a folder containing per-participant Excel workbooks with the following sheets:

- **Z Score**
- **SNR**
- **BCA (uV)**

Each sheet must include an `Electrode` column and frequency columns named like `X.XXXX_Hz` (e.g., `1.2000_Hz`).

## ROI handling
ROIs are defined by channel lists. For each ROI, the tool:

1. Selects rows in the sheet where `Electrode` matches the ROI channel list.
2. Averages those channels per frequency to build an ROI-level spectrum.

## Significant harmonics
Significant harmonics are computed separately for Condition A and Condition B using Z-scores.

- **Group mode**: the Z-score is averaged across participants per ROI. Frequencies above the Z threshold are significant.
- **Individual mode**: significant frequencies are computed per participant and then merged for the ROI.
- **Minimum K rule**: an ROI must have at least `K` significant harmonics **in both conditions**. If either condition fails the threshold, ratios are skipped for that ROI/participant.

## SummaryA / SummaryB
Summary values depend on the selected metric:

- **SNR**: mean across the selected harmonics.
- **BCA**: sum across the selected harmonics.
  - **Strict** mode rejects nonpositive BCA (<= 0).
  - **Rectify** mode clips negative values to 0 before summing.

Significant harmonics are chosen separately for each condition, so SummaryA and SummaryB may use different harmonic sets.

## Ratio metrics and inclusion rules
Computed per participant/ROI when possible:

- **Ratio** = SummaryA / SummaryB
- **LogRatio** = ln(Ratio) (only if Ratio > 0 and both summaries are positive)
- **RatioPercent** = (exp(LogRatio) - 1) × 100

Exclusions occur when:

- A required sheet or channel data is missing.
- SummaryB is 0 (denominator is zero).
- BCA is nonpositive and strict mode is selected.
- Denominator floor excludes the participant (see below).
- Outlier exclusion is enabled (see below).

## Outlier detection
Outlier detection can flag or exclude participants on a per-ROI basis.

- **MAD**: robust z-scores using median absolute deviation.
- **IQR**: values outside `Q1 - k*IQR` or `Q3 + k*IQR` are flagged.

When `exclude` is selected, flagged participants are removed from summary statistics.

## Denominator floor
A floor can be applied to SummaryB values to prevent unstable ratios:

- **Absolute**: a fixed minimum SummaryB.
- **Quantile**: the `q` quantile of eligible SummaryB values.

Scope options:

- **Per-ROI**: each ROI uses its own floor.
- **Global**: all ROIs share a floor.

Reference groups:

- A JSON file at `excel_root/ratio_calculator_reference_groups.json` can define PID lists for reference groups.
- If a reference key is supplied, only those PIDs contribute to the quantile floor.

## Summary statistics
Summary rows are reported per ROI:

- **Mean / Variance / Std / Median / Min / Max** are computed on the selected summary metric scale (Ratio or LogRatio).
- **CV%** is percent coefficient of variation (geometric CV when LogRatio is selected).
- **MeanRatio_fromLog / MedianRatio_fromLog** are exp-transformed summaries of log ratios.
- **Trimmed** stats drop the min and max values (when at least 3 values exist).

## Confidence intervals
For each ROI summary (untrimmed only):

- A bootstrap percentile 95% CI is computed for the **mean** of the selected summary metric.
- If the summary metric is **LogRatio**, a **GMR CI** is computed by exponentiating the log-mean CI.
- Trimmed summary rows do **not** include CIs (values are left blank).

## Outputs
The output Excel file includes participant rows plus:

- **SUMMARY**: untrimmed summary statistics and confidence intervals.
- **SUMMARY_TRIMMED**: trimmed statistics (no confidence intervals).

Use the output columns `Mean_CI_low`, `Mean_CI_high`, `GMR_CI_low`, and `GMR_CI_high` to interpret the confidence intervals.
