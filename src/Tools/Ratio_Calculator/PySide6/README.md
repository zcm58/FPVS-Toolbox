# Ratio Calculator (PySide6)

The Ratio Calculator computes ROI-level SNR ratios between two conditions from already-exported per-condition Excel workbooks.

## Inputs
- **Excel root folder:** One subfolder per condition containing participant `.xlsx` files.
- **Conditions:** Discovered via `scan_folder_simple` using `EXCEL_PID_REGEX` for participant IDs.
- **ROIs:** Loaded from `resolve_active_rois()`; channel membership follows Stats ROI settings.
- **Sheets used:** `SNR` and `Z Score` with an `Electrode` column plus frequency columns named `{freq:.4f}_Hz`.

## Computation
1. **Significant harmonics (group level, per ROI):**
   - For each participant with both conditions, compute ROI-mean Z-scores per harmonic by averaging rows where `Electrode` matches the ROI channels (case-insensitive).
   - Take the group mean across participants for each harmonic.
   - Harmonics with mean Z > 1.64 (default threshold) are considered significant.
2. **Summary SNR (per participant & ROI):** Mean SNR across the significant harmonics for each condition.
3. **Ratio:** `summary_SNR_A / summary_SNR_B`.

## Output
- Single-sheet Excel export formatted via `_auto_format_and_write_excel(...)` with rows labeled `{ConditionA} to {ConditionB} - {ROI}`.
- Participant columns contain per-ROI ratios; summary columns include N, Mean, Median, Std, Variance, CV%, Min, and Max (CV% = (Std / Mean) * 100 when Mean ≠ 0).

## Skip rules and warnings
- Missing condition files for a participant.
- Missing `SNR` or `Z Score` sheets.
- ROI without matching channels in a file.
- No significant harmonics for an ROI (ratios left blank/NaN).
- Denominator summary SNR equals zero.

## Future work
- Individual-level harmonic significance selection is a planned enhancement.
