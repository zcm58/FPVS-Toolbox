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
- `group_count == 1` projects keep the normal single-group shape and do not
  write `groups` metadata.
- Generated incremental-processing state lives under the active project root at
  `.fpvs_processing/processing_ledger.json` and
  `.fpvs_processing/processing_runs.jsonl`. This folder is recoverable state,
  not canonical project configuration.
- Processing-end harmonic selection writes
  `Quality Check/Harmonic_Selection_Summary.xlsx` under the active project root
  and saves the matching harmonic-selection metadata into
  `tools.stats.group_significant_harmonics_cache`. The raw data and generated
  condition workbooks are not altered by this QC export.
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
  raw folders; after group lock, missing registered raw folders hard-block
  processing.
- `Reprocess All` may delete generated Excel workbook files only under the
  managed Excel output root. It must preserve condition/group directories and
  non-workbook files, then recreate the root before processing. Incremental
  stale reruns delete only the planned participant's expected Excel outputs.
- User-facing warnings/errors must use PySide6-safe message helpers, not Tk dialogs. Worker/background callers should log rather than block on a GUI popup.

Useful checks:

```powershell
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/scripts/audit/agent_audit.py --check paths
python -m pytest tests/project_io/test_project_settings_roundtrip.py tests/project_io/test_project_results_layout.py -q
```

Run the skill-local script before manually searching for hard-coded paths across the repo.
