# Legacy Quarantine Audit (2026-03-05)

This audit is based on static AST import analysis of `src/` and `tests/`.

Legend:
- `Runtime-used`: imported by non-legacy `src/` modules directly, via `from Main_App import ...` proxy, or through transitive legacy dependencies.
- `Test-only`: not used by runtime `src/`, but imported by tests.
- `Quarantine candidates`: not referenced by runtime `src/` or tests.

## Runtime-used (do not quarantine yet)

- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`
- `src/Tools/Stats/cli/between_groups_cli.py`
- `src/Tools/Stats/common/blas_limits.py`
- `src/Tools/Stats/analysis/cross_phase_lmm_core.py`
- `src/Tools/Stats/io/excel_io.py`
- `src/Tools/Stats/analysis/full_snr.py`
- `src/Tools/Stats/analysis/group_contrasts.py`
- `src/Tools/Stats/analysis/interpretation_helpers.py`
- `src/Tools/Stats/analysis/mixed_effects_model.py`
- `src/Tools/Stats/analysis/mixed_group_anova.py`
- `src/Tools/Stats/analysis/noise_utils.py`
- `src/Tools/Stats/analysis/posthoc_tests.py`
- `src/Tools/Stats/analysis/repeated_m_anova.py`
- `src/Tools/Stats/analysis/stats_analysis.py`
- `src/Tools/Stats/reporting/stats_export.py`

The old `src/Tools/Stats/Legacy/**` compatibility namespace has been removed.
The moved statistical engines now live under the active `src/Tools/Stats/`
functional packages listed above.

## Main_App Legacy_App retirement inventory (2026-05-05)

`src/Main_App/Legacy_App/**` has been retired. Do not recreate this directory; active behavior belongs in purpose-based `Main_App` packages.

Already has current-app replacement or bridge:

- `settings_manager.py`: deleted after current shared implementation ownership moved to `src/Main_App/Shared/settings_manager.py`.
- `eeg_preprocessing.py`: deleted after confirming active preprocessing imports use `src/Main_App/processing/preprocess.py`.
- `post_process.py`: deleted after current shared implementation ownership moved to `src/Main_App/Shared/post_process.py`.
- `post_process_excel.py`: deleted after current shared implementation ownership moved to `src/Main_App/Shared/post_process_excel.py`.
- `processing_utils.py`: deleted after current shared implementation ownership moved to `src/Main_App/Shared/processing_mixin.py`.
- `load_utils.py`: deleted after active import surface moved to `src/Main_App/io/load_utils.py` and implementation ownership moved to `src/Main_App/Shared/load_utils.py`.

Compatibility wrappers:

- No `src/Main_App/Legacy_App/**` compatibility wrappers remain.

Recent migration slices:

- Legacy debug/file-selection cleanup removed `src/Main_App/Legacy_App/debug_utils.py`, `src/Main_App/Legacy_App/file_selection.py`, stale top-level lazy exports for missing/quarantined Legacy GUI modules, and the GUI smoke stub for `Main_App.Legacy_App.debug_utils`.
- Legacy settings/loader/mixin wrapper cleanup removed `src/Main_App/Legacy_App/settings_manager.py`, `src/Main_App/Legacy_App/load_utils.py`, and `src/Main_App/Legacy_App/processing_utils.py` after grep confirmed no active callers.
- Legacy FFT/post-processing wrapper cleanup removed `src/Main_App/Legacy_App/fft_crop_utils.py`, `src/Main_App/Legacy_App/post_process.py`, and `src/Main_App/Legacy_App/post_process_excel.py` after grep confirmed no active callers.
- Final Legacy_App cleanup removed inactive `src/Main_App/Legacy_App/eeg_preprocessing.py`, `src/Main_App/Legacy_App/AGENTS.md`, and `src/Main_App/Legacy_App/__init__.py` after preprocessing ownership checks confirmed no active callers.
- Event-map GUI row behavior now lives in `src/Main_App/gui/event_map.py`.
- eLORETA/Source Localization was removed from active runtime because it has no working GUI access path and is not part of the current app.
- Tkinter/CustomTkinter runtime code was removed from active Main App paths; user dialogs now route through PySide6-safe helpers.
- Processing mixin ownership moved to `src/Main_App/Shared/processing_mixin.py`; the legacy wrapper has been deleted.
- BDF loader import ownership moved to `src/Main_App/io/load_utils.py`; implementation still lives in `src/Main_App/Shared/load_utils.py`.
- Preprocessing ownership for active runtime was locked to `src/Main_App/processing/preprocess.py`; GUI processing routes through the active process runner and no active runtime/test imports point at retired Legacy_App preprocessing paths.

## Main_App PySide6_App retirement inventory (2026-05-06)

`src/Main_App/PySide6_App/**` has been retired. Do not recreate this directory; PySide6 runtime behavior now belongs in purpose-based `Main_App` packages such as `gui`, `processing`, `projects`, `workers`, `io`, `diagnostics`, and `exports`.

Recent migration slices:

- GUI shell, settings, event-map, sidebar, UI assembly, style-token, update-manager, and widget implementations moved to `src/Main_App/gui/`.
- Processing-controller and preprocessing implementations moved to `src/Main_App/processing/`.
- Qt worker and multiprocessing bridge implementations moved to `src/Main_App/workers/`.
- Runtime diagnostics moved to `src/Main_App/diagnostics/`.
- Project model/manager/settings/root helpers moved to `src/Main_App/projects/`.
- Post-export adapter ownership moved to `src/Main_App/exports/`.
- Final cleanup deleted the old `src/Main_App/PySide6_App/**` package tree after active source/test/script imports were migrated.

## Newly quarantined after follow-up cleanup

- `src/Main_App/Legacy_App/app_logic.py` -> moved to `src/quarantine/Main_App/Legacy_App/app_logic.py`
- `src/Main_App/Legacy_App/validation_mixins.py` -> moved to `src/quarantine/Main_App/Legacy_App/validation_mixins.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/stats.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/stats.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/stats_ui.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/stats_ui.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/__init__.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/__init__.py`

## Source Localization/eLORETA removal

- Source Localization/eLORETA has been removed from active runtime, GUI menus, settings, tracked tests, and active migration shims.
- `src/Tools/SourceLocalization/**` must remain empty of source files.
- Do not revive imports from `Tools.SourceLocalization` or quarantine-tree Source Localization code unless restoration is explicitly scoped as a new feature.

Removed from active runtime after the Main App refactor slice:

- `src/Main_App/Legacy_App/eloreta_launcher.py`
- `src/Main_App/Shared/source_localization_optional.py`
- Source Localization/eLORETA branches in the deleted `src/Main_App/Legacy_App/processing_utils.py`

## Quarantine candidates (no runtime/test import references found)

- `src/Main_App/Legacy_App/event_detection.py` -> moved to `src/quarantine/Main_App/Legacy_App/event_detection.py`
- `src/Main_App/Legacy_App/event_map_utils.py` -> moved to `src/quarantine/Main_App/Legacy_App/event_map_utils.py`
- `src/Main_App/Legacy_App/fpvs_app_legacy.py` -> moved to `src/quarantine/Main_App/Legacy_App/fpvs_app_legacy.py`
- `src/Main_App/Legacy_App/logging_mixin.py` -> moved to `src/quarantine/Main_App/Legacy_App/logging_mixin.py`
- `src/Main_App/Legacy_App/menu_bar.py` -> moved to `src/quarantine/Main_App/Legacy_App/menu_bar.py`
- `src/Main_App/Legacy_App/relevant_publications_window.py` -> moved to `src/quarantine/Main_App/Legacy_App/relevant_publications_window.py`
- `src/Main_App/Legacy_App/roi_settings_editor.py` -> moved to `src/quarantine/Main_App/Legacy_App/roi_settings_editor.py`
- `src/Main_App/Legacy_App/test_fft_onbin.py` -> moved to `src/quarantine/Main_App/Legacy_App/test_fft_onbin.py`
- `src/Main_App/Legacy_App/ui_event_map_manager.py` -> moved to `src/quarantine/Main_App/Legacy_App/ui_event_map_manager.py`
- `src/Main_App/Legacy_App/ui_setup_panels.py` -> moved to `src/quarantine/Main_App/Legacy_App/ui_setup_panels.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_demo.py` -> moved to `src/quarantine/Tools/Average_Preprocessing/Legacy/advanced_analysis_demo.py`

## Note

- `Main_App.__init__` no longer defines lazy exports for missing/quarantined Legacy GUI modules.
- `Main_App.__init__` still keeps fail-fast `preprocess_raw` compatibility while active preprocessing uses `Main_App.processing.preprocess`.
