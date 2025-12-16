# Ratio Calculator (PySide6)

The Ratio Calculator computes ROI-level SNR ratios between two conditions from already-exported per-condition Excel workbooks.

## Inputs
- **Excel root folder:** Defaults to the Stats tool's project folder at `1 - Excel Data Files` (auto-detected via the project's
  `project.json`); one subfolder per condition containing participant `.xlsx` files.
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
- Default output folder: `4 - Ratio Calculator Results` under the active project root (auto-created). You can override the folder
  and filename; `.xlsx` is appended automatically.
- Single-sheet Excel export formatted via `_auto_format_and_write_excel(...)` in a **vertical layout**:
  - Columns: Ratio Label, PID, SNR_A, SNR_B, Ratio, SigHarmonics_N, N, Mean, Median, Std, Variance, CV%, Min, Max.
  - Participant rows list each PID with its ROI summary SNRs and ratio.
  - SUMMARY rows appear after each ROI block with per-ROI statistics (blank separator row after each block).

## Skip rules and warnings
- Missing condition files for a participant.
- Missing `SNR` or `Z Score` sheets.
- ROI without matching channels in a file.
- No significant harmonics for an ROI (ratios left blank/NaN).
- Denominator summary SNR equals zero.

## Future work
- Individual-level harmonic significance selection is a planned enhancement.
