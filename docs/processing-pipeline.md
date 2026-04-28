# Processing Pipeline

Use this page when you want a practical overview of what FPVS Toolbox does after you start processing a `.bdf` file.

FPVS Toolbox turns raw BioSemi EEG recordings into Excel files that can be used by the Statistics tool. The pipeline is designed to keep the same processing order for each file so that results are reproducible across participants and conditions.

## Pipeline at a glance

```text
.bdf file
  -> load EEG and trigger channel
  -> apply preprocessing settings
  -> find events from trigger codes
  -> create epochs for each condition
  -> average epochs
  -> run FFT
  -> export Excel results
  -> run statistics
```

Alt text: A linear workflow from a raw BDF file through preprocessing, event detection, epoching, FFT, Excel export, and statistical analysis.

## What happens during processing

| Step | What FPVS Toolbox does | What you should check |
|---|---|---|
| Load data | Opens BioSemi `.bdf` files and reads the configured trigger channel. | The file is readable and the stim channel is correct. |
| Preprocess | Applies reference, filtering, downsampling, and bad-channel handling from project settings. | Settings match the method you intend to report. |
| Find events | Matches trigger codes to your condition labels. | Every expected condition has events. |
| Create epochs | Cuts the recording into time windows around events. | Warnings do not show zero usable epochs. |
| Average and FFT | Averages epochs, converts the response to frequency-domain values, and computes metrics. | Excel sheets are created for each condition. |
| Export results | Saves participant-by-condition workbooks for later statistics. | Output folders and filenames look correct. |

!!! warning "Most processing problems start with event codes"
    If a condition is missing, check the trigger code and stim channel before changing preprocessing settings.

## Project folder diagram

```text
Project root
  -> Project settings and logs
  -> 1 - Excel Data Files
       -> Condition A
            -> P1_Condition A_Results.xlsx
            -> P2_Condition A_Results.xlsx
       -> Condition B
            -> P1_Condition B_Results.xlsx
  -> 3 - Statistical Analysis Results
```

Alt text: A project root folder containing settings, logs, Excel data files organized by condition, and statistical analysis results.

## Outputs created by processing

Each participant-condition workbook usually contains these sheets:

| Sheet | Meaning |
|---|---|
| `FFT Amplitude (uV)` | Frequency-domain amplitude at target harmonics. |
| `SNR` | Signal-to-noise ratio around the target harmonic. |
| `Z Score` | Standardized response relative to local noise. |
| `BCA (uV)` | Baseline-corrected amplitude. |
| `FullSNR` | Full-spectrum SNR for plotting and inspection. |

See [Output Files](outputs-reference.md) for a fuller map of exported files.

## What to do after processing

1. Confirm each expected condition has participant Excel files.
2. Open one workbook and check that the expected sheets exist.
3. Review logs for skipped files, missing events, or zero epochs.
4. Open [Statistical Analysis Overview](statistical-analysis.md) to choose the next analysis step.
5. Use [Which Statistical Test Should I Use?](statistics/which-test.md) if you are unsure which test fits your dataset.

For manuscript wording and detailed reporting values, use [Methods Reporting Checklist](methods-reporting-checklist.md).
