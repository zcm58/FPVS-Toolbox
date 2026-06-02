# Publication Scalp Maps

## Status

Active plan for branch `codex/publication-scalp-maps-harmonics`.

This plan was tightened against the current code on 2026-06-02. Read it before
changing Stats, Plot Generator scalp code, or Main App tool-launcher surfaces
for this feature.

## Goal

Add a publication-focused embedded tool that builds condition-level grand
average scalp maps from FPVS Excel workbooks.

Required map families:

- SNR scalp maps in the style requested for Stothart et al. (2020), with
  0/near-0 values rendered as the low blue color.
- BCA scalp maps in the style requested for David et al. (2025), with
  0/near-0 values rendered as the low blue color.
- Z-score scalp maps for the David et al. (2025)-style reporting workflow.

The tool must export both publication figures and a rectangular source-data
workbook so figures can be audited from workbook -> condition -> subject ->
electrode -> harmonic -> rendered value.

## Current Code Anchors

Stats code that can be reused:

- `src/Tools/Stats/analysis/full_snr.py`
  - `compute_full_snr_from_amplitudes(...)` preserves the locked neighboring-bin
    SNR behavior and is the only acceptable fallback when `FullSNR` is missing.
- `src/Tools/Stats/analysis/dv_policy_group_significant.py`
  - `build_group_significant_harmonic_selection(...)` selects one common
    group-level significant harmonic list from `FullFFT Amplitude (uV)`.
  - `GroupSignificantHarmonicSelection.to_metadata(...)` exposes selected
    harmonics, z scores, noise bins, and provenance-ready selection rows.
  - `_build_grand_average_amplitude(...)` is for Stats harmonic selection only:
    it averages each workbook over all scalp electrodes, then across selected
    subjects/conditions. Do not use it as the publication scalp-map data frame.

Plot Generator code that can be reused carefully:

- `src/Tools/Plot_Generator/scalp_utils.py`
  - `ScalpInputs` and BioSemi64 alignment behavior are useful.
  - `summarize_subject_scalp(...)` is not the publication-map method. It sums
    BCA only when the same electrode's workbook `Z Score` is at least 1.64.
    Do not call it for the new tool unless adding a clearly named legacy
    compatibility mode.
  - `prepare_scalp_inputs(...)` currently fills missing montage electrodes with
    0 before rendering. For publication maps, preserve missingness in exported
    source data and only convert missing values for rendering after logging the
    missing electrode count.
- `src/Tools/Plot_Generator/scalp_rendering.py`
  - `_plot_scalp_map(...)` has useful MNE `plot_topomap` compatibility
    fallbacks.
  - `_SCALP_CMAP` is blue-green-red centered around 0 and is not acceptable for
    SNR or BCA maps where 0/near-0 must be blue.
- `src/Tools/Plot_Generator/data_collection.py`
  - Existing line-plot data loading prefers `FullSNR` and falls back to
    `FFT Amplitude (uV)`.
  - Existing scalp loading requires `BCA (uV)` and `Z Score` and silently skips
    maps after one warning. The new tool must surface missing sheets/columns as
    per-workbook diagnostics.

Main App embedding anchors:

- `src/Main_App/gui/main_window.py` embeds Stats and Plot Generator pages with
  `_ensure_stats_page(...)` and `_ensure_plot_generator_page(...)`.
- `src/Main_App/gui/sidebar.py` owns Workspace Tools sidebar buttons.
- `src/Main_App/gui/tool_workflows.py` still contains subprocess launch helpers
  for some standalone tools. Prefer the embedded-page pattern for this feature.

Existing tests:

- `tests/plot_generator/test_plot_generator_scalp_utils.py` only covers
  duplicate electrode handling and cached BioSemi64 info reuse.
- `tests/stats/analysis/test_full_snr_reference_equivalence.py` protects SNR
  helper behavior.
- `tests/stats/analysis/test_fixed_predefined_harmonics.py` protects the locked
  Stats group-significant harmonic policy.

## Scope Decision

Build a separate embedded publication-map tool. Do not overload the current
Stats single-group analysis pipeline and do not add more behavior to the SNR
line Plot Generator.

Preferred package:

- `src/Tools/Publication_Maps/`

Suggested module split:

- `__init__.py`: public package surface.
- `models.py`: dataclasses/enums for metric, harmonic mode, request, result,
  diagnostics, and exported frame names.
- `excel_inputs.py`: workbook discovery, exact frequency-column parsing, and
  sheet reads.
- `metrics.py`: SNR, BCA, and z-score per-electrode value builders.
- `harmonics.py`: manual list, highest-harmonic expansion, and optional Stats
  group-significant selection integration.
- `scalp_io.py`: BioSemi64 alignment and source-data frame building.
- `rendering.py`: MNE topomap rendering and metric-specific color scales.
- `worker.py`: QObject worker or QRunnable wrapper with progress/error signals.
- `gui.py`: embedded PySide6 page.
- `AGENTS.md`: scoped ownership/verification notes after the package exists.

If implementation discovers a stronger local naming convention, keep the package
purpose-based and update this plan plus the nearest scoped `AGENTS.md`.

## Hard Constraints

- Preserve the locked Stats group-significant method. Do not change z > 1.64,
  the locked 1.2 Hz oddball spacing, exact-column requirements, noise-window
  bins, base-rate exclusion, candidate generation, or BCA summation in
  `Tools.Stats`.
- Do not use nearest-bin matching for Stats group-significant selection or
  selected BCA summation. For publication maps, only allow nearest-bin behavior
  if it is a user-visible option with exported provenance; default must be exact
  frequency columns.
- Do not use workbook `Z Score` sheets as a replacement for the Stats
  group-significant z calculation.
- Do not reuse `Plot_Generator.summarize_subject_scalp(...)` as the default
  BCA map calculation.
- Do not alter existing Plot Generator line-plot output, filenames, group
  overlay behavior, or scalp-map checkbox behavior as part of this tool.
- Do not write outputs outside the selected output folder or active project
  results folder.
- Do not add Source Localization/eLORETA or MRI template dependencies.
- Do not block the UI thread. Long workbook reads and rendering must run through
  worker signals.
- Do not run offscreen Qt workflows in this repo.
- Use PySide6 only; do not introduce Tkinter, CustomTkinter, PyQt, or blocking
  modal progress loops.

## Method Defaults

Use these defaults unless the user explicitly changes the publication method:

- Project input: active project Excel root, with condition subfolders matching
  the existing FPVS workbook layout.
- Subject inclusion: all workbooks in the selected condition after applying any
  user-visible subject exclusions added by the new tool.
- Electrode labels: normalize by `str.upper().strip()` first. Log and export
  any workbook electrode that is not in the BioSemi64 montage.
- Frequency columns: exact `"{freq:.4f}_Hz"` columns are preferred. Accept
  existing workbook labels with parseable numeric prefixes, but record the
  original column label in provenance.
- Harmonic modes for MVP, in this order:
  1. Single frequency in Hz.
  2. Explicit comma-separated frequency list.
  3. Highest oddball harmonic mode: expand locked 1.2 Hz multiples up to the
     entered highest frequency and exclude base-rate overlaps using the Stats
     base-overlap tolerance.
  4. Stats selected significant harmonics: call
     `build_group_significant_harmonic_selection(...)` or the Stats DV policy
     facade and use its `selected_harmonics_hz`.
- SNR map: read `FullSNR` at selected harmonics. If `FullSNR` is missing, read
  `FullFFT Amplitude (uV)` and use `compute_full_snr_from_amplitudes(...)`.
- BCA map: read `BCA (uV)` and sum selected harmonic columns per electrode
  before condition-level subject averaging.
- Z-score map MVP: read workbook `Z Score` values at selected harmonics and
  average within condition. If recomputed grand-average z maps are later added,
  make them a separate mode with a distinct export label.
- Multi-harmonic SNR and Z maps: do not silently collapse across harmonics.
  Either render one map per harmonic or use an explicitly labeled aggregate mode.
- Missing subject/electrode cells: ignore NaN values during subject averaging,
  keep per-electrode valid-subject counts, and export those counts.

## Color And Rendering Rules

- SNR and BCA maps must use a sequential scale where `vmin=0` maps to blue by
  default. Do not use `TwoSlopeNorm(vcenter=0)` for these maps.
- Export signed BCA source values even if the rendered BCA map clips negative
  values to the low blue color. The source workbook must make clipping visible.
- Z-score maps may use a diverging scale only if the label and colorbar make the
  interpretation clear. If using a threshold, show/export the threshold value.
- Colorbar labels must be metric-specific: `SNR`, `BCA (uV)`, or `z score`.
- Save PNG and SVG. Default PNG should be at least 300 DPI.
- Every exported figure title or metadata block must name condition, metric,
  harmonic mode, selected harmonics, and subject count.
- Rendering failures from MNE must surface as worker errors or per-map
  diagnostics, not disappear behind a blank saved image.

## Implementation Order

### 1. Non-GUI Core

Create the package with GUI-free dataclasses and pure functions first. Add tests
before wiring into the Main App shell.

Minimum outputs from the core:

- `long_values`: one row per condition, subject, electrode, metric, harmonic,
  source sheet, source column, and raw value.
- `grand_average_values`: one row per condition, electrode, metric, aggregate
  value, valid subject count, selected harmonics, and render value.
- `diagnostics`: missing sheets, missing columns, missing montage electrodes,
  empty maps, and fallback SNR calculations.

### 2. Harmonic Selection

Implement manual/single/highest-harmonic modes first. Then add Stats selected
harmonics by calling the existing Stats selection path. When using Stats
selection, pass the same selected participants, conditions, base frequency,
ROIs, and max frequency that the user selected in the publication tool.

Do not copy/paste the Stats z/noise algorithm into the new package.

### 3. Rendering

Extract or wrap the reusable MNE compatibility behavior from Plot Generator, but
keep publication colormap and colorbar policy in the new package. Add a
non-GUI rendering smoke test that confirms generated PNG/SVG files are non-empty
and the image is not blank.

### 4. Worker

Wire the non-GUI core into a worker with progress, message, error, and finished
signals. Workers may read files and render figures but must not touch widgets.

### 5. Embedded GUI

Follow existing embedded page patterns in `src/Main_App/gui/main_window.py`.
Use active components from `src/Main_App/gui/components/` where practical.

Required controls:

- Input project/folder display and refresh.
- Conditions multi-select.
- Metric checkboxes for SNR, BCA, and z score.
- Harmonic mode selector and exact-frequency entry/highest-harmonic entry.
- Base frequency display/input if needed for base-rate exclusion.
- Color bounds per metric with an auto-scale option.
- Output folder and format selection.
- Run/cancel buttons and visible diagnostics/status log.

### 6. Main App Registration

After the embedded page exists:

- Add a public import surface for the tool.
- Add an `_ensure_publication_maps_page(...)` method to `main_window.py`.
- Add an `open_publication_maps(...)` method that switches the workspace stack.
- Add a Workspace Tools sidebar button in `sidebar.py`.
- Avoid subprocess launch plumbing unless packaging requires it; if required,
  mirror `tool_workflows.open_plot_generator(...)` and pass `FPVS_PROJECT_ROOT`.

### 7. Docs

Update docs only after behavior is settled:

- New scoped `src/Tools/Publication_Maps/AGENTS.md`.
- `docs/agent/architecture/statistics-tools.md` if ownership or tool layout
  changes.
- User-facing docs for publication map inputs, harmonic modes, color scales,
  and exported workbook interpretation.

## Tests To Add

Suggested focused tests:

- `tests/publication_maps/test_harmonic_modes.py`
  - exact list parsing;
  - highest-harmonic expansion using locked 1.2 Hz spacing;
  - base-rate overlap exclusion;
  - Stats selected-harmonics integration with a stub selection.
- `tests/publication_maps/test_excel_inputs.py`
  - condition workbook discovery;
  - exact column parsing;
  - missing `FullSNR`, `BCA (uV)`, or `Z Score` diagnostics.
- `tests/publication_maps/test_metric_values.py`
  - SNR from `FullSNR`;
  - SNR fallback from `FullFFT Amplitude (uV)`;
  - BCA per-electrode harmonic summation;
  - Z Score workbook mode;
  - valid-subject counts and NaN handling.
- `tests/publication_maps/test_rendering.py`
  - BioSemi64 alignment;
  - low values map to blue for SNR/BCA colormaps;
  - PNG/SVG non-empty output.
- `tests/publication_maps/test_worker.py`
  - worker emits diagnostics and completion without widget access.

Do not run pytest-qt/offscreen tests locally. If adding GUI smoke definitions,
leave local verification to non-GUI tests and a visible manual smoke path.

## Verification Plan

Use `.venv` in this checkout unless `.venv1` is restored.

```powershell
.\.venv\Scripts\python.exe -m py_compile src\Tools\Publication_Maps\*.py
.\.venv\Scripts\python.exe -m pytest tests\publication_maps -q
.\.venv\Scripts\python.exe -m pytest tests\stats\analysis\test_full_snr_reference_equivalence.py tests\stats\analysis\test_fixed_predefined_harmonics.py -q
.\.venv\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_scalp_utils.py -q
.\.venv\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-structure
```

Manual visible smoke path after GUI wiring:

1. Launch FPVS Toolbox normally.
2. Open a project with generated Excel workbooks.
3. Open the Publication Scalp Maps page from Workspace Tools.
4. Select one condition, SNR/BCA/z metrics, and one exact harmonic.
5. Generate maps.
6. Confirm PNG/SVG figures and source-data workbook exist in the selected output
   folder.
7. Confirm diagnostics report selected harmonics, subject counts, missing
   electrodes, and any fallback SNR behavior.

## Completion Criteria

- Condition-level grand averages are computed per electrode for SNR, BCA, and
  z-score maps.
- SNR and BCA maps render 0/near-0 values in blue.
- Exported source data traces every plotted value to condition, subject,
  electrode, metric, harmonic, source sheet, and source column.
- The tool is embedded in the Main App without blocking the UI thread.
- Existing Stats DV policy behavior and Plot Generator line plot behavior remain
  unchanged.
