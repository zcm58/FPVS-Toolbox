# SNR Plots Multi-Group Overlay Hardening

## Status

Implemented on 2026-07-28. This file is retained temporarily as the focused
verification record while the broader active multi-group plan still links to
it. The hardening work preserved the single-condition group-overlay contract.

## Scope Decision

Treat multi-group SNR overlay as a **single-condition, group-overlay workflow**.

The current repo contract in `src/Tools/Plot_Generator/AGENTS.md` says
multi-group plotting is one condition with one average curve per selected
group. It also says condition overlay and scalp-map controls are hidden in
multi-group mode. Do not expand this plan to condition-A-vs-condition-B group
comparison unless the user explicitly requests a separate behavior change and
approves the visual/legend design first.

## Target Files

Primary implementation:

- `src/Tools/Plot_Generator/gui.py`
- `src/Tools/Plot_Generator/gui_settings.py`
- `src/Tools/Plot_Generator/selection_state.py`
- `src/Tools/Plot_Generator/generation_workflow.py`
- `src/Tools/Plot_Generator/worker.py`
- `src/Tools/Plot_Generator/worker_config.py`
- `src/Tools/Plot_Generator/manifest_utils.py`
- `src/Tools/Plot_Generator/excel_inputs.py`
- `src/Tools/Plot_Generator/data_collection.py`
- `src/Tools/Plot_Generator/aggregation.py`
- `src/Tools/Plot_Generator/rendering.py`

Primary tests:

- `tests/plot_generator/test_plot_generator_multigroup_smoke.py`
- `tests/plot_generator/test_plot_generator_group_overlay_worker.py`
- `tests/plot_generator/test_plot_generator_worker_config.py`
- `tests/plot_generator/test_plot_generator_manifest_utils.py`
- `tests/plot_generator/test_plot_generator_excel_inputs.py`
- `tests/plot_generator/test_plot_generator_project_input_policy.py`
- Existing rendering/legend/outcome tests under `tests/plot_generator/`

## Current Code State

### Project and Manifest Routing

- `gui.py` resolves `_canonical_project_excel_root` from the active project
  root and project manifest subfolder settings.
- `gui_settings.py::_project_plot_input_folder(...)` ignores saved
  `input_folder` settings for multi-group projects and returns the canonical
  project Excel root instead.
- `gui_settings.py::_persist_project_plot_settings(...)` drops stale saved
  `input_folder` values for grouped projects while still saving the output
  folder and visual settings.
- `selection_state.py::_folder_is_canonical_project_excel_root(...)` only
  enables group options when the selected input folder is the canonical Excel
  root. A condition subfolder under that root is not enough.
- `manifest_utils.py::load_manifest_for_excel_root(...)` walks upward from the
  Excel root, loads the nearest `project.json`, and confirms that the manifest's
  expected Excel path is compatible with the selected folder before accepting
  it.

### Manifest Shape and Group Labels

Supported manifest shapes:

- v2 project groups: `groups` keyed by `group_id`, with optional `label` and
  `folder_name`.
- v2 participants: `participants[participant_id].group_id`.
- legacy participants: `participants[participant_id].group`.

Current normalization behavior:

- `manifest_utils.py::extract_group_names(...)` returns sorted unique display
  labels, resolving group IDs through `label` or `folder_name`.
- `manifest_utils.py::normalize_participants_map(...)` returns uppercase
  `{subject_id: group_label}`.
- `excel_inputs.py::_infer_subject_id_from_path(...)` prefers known manifest
  participant IDs before falling back to legacy `P#` parsing. This protects
  names such as `E2P2final_Angry_Results.xlsx` from collapsing to `P2`.

### GUI State

- `ui_sections.py` defines a hidden `SectionCard("Group Options")` with an
  `Overlay groups on plots` checkbox and a checkable group list.
- `selection_state.py::_refresh_group_controls(...)` populates group rows from
  the manifest, checks all groups by default, disables the list until overlay
  is enabled, and resets overlay to off whenever the folder/conditions refresh.
- `selection_state.py::_update_multigroup_mode_controls(...)` hides the
  condition-comparison row in multi-group mode and unchecks `scalp_check`.
- `selection_state.py::_overlay_toggled(...)` disables group overlays while
  condition comparison is on.
- `gui.py::_update_legend_group_visibility(...)` changes custom legend labels
  from condition language to first/second group language when group overlay is
  enabled.
- `selection_state.py::_group_color_assignment(...)` maps the first selected
  group to `stem_color`, the second selected group to `stem_color_b`, unselected
  groups to a disabled swatch, and additional selected groups to the automatic
  palette.

### Worker Payload and Validation

- `selection_state.py::_group_worker_kwargs(...)` sends `subject_groups`,
  `selected_groups`, `enable_group_overlay`, and `multi_group_mode` to the
  worker.
- `generation_workflow.py::_generate(...)` fails fast in the GUI if group
  overlay is enabled with no selected groups or no manifest group assignments.
- `worker_config.py::PlotWorkerConfig` carries group-overlay settings without
  changing the public `_Worker` constructor.
- `worker.py` normalizes subject IDs to uppercase, drops invalid empty groups,
  preserves selected group order, and enables group overlay only when
  `enable_group_overlay` and selected groups are both truthy.

### Data Collection and Aggregation

- `data_collection.py::_list_excel_files(...)` recursively reads `.xlsx` files
  under the selected condition folder, so
  `<Excel Root>/<Condition>/<Group>/<Participant>_<Condition>_Results.xlsx`
  works.
- Group membership comes from `project.json`, not folder names.
- `data_collection.py::_collect_data(...)` tracks Excel files whose inferred
  subject ID is not present in `subject_groups` while group overlay is enabled.
- `aggregation.py::_build_group_curves(...)` reuses collected subject data,
  filters by selected group, averages each group's subjects per ROI, and does
  not re-read Excel files.
- Unknown subjects are excluded from group curves and logged by
  `_warn_unknown_subjects(...)`; they remain warnings rather than failed items
  and are included in the worker completion payload.
- Per-group sample sizes count participants with at least one finite value for
  each ROI and are shown in the curve labels.
- Selected group/ROI combinations without usable data are named in warnings and
  omitted. An all-empty group-overlay ROI is skipped instead of being replaced
  by the pooled all-participant average.
- Workbooks whose selected FullSNR frequency grids differ from the first usable
  workbook are skipped and reported instead of being averaged by column
  position.

### Rendering and Output

- `rendering.py::_plot(...)` accepts `group_curves` for single-condition plots.
- One line is drawn per selected group that has ROI data.
- The first selected group uses `stem_color`, the second uses `stem_color_b`,
  and further groups use non-conflicting colors from Matplotlib's palette.
- Oddball markers are drawn for each plotted group. The first group uses circle
  markers, the second uses triangle markers, and additional groups cycle through
  distinct marker shapes with no extra peak legend label.
- Ordinary filenames use the visible title (or condition fallback) plus ROI:
  `{title or condition} - {ROI}.png` and the matching `.pdf`.
- Group-overlay filenames append `_group_overlay`, preserving an ordinary
  single-condition figure with the same title and ROI.

### Existing Tests

Current focused coverage already pins:

- worker config defaults and constructor compatibility;
- group option activation only at the canonical project Excel root;
- stale saved input folders being dropped for grouped projects;
- v2 `group_id` to display-label normalization;
- legacy `group` normalization;
- known participant IDs taking precedence over legacy `P#` parsing;
- grouped Excel files under condition/group folders;
- group curves matching project participant IDs;
- PNG/PDF files being written for group overlays;
- all-ROI group aggregation across more than one ROI;
- group color assignment following selected-group order;
- custom legend defaults switching to selected group labels;
- pytest-qt GUI smoke for single-group defaults, group overlay selection, and
  unassigned-subject logging.

Do not run pytest-qt/offscreen tests locally in this repo. The pytest-qt smoke
tests are useful coverage definitions, but local verification should use
non-GUI checks plus a documented visible/manual smoke path unless the user
explicitly approves a safe visible Qt test environment.

## Locked Behavior To Preserve

- Multi-group overlay is single-condition only.
- Group Options appear only for projects with at least two manifest groups and
  only when the input folder is the canonical project Excel root.
- Condition comparison is hidden/disabled in multi-group mode.
- Scalp maps are disabled in multi-group mode.
- All manifest groups are checked by default when the group list is populated.
- Group membership is resolved from `project.json`, never inferred from output
  group folders.
- Known manifest participant IDs are preferred over legacy `P#` parsing.
- Unassigned subjects are excluded from group curves and logged as warnings,
  not counted as partial failures.
- Group-overlay output filenames use the `_group_overlay` suffix; non-group
  filenames remain unchanged.
- A group-overlay request never falls back to a pooled all-participant curve
  when the selected groups have no usable data.

## Completed First-Class Hardening

- [x] Distinct `_group_overlay` PNG/PDF output identity.
- [x] Documented and tested support for more than two selected groups.
- [x] Per-ROI participant sample sizes in legend labels.
- [x] Named no-data and unassigned-participant warnings in the completion
      payload and GUI run summary.
- [x] No pooled fallback for an empty selected-group/ROI overlay.
- [x] All-ROI grouped export coverage for one PNG/PDF pair per usable ROI.
- [x] Frequency-grid mismatch guard before participant averaging.

## Gaps Resolved Since The Previous Refresh

- `docs/user/tools/snr-plot-generator.md` now documents the canonical project
  Excel-root requirement, one-condition group overlay, project-manifest group
  assignments, first/second color and legend mapping, and unassigned-workbook
  warning behavior.
- Non-GUI coverage now proves all-ROI group aggregation across two ROIs.
- The Windows-safe filename contract now preserves ordinary
  `{title or condition} - {ROI}` exports and gives group overlays the explicit
  `_group_overlay` suffix.

## Implemented Slices

1. Locked the one-condition overlay policy and disabled `All Conditions` while
   group overlay is enabled.
2. Added the `_group_overlay` filename suffix without changing ordinary export
   names.
3. Kept editable first/second group styles and added deterministic automatic
   colors, labels, and marker shapes for additional groups.
4. Added per-ROI sample counts, structured no-data/unassigned warnings, and a
   completion warning count without treating warnings as failed workbooks.
5. Added all-ROI paired-export coverage and prevented pooled fallback figures
   for empty group/ROI combinations.
6. Updated scoped developer and user documentation. The remaining visible smoke
   path is listed below.

## Verification Plan

Use focused checks first:

The commands use the preferred `.venv1` interpreter. Substitute
`.venv\Scripts\python.exe` when `.venv1` is absent. The baseline below records
the environment used when that historical verification was run.

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\selection_state.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\worker_config.py src\Tools\Plot_Generator\manifest_utils.py src\Tools\Plot_Generator\excel_inputs.py src\Tools\Plot_Generator\data_collection.py src\Tools\Plot_Generator\aggregation.py src\Tools\Plot_Generator\rendering.py
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_worker_config.py tests\plot_generator\test_plot_generator_group_overlay_worker.py tests\plot_generator\test_plot_generator_manifest_utils.py tests\plot_generator\test_plot_generator_excel_inputs.py tests\plot_generator\test_plot_generator_project_input_policy.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check paths
```

Use pytest-qt coverage as a definition of expected GUI behavior, but do not run
it locally/offscreen:

```powershell
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_multigroup_smoke.py -q
```

Run that command only in an explicitly approved safe visible Qt environment.

## Baseline Verification From Plan Refresh

Passed on 2026-05-31:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\selection_state.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\worker_config.py src\Tools\Plot_Generator\aggregation.py src\Tools\Plot_Generator\rendering.py src\Tools\Plot_Generator\manifest_utils.py src\Tools\Plot_Generator\excel_inputs.py src\Tools\Plot_Generator\data_collection.py
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_worker_config.py tests\plot_generator\test_plot_generator_group_overlay_worker.py tests\plot_generator\test_plot_generator_manifest_utils.py tests\plot_generator\test_plot_generator_excel_inputs.py tests\plot_generator\test_plot_generator_project_input_policy.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check paths
```

Notes:

- The focused pytest command collected 17 tests and all passed.
- Pytest-qt GUI smoke was not run locally because this repo forbids offscreen
  Qt workflows.

## Reporting Requirements

Future agents using this plan must report:

- Whether the work preserved single-condition-only group overlays.
- Manifest shape tested (`group_id` labels, legacy `group`, participant IDs).
- Selected group ordering, default checked state, and max group-count policy.
- Unknown-subject and selected-empty-group warning behavior.
- Generated filenames and formats verified.
- Legend label, color, and marker behavior verified.
- Commands run and results.
- Any skipped visible GUI smoke and residual risk.
