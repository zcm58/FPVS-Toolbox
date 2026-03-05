# Getting Started

This page is for first-time users who want a clear path from installation to first results.

## Before you begin

- OS: Windows.
- Input data: BioSemi `.bdf` recordings.
- Experiment support: FPVS paradigms run with PsychoPy event codes.

!!! warning "Recommended project folder"
    Use a local folder path (for example `C:\EEG\FPVS_Projects`) instead of cloud-synced folders like OneDrive.

## Step 1: Install the app

1. Download the latest installer from the GitHub Releases page.
2. Run the installer.
3. Open FPVS Toolbox.
4. Select a **Project Root** folder when prompted.

## Step 2: Create a project

1. Click **Create New Project**.
2. Enter a project name.
3. Set the number of groups and group names.
4. Select each group's input folder containing `.bdf` files.
5. Enter condition names and matching trigger codes from your PsychoPy task.

## Step 3: Process EEG files

1. Open the processing view.
2. Select one file (or a batch folder).
3. Confirm preprocessing settings (reference, filters, downsample rate, rejection settings).
4. Start processing.

After processing, results are exported to Excel files for each condition.

## Step 4: Run statistics

1. Open **Statistical Analysis**.
2. Select your dependent variable workflow (typically Summed BCA).
3. Run RM-ANOVA, mixed model, and post-hoc tests as needed.
4. Export tables for reporting.

## Step 5: Verify outputs

Use [Output Files](outputs-reference.md) to check the expected folders and files.

## Next pages

- [FPVS Concepts for Non-Experts](fpvs-concepts.md)
- [Feature Tour](feature-tour.md)
- [First End-to-End Walkthrough](tutorial.md)
