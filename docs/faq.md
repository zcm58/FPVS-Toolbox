# FAQ

Use this page when you have a common setup, processing, output, or statistics question.

## Do I need coding experience?

No. The main workflow is designed to run through the graphical interface. You
need to know your study design, condition names, trigger codes, and where your
files are stored, but you do not need to write Python code.

## What file format can I process?

The main processing pipeline is built for BioSemi `.bdf` files. If your data are
in another format, convert or export them to a supported workflow before using
the standard processing path.

## What is a project root?

The project root is the main folder where FPVS Toolbox organizes project files
and outputs. Think of it as the home folder for your FPVS analyses.

Use a local folder such as:

```text
C:\EEG\FPVS_Projects
```

Avoid cloud-synced folders while processing.

## Why should I avoid OneDrive or other sync folders?

Sync tools can lock files, rename temporary files, or upload files while the app
is writing them. That can cause missing Excel exports, save errors, or confusing
file permission problems.

You can copy final outputs to cloud storage after processing is complete.

## What are trigger codes?

Trigger codes are numeric event markers saved in the EEG file by your task
software. The Toolbox uses them to decide which EEG segments belong to each
condition.

Example:

| Condition | Trigger code |
|---|---|
| Faces | 11 |
| Objects | 12 |
| Words | 21 |

If a trigger code is wrong, the Toolbox may report "No events found" or skip a
condition.

## What is a condition?

A condition is one category or task event you want to analyze, such as `Faces`,
`Objects`, `Semantic`, or `Color`. Conditions are linked to trigger codes in the
project event map.

## What is an ROI?

An ROI, or region of interest, is a named group of electrodes. The Statistics
tool uses ROIs to summarize responses across electrodes.

Example:

```text
LOT = P7, P9, PO7, PO3, O1
```

ROIs should match your analysis plan and should be saved with your project
outputs.

## What does Summed BCA mean?

Summed BCA is a common dependent variable used by the Statistics tool.

In plain language:

1. The Toolbox estimates the response amplitude at selected oddball harmonics.
2. It subtracts a local noise estimate around each harmonic.
3. It sums the selected harmonic responses.
4. It averages the result across electrodes in an ROI.

This gives one response value per participant, condition, and ROI.

## What are SNR and Z score?

SNR and Z score are two ways to describe how clearly the response stands out
from nearby noise.

- **SNR** compares the target frequency response to nearby noise.
- **Z score** describes how unusual the target response is relative to nearby
  noise variability.

They are useful for inspecting signal quality and detectability.

## Why am I missing condition results for a participant?

Common reasons include:

- The trigger code for that condition was not found.
- The stim channel setting is wrong.
- There were too few usable epochs after preprocessing.
- The input file was locked, unreadable, or interrupted during processing.
- The condition label or folder path contains problematic characters.

Start by checking the processing log for that participant.

## Why did RM-ANOVA fail?

RM-ANOVA expects a balanced table. In practice, that means each included
participant should have data for every required condition and ROI.

If some cells are missing, use the mixed model workflow or fix the missing data
problem before running RM-ANOVA.

## Should I use RM-ANOVA or mixed model?

Use RM-ANOVA when the dataset is balanced and you want a traditional
within-subject analysis.

Use mixed models when the dataset has some missing cells, when you want a more
flexible repeated-measures model, or when the mixed-model output better matches
your reporting plan.

## What should I check before reporting results?

Before writing results, confirm:

- Which participants were included.
- Which participants or values were flagged.
- Which values were manually excluded.
- Which harmonics were included.
- Which ROIs were used.
- Which correction method was used for post-hoc tests.
- Where the exported statistics tables are saved.

## Where are my output files?

See [Output Files](outputs-reference.md). The most common folders are:

- `1 - Excel Data Files` for processing exports.
- `3 - Statistical Analysis Results` for statistics exports.

Folder names may vary slightly depending on project setup.

## What should I save for reproducibility?

Save:

- Raw file list.
- Project settings.
- Processing logs.
- Excel outputs.
- Statistics exports.
- ROI definitions.
- Exclusion or QC reports.
- Notes about any manual decisions.

Keeping these together makes it much easier to reproduce the analysis later.
