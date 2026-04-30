# Test Selection

Pick the smallest relevant tests first, then broaden when the change affects shared behavior.

## Marker Shortcuts

The repository auto-applies common pytest markers from test filenames during
collection. Use these for quick local selection:

```powershell
python -m pytest -m "not slow and not source_localization" -q
python -m pytest -m gui -q
python -m pytest -m stats -q
python -m pytest -m project_io -q
python -m pytest -m processing -q
python -m pytest -m smoke -q
```

Available markers are declared in `pytest.ini`: `gui`, `stats`, `project_io`,
`processing`, `plot_generator`, `ratio`, `source_localization`, `smoke`,
`integration`, `slow`, and `qt`.

Markers are selection aids, not a substitute for the focused test lists below.
When changing a specific module, run the nearest named test first.

## Main Window And GUI

- Main window layout: `tests/test_main_window_layout_smoke.py`
- Main window processing wiring: `tests/test_main_window_processing.py`
- Preprocessing dialog: `tests/test_gui_preproc_dialog.py`
- Settings/status behavior: `tests/test_settings_and_status.py`
- Startup import hygiene: `tests/test_startup_imports_no_customtkinter.py`

## Project I/O

- Project settings round trip: `tests/test_project_settings_roundtrip.py`
- Project enumeration and scanning: `tests/test_project_enumeration_io.py`, `tests/test_project_scan_job.py`
- Project result layout: `tests/test_project_results_layout.py`
- Open existing project dialog: `tests/test_open_existing_project_dialog.py`

## Processing Pipeline

- Preprocessing persistence and snapshots: `tests/test_preproc_persistence.py`, `tests/test_preproc_settings_snapshot.py`
- Pipeline speed and safety: `tests/test_pipeline_speed_safety.py`
- Process runner contracts: `tests/test_process_runner_epoch_contract.py`
- Post-processing worker: `tests/test_postprocess_worker_qt.py`, `tests/test_postprocess_worker_excel_payload.py`

## Plot Generator

- GUI smoke and layout: `tests/test_plot_generator_gui.py`, `tests/test_plot_generator_gui_layout_smoke.py`
- FFT/SNR behavior: `tests/test_plot_generator_fft_snr.py`, `tests/test_plot_generator_full_snr_roi.py`
- Exports and manifests: `tests/test_plot_generator_export_svg_smoke.py`, `tests/test_plot_generator_project_defaults.py`

## Ratio Calculator

- Plot behavior: `tests/test_ratio_calculator_plots.py`
- Dynamic ROI behavior: `tests/test_ratio_calculator_roi_dynamic.py`
- Removed legacy smoke: `tests/test_ratio_calculator_removed_smoke.py`

## Statistics

- GUI/layout smoke: `tests/test_stats_layout_smoke.py`, `tests/test_stats_window_smoke_phase0.py`
- Pipeline smoke: `tests/test_stats_pipeline_smoke.py`, `tests/test_stats_multigroup_smoke.py`
- File scanning and project paths: `tests/test_stats_file_scanner.py`, `tests/test_stats_project_paths.py`
- DV and reporting rules: `tests/test_stats_dv_policy.py`, `tests/test_stats_reporting_summary_smoke.py`
- CustomTkinter quarantine: `tests/test_stats_no_customtkinter_import.py`, `tests/test_stats_legacy_ui_quarantine.py`

## Source Localization

Source Localization is quarantined dead code. Prefer availability-shim tests only:

- `tests/test_source_localization_optional_smoke.py`
- `tests/test_source_localization_import.py`

Do not add new tests that import active `Tools.SourceLocalization` unless the feature is explicitly restored.
