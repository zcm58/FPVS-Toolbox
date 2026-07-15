# Project I/O Architecture

Project-aware workflows should resolve paths from the active project root, not from the process current directory or a developer-machine path.

Primary paths:

- `src/Main_App/projects/` is the canonical active import surface for project
  model, metadata, manager, projects-root, and preprocessing-settings behavior.
  It owns those implementations.
- `src/Main_App/Shared/settings_paths.py`
- tool modules that import, export, or generate files under `src/Tools/`

## Settings Storage

FPVS Toolbox uses a strict hybrid settings model:

- App-level settings use `FPVS_CONFIG_HOME` when set, otherwise the user-writable app config root under `%LOCALAPPDATA%\FPVS Toolbox\settings\` on Windows.
- `Main_App.Shared.settings_manager.SettingsManager` is the single active writer for app-level settings.
- Project-specific settings stay in the active project's `project.json`.
- Stats may store reusable analysis metadata in `project.json` under
  `tools.stats`. The group-significant harmonics cache lives at
  `tools.stats.group_significant_harmonics_cache`, is keyed by selected
  participants/conditions, source workbook fingerprints, Stats harmonic
  settings, predefined ROI definitions, and the current project
  preprocessing/event-map signature, and must be invalidated when any of those
  inputs change. Project saves must preserve this namespace when Stats or
  processing-end harmonic QC updates it directly from a worker.
- v2.1 multi-group projects store canonical group definitions in
  `project.json` under `groups`. Keys are stable readable `group_id` slugs;
  entries carry `label`, `folder_name`, and `raw_input_folder`. Participant
  entries use `group_id` plus `raw_file`; legacy `group` values may be read only
  as migration/input compatibility.
- Every declared group requires a nonblank `raw_input_folder`. Its
  `folder_name` must be a safe single Windows path component; absolute paths,
  separators/traversal, reserved device names, and trailing dots/spaces are
  invalid. Group raw folders and output `folder_name` values must be unique.
- Grouped manifests do not persist a top-level `input_folder`; the registered
  group raw roots are the complete source of truth. New projects default to
  batch processing.
- `group_count == 1` projects keep the normal single-group shape and do not
  write `groups` metadata.
- Generated incremental-processing state lives under the active project root at
  `.fpvs_processing/processing_ledger.json` and
  `.fpvs_processing/processing_runs.jsonl`. This folder is recoverable state,
  not canonical project configuration.
- Condition-aware preflight QC stores recoverable, atomically written JSON
  entries under `.fpvs_processing/preflight_qc/v2`. The GUI must pass the
  active absolute project root explicitly; the cache helper rejects relative
  roots and never derives a location from the current working directory. Cache
  entries contain derived QC payloads only, are safe to delete, and are treated
  as misses when missing, corrupt, schema-incompatible, or fingerprint-stale.
- **File > Reset Project Processing Cache...** makes the next data-quality,
  raw-preprocessing, and incremental-planning run cold by deleting only
  `.fpvs_processing/preflight_qc/v2`,
  `.fpvs_cache/preprocessed`, `.fpvs_processing/processing_ledger.json.tmp`, and
  `.fpvs_processing/processing_ledger.json` beneath the active absolute project
  root. `Main_App.processing.project_processing_cache` owns this exact deletion
  boundary. It must preserve `.fpvs_processing/processing_runs.jsonl`, every
  other `.fpvs_cache` child, `project.json`, raw data, current outputs, logs,
  saved manual QC choices, and review workbooks. Existing participant outputs
  remain until the next run begins; normal processing then replaces the outputs
  it recomputes. The ledger reset deliberately removes its derived
  participant-status/QC provenance; if the following run is cancelled, that
  index remains absent until a later run rebuilds it.
- Processing-end harmonic selection writes
  `Quality Check/Harmonic_Selection_Summary.xlsx` under the active project root
  and saves the matching harmonic-selection metadata into
  `tools.stats.group_significant_harmonics_cache`. The raw data and generated
  condition workbooks are not altered by this QC export.
- Processing-end frequency-domain QC writes reviewed summed-BCA plausibility
  decisions into `project.json` under `tools.frequency_domain_qc` and writes
  `Quality Check/Frequency_Domain_QC_Review.txt` after user acceptance. This
  namespace stores read-only thresholds, automatic participant-electrode
  exclusions, automatic participant exclusions, manual participant exclusions,
  the last accepted review fingerprint, and whether downstream
  frequency-domain outputs are stale. Automatic exclusions are recalculated
  from current processed workbooks; manual participant exclusions persist until
  the user clears them in Settings.
- `%APPDATA%\FPVS_Toolbox\*.ini` files and old Qt `QSettings` locations are legacy migration inputs only; do not add new writers there.
- Do not write settings to the install directory, repo directory, `Program Files`, or the process current working directory.
- FPVS Studio `.fpvsconfig` import is a project-shell helper under
  `Main_App.projects.fpvs_config_import`. It imports `project.name`,
  `conditions[].name`/`conditions[].trigger_code` into `project.json`
  `event_map`, and optional per-participant manually removed electrode metadata
  into `preprocessing.manual_removed_electrodes`. Supported Studio-side
  scaffold shapes are a top-level PID-to-electrodes map such as
  `manual_removed_electrodes` or participant entries carrying
  `manual_removed_electrodes`, `removed_electrodes`, `excluded_electrodes`, or
  `physically_removed_electrodes`. When this metadata is present, the imported
  Toolbox project starts in manual removed-electrode mode. The importer then
  prompts for the raw `.bdf` input folder. The GUI exposes this as an option in
  the New Project flow from the landing page and File menu; it must not copy
  Studio stimulus assets or runtime artifacts.
- The preprocessing runner may create a generated cache under the active project
  root at `.fpvs_cache/preprocessed/`. Cache keys include source file path,
  size, mtime, MNE version, loader profile, and preprocessing settings. Cache
  files are generated artifacts, not project configuration, and are ignored by
  git when a project root is inside the repo. After a new preprocessed cache
  entry is written, older cache entries whose metadata points at the same source
  file are pruned.
- Multi-group Excel output layout is condition-first/group-second:
  `1 - Excel Data Files/<Condition>/<Group>/<Participant>_<Condition>_Results.xlsx`.
  Single-group output remains flat under each condition folder.
- Experimental LORETA Visualizer source-map exports are generated under the
  active project root at `6 - Source Localization/`, with method-specific
  subfolders such as `L2-MNE Hauk Z-Score Beta/` and
  `L2-MNE Cortical Surface Beta/`. These are generated payload/manifest files,
  not `project.json` settings.

## Multi-Group Processing Foundation

`Main_App.projects.grouping` is the canonical, GUI-neutral normalizer for group
and participant metadata. It exposes immutable `GroupInfo`, `ParticipantInfo`,
and `ProjectGroupContext` records plus a read-only `project.json` loader that
does not create project directories. `Main_App.projects.project.Project` uses
the same normalizer when loading and saving. Active processing carries stable
`group_id` values from registered raw folders through participant review,
incremental planning, worker routing, and post-processing export.

The processing contract is deliberately strict:

- Batch mode scans every registered group raw-input folder and does not fall
  back to only `project.input_folder` for a grouped project.
- Grouped manifests omit top-level `input_folder`, and the active `Project`
  exposes `input_folder = None`; all grouped consumers must use
  `ProjectGroupContext.groups`.
- Participant IDs must be unique across the whole project. Duplicate IDs across
  files or groups, including case-only manifest duplicates, hard-block
  processing. Ambiguous group aliases hard-block project loading.
- New participant/group/raw-file assignments require review before they are
  saved. Canceling review must not mutate `project.json`.
- Missing registered group folders and missing participant `raw_file` paths
  hard-block processing before or after group lock. Files selected outside a
  registered raw root, registered files that are not direct `.bdf` children of
  their assigned root, and known participants discovered in a different group
  also hard-block processing.
- The processing ledger computes expected condition/group workbook paths before
  work starts. The active process runner passes a per-source-file group folder
  to post-processing, which writes the condition-first/group-second layout.
- Missing per-file group routing and output-directory creation errors hard-fail;
  the exporter does not redirect a workbook to a parent folder.
- The first current-run grouped workbook sets `groups_locked`,
  `groups_locked_at`, and a group-definition fingerprint. This includes a
  partial-condition result or completed participant before cancellation.
  Project creation and participant review alone do not lock the layout. Later
  direct model or manifest changes to locked group definitions hard-fail.

The shared read-only group/participant context is now available from
`Main_App.projects`. The current downstream workbook scanners are compatibility
implementations, not the intended long-term ownership boundary. The remaining
target is a processed-workbook index under `Main_App.projects` that adds
conditions and workbook records to that context for all tools. New code should
not add another manifest normalizer or import a scanner from Stats or Plot
Generator. Until the shared index lands, preserve existing adapters and output
behavior. See
`docs/agent/exec-plans/active/multi-group-project-foundation.md`.

Rules:

- Preserve existing output formats, filenames, sheet names, and folder layout unless explicitly asked to change them.
- Active callers should import project model/settings/manager helpers through
  `Main_App.projects`.
- Use `tmp_path` in tests instead of hard-coded local paths.
- Handle `QFileDialog` Cancel without exceptions or stale UI state.
- Treat repeated operations and existing output files as normal user behavior.
- File-selection dialogs must use PySide6 `QFileDialog`. Single-file mode
  accepts only `.bdf` files inside the active project's registered raw source:
  the input folder for single-group projects, or a registered group raw folder
  for multi-group projects. It updates `data_paths`, `_selected_bdf`, the input
  line edit, logs, and Start enabled state without changing project paths.
- Loading a multi-group project must not silently recreate missing registered
  raw folders; missing registered raw folders hard-block processing regardless
  of lock state.
- `Reprocess All` may delete generated Excel workbook files only under the
  managed Excel output root. It must preserve condition/group directories and
  non-workbook files, then recreate the root before processing. Incremental
  stale reruns delete only the planned participant's expected Excel outputs.
- User-facing warnings/errors must use PySide6-safe message helpers, not Tk dialogs. Worker/background callers should log rather than block on a GUI popup.

Focused local verification:

```powershell
python .agents/scripts/verify.py --scope project-io --tier focused
```

The driver includes the project-path audit and safe project I/O contracts. File
dialog pytest-qt coverage is CI-only by default; document a visible/manual smoke
path when dialog behavior changes. Run the skill-local audit directly only as
an initial diagnostic before manually searching for hard-coded paths.
