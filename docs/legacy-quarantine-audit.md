# Legacy Quarantine Audit (2026-03-05)

This audit is based on static AST import analysis of `src/` and `tests/`.

Legend:
- `Runtime-used`: imported by non-legacy `src/` modules directly, via `from Main_App import ...` proxy, or through transitive legacy dependencies.
- `Test-only`: not used by runtime `src/`, but imported by tests.
- `Quarantine candidates`: not referenced by runtime `src/` or tests.

## Runtime-used (do not quarantine yet)

- `src/Main_App/Legacy_App/debug_utils.py`
- `src/Main_App/Legacy_App/eeg_preprocessing.py`
- `src/Main_App/Legacy_App/eloreta_launcher.py`
- `src/Main_App/Legacy_App/fft_crop_utils.py`
- `src/Main_App/Legacy_App/file_selection.py`
- `src/Main_App/Legacy_App/load_utils.py`
- `src/Main_App/Legacy_App/post_process.py`
- `src/Main_App/Legacy_App/post_process_excel.py`
- `src/Main_App/Legacy_App/processing_utils.py`
- `src/Main_App/Legacy_App/settings_manager.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_base.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_file_ops.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_group_ops.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_post.py`
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_processing.py`
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

## Newly quarantined after follow-up cleanup

- `src/Main_App/Legacy_App/app_logic.py` -> moved to `src/quarantine/Main_App/Legacy_App/app_logic.py`
- `src/Main_App/Legacy_App/validation_mixins.py` -> moved to `src/quarantine/Main_App/Legacy_App/validation_mixins.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/stats.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/stats.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/stats_ui.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/stats_ui.py`
- `src/Tools/Stats/Quarantined/Legacy_UI/__init__.py` -> moved to `src/quarantine/Tools/Stats/Legacy_UI/__init__.py`

## Source Localization dead-code quarantine

- `src/Tools/SourceLocalization/**` is no longer an active black-box module and must remain empty of source files.
- The ignored reference copy under `src/quarantine/Tools/LORETA/SourceLocalization/**` is quarantined dead code.
- Do not revive imports from `Tools.SourceLocalization` or `quarantine.Tools.LORETA.SourceLocalization` unless Source Localization is explicitly restored.

## Quarantine candidates (no runtime/test import references found)

- `src/Main_App/Legacy_App/eloreta_gui.py` -> moved to `src/quarantine/Main_App/Legacy_App/eloreta_gui.py`
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
