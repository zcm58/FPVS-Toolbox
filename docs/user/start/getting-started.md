# Getting Started

Use this page when you are opening FPVS Toolbox for the first time or preparing your first project.

This page is for first-time users. It explains what FPVS Toolbox needs, what it
creates, and how to get through your first run without needing to write code.

## What FPVS Toolbox does

FPVS Toolbox helps you process fast periodic visual stimulation EEG data. In a
typical workflow, it:

1. Reads BioSemi `.bdf` EEG files.
2. Detects task events from trigger codes.
3. Preprocesses and averages the EEG.
4. Converts the averaged response into frequency-domain measures.
5. Exports Excel files for each participant and condition.
6. Runs statistical analyses on those exported values.

The app is meant to make the analysis workflow easier to run and easier to
document.

## What you need before opening the app

Prepare these items first:

- Your raw BioSemi `.bdf` files.
- A list of condition names, such as `Faces`, `Objects`, or `Semantic`.
- The numeric trigger codes for each condition.
- A local folder where the Toolbox can create project files and outputs.

!!! warning "Use a local folder"
    Avoid OneDrive, Dropbox, Google Drive, and network folders for active
    processing. Sync tools can lock files while the Toolbox is trying to write
    Excel outputs.

## Recommended folder setup

Create a simple project root before you start, for example:

```text
C:\EEG\FPVS_Projects
```

Inside the app, each project will create or use its own folders for input files,
Excel outputs, logs, and statistics results.

Keep folder and condition names simple:

- Use letters, numbers, spaces, hyphens, or underscores.
- Avoid symbols like `/`, `\`, `:`, `*`, `?`, and quotes.
- Avoid very long folder paths.

## Install and open the app

1. Download the installer from the project release page.
2. Run the installer.
3. Open FPVS Toolbox.
4. Choose a project root when prompted.

If Windows or antivirus software warns you about the installer, confirm that it
came from the official project release page and follow your institution's
security policy.

## Create your first project

1. Click **Create New Project**.
2. Enter a project name.
3. Add group names if your study has groups.
4. Select the input folder containing `.bdf` files.
5. Enter each condition name and trigger code.
6. Save the project.

For a single-group study, use one group. For a group comparison study, create a
separate group for each participant group and point each group to the correct
input folder.

## Run one file first

Before processing every participant, run one file as a pilot.

Check that:

- Events are found.
- The log does not show a critical error.
- Excel files are created.
- The Excel files contain sheets such as `SNR`, `Z Score`, `BCA (uV)`, and
  `FullSNR`.

If the one-file run works, move on to the full batch. If it does not, fix the
event map, folder paths, or preprocessing settings before running more files.

## Run the full project

After the pilot file succeeds:

1. Run processing for the full set of files.
2. Watch the log for skipped files or missing conditions.
3. Confirm that each condition folder contains participant Excel files.
4. Open the Statistics tool.
5. Select the processed data folder.
6. Run the statistics workflow that matches your study design.

## What to read next

If you are new to FPVS:

- Read [FPVS Concepts for Non-Experts](fpvs-concepts.md).
- Follow [First End-to-End Walkthrough](tutorial.md).

If you already processed files:

- Use [Output Files](../study/outputs-reference.md) to understand what was exported.
- Use [Statistical Analysis Overview](../results/statistical-analysis.md) to decide which
  stats to run.
- Use [Troubleshooting](../study/troubleshooting.md) if a file or condition is missing.
