# First End-to-End Walkthrough

This walkthrough is for a first successful FPVS Toolbox run. It assumes you are
not an EEG analysis expert and want a practical path from raw files to results
you can inspect.

The goal is not to make every final analysis decision on the first pass. The
goal is to confirm that the project is set up correctly, events are detected,
Excel outputs are created, and the Statistics tool can read those outputs.

## Before you start

You need:

- A folder of BioSemi `.bdf` files.
- The condition names from your experiment.
- The trigger/event codes used by your PsychoPy task.
- A local project folder, preferably outside OneDrive or other sync folders.

!!! tip "Start with one participant"
    Run one file first. A single-file pilot is the fastest way to catch event
    code mistakes, bad folder choices, or preprocessing settings that need
    adjustment.

## Step 1: Choose a project root

When FPVS Toolbox asks for a project root, choose a local folder where the app
can create and update project files.

Good examples:

- `C:\EEG\FPVS_Projects`
- `D:\FPVS_Projects`

Avoid:

- OneDrive, Dropbox, Google Drive, or network sync folders.
- Folders where you do not have write permission.
- Deep folder paths with many special characters.

The project root is the main place where the Toolbox will store project
settings and organize output folders.

## Step 2: Create a project

1. Open FPVS Toolbox.
2. Click **Create New Project**.
3. Enter a short project name.
4. Add the group names for your study.
5. Select each group's input folder containing `.bdf` files.
6. Enter condition labels and their trigger codes.
7. Save the project.

Use condition names that are easy to read later, such as `Faces`, `Objects`, or
`Semantic`. Avoid symbols that Windows does not allow in folder names, such as
`/`, `\`, `:`, `*`, `?`, and quotes.

## Step 3: Confirm event codes

Before processing the full dataset, make sure the event map matches the task.

Check:

- Each condition has the correct numeric trigger code.
- Trigger codes are unique unless your experiment intentionally reuses them.
- The stimulus channel matches the channel used in the recording.
- The condition labels are spelled the way you want them to appear in output
  folders and Excel files.

If the Toolbox later says "No events found," the most common cause is a mismatch
between the trigger code in the project and the trigger code in the `.bdf` file.

## Step 4: Review preprocessing settings

Open the processing settings and confirm the values before running.

Important settings:

- Reference channels: the electrodes used for the initial reference.
- Stim channel: the channel that contains event triggers.
- Filter settings: high-pass and low-pass values.
- Downsampling: optional, used to reduce file size and processing time.
- Epoch window: the time window around each event that will be averaged.
- Bad-channel handling: thresholds for detecting unstable channels.

!!! note "Do not optimize everything on the first run"
    For the first pass, use sensible default settings and check whether the
    pipeline completes. Fine-tune thresholds only after you know the project and
    event map are correct.

## Step 5: Process one file

1. Select one participant `.bdf` file.
2. Start processing.
3. Watch the log for warnings or errors.
4. Wait for the run to finish.
5. Open the output folder and confirm that Excel files were created.

For each condition, you should see a participant results workbook. The exact
file name depends on the participant and condition label.

Open one workbook and confirm these sheets exist:

- `FFT Amplitude (uV)`
- `SNR`
- `Z Score`
- `BCA (uV)`
- `FullSNR`

If those sheets are present, the main processing path is working.

## Step 6: Process the full batch

After the one-file pilot succeeds:

1. Select the batch or project processing option.
2. Run the remaining files.
3. Keep the app open until processing finishes.
4. Review the log for skipped files, missing events, or files with no valid
   epochs.
5. Confirm each expected condition has participant Excel outputs.

If a participant is missing for one condition, check the log before rerunning.
The usual causes are missing triggers, too few valid epochs, or an unreadable
input file.

## Step 7: Open the Statistics tool

After processing, open **Statistical Analysis**.

Start with these checks:

- The data folder points to the Excel output folder.
- ROI definitions are present.
- Conditions are detected correctly.
- Participant IDs look correct.

For a first pass, run analyses in this order:

1. Harmonic selection, if you are using the Rossion-style summed harmonic
   workflow.
2. RM-ANOVA, if your dataset is balanced across participants, conditions, and
   ROIs.
3. Mixed model, especially if some cells are missing.
4. Post-hoc tests, when you need specific pairwise comparisons.
5. Baseline vs Zero tests, when you want to ask whether a condition response is
   detectably above local noise.

## Step 8: Review statistics outputs

Statistics results are saved in the statistical analysis results folder.

Look for:

- RM-ANOVA tables.
- Mixed model results.
- Post-hoc comparison tables.
- Baseline vs Zero workbooks.
- Flagged participant reports.
- Excluded participant reports.
- Logs or summary text explaining significant effects.

Do not rely only on whether a p-value is significant. Also check which
participants and conditions were included, whether any values were flagged, and
whether the result matches the pattern you expected from the data.

## Step 9: Archive the run

For reproducibility, save these together:

- The project folder.
- The processing logs.
- The project settings.
- The Excel outputs.
- The statistics outputs.
- Any notes about excluded participants or changed settings.

This makes it much easier to explain exactly what was done later in a thesis,
manuscript, or lab meeting.

## Done checklist

Your first complete run is successful when:

- At least one `.bdf` file processed without a critical error.
- Condition-specific Excel files were created.
- Expected Excel sheets are present.
- The Statistics tool detects the processed data.
- At least one statistical export is created.
- Logs and settings are saved with the outputs.

## If something fails

Use this quick triage:

| Problem | First thing to check |
|---|---|
| No events found | Trigger codes and stim channel |
| No Excel file created | Processing log and output folder permissions |
| Missing condition | Event code for that condition |
| Statistics tool cannot find data | Selected data folder |
| RM-ANOVA fails | Missing participant x condition x ROI cells |
| Results look surprising | ROI definitions, exclusions, and included participants |

Next pages:

- [Output Files](outputs-reference.md)
- [Troubleshooting](troubleshooting.md)
- [Statistical Analysis Overview](statistical-analysis.md)
