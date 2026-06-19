# Test Selection

Pick the smallest relevant tests first, then broaden when the change affects shared behavior.

## GUI Execution Boundary

Do not run offscreen Qt workflows in this repo. Do not set
`QT_QPA_PLATFORM=offscreen`, do not run pytest-qt/offscreen GUI tests, and do
not launch ad-hoc offscreen Qt scripts; they can freeze or hang indefinitely in
this Windows environment.

For GUI changes, update focused pytest-qt coverage when useful, but verify
locally with non-GUI checks such as `py_compile`, focused `ruff`,
`.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`, and
`.agents/scripts/audit/agent_audit.py --check gui`. Document a visible/manual
smoke path instead of running offscreen GUI tests unless the user explicitly
approves a safe visible GUI test environment.

## Marker Shortcuts

The repository auto-applies common pytest markers from test filenames during
collection. Use these for quick local selection:

```powershell
python -m pytest -m "not slow" -q
python -m pytest -m gui -q
python -m pytest -m stats -q
python -m pytest -m project_io -q
python -m pytest -m processing -q
python -m pytest -m smoke -q
```

Available markers are declared in `pyproject.toml`: `gui`, `stats`, `project_io`,
`processing`, `plot_generator`, `ratio`, `smoke`, `integration`, `slow`, and
`qt`.

Markers are selection aids, not a substitute for the focused test lists below.
When changing a specific module, run the nearest named test first.

## Category Folders

Tests are grouped by workflow under `tests/audit/`, `tests/gui/`,
`tests/processing/`, `tests/project_io/`, `tests/plot_generator/`,
`tests/publication_maps/`, `tests/publication_report/`,
`tests/ratio_calculator/`, and `tests/stats/`.

## Figure Generation

- Shared figure style contract and GUI-typography boundary:
  `python -m pytest tests/audit/test_figure_style_contract.py -q`
- Plot Generator export pairs:
  `python -m pytest tests/plot_generator/test_plot_generator_export_pdf_smoke.py tests/plot_generator/test_plot_generator_group_overlay_worker.py -q`
- Publication Maps figure output and typography:
  `python -m pytest tests/publication_maps/test_bca_publication_maps.py -q`
- Ratio Calculator figure output:
  `python -m pytest tests/ratio_calculator/test_ratio_calculator_plots.py -q`
- Individual Detectability figure output:
  `python -m pytest tests/processing/test_individual_detectability_core.py -q`
- LORETA Visualizer split-hemisphere figure output:
  `python -m pytest tests/loreta/test_demo_conditions.py tests/loreta/test_project_l2_mne_export.py -q`

## Main Window And GUI

The targets below identify relevant coverage only; do not run them locally via
pytest-qt/offscreen unless explicitly approved.

- Main window layout: `tests/gui/test_main_window_layout_smoke.py`
- Main window processing wiring: `tests/gui/test_main_window_processing.py`
- Preprocessing dialog: `tests/gui/test_gui_preproc_dialog.py`
- Settings/status behavior: `tests/gui/test_settings_and_status.py`
- Startup import hygiene: `tests/audit/test_startup_imports_no_customtkinter.py`

## Project I/O

- Project settings round trip: `tests/project_io/test_project_settings_roundtrip.py`
- Project enumeration and scanning: `tests/project_io/test_project_enumeration_io.py`, `tests/project_io/test_project_scan_job.py`
- Project result layout: `tests/project_io/test_project_results_layout.py`
- Open existing project dialog: `tests/project_io/test_open_existing_project_dialog.py`

## Processing Pipeline

- Processing order and cache fingerprint: `tests/processing/test_filter_downsample_order.py`
- Preprocessing persistence and snapshots: `tests/processing/test_preproc_persistence.py`, `tests/processing/test_preproc_settings_snapshot.py`
- Pipeline speed and safety: `tests/processing/test_pipeline_speed_safety.py`
- FFT crop/bin-lock contract: `tests/processing/test_fft_crop_utils.py`
- Process runner contracts: `tests/processing/test_process_runner_epoch_contract.py`
- Post-processing worker: `tests/processing/test_postprocess_worker_qt.py`, `tests/processing/test_postprocess_worker_excel_payload.py`

## Plot Generator

The GUI targets below identify relevant coverage only; do not run them locally
via pytest-qt/offscreen unless explicitly approved.

- GUI smoke and layout: `tests/plot_generator/test_plot_generator_gui.py`, `tests/plot_generator/test_plot_generator_gui_layout_smoke.py`
- Worker helper contracts: `tests/plot_generator/test_plot_generator_excel_inputs.py`, `tests/plot_generator/test_plot_generator_worker_config.py`
- FFT/SNR behavior: `tests/plot_generator/test_plot_generator_fft_snr.py`, `tests/plot_generator/test_plot_generator_full_snr_roi.py`
- Exports and manifests: `tests/plot_generator/test_plot_generator_export_pdf_smoke.py`, `tests/plot_generator/test_plot_generator_project_defaults.py`
- Full focused suite after worker/rendering changes: `python -m pytest tests/plot_generator -q`

## Publication Maps

The GUI target below identifies relevant coverage only; do not run it locally
via pytest-qt/offscreen unless explicitly approved.

- Scalp-map source workbook, BCA/SNR rendering contracts, selected harmonics,
  paired-condition output, and colorbar behavior:
  `python -m pytest tests/publication_maps/test_bca_publication_maps.py -q`
- After changing shared harmonic-selection behavior, also run
  `python -m pytest tests/stats/analysis/test_fixed_predefined_harmonics.py tests/stats/analysis/test_full_snr_reference_equivalence.py -q`

## Publication Report

The GUI target below identifies relevant coverage only; do not run it locally
via pytest-qt/offscreen unless explicitly approved.

- Headless report runner, source workbook, audit JSON, Markdown, DOCX, default
  ROIs, exclusions, single-group guard, and generated report tables:
  `python -m pytest tests/publication_report/test_publication_report_runner.py -q`
- GUI wiring changes should use `py_compile` on
  `src/Tools/Publication_Report/gui.py`, focused `ruff`, agent audits, and a
  documented visible/manual smoke path for the embedded sidebar page.

## Ratio Calculator

- Plot behavior: `tests/ratio_calculator/test_ratio_calculator_plots.py`
- Dynamic ROI behavior: `tests/ratio_calculator/test_ratio_calculator_roi_dynamic.py`
- Removed legacy smoke: `tests/ratio_calculator/test_ratio_calculator_removed_smoke.py`
- GUI refactor boundaries: use `py_compile` on `src/Tools/Ratio_Calculator/gui.py`
  plus its focused GUI mixins; do not run pytest-qt/offscreen locally without
  explicit approval.

## Sequence Figure

- Renderer behavior and high-DPI export: `python -m pytest tests/sequence_figure -q`
- GUI wiring changes should use `py_compile` on `src/Tools/Sequence_Figure/gui.py`,
  focused `ruff`, GUI import audits, and a documented visible/manual smoke path.
  Do not run pytest-qt/offscreen locally.

## Statistics

The GUI targets below identify relevant coverage only; do not run them locally
via pytest-qt/offscreen unless explicitly approved.

- GUI/layout smoke: `tests/stats/gui/test_stats_layout_smoke.py`, `tests/stats/gui/test_stats_window_smoke_phase0.py`
- Pipeline smoke: `tests/stats/pipeline/test_stats_pipeline_smoke.py`
- File scanning and project paths: `tests/stats/pipeline/test_stats_file_scanner.py`, `tests/stats/pipeline/test_stats_project_paths.py`, `tests/stats/data/test_stats_project_context.py`
- DV, harmonic-selection, FullSNR, and reporting rules: `tests/stats/analysis/test_stats_dv_policy.py`, `tests/stats/analysis/test_fixed_predefined_harmonics.py`, `tests/stats/analysis/test_full_snr_reference_equivalence.py`, `tests/stats/reporting/test_stats_reporting_summary_smoke.py`
- Summary reporting: `tests/stats/analysis/test_summary_utils_mixed_model.py`, `tests/stats/analysis/test_summary_utils_posthoc_directions.py`, `tests/stats/reporting/test_lmm_reporting_exports.py`, `tests/stats/reporting/test_stats_rm_anova_summary_reporting.py`
- Reporting audit guardrails: `tests/audit/test_agent_audit_stats_reporting_legibility.py`
- CustomTkinter quarantine: `tests/audit/test_stats_no_customtkinter_import.py`, `tests/audit/test_stats_legacy_ui_quarantine.py`

## Removed Source Localization

Source Localization/eLORETA has been removed from active runtime. Do not add tests that import `Tools.SourceLocalization`, restore availability shims, or assert GUI/settings behavior unless restoration is explicitly scoped as a new feature.
Do not add tests that require bundled `fsaverage` MRI template data; that template is no longer retained in active source or quarantine.
