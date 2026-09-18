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
history. The next processing run rechecks eligible files and recomputes from raw
data; once that run starts, its normal output step replaces the participant
outputs being recomputed. Windows may still retain its own filesystem cache,
which this action does not control.

### Dataset Exclusions

Open **Settings > Advanced > Processing QC > Manage Dataset Exclusions…** to
manage participant and recording exclusions in one list. The table shows
whether processed data is available and distinguishes three choices:

- **Included** removes the selected participant's or recording's whole-scope
  processing and analysis exclusions.
- **Skip processing entirely** leaves that participant or recording out of
  EEG processing. Raw files and existing results remain on disk.
- **Exclude from analysis after processing** preserves the processed data but
  excludes it from downstream analysis. This choice requires existing processed
  data; use the processing scope for an entry that has not been processed.

Select a row to change its scope or reason. Select multiple rows to apply one
scope to them, or choose **Include all participants and recordings** to stage
restoration across the entire list, including rows hidden by the search.
**Apply** saves these changes immediately; **Cancel** discards pending changes.
An older project with overlapping exclusions shows both until you choose a
scope explicitly.

Participant-wide exclusions also affect that participant's recordings. A
recording-specific choice does not override a participant-wide exclusion;
restore the participant row as well when needed. Condition-specific decisions
remain visible in the selected row's details and are not cleared by this
whole-participant/recording manager.

Restored processing exclusions are reconsidered on the next **Start Processing**
without a cache reset. Changed analysis choices require regenerated downstream
outputs; resume post-processing to rebuild them. Clearing caches continues to
preserve saved exclusions.

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

### Repeated-Session Project Setup

When creating a project, choose **Repeated sessions / visits**, enter the
stable between-participant groups, then enter session labels in visit order.
Select one raw source folder for every group x session cell. If the named
project folder already contains raw data but has no `project.json`, the GUI can
create the project in place after confirmation; existing files are preserved.

When BDFs already exist, setup performs a read-only identity preflight before
writing the manifest. Cross-session group changes, duplicate
participant/session files, nested BDFs, and partially empty group/session cells
block creation. Missing visits for individual participants are shown as
warnings and retained. The preflight does not open BDF signal contents and does
not infer group or session membership from generated output folders.

### Adding Recordings After Processing

Place new BDF files directly in the project's configured raw source folders,
then start **Processing**. The **Add BDF Files** popup shows each new file's
participant, group and session/visit from those folders. Choose **Add Files and
Continue** to save the additions and continue through the normal QC workflow.
**Cancel** leaves the registry unchanged and stops processing.

The lock protects existing assignments; it permits confirmed additions without
requiring equal participant counts or complete visits. Conflicting group
assignments and duplicate participant/visit files still need correction.
Opening a project alone does not register new files or prevent analysis of its
existing valid results. Once additions are confirmed, finish Processing before
resuming post-processing or using the expanded dataset in analysis.

### Repeated-Session Processing QC

Repeated-session projects keep participant identity and recording identity
separate. The QC screens show the participant, recording, session or
phase-at-visit label, visit index, and group for every available recording.
A declared visit with no registered recording is shown as missing coverage; the
Toolbox does not create or impute a visit.

Participant-wide exclusions apply to every visit. Use the single-recording
scope when only one visit should be excluded, and use recording-condition scope
when only one condition from one visit should be omitted downstream. Removed
electrodes can likewise be saved per recording; the participant-level list is a
legacy fallback for recordings without an explicit override.

The session label and visit index describe different facts. For example,
"Luteal" can be the phase-at-visit label while `visit_index = 1` records when
that visit occurred. If every participant is tested in the same phase order,
phase and order or time effects are confounded; the QC metadata preserves this
fact but cannot statistically separate those effects.

### Data Compatibility

The currently validated workflow targets BioSemi ActiveTwo 64-channel BDF
recordings with the MNE BioSemi64 sensor geometry. **Settings >
Preprocessing > Electrode montage** therefore shows one fixed choice: **BioSemi
ActiveTwo 64**. Other recording systems, file formats, channel layouts, and
custom montages are not supported by the current processing path.

The default channel mapping expects the 64 anatomical electrode names. If a
BDF instead uses A1-A32/B1-B32, select the mapping profile only when the file
came from the standard BioSemi 64-channel 10/20 wiring. That profile does not
support BioSemi ABC/equiradial or custom cap layouts. The Toolbox checks the
complete header before preflight or processing and stops with a clear error for
missing, duplicate, mixed, or unsupported channel identities. It does not
guess positions from channel order.

The geometry check is separate from signal-quality QC. A physically removed or
disconnected electrode can still have a valid channel name in the BDF, so it
may pass the header check and then be flagged from its recorded signal. CMS and
DRL are part of the BioSemi acquisition loop and should not appear as recorded
scalp/data channels; selected EXG mastoid signals remain reference channels.
See BioSemi's
[headcap documentation](https://www.biosemi.com/headcap.htm) and
[CMS/DRL explanation](https://www.biosemi.com/faq/cms%26drl.htm).

Projects processed by older Toolbox builds may contain outputs made with the
generic `standard_1005` coordinates. Reprocess before new analysis or
publication when those recordings used interpolation or a geometry-based
channel decision, and do not combine them with current BioSemi64 outputs.
Scalp maps should be regenerated even when no interpolation occurred because
the plotted sensor positions changed. The current synthetic comparison shows
that interpolation can also change FFT/BCA/SNR/local-z values near a decision
boundary, but it does not estimate the effect in representative lab data.

### Experiment Assumptions

FPVS Toolbox assumes trigger codes are defined on a per-condition basis before analysis, typically in
PsychoPy or FPVS Studio.

When creating a project, the condition settings in FPVS Toolbox should match the trigger codes used during
data collection.

## Tool Pages

The **Workspace Tools** section of the app sidebar shows these default tools:
Free Harmonic Clustering Analysis and SNR Plots.

Scalp Maps, Standard FPVS Screening, Sensitivity Analysis, LORETA Visualizer,
Sequence Figure, Ratio Calculator, and Individual Detectability are beta tools.
To show their separate **Beta Tools** sidebar subsection, open
**Settings > Advanced**, enable **Beta Tools**, then close and reopen FPVS
Toolbox. Before each beta tool opens for the first time in an app session, the
Toolbox warns that the tool is in beta and its features may change.

See the following sections for more information regarding each tool provided in FPVS Toolbox.

- [Free Harmonic Clustering Analysis](tools/free-harmonic-clustering.md)
- [SNR Plots](tools/snr-plot-generator.md)
- [Scalp Maps](tools/publication-maps.md)
- [Standard FPVS Screening](tools/statistics.md)
- [Sensitivity Analysis](tools/sensitivity-analysis.md)
- [LORETA Visualizer](tools/loreta-visualizer.md)
- [Sequence Figure](tools/sequence-figure.md)
- [Ratio Calculator](tools/ratio-calculator.md)
- [Individual Detectability](tools/individual-level-detectability.md)
