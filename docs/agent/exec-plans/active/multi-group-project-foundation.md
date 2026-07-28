# Multi-Group Project Foundation and Shared Dataset Index

## Status

Active. The processing foundation and shared processed-workbook index are
implemented and covered by focused tests. Current group-aware consumers are
being migrated to the `Main_App.projects` API; remaining figure/summary tools
still need explicit group selection without changes to their scientific
calculations or existing exports.

Last reviewed against the repository on 2026-07-28.

## Goal

Make multi-group projects a durable project-level capability rather than a set
of tool-specific special cases:

- `project.json` is the only canonical source for groups and participant-group
  assignments;
- Batch processing processes every registered `.bdf` file across all project
  groups by default;
- Processing refuses ambiguous or unsafe group states before work begins;
- Generated workbooks use the locked condition-first/group-second layout;
- Group definitions become immutable after the first successful grouped run;
- Downstream tools share one read-only processed-workbook index and selection
  contract owned by `Main_App.projects`, without depending on Stats internals.

## Non-Goals

- Do not add native multi-group statistical models to the Stats tool in this
  plan. Its current group-aware Stats-ready export remains supported.
- Do not change preprocessing order, harmonic-selection policy, workbook sheet
  names, result filenames, or scientific calculations.
- Do not infer canonical group membership from generated output folder names.
- Do not change the separately retained SNR group-overlay policy or its future
  design decisions in
  `docs/agent/exec-plans/future/plot-generator-multigroup-snr-overlays.md`.
- Do not couple tools to one another merely to reuse a scanner or participant-ID
  parser.

## Locked Project Contract

### Canonical metadata

- Multi-group manifests store `groups` keyed by stable readable `group_id`
  slugs.
- Each group entry carries `label`, `folder_name`, and `raw_input_folder`.
- `raw_input_folder` is required and nonblank for every declared group.
- `folder_name` is one safe Windows folder component: it cannot be absolute,
  contain separators or traversal, use reserved device names, or end in a dot
  or space.
- Each group has a unique raw-data folder and a unique output `folder_name`.
- Participant entries use `group_id` and `raw_file`.
- Legacy participant `group` values are read-only compatibility input and are
  normalized to `group_id` when the project is saved.
- A normal single-group project omits `groups` metadata and keeps the existing
  flat output layout.
- A grouped manifest omits the ambiguous top-level `input_folder`; registered
  group raw roots are the complete input source of truth. The active `Project`
  model exposes `input_folder = None` for grouped projects so a downstream tool
  cannot accidentally consume a synthesized fallback path.
- Participant IDs are unique across the whole project, not merely within a
  group, including case-insensitive collisions such as `P01` versus `p01`.
- Group IDs, labels, and folder names cannot create ambiguous aliases.
- A registered participant `raw_file` must be a `.bdf` directly inside that
  participant's assigned group raw root and must be discoverable there.

### Batch default and hard preflight

- Batch discovery enumerates every registered group raw-input folder. It must
  never fall back silently to only `project.input_folder` for a grouped project.
- New projects default `options.mode` to `batch`, so processing the full
  registered project is the normal workflow.
- Duplicate inferred participant IDs across files or groups hard-block the run.
- Any missing registered group raw folder hard-blocks processing, whether or
  not the group layout has locked yet.
- Any participant entry whose registered `raw_file` is missing hard-blocks
  processing rather than silently producing a partial project run.
- A manually selected `.bdf` must be inside a registered group raw folder.
- A known participant discovered in a different group after lock hard-blocks
  processing.
- New or changed participant/raw-file assignments are reviewed before they are
  persisted. Canceling review leaves `project.json` unchanged.

### Safe output routing

- Single-group workbooks remain
  `<Excel Root>/<Condition>/<Participant>_<Condition>_Results.xlsx`.
- Multi-group workbooks use
  `<Excel Root>/<Condition>/<Group folder>/<Participant>_<Condition>_Results.xlsx`.
- The processing plan computes expected output paths before work starts and the
  process runner receives a per-source-file group-folder mapping.
- Missing per-file mappings, unsafe condition/group folder components, and
  output-directory creation failures hard-block export; no workbook is
  redirected to a parent folder.
- Cleanup remains bounded to managed output roots and preserves the condition
  and group directory structure.

### Lock on success

- Creating a project and reviewing participant assignments does not lock its
  group layout.
- The first current-run grouped workbook sets `groups_locked`,
  `groups_locked_at`, and a persisted group-definition fingerprint.
- Any such workbook is enough to lock the layout, including a
  partial-condition result or a completed participant before cancellation,
  because generated output already depends on that group definition.
- The fingerprint makes later direct model or manifest changes hard-fail; the
  GUI lock is not the only enforcement boundary.
- Later discovery validates registered folders and participant assignments
  against that locked state rather than silently rewriting them.

## Current Implementation

- `Main_App.projects.grouping` owns canonical group/participant normalization,
  immutable `GroupInfo`/`ParticipantInfo`/`ProjectGroupContext` records, a
  non-mutating read-only manifest loader, safe group IDs, and output-folder
  validation/resolution.
- `Main_App.projects.project.Project` consumes that same normalizer and owns
  manifest persistence, grouped `input_folder = None`, and locked group
  fingerprint enforcement.
- `Main_App.projects.dataset_index` owns non-mutating processed-workbook and
  condition discovery, exact manifest-first participant matching, canonical
  group assignment, stable-ID selection, legacy adapter shapes, duplicate
  preference, and discovery diagnostics.
- Generated group folders are observed routing provenance only. The shared
  index always derives group IDs and labels from canonical participant
  metadata.
- `Main_App.processing.processing_controller.RawFileInfo` carries the raw file,
  participant ID, and stable group ID through discovery and review.
- `discover_raw_files(...)` and `prepare_batch_file_infos(...)` enumerate all
  configured raw folders and enforce participant identity, assignment, and
  registered-source completeness.
- `Main_App.processing.processing_ledger` computes condition/group output paths,
  guards cleanup boundaries, and locks a grouped project after successful
  processing.
- `Main_App.gui.processing_workflows` passes group output routing to the active
  process runner.
- The post-processing exporter writes the group folder beneath each condition.
- Raw preprocessing QC preserves canonical group IDs and shows manifest group
  labels in live status, all participant/file review tables, detail dialogs,
  and saved review flags. The processing-end frequency-domain QC dialog also
  shows manifest labels in its summary and flagged-value tables. Its numeric
  workbook discovery now comes from the shared project dataset index while the
  scientific calculation remains intentionally project-pooled.

Focused coverage lives in:

- `tests/project_io/test_project_v2_group_schema.py`
- `tests/project_io/test_project_group_context.py`
- `tests/project_io/test_project_dataset_index.py`
- `tests/processing/test_processing_discovery_v2.py`
- `tests/processing/test_processing_ledger.py`
- `tests/processing/test_process_runner_epoch_contract.py`
- `tests/processing/test_post_process_target_freqs.py`
- `tests/processing/test_preflight_qc.py`
- `tests/processing/test_preprocessing_qc_workflow_helpers.py`
- `tests/gui/test_qc_group_membership.py` (CI Qt smoke)

## Shared Index and Remaining Architecture Work

### Shared processed-workbook index

The landed `src/Main_App/projects/dataset_index.py` extends the pure,
read-only project group context. It does not import PySide6, pandas, Stats,
Plot Generator, or another tool package.

The landed model preserves both stable identity and presentation values:

```python
@dataclass(frozen=True)
class WorkbookRecord:
    participant_id: str
    condition: str
    path: Path
    group_id: str | None
    group_label: str | None
    observed_layout: str
    observed_group_folder: str | None

@dataclass(frozen=True)
class DatasetDiagnostic:
    code: str
    message: str
    paths: tuple[Path, ...]

@dataclass(frozen=True)
class ProjectDatasetIndex:
    project_root: Path
    excel_root: Path
    scan_root: Path
    manifest: Mapping[str, Any] | None
    groups: Mapping[str, GroupInfo]
    participants: Mapping[str, ParticipantInfo]
    workbooks: tuple[WorkbookRecord, ...]
    diagnostics: tuple[DatasetDiagnostic, ...]
```

Required query/adaptation behavior:

- Select records by condition, stable group ID, and participant ID.
- Expose ordered conditions, groups, and participants for GUI population.
- Provide a compatibility adapter for the existing Stats
  `{participant: {condition: workbook_path}}` shape.
- Provide a compatibility adapter for display-label group maps currently used
  by Stats-ready export and SNR group overlays.
- Prefer exact known manifest participant IDs before legacy filename regexes.
- Report missing assignments, duplicate participant/condition workbooks, and
  stale flat/grouped duplicates explicitly. Preserve the current compatibility
  preference for canonical grouped workbooks over stale flat copies.
- Resolve project and Excel roots without mutating the project or creating
  directories.

Group membership must come from the participant manifest. A group directory in
the processed layout can validate or diagnose routing, but it cannot override
the manifest assignment.

### Downstream migration order

1. [x] Add workbook records and indexing to the shared context, cover them with
   project-I/O tests, then export the new public names from `Main_App.projects`.
2. [x] Keep thin compatibility wrappers in
   `Tools.Stats.data.stats_data_loader`, but move manifest lookup, group
   normalization, participant matching, and workbook indexing to the shared
   owner.
3. [x] Change processing-end harmonic and frequency-domain QC to import the shared
   index directly instead of importing the Stats scanner.
4. [x] Change the LORETA Visualizer Stats-ready bridge to use the shared index
   rather than Stats data-loader internals. Migrate its independent
   `source_producers.project_inputs` workbook aggregator in the same step so it
   filters by canonical group before computing participant means.
5. [x] Change Plot Generator manifest/path/discovery helpers to shared adapters
   while preserving its canonical-Excel-root and manifest-membership policies.
6. [ ] Add group-aware selection to Publication Maps without changing map
   calculations.
7. [ ] Migrate Ratio Calculator and Individual Detectability from flat-folder
   globbing to indexed records before offering per-group output controls.
8. [ ] Give the beta Epoch Averaging tool an explicit group-aware input contract;
   until then it hard-fails for grouped projects instead of substituting the
   removed project-level input folder.

Every migrated figure/summary tool must follow the same group behavior unless
an existing, explicitly retained overlay contract says otherwise:

- filter workbook records to one canonical `group_id` before any participant
  aggregation;
- offer each group as a selectable unit and treat an all-groups action as
  separate per-group outputs rather than an implicit pooled sample;
- include the safe group folder/name in output routing so groups cannot
  overwrite one another;
- hard-fail an empty selected group and report unassigned participants through
  shared index diagnostics rather than silently dropping them.

Numeric aggregation, workbook-sheet reading, plotting, and report generation
remain owned by each tool. The shared layer owns identity, paths, discovery,
selection, and diagnostics only.

## Compatibility Requirements

- Preserve legacy `group` reads and canonical `group_id` writes.
- Preserve known full participant IDs before `P#` fallback matching.
- Preserve the existing single-group manifest and flat workbook layout.
- Preserve condition labels, output filenames, workbook formats, and sheet
  names.
- Preserve the Stats scanner adapter and its current duplicate-candidate
  preference until all active callers migrate.
- Preserve the current Stats-ready export column/value behavior unless a
  separate export-schema change is explicitly approved.
- Distinguish `has_group_metadata` from `is_multi_group`; the latter requires at
  least two canonical groups.

## Progress

- [x] Canonical v2.1 group and participant manifest shape.
- [x] Required group raw roots and safe single-component output folder names.
- [x] Shared, immutable, read-only group/participant project context.
- [x] Batch as the default project processing mode.
- [x] All-group batch raw-file discovery.
- [x] Participant review before manifest persistence.
- [x] Locked-assignment and missing-folder preflight guards.
- [x] Condition-first/group-second output routing.
- [x] Lock-on-success behavior.
- [x] Focused processing verification includes multi-group discovery and ledger
      tests.
- [x] Preprocessing and frequency-domain QC GUI reviews display canonical group
      membership without changing participant-keyed exclusion behavior.
- [x] Processed-workbook records/index added to the shared project context.
- [x] Stats compatibility wrapper migrated to the shared index.
- [x] Processing QC and LORETA cross-tool Stats dependencies removed.
- [x] Plot Generator discovery migrated to the shared index.
- [ ] Remaining figure/summary tools migrated and given explicit group
      selection where appropriate.

## Verification

Use the repository-selected `.venv1`/`.venv` interpreter:

```powershell
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope plot-generator --tier focused
```

For future shared-index work, add non-GUI tests covering:

- canonical and legacy manifests;
- one-group manifests versus true multi-group manifests;
- flat and condition/group workbook layouts;
- full participant IDs that contain an internal `P#` token;
- unassigned participants and unknown group IDs;
- duplicate canonical/legacy workbook candidates;
- project-root, Excel-root, condition-folder, and group-folder scopes;
- missing and permission-denied paths without filesystem mutation.

Do not run pytest-qt/offscreen tests locally. When group controls change, use
the CI Qt coverage plus a documented visible Main App smoke path.
