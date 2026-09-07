# Project I/O Architecture

Project-aware workflows should resolve paths from the active project root, not from the process current directory or a developer-machine path.

Processed condition discovery supports native `.fpvs` manifest anchors and
historical `.xlsx` workbooks through `Main_App.projects.dataset_index`.
`Main_App.projects.list_result_files` owns flat/recursive file eligibility and
native-over-exact-legacy-sibling preference for older folder-based consumers;
it does not change their existing cohort or filename interpretation. Native
manifests contain only portable sibling companion descriptors, and numerical
readers validate those companions through the shared Main App I/O layer.
Existing long/wide Excel reports remain unchanged. Reprocessing/exclusion
cleanup retires both exact sibling anchors and their declared companions so
an obsolete XLSX cannot reappear after its native replacement is removed.

The canonical project root is runtime context: it is the directory containing
the opened `project.json`, exposed as `Project.project_root`. It is not stored
as an absolute manifest field, because copied, renamed, or cross-platform
projects must rebase to the directory that was actually opened. Embedded tools
with the standard explicit/environment/current-project fallback use the public
`Main_App.projects.resolve_active_project_root()` helper; specialized tools may
retain stricter request validation or ancestry discovery when their established
workflow requires it.

Primary paths:

- `src/Main_App/projects/` is the canonical active import surface for project
  model, metadata, manager, projects-root, and preprocessing-settings behavior.
  It owns those implementations.
- `src/Main_App/Shared/settings_paths.py`
- tool modules that import, export, or generate files under `src/Tools/`

Disposable cache ownership, automatic QC replacement, and the Advanced settings
cache-clearing action are documented in [Cache Maintenance](cache-maintenance.md).
Cache removal preserves analysis companions, review decisions, and ledgers.

## Dataset Exclusion Management

`processing/dataset_exclusions.py` is the GUI-neutral adapter for a single
project's whole-participant and whole-recording exclusions. It combines existing
preprocessing skip lists with frequency-QC manual entries and reviewed
whole-owner decisions; it does not migrate these distinct processing and
analysis scopes into a new scientific policy. Participant/group/recording
identity and processed-file availability use the canonical project dataset
index. Existing overlapping scopes remain visible until explicitly edited.

The snapshot revision binds edits to the loaded project state. Saves patch
only requested scopes/reasons, preserve condition decisions and unrelated
metadata, retain exclusion history, and atomically replace the active
`project.json`. Scope changes invalidate affected downstream readiness and
saved harmonic cache entries. A restored current review exclusion must lose
its active authority while retaining its original audit record.

`gui/dataset_exclusions_dialog.py` owns the flat modal editor;
`workers/dataset_exclusions.py` loads/saves snapshots outside the GUI thread.
`gui/dataset_exclusions_workflow.py` holds the processing/navigation guard and
synchronizes saved skip lists into the active Project and open Settings cache,
preserving unrelated pending Settings edits. Apply saves immediately. The
Settings page exposes one manager instead of separate processing and frequency
participant-exclusion controls.

`processing/processing_ledger.py` rechecks current manual participant and
recording scopes before reusing a cached manual exclusion. Restoring its last
active processing scope makes that recording eligible for incremental QC and
processing without deleting the ledger or caches. Header-only and automatic
QC exclusion validation retain their existing behavior.

## Settings Storage

FPVS Toolbox uses a strict hybrid settings model:

- App-level settings use `FPVS_CONFIG_HOME` when set. Otherwise they use
  `%LOCALAPPDATA%/FPVS Toolbox/settings/` on Windows and
  `$XDG_CONFIG_HOME/FPVS Toolbox/settings/` on CachyOS, falling back to
  `~/.config/FPVS Toolbox/settings/` when `XDG_CONFIG_HOME` is unset or relative.
  Non-Windows `FPVS_CONFIG_HOME` overrides are expanded and made absolute;
  use an absolute override to keep its location stable across launch folders.
  Windows override expansion, relative-path handling, `%LOCALAPPDATA%` lookup,
  and missing-variable errors remain unchanged.
- `Main_App.Shared.settings_manager.SettingsManager` is the single active writer for app-level settings.
  Ordinary saves merge keys changed since that instance last loaded or saved
  into the latest INI, then publish atomically under an in-process lock. An
  unrelated save from an older settings instance cannot resurrect a deleted
  ROI. Explicit reset/import operations replace the configuration. Reloading
  starts with a fresh parser so removed options do not linger in memory.
- Project-specific settings stay in the active project's `project.json`.
- The experimental removed-electrode detector choice remains in the
  `preprocessing` namespace for compatibility with existing processing inputs.
  Its versioned choice status and source distinguish an actual saved selection
  from a provisional value. New projects record Off as a ready choice. An
  existing valid mode wins over a legacy boolean; a legacy boolean maps to a
  ready Auto or Off choice; a project with neither loads as provisional Off and
  `confirmation_required`. Routine saves keep that unresolved choice absent,
  and only the explicit confirmation API may persist it. Manual participant and
  recording electrode maps survive independently of this automatic-detector
  choice.
- Project-owned QC-17 configuration lives separately from raw preprocessing in
  the top-level, versioned `experimental_qc` record. Its
  `summed_bca_screening` subsection defaults to enabled review-only screening
  with the accepted absolute electrode-amplitude and flagged-cell/electrode
  count thresholds. Retired cohort-relative ROI thresholds are ignored when
  loading older settings and are omitted from newly saved settings. Existing
  projects with no record receive the electrode-screening defaults and
  persist them on their next save. This settings record is distinct from
  `tools.frequency_domain_qc` findings and decisions; the Wave 1 foundation
  does not reinterpret or change prior automatic exclusion state.
- Project-wide FPVS timing lives in the top-level, versioned
  `frequency_protocol` record. Protocol v1.1 stores exact rational identities for
  the presentation rate, integer oddball recurrence, canonical oddball rate,
  and one expected analyzed oddball-cycle count. The cycle source is `manual`
  or `fpvs_studio_import`; analyzed seconds are derived as cycles divided by
  oddball rate and are never stored as an independent setting. Direct-Hz entry
  is accepted only within half of one four-decimal display unit (0.00005 Hz) of
  an exact whole-stimulus recurrence, then canonicalized to presentation rate
  divided by that recurrence. The direct value as entered is retained for
  audit but is excluded from the canonical scientific fingerprint. A new
  project seeds 6 Hz/every 5 but remains
  `incomplete` until a positive expected cycle count is supplied. An existing
  manifest with no protocol loads as `confirmation_required` and a routine
  save keeps the record absent, so historical outputs are not silently
  relabeled with guessed defaults. Marker-less protocol v1.0 records retain
  their validated rate, recurrence, direct-entry audit text, cycle count, and
  cycle source while migrating to v1.1 `confirmation_required`; the proposed
  marker remains unclaimed until the user saves from Protocol. Accepting 55 at
  that point records `legacy_default_55`, while editing the code records
  `manual`. Saving an unrelated Settings tab preserves an unresolved protocol
  unchanged. Processing and harmonic recalculation still require a ready,
  explicitly confirmed protocol.
- Electrode geometry is project-specific scientific state in the
  `preprocessing` namespace. `electrode_montage` currently accepts only
  `biosemi64`, displayed as **BioSemi ActiveTwo 64**. The default
  `electrode_mapping_profile` is `anatomical_labels`; the alternative
  `biosemi64_1020_ab_v1` means only the standard BioSemi 64-channel 10/20
  A1-A32/B1-B32 wiring. It does not support BioSemi ABC/equiradial or custom
  layouts. Both values normalize and round-trip with the project and are
  passed into workers rather than reread from app-global settings.
  GUI processing parameter construction forwards both fields into the frozen
  run plan and worker settings. Omitting them would silently process with the
  anatomical default while final validation reads a different project choice.
  App defaults and newly created projects explicitly use BioSemi64 with
  anatomical labels. The A/B profile is an input-label translation for sources
  actually labeled A1-A32/B1-B32, not a different montage or a round-trip rename
  of already anatomical channel names.
  Project saves reconcile these two geometry fields against the last observed
  disk values: unchanged local fields adopt a newer saved correction, while
  explicit local changes remain authoritative. Other preprocessing fields keep
  their existing save behavior. `Project.refresh_electrode_geometry_settings()`
  performs the same reconciliation without writing; processing parameter
  construction calls it before freezing the run plan. Unreadable or malformed
  saved geometry blocks the operation with an error rather than overwriting it
  or building a run from stale settings. A successful save advances the saved
  baseline; a failed save does not.
  Open Settings panels separately track the geometry values displayed in their
  controls. Unchanged selectors adopt refreshed project geometry; edited
  selectors remain pending through validation and failed saves. Successful
  saves synchronize and rebase the controls, so a later unrelated save cannot
  resubmit a stale mapping from the panel's older general settings cache.
- Harmonic Selection and Summation is project-specific scientific state in the
  `preprocessing` namespace. New projects persist the
  `dzhelyova_poncet_two_consecutive_failures` v1 profile with all retained
  scalp electrodes. Loading an older project with no profile/version must
  preserve the exact `legacy_fpvs_toolbox` v1 behavior; normalization must not
  silently migrate that project to the new-project default. Fixed-profile
  exact-list/upper-harmonic/upper-frequency inputs and any frozen electrode
  mask travel with the project rather than app-global settings.
- `preprocessing.manual_excluded_participant_conditions` stores a normalized,
  deterministic participant-ID-to-condition-list mapping. Participant and
  condition matching is case-insensitive. These are downstream cohort
  exclusions: the raw recordings and generated workbooks remain available for
  audit, and changing the map does not request raw EEG reprocessing.
- Stats may store reusable analysis metadata in `project.json` under
  `tools.stats`. The group-significant harmonics cache lives at
  `tools.stats.group_significant_harmonics_cache`, is keyed by selected
  participants/conditions, canonical group assignments, source-workbook
  fingerprints, named harmonic profile/version and parameters, selection
  electrode mask, applicable ROI definitions for Legacy, and the current
  project preprocessing/event-map signature. Cache entries retain evaluated,
  detected, and included harmonics, pooling-cell sample sizes/weights, stopping
  provenance, and the canonical selection fingerprint. Project saves must
  preserve this namespace when Stats or processing-end harmonic QC updates it
  directly from a worker.
- Neutral FullFFT provenance lives at
  `tools.processing.full_fft_provenance`. It stores only project-relative
  source identity, rates, grid/resolution, cohort/QC, processing/export
  identity, the validated canonical BioSemi64 geometry identity, and their
  fingerprints. It contains no Stats profile, selected harmonic list, or
  Summed-BCA freshness state. Copied projects therefore resolve every recorded
  source beneath the copied active project root. Missing, legacy, or mixed
  geometry records make this provenance stale and block downstream FullFFT
  analysis until the affected EEG is reprocessed under one project geometry.
- Per-artifact selection freshness lives at
  `tools.post_processing.artifact_freshness`. Its active selection fingerprint
  and project-relative records use `current`, `stale`, or `failed` status. The
  tracked selection-dependent derivatives are the Stats-ready workbook, the
  full-audit workbook, the L2-MNE Hauk source-PSD map directory, and the
  eLORETA Hauk source-PSD map directory; the harmonic-selection summary is
  tracked as the current accepted-selection audit. A changed fingerprint
  invalidates all four derivatives; an identical fingerprint does not. Legacy
  cache keys or deterministic legacy metadata hashes are accepted only to
  migrate an older project into the registry.
- v2.1 multi-group projects store canonical group definitions in
  `project.json` under `groups`. Keys are stable readable `group_id` slugs;
  entries carry `label`, `folder_name`, and `raw_input_folder`. Participant
  entries use `group_id` plus `raw_file`; legacy `group` values may be read only
  as migration/input compatibility. Harmonic pooling, cache identity, and
  Stats-ready inference columns use the canonical `group_id`. The optional
  `group_label` is a separate display field and may duplicate another group's
  label without merging those groups.
- Every declared group requires a nonblank `raw_input_folder`. Its
  `folder_name` must be a safe single Windows path component; absolute paths,
  separators/traversal, reserved device names, and trailing dots/spaces are
  invalid. Group raw folders and output `folder_name` values must be unique.
- Grouped manifests do not persist a top-level `input_folder`; the registered
  group raw roots are the complete source of truth. New projects default to
  batch processing.
- `group_count == 1` projects keep the normal single-group shape and do not
  write `groups` metadata.
- Repeated-session projects opt into schema v2.2 with three additive
  namespaces: `sessions`, `recording_sources`, and `recordings`. A session owns
  a stable `session_id`, display label, and positive `visit_index`; a recording
  source owns exactly one canonical `group_id` x `session_id` raw folder; a
  recording owns one participant, source, session, direct-child BDF path,
  visit index, and optional `days_from_baseline`. `participant_id` remains the
  person/pairing identity and its `group_id` cannot change between sessions.
  `recording_id` is the durable processing, ledger, derivative, workbook, and
  recording-scoped QC identity.
- The repeated-project creation flow collects groups and ordered sessions
  separately, requires one source folder per group x session cell, and runs a
  BDF-header-free identity preflight in a cancellable background worker when
  source files already exist. Project creation resumes on the GUI thread only
  after that worker returns an accepted audit; cancellation or failure creates
  no project manifest. The
  preflight blocks duplicate participant/session recordings, cross-session
  group drift, nested BDFs, empty cells in a partially populated design, and
  optionally declared filename-token conflicts. Missing participant sessions
  remain explicit warnings and are imported without imputation. A completely
  empty source scaffold remains valid.
- Schema v2.1 manifests retain their exact field and preprocessing-setting
  shape. Loading a legacy project may synthesize compatibility recording
  identity in memory, but must not rewrite the manifest as v2.2.
- Generated incremental-processing state lives under the active project root at
  `.fpvs_processing/processing_ledger.json` and
  `.fpvs_processing/processing_runs.jsonl`. This folder is recoverable state,
  not canonical project configuration. Each current ledger result records the
  canonical/retained BioSemi64 geometry identity and interpolation request,
  outcome, successful channels, and error text. A missing or mismatched
  geometry identity classifies an otherwise completed input as changed/stale.
- Condition-aware preflight QC stores recoverable, atomically written JSON
  entries under `.fpvs_processing/preflight_qc/v4_biosemi64_geometry`. The GUI
  must pass the active absolute project root explicitly; the cache helper
  rejects relative roots and never derives a location from the current working
  directory. Cache entries contain derived QC payloads only, are safe to
  delete, and are treated as misses when missing, corrupt, schema-incompatible,
  fingerprint-stale, or built for another geometry identity.
- **File > Reset Project Processing Cache...** makes the next data-quality,
  raw-preprocessing, and incremental-planning run cold by deleting only
  `.fpvs_processing/preflight_qc/v4_biosemi64_geometry`,
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
  and saves the authoritative active/history record under
  `tools.processing.harmonic_selection`. A matching
  `tools.stats.group_significant_harmonics_cache` entry is reusable calculation
  state, not the downstream source of truth. The summary is registered as
  current for the accepted selection, while a changed canonical fingerprint
  marks the Stats-ready and full-audit workbooks plus the L2-MNE and eLORETA
  Hauk source-PSD map directories stale before their rebuild. The raw data,
  FullFFT sheets, generated condition workbooks, and neutral FullFFT provenance
  are not altered by a selection-only recalculation.
- After accepted processing-end harmonic selection, the background
  post-processing pipeline also writes
  `3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx`.
  This additive external-analysis export uses the canonical union of active
  and manually excluded processed workbooks. It retains every available
  participant, condition, and electrode value; project and frequency-domain
  QC decisions are recorded as flags rather than applied as filters. Group
  labels still come only from `project.json`, and the already accepted
  processing-time harmonic list is not recalculated on the audit cohort.
  Canonical replacements are published atomically. The worker archives an old
  file below `.fpvs_processing/stale_artifacts/` before replacement, restores
  it if publication fails, and keeps the new fingerprint's freshness record
  failed rather than destroying or relabeling the preceding reproducible file.
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
  size, mtime, MNE version, loader profile, preprocessing settings, and the
  canonical BioSemi64 geometry identity. Cache metadata records the retained
  scalp set and interpolation outcome. A cached FIF is accepted only after its
  channels and canonical coordinates are revalidated and its runtime geometry
  identity is reattached. Cache files are generated artifacts, not project
  configuration, and are ignored by git when a project root is inside the repo.
  After a new preprocessed cache entry is written, older cache entries whose
  metadata points at the same source file are pruned.
- Multi-group Excel output layout is condition-first/group-second:
  `1 - Excel Data Files/<Condition>/<Group>/<Participant>_<Condition>_Results.xlsx`.
  Single-group output remains flat under each condition folder.
- Repeated-session Excel output preserves the same condition-first/group-second
  directories but uses
  `<recording_id>_<condition>_Results.xlsx`. `WorkbookRecord` carries the
  participant, recording, session, visit, interval, and group fields; duplicate
  identity is `(recording_id, condition)`. `subject_data()` rejects repeated
  projects because its participant-only key cannot represent two visits;
  session-aware consumers use `recording_data()` and recording/session filters.
- Experimental LORETA Visualizer source-map exports are generated under the
  active project root at `6 - Source Localization/`, with method-specific
  subfolders such as `L2-MNE Hauk Z-Score Beta/` and
  `L2-MNE Cortical Surface Beta/`. These are generated payload/manifest files,
  not `project.json` settings.
- Source-PSD input derivatives are durable generated outputs under
  `6 - Source Localization/Source-Ready Time Domain v1/`. Artifact routing is
  `<condition label>/[<group>/]<participant>_<condition_id>_avg_raw.fif` with a
  sibling `<participant>_<condition_id>_avg_raw.json`; the optional group folder
  therefore remains second. Participant commit manifests are
  `manifests/[<group>/]<participant>.json` and are published only after all
  expected condition pairs succeed. These derivatives are distinct from
  resettable `.fpvs_cache/preprocessed` Raw files and are not deleted by
  **Reset Project Processing Cache**. Incremental reprocessing may replace only
  the planned participant's ledger-recorded derivative files. Ledger paths are
  project-relative so copied projects rebase safely; every resolved cleanup
  target must remain beneath the active project root.
- Time-domain Hauk-informed prepared outputs use
  `6 - Source Localization/L2-MNE Hauk Source PSD Beta/`. Source derivative,
  inverse-cache, and prepared-output state must not be written to `project.json`.

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
- QC-20's versioned expected-plan record builds the complete
  recording-by-condition matrix from the processing plan before numerical
  result accounting. It keys recordings by canonical recording ID when one
  exists, preserves participant/group/session/source metadata, and binds exact
  QC-19 occurrence spans to the project frequency-protocol, marker-evidence,
  raw-file, processing, and BioSemi64 geometry fingerprints. A current run file
  without a fully reviewed marker plan is rejected. Explicit current
  recording/condition exclusions instead store scoped no-output decisions and
  do not require a workbook for that scope. Reprocess-all and single-file
  reprocessing extend the reviewed plan set for any previously skipped files
  before output cleanup. A skipped legacy cell stays
  `legacy_unknown`; existing workbook presence or the old `partial` warning
  cannot promote it to a verified final outcome.
- Missing per-file group routing and output-directory creation errors hard-fail;
  the exporter does not redirect a workbook to a parent folder.
- The first current-run grouped workbook sets `groups_locked`,
  `groups_locked_at`, and a group-definition fingerprint. This includes a
  partial-condition result or completed participant before cancellation.
  Project creation and participant review alone do not lock the layout. Later
  direct model or manifest changes to locked group definitions hard-fail.

For v2.2, batch discovery enumerates explicit recording sources instead of the
common group roots. The same participant is expected across different
sessions, but more than one BDF for one participant/session, reuse of a
recording ID, or group drift across visits blocks before BDF loading. The
processing ledger and expected-output planner key by recording ID, and the
group/session/source/recording fingerprint locks with the first repeated
output. Participant-wide, recording-wide, participant-condition, and
recording-condition exclusions remain distinct. Per-recording removed-
electrode choices override the participant-level compatibility fallback.

The shared read-only group/participant context is now available from
`Main_App.projects`. `Main_App.projects.dataset_index` is the single
GUI-neutral owner for processed-workbook discovery, condition and participant
identity, canonical group IDs/labels, duplicate selection, and discovery
diagnostics. It accepts the project root, configured Excel root, condition
folder, or group folder without creating directories. Exact manifest
participant IDs take precedence over legacy filename matching; canonical
grouped copies take precedence over stale flat copies.

For managed project scans, the shared index applies
`manual_excluded_participant_conditions` only after canonical participant/group
identity and duplicate priority are resolved. Active `workbooks`, condition
partitions, and selection helpers omit those records, while
`excluded_workbooks` and `excluded_participant_condition` diagnostics preserve
the resolved paths for review. Unmanaged scans do not apply manifest
exclusions.

Group membership always comes from the normalized participant metadata in
`project.json`. A generated group folder is retained on `WorkbookRecord` only
to validate routing and report mismatches; it must never assign or override a
group. Downstream tools may retain thin compatibility adapters for established
return shapes, but they must query `load_project_dataset_index(...)` rather
than implement manifest-group normalization, participant-ID parsing, or
workbook/group discovery themselves. See
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

```console
python .agents/scripts/verify.py --scope project-io --tier focused
```

The driver includes the project-path audit and safe project I/O contracts. File
dialog pytest-qt coverage is CI-only by default; document a visible/manual smoke
path when dialog behavior changes. Run the skill-local audit directly only as
an initial diagnostic before manually searching for hard-coded paths.
