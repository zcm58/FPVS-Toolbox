# Processing quick start

This workflow uses BioSemi ActiveTwo 64-channel BDF recordings. Review
[data compatibility](index.md#data-compatibility) before starting. Existing
v2.1.2 projects should follow the [migration guide](migration-v3.md) first.

## 1. Create or open a project

Choose **File > New Project…**, then **Create Manually** or **Import FPVS Studio
Config**. Choose the project location and register the raw recording folders.
For multiple groups, assign each group its own source folder. For repeated
sessions, use **Repeated sessions / visits** and provide every group-by-session
folder. Keep project data outside the Toolbox installation directory.

To continue an existing project, use **File > Open Existing Project…**.
Opening a project does not register newly added recordings automatically;
Processing asks you to confirm additions before continuing.

## 2. Verify settings against the experiment

Open **Settings** and check:

- **Preprocessing:** references, filter/downsampling choices, retained channels
  and BioSemi64 label mapping.
- **Protocol:** presentation rate, oddball rule, analyzed duration and condition
  markers. Confirm recording-specific trigger assignments if acquisition codes
  changed during the study. For differing condition-onset codes or reused source
  participant IDs, follow the [source trigger map guide](reference/source-trigger-maps.md).
- **Harmonics:** the profile and search/domain limits that define Summed BCA.
  New projects use the two-consecutive-failures profile; existing legacy
  projects keep their earlier profile.
- **ROIs:** electrode membership needed by the planned plots and analyses.
- **Experimental:** optional QC screens. These start off in new projects;
  required input-validity checks still run.

Choose **Save**. Settings edits across tabs share this Save action.

## 3. Process and review

Choose **Start Processing**. Check any requested new-recording registrations,
trigger evidence, channel decisions and enabled QC findings. Use the review
dialogs to record justified decisions; consult the
[QC guide](reference/preprocessing-qc-review.md) when a finding is unclear.
Canceling allows investigation without inventing missing data or marker times.

Wait for processing and post-processing to finish. If the app offers **Resume
Post-processing**, use it to complete the remaining downstream stages after
resolving the reported issue. A missing condition output requires the specific
repair or explicit exclusion in the
[missing-condition guide](reference/missing-condition-outputs.md).

## 4. Inspect and export

Use **SNR Plots** for condition/group spectra and **Free Harmonic Clustering**
for a supported planned electrode-by-harmonic contrast. Their
[tool guides](tools/index.md) specify inputs, design restrictions and outputs.
Use long/wide exports for study-specific statistical models outside the Toolbox.

Retain the project settings, QC decisions and harmonic-selection summary with
the results. Keep each condition workbook together with its spectral and metric
companions when moving or backing up the project. See
[spectral data files](reference/spectral-data-files.md).

If settings or exclusions change, complete the indicated processing,
post-processing or harmonic rebuild before making new figures or analyses.
