# Ratio Calculator (PySide6)

The Ratio Calculator computes ROI-level SNR ratios between two conditions from already-exported per-condition Excel workbooks.

## Inputs
- **Excel root folder:** Defaults to the Stats tool's project folder at `1 - Excel Data Files` (auto-detected via the project's
  `project.json`); one subfolder per condition containing participant `.xlsx` files.
- **Conditions:** Discovered via `scan_folder_simple` using `EXCEL_PID_REGEX` for participant IDs.
- **ROIs:** Loaded only from ROI pairs defined in **Settings**; channel membership follows the saved Stats ROI settings. Defaults (Frontal/Parietal/Central/Occipital) are not added automatically.
- **Sheets used:** `SNR` and `Z Score` with an `Electrode` column plus frequency columns named `{freq:.4f}_Hz`.

## Computation
1. **Significance mode (Advanced → Significance mode):**
   - **Group-level (default/recommended):**
     - For each ROI, compute mean Z-scores per harmonic across participants (Condition A only).
     - Harmonics with mean Z > 1.64 (default threshold) are significant for all participants in that ROI.
   - **Per-participant (experimental):**
     - For each participant and ROI, compute mean Z-scores per harmonic across ROI channels (Condition A only).
     - Each participant uses their own significant harmonics set (Z > 1.64).
2. **Summary metric (per participant & ROI):**
   - **SNR (default metric):** Mean SNR across the significant harmonics for each condition (group shared set or participant-specific set depending on the mode).
   - **BCA (uV):** Sum of ROI-mean BCA across the significant harmonics for each condition using the `BCA (uV)` sheet and the same frequency columns as SNR.
3. **Ratio:** `summary_A / summary_B` using the selected metric.

## Metric modes (SNR vs BCA)
- **Default:** SNR with the existing behavior preserved.
- **Metric dropdown:** Choose between SNR and BCA without affecting other defaults (significance remains group-level unless changed).
- **BCA negative handling (Advanced, shown only in BCA mode):**
  - **Strict (default):** If either condition’s summed BCA ≤ 0, the ratio is skipped (row retained with `SkipReason`).
  - **Rectify negatives to 0:** Negative ROI-mean BCA values per harmonic are clamped to 0 before summing; ratios are skipped if the denominator remains 0.

## Outlier detection (Advanced, optional)
- Disabled by default; enabling toggles per-ROI detection on computed ratios (requires ≥5 valid ratios).
- **Methods:**
  - **MAD (robust z, default when enabled):** `robust_z = 0.6745 * (x - median) / MAD`; if MAD is 0, robust z-scores are treated as 0.
  - **IQR:** Flags ratios below `Q1 - k*IQR` or above `Q3 + k*IQR` (k = threshold).
- **Threshold defaults:** MAD = 3.5; IQR multiplier = 1.5.
- **Actions:**
  - **Flag only (default):** Outliers are marked but still included in summary stats.
  - **Exclude from summary stats:** Outliers remain in participant rows but are omitted from summary aggregates.

## Output
- Default output folder: `4 - Ratio Calculator Results` under the active project root (auto-created). You can override the folder
  and filename; `.xlsx` is appended automatically.
- Single-sheet Excel export formatted via `_auto_format_and_write_excel(...)` in a **vertical layout**:
  - Columns: Ratio Label, PID, SNR_A, SNR_B, SummaryA, SummaryB, Ratio, MetricUsed, SkipReason, OutlierFlag, OutlierMethod, OutlierScore, SigHarmonics_N, N, Mean, Median, Std, Variance, CV%, Min, Max.
  - Participant rows list each PID with ROI summaries for the chosen metric (`SummaryA`/`SummaryB`) alongside legacy SNR columns. `SigHarmonics_N` reflects the count of significant harmonics actually used for that participant (group mode uses the shared ROI count).
  - SUMMARY rows appear after each ROI block with per-ROI statistics (blank separator row after each block).
  - Outliers (if enabled) are flagged per participant, and summary stats optionally exclude them depending on the selected action.

## Skip rules and warnings
- Missing condition files for a participant.
- Missing `SNR` or `Z Score` sheets.
- ROI without matching channels in a file.
- No significant harmonics for an ROI (ratios left blank/NaN).
- Denominator summary equals zero.
- Non-positive summed BCA when using strict negative handling.
