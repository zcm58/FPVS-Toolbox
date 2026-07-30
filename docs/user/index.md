# FPVS Toolbox Documentation

This site explains the active FPVS Toolbox workflow, its built-in tools, and the
published methods that inform the application.

## Key Features and Assumptions

### FPVS Toolbox Project Root

FPVS Toolbox organizes work under a project root. Each project has its own
subfolder containing the project manifest, source-data location, processed
workbooks, quality-control records, statistical outputs, and figures.

To benchmark or troubleshoot data-quality and raw preprocessing without reusing
their FPVS-managed caches, choose **File > Reset Project Processing Cache...**.
This clears cached data-quality results, cached preprocessed EEG data, and the
incremental completion index for the active project. It does not delete raw BDF
files, project settings, manual QC choices, current outputs, or processing run
history. The next processing run rechecks every file and recomputes from raw
data; once that run starts, its normal output step replaces the participant
outputs being recomputed. Windows may still retain its own filesystem cache,
which this action does not control.

### Multi-Group Projects

When creating a project with two or more experimental groups, select one raw
`.bdf` folder for each group. Batch mode is the default and processes every
registered group folder in one run. Processed workbooks are organized by
condition and then group.

Group definitions are strict so partial projects are not processed silently.
Missing group folders, missing registered participant files, duplicate
participant IDs, or invalid group output-folder names stop processing with an
error that identifies what must be repaired. After the first grouped workbook
is produced—even if another condition or participant is later interrupted—the
group-folder layout is locked and fingerprinted. Restore a missing registered
folder or create a new project if the group design itself must change.

### Data Compatibility

The currently validated workflow targets BioSemi ActiveTwo 64-channel BDF
recordings using the standard BioSemi64 electrode names. Other recording
systems, file formats, channel layouts, or custom montages have not been
validated and may fail or produce incomplete analyses or figures.

### Experiment Assumptions

FPVS Toolbox assumes trigger codes are defined on a per-condition basis before analysis, typically in
PsychoPy or FPVS Studio.

When creating a project, the condition settings in FPVS Toolbox should match the trigger codes used during
data collection.

## Tool Pages

The **Workspace Tools** section of the app sidebar shows these default tools:
Standard FPVS Screening, Sensitivity Analysis, SNR Plots, Scalp Maps, LORETA
Visualizer, and Sequence Figure.

Ratio Calculator, Individual Detectability, and Epoch Averaging are beta tools.
To show them, open **Settings > Advanced**, enable **Beta Tools**, then close
and reopen FPVS Toolbox.

See the following sections for more information regarding each tool provided in FPVS Toolbox.

- [Standard FPVS Screening](tools/statistics.md)
- [Sensitivity Analysis](tools/sensitivity-analysis.md)
- [SNR Plots](tools/snr-plot-generator.md)
- [Scalp Maps](tools/publication-maps.md)
- [LORETA Visualizer](tools/loreta-visualizer.md)
- [Sequence Figure](tools/sequence-figure.md)
- [Ratio Calculator](tools/ratio-calculator.md)
- [Individual Detectability](tools/individual-level-detectability.md)
- [Epoch Averaging](tools/epoch-averaging.md)
