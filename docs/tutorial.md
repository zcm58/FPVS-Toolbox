# First End-to-End Walkthrough

This walkthrough is designed for a first successful run.

## Goal

Take one FPVS project from raw `.bdf` files to exported statistical tables.

## Step 1: Create a project

1. Open FPVS Toolbox.
2. Select or create your Project Root.
3. Click **Create New Project**.
4. Add group names and input folders.
5. Add condition names and trigger codes.

## Step 2: Configure preprocessing

1. Open processing settings.
2. Confirm reference channels, stim channel, and filter values.
3. Confirm epoch timing values.
4. Save settings.

## Step 3: Run processing

1. Select one participant file first.
2. Start processing and inspect logs.
3. Confirm a condition export workbook is created.
4. Repeat on full batch after pilot success.

## Step 4: Check exported spectral sheets

For one participant workbook, confirm these sheets exist:

- `FFT Amplitude (uV)`
- `SNR`
- `Z Score`
- `BCA (uV)`
- `FullSNR`

## Step 5: Run statistics

1. Open **Statistical Analysis**.
2. Build or confirm ROI definitions.
3. Run harmonic selection workflow (if using Rossion method).
4. Run RM-ANOVA and mixed model.
5. Run post-hoc and baseline-vs-zero tests if needed.

## Step 6: Export and archive

1. Save all statistics tables.
2. Save flagged/excluded participant reports.
3. Archive settings and logs with outputs.

## Done checklist

- Processing completed for all intended participants.
- Expected Excel sheets exist per condition.
- Statistical output files were generated without critical errors.
- Final reports are archived with analysis settings.

## Next pages

- [Feature Tour](feature-tour.md)
- [Output Files](outputs-reference.md)
- [Troubleshooting](troubleshooting.md)
