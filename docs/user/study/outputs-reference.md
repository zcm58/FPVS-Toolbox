# Output Files

Use this page when you need to find, check, or interpret FPVS Toolbox output files.

This page maps the main result files to the workflow steps that create them.

## Default result folders

- `1 - Excel Data Files`: per-condition, per-participant spectral exports from processing.
- `3 - Statistical Analysis Results`: inferential tables, QC flags, and exclusion reports.

Your exact folder names may vary by project setup, but the file types below are expected.

## Processing outputs (Excel)

Each condition folder typically contains participant files like `PID_<Condition>_Results.xlsx` with sheets such as:

- `FFT Amplitude (uV)`
- `SNR`
- `Z Score`
- `BCA (uV)`
- `FullSNR`

## Statistical outputs

Common statistical exports include:

- RM-ANOVA tables
- Mixed model fixed-effects tables
- Post-hoc pairwise test tables with raw and adjusted p-values
- Baseline vs Zero test workbook
- Summed BCA DV definition workbook (Rossion workflow)
- Flagged participants and excluded participants reports

## Quick checks when reviewing outputs

1. Confirm each expected condition has a folder and participant files.
2. Confirm sheet names exist in each Excel file.
3. Confirm statistical tables include effect, df, test statistic, p-value, and corrected p-value where relevant.
4. Archive the project settings and logs with exported files for reproducibility.
