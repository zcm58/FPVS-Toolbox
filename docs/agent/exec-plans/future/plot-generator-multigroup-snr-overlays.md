# Plot Generator Multi-Group SNR Overlays

## Status

Future plan. Not active implementation work.

This plan was refreshed against the current code on 2026-05-31. The existing
implementation is no longer just a stub: single-condition group overlays are
present in the GUI, worker payload, data collection, aggregation, rendering,
and focused tests. Future work should finish and harden that workflow, not
restart it.

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
  `_warn_unknown_subjects(...)`; they are not currently counted as failed
  items.
- If no selected group has data, the worker logs that it is showing the overall
  average only and renders the non-group average.

### Rendering and Output

- `rendering.py::_plot(...)` accepts `group_curves` for single-condition plots.
- One line is drawn per selected group that has ROI data.
- The first selected group uses `stem_color`, the second uses `stem_color_b`,
  and further groups use Matplotlib's palette.
- Oddball markers are drawn for each plotted group. The first group uses circle
  markers and the second uses triangle markers; additional groups use square
  markers with no extra peak legend label.
- Current filenames remain unchanged:
  `{condition}_{roi}_{metric}.png` and `{condition}_{roi}_{metric}.pdf`.
- This means group overlays currently overwrite the same output path shape as
  a non-group single-condition plot for the same condition/ROI/metric.

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
- Current output filenames stay unchanged unless the user explicitly requests a
  group-overlay filename suffix.

## Remaining Gaps Before This Is "First-Class"

These are the useful remaining implementation targets. Do not repeat already
covered fixture work unless a test demonstrates a gap.

1. **Output identity is ambiguous.**
   Group overlays currently save to the same filename shape as ordinary
   single-condition plots. Decide whether that is acceptable. If not, add a
   small explicit suffix such as `_group_overlay` and update tests/user docs.

2. **More-than-two selected groups need a clearer contract.**
   The code supports more than two groups with automatic palette colors and
   square oddball markers, but only the first two groups have custom legend and
   peak-label fields. Either document this as supported behavior or restrict
   selection to two groups in the GUI.

3. **No-data selected groups are silently omitted except for the all-empty case.**
   `_build_group_curves(...)` skips individual selected groups with no subject
   data. Add a warning that names each selected group with no data, or document
   intentional omission.

4. **Unassigned-subject behavior is log-only.**
   This matches current behavior, but the finished payload does not expose a
   warning count. If the GUI should summarize warnings at completion, add an
   explicit warning payload field rather than overloading `failed_items`.

5. **All-ROI grouped rendering needs explicit non-GUI coverage.**
   The code path should work because `_selected_roi_names()` expands
   `ALL_ROIS_OPTION`, but current non-GUI group-overlay tests focus on one ROI.

6. **Manual visible workflow is not documented in user-facing docs.**
   If the feature is promoted as user-facing, update the SNR Plot Generator
   docs with: canonical project requirement, group selection behavior,
   first/second group color mapping, and unassigned-subject warning behavior.

## Execution Slices

### Slice 1: Baseline and Policy Lock

Goal: convert the current implicit behavior into explicit tests/docs before
changing output behavior.

1. Run the focused non-GUI checks listed below.
2. Add/adjust tests to lock:
   - single-condition-only group overlay;
   - comparison mode remains hidden/disabled for multi-group projects;
   - scalp maps remain disabled in multi-group mode;
   - all groups are checked by default;
   - group overlay off still produces normal overall-average plots.
3. Update this plan or the Plot Generator scoped `AGENTS.md` only if the
   locked policy changes.

### Slice 2: Output Filename Decision

Goal: make generated files distinguishable enough for users.

1. Decide between:
   - preserve current filename shape, or
   - add a suffix such as `_group_overlay`.
2. If suffixing, update `rendering.py` and tests around generated PNG/PDF
   filenames.
3. Preserve non-group filenames exactly.

### Slice 3: Group Count and Legend Contract

Goal: make selected group count behavior unambiguous.

1. Decide whether more than two selected groups are supported.
2. If supported, document:
   - first/second group custom label fields;
   - automatic labels for group 3+;
   - palette and marker behavior.
3. If not supported, enforce max-two group selection in the GUI and add tests.
4. Preserve first/second group color mapping either way.

### Slice 4: Warning Semantics

Goal: make missing/empty group cases visible without turning warnings into
false failures.

1. Add or pin warnings for:
   - selected groups with no subject data;
   - Excel files with subjects absent from `project.json`;
   - manifests with groups but no participant assignments.
2. Keep fail-fast GUI validation for missing group assignments when overlay is
   requested.
3. If a completion summary should mention warnings, add explicit warning
   payload data and tests; do not overload `failed_items`.

### Slice 5: All-ROI and Rendering Coverage

Goal: prove grouped overlays work beyond the one-ROI happy path.

1. Add a non-GUI worker/rendering test for `ALL_ROIS_OPTION` with at least two
   ROIs.
2. Verify one PNG/PDF pair per ROI.
3. Verify current line-plot baseline/grid/oddball behavior remains unchanged
   for non-group plots.

### Slice 6: Documentation and Visible Smoke

Goal: make the feature executable by users and future agents.

1. Update user-facing SNR Plot Generator docs if the visible workflow or
   filename behavior changes.
2. Update `src/Tools/Plot_Generator/AGENTS.md` if ownership, policy, or
   verification commands change.
3. Document a visible/manual smoke path:
   - open a multi-group project;
   - confirm input folder is the canonical Excel root;
   - confirm Group Options appear;
   - enable group overlay;
   - uncheck one group and generate one ROI plot;
   - verify log warnings for unassigned participants, if present;
   - verify PNG/PDF output and legend colors.

## Verification Plan

Use focused checks first:

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
- An existing `SyntaxWarning` was reported in
  `src/Tools/Plot_Generator/snr_utils.py` for a docstring escape sequence. It
  is unrelated to multi-group overlay behavior.
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
