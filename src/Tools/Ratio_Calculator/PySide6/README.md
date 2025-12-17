# Ratio Calculator (PySide6)

The Ratio Calculator computes ROI-level SNR ratios between two conditions from already-exported per-condition Excel workbooks.

## Inputs
- **Excel root folder:** Defaults to the Stats tool's project folder at `1 - Excel Data Files` (auto-detected via the project's
  `project.json`); one subfolder per condition containing participant `.xlsx` files.
- **Conditions:** Discovered via `scan_folder_simple` using `EXCEL_PID_REGEX` for participant IDs.
- **ROIs:** Loaded only from ROI pairs defined in **Settings**; channel membership follows the saved Stats ROI settings. Defaults (Frontal/Parietal/Central/Occipital) are not added automatically.
- **Sheets used:** `SNR` and `Z Score` with an `Electrode` column plus frequency columns named `{freq:.4f}_Hz`.

## Metrics and stability rules
1. **Significance mode (Advanced → Significance mode):**
   - **Group-level (default/recommended):**
     - For each ROI, compute mean Z-scores per harmonic across participants (Condition A only).
     - Harmonics with mean Z > 1.64 (default threshold) are significant for all participants in that ROI.
   - **Per-participant (experimental):**
     - For each participant and ROI, compute mean Z-scores per harmonic across ROI channels (Condition A only).
     - Each participant uses their own significant harmonics set (Z > 1.64).
2. **Minimum significant harmonics (K):**
   - Advanced setting default **K = 3** (range 1–50).
   - If the significant set for an ROI/participant is smaller than K, the ROI is considered unstable: participant rows are skipped from summary stats and the SUMMARY row records the skip reason with `N_used = 0`.
3. **Summary metric (Advanced → Summary metric):**
   - Default: **LogRatio**. Ratio is still exported, but summary statistics (mean/median/std/variance/CV%) are computed on LogRatio for symmetry and skew reduction.
   - Optional: **Ratio** if you prefer raw ratios for the summary calculations.
   - Derived fields always exported when valid:
     - **SummaryA**, **SummaryB** (metric-specific aggregates)
     - **Ratio = SummaryA / SummaryB**
     - **LogRatio = ln(Ratio)** when SummaryA > 0 and SummaryB > 0
     - **RatioPercent = (exp(LogRatio) - 1) * 100**
4. **Metric modes (SNR vs BCA):**
   - **Default:** SNR (mean across harmonics).
   - **BCA (uV):** Sum across harmonics; negative handling (shown only in BCA mode):
     - **Strict (default):** If either summed BCA ≤ 0, the row is skipped.
     - **Rectify negatives to 0:** Negative harmonic values are clamped to 0 before summing; ratios are still skipped if the denominator remains 0.
5. **Denominator stability floor (Advanced → Denominator stability):**
   - Optional checkbox (off by default).
   - **Norm-referenced (quantile, default mode when enabled):**
     - Reference group: current dataset (young controls placeholder).
     - Quantile default **0.05** (range 0.01–0.25).
     - Scope: **Per ROI (default)** or **Global** across ROIs.
     - If SummaryB < floor value → Ratio/LogRatio invalid, `SkipReason = denom_below_floor`, row excluded from summaries.
   - **Absolute value:** Uses a user-supplied floor when provided.
6. **Outlier detection (Advanced → Outlier detection):**
   - Disabled by default; requires ≥5 base-valid rows.
   - **Methods:** MAD (robust z, default) or IQR; thresholds default to 3.5 (MAD) / 1.5 (IQR).
   - **Metric:** Summary metric (default), Ratio, or LogRatio.
   - **Actions:** Flag only (default) or **Exclude from analysis and summary**; excluded rows remain in the export with `ExcludedAsOutlier=True` and are removed from quantile floor calculations and summary stats.

## Output
- Default output folder: `4 - Ratio Calculator Results` under the active project root (auto-created). You can override the folder and filename; `.xlsx` is appended automatically.
- Single-sheet Excel export formatted via `_auto_format_and_write_excel(...)` in a **vertical layout**:
  - Columns: Ratio Label, PID, **metric-specific Summary columns** (`SNR_A`/`SNR_B` or `BCA_A`/`BCA_B`), SummaryA, SummaryB, Ratio, LogRatio, RatioPercent, MetricUsed, SkipReason, IncludedInSummary, OutlierFlag, OutlierMethod, OutlierScore, ExcludedAsOutlier, SigHarmonics_N, DenomFloor, N_detected, N_base_valid, N_outliers_excluded, N_floor_excluded, N_used, N, N_used_untrimmed, N_used_trimmed, N_trimmed_excluded, Mean, Median, Std, Variance, CV%, MeanRatio_fromLog, MedianRatio_fromLog, Min, Max, MinRatio, MaxRatio, Mean_trim, Median_trim, Std_trim, Variance_trim, gCV%_trim, MeanRatio_fromLog_trim, MedianRatio_fromLog_trim, MinRatio_trim, MaxRatio_trim.
  - Participant rows list each PID with ROI summaries for the chosen metric (`SummaryA`/`SummaryB`) alongside metric-specific columns and QC flags.
  - SUMMARY rows appear after each ROI block with per-ROI statistics and QC counts; **SUMMARY_TRIMMED** rows follow immediately and exclude the single highest and lowest LogRatio before recomputing stats.
  - Outliers (if enabled) are flagged per participant; exclusions are tracked separately from skip reasons and surfaced in the post-run summary dialog.

## Skip rules and warnings
- Missing condition files for a participant.
- Missing `SNR` or `Z Score` sheets.
- ROI without matching channels in a file.
- Insufficient significant harmonics (SigHarmonics_N < K) for an ROI.
- Denominator summary equals zero or falls below the stability floor.
- Non-positive summed BCA when using strict negative handling.
