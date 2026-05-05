# Legacy Quarantine Audit (2026-03-05)

This audit is based on static AST import analysis of `src/` and `tests/`.

Legend:
- `Runtime-used`: imported by non-legacy `src/` modules directly, via `from Main_App import ...` proxy, or through transitive legacy dependencies.
- `Test-only`: not used by runtime `src/`, but imported by tests.
- `Quarantine candidates`: not referenced by runtime `src/` or tests.

## Runtime-used (do not quarantine yet)

- `src/Main_App/Legacy_App/settings_manager.py`
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

## Main_App Legacy_App migration inventory (2026-05-05)

`src/Main_App/Legacy_App/**` is a temporary migration boundary, not a permanent architecture. Targeted edits are allowed for active refactors only when they preserve the processing pipeline, processing order, data formats, and exports.

Already has current-app replacement or bridge:

- `settings_manager.py`: current shared implementation exists at `src/Main_App/Shared/settings_manager.py`; keep compatibility imports stable while remaining callers are migrated.
- `eeg_preprocessing.py`: current PySide6 preprocessing implementation exists at `src/Main_App/PySide6_App/Backend/preprocess.py`; active runtime and tests no longer import the legacy module. Keep the legacy file untouched until a later deletion or wrapper slice is explicitly scoped.
- `post_process.py`: current shared implementation exists at `src/Main_App/Shared/post_process.py`; legacy module remains as a temporary compatibility wrapper.
- `post_process_excel.py`: current shared implementation exists at `src/Main_App/Shared/post_process_excel.py`; legacy module remains as a temporary compatibility wrapper.
- `debug_utils.py`: no longer imported by `MainWindow`; retained for logging/settings compatibility without Tk messagebox imports.
- `file_selection.py`: no longer inherited by `MainWindow`; retained for stale compatibility and now uses PySide6 dialogs.
- `processing_utils.py`: current shared implementation exists at `src/Main_App/Shared/processing_mixin.py`; legacy module remains as a temporary compatibility wrapper.
- `load_utils.py`: current shared implementation exists at `src/Main_App/Shared/load_utils.py`; legacy module remains as a temporary compatibility wrapper.

Compatibility wrappers:

- `fft_crop_utils.py`: retained only as a temporary import-compatible wrapper around `src/Main_App/Shared/fft_crop_utils.py`; current runtime callers import the shared owner.
- `post_process.py`: retained only as a temporary import-compatible wrapper around `src/Main_App/Shared/post_process.py`; current runtime callers import the shared owner.
- `post_process_excel.py`: retained only as a temporary import-compatible wrapper around `src/Main_App/Shared/post_process_excel.py`; current runtime callers import the shared owner.
- `processing_utils.py`: retained only as a temporary import-compatible wrapper around `src/Main_App/Shared/processing_mixin.py`; current runtime callers import the shared owner.
- `load_utils.py`: retained only as a temporary import-compatible wrapper around `src/Main_App/Shared/load_utils.py`; current runtime callers import the shared owner.

Recent migration slices:

- Event-map GUI row behavior was extracted from `src/Main_App/PySide6_App/GUI/main_window.py` into `src/Main_App/PySide6_App/GUI/event_map.py`.
- eLORETA/Source Localization was removed from active runtime because it has no working GUI access path and is not part of the current app.
- Tkinter/CustomTkinter runtime code was removed from active Main App paths; user dialogs now route through PySide6-safe helpers.
- Processing mixin ownership moved to `src/Main_App/Shared/processing_mixin.py`; `src/Main_App/Legacy_App/processing_utils.py` is now a compatibility wrapper.
- BDF loader ownership moved to `src/Main_App/Shared/load_utils.py`; `src/Main_App/Legacy_App/load_utils.py` and `src/Main_App/PySide6_App/Backend/loader.py` are now compatibility wrappers.
- Preprocessing ownership for active runtime was locked to `src/Main_App/PySide6_App/Backend/preprocess.py`; GUI processing routes through the PySide6 process runner and no active runtime/test imports point at `src/Main_App/Legacy_App/eeg_preprocessing.py`.

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
- Source Localization/eLORETA branches in `src/Main_App/Legacy_App/processing_utils.py`

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

- `Main_App.__init__` still defines a proxy for `SettingsWindow`, but `src/Main_App/Legacy_App/settings_window.py` does not exist.
- `Main_App.__init__` keeps fail-fast compatibility exports for quarantined `ValidationMixin` and `preprocess_raw`.
