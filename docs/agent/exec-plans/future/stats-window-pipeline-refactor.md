# Stats Window Pipeline Refactor

## Status

Future plan. This work has not started.

## Target

`src/Tools/Stats/ui/stats_window_pipeline.py`

## Summary

`stats_window_pipeline.py` is the Stats view-side pipeline bridge. It implements
the controller view protocol, runs prechecks, builds worker kwargs, wires
`StatsWorker` signals, applies worker payloads to UI state, manages reporting
summary generation, updates export buttons, and handles final UI completion
state. It slows future development because small UI or callback changes require
reasoning through a large mixin with many responsibilities.

Do not move statistical computation in this plan. Keep the controller as the
pipeline coordinator and keep worker job logic in workers/analysis modules.

## Behavior To Preserve

- `StatsWindowPipelineMixin` remains part of the public `StatsWindow` mixin
  composition.
- The methods required by `StatsViewProtocol` remain available on `StatsWindow`:
  `append_log`, `set_busy`, `start_step_worker`, `on_pipeline_started`,
  `on_analysis_finished`, `ensure_pipeline_ready`, `export_pipeline_results`,
  `build_and_render_summary`, `get_step_config`, `store_run_report`,
  `ensure_results_dir`, `prompt_phase_folder`, and
  `get_analysis_settings_snapshot`.
- Worker signals continue to be connected to progress, message, error, and
  finished handlers without dropping workers to garbage collection.
- Button enabled states, spinner behavior, status labels, log lines, blocked
  between-group messages, export button behavior, result dialogs, and reporting
  summary behavior remain stable unless explicitly scoped.
- Keep PySide6-only imports and avoid moving worker code into GUI modules.

## Suggested Seams

Prefer one seam per PR. Keep `StatsWindowPipelineMixin` as a compatibility
facade until the mixin composition is deliberately changed.

1. Run state, logging, and guard helpers:
   - Move `append_log`, `_section_label`, `_log_pipeline_event`, `_focus_self`,
     `_set_running`, `_begin_run`, and `_end_run` to
     `src/Tools/Stats/ui/stats_window_run_state.py`.
   - Preserve log formatting through `format_log_line` and all button/spinner
     enabled-state behavior.

2. Settings and precheck helpers:
   - Move `_safe_settings_get`, `_get_analysis_settings`,
     `_get_harmonic_settings`, `_get_qc_settings`, and `_precheck` to
     `src/Tools/Stats/ui/stats_window_precheck.py`.
   - Preserve Excel-open checks, selected-condition checks, manual-exclusion
     all-excluded checks, ROI refresh, analysis settings, harmonic settings,
     QC thresholds, and optional guard start.

3. Reporting summary helpers:
   - Move `_build_summary_frames`, `_render_summary`,
     `_collect_excluded_reasons`, `_build_reporting_summary_payload`,
     `_start_reporting_summary_worker`, and `_on_report_ready` to
     `src/Tools/Stats/ui/stats_window_reporting.py`.
   - Preserve auto-export behavior, default report path behavior, summary text
     rendering, and non-blocking failure handling.

4. Worker signal wiring:
   - Move `_wire_and_start`, `start_step_worker`, `_on_worker_progress`,
     `_on_worker_message`, and `_on_worker_error` to
     `src/Tools/Stats/ui/stats_window_workers.py`.
   - Preserve active-worker strong references, finished/error release behavior,
     diagnostic log keys, optional `message_cb` wiring, and `_end_run` on
     worker errors.

5. Controller protocol and pipeline lifecycle view methods:
   - Move `set_busy`, `ensure_results_dir`, `prompt_phase_folder`,
     `get_analysis_settings_snapshot`, `ensure_pipeline_ready`,
     `on_pipeline_started`, `on_analysis_finished`,
     `build_and_render_summary`, and `export_pipeline_results` to
     `src/Tools/Stats/ui/stats_window_controller_adapter.py`.
   - Keep concrete UI state access in the view layer; do not import the
     controller from helper modules.

6. Step config builders:
   - Move `_build_harmonic_kwargs` and `get_step_config` to
     `src/Tools/Stats/ui/stats_window_step_config.py`.
   - This is high-risk because kwargs are worker contracts. Preserve every key
     passed to single and between steps, including DV policy, DV variants,
     outlier/QC config/state, manual exclusions, fixed-harmonic DV table,
     prepared multigroup payload, and `results_dir`.

7. Result application and legacy direct-slot handlers:
   - Move `_store_dv_metadata`, `_store_dv_variants`, `_store_run_report`,
     `store_run_report`, `_apply_*_results`, `_on_*_finished`,
     `_on_lela_mode_finished`, and `_on_lela_mode_error` to
     `src/Tools/Stats/ui/stats_window_results.py`.
   - Preserve dataframe attributes, stored pipeline metadata, summary text
     updates, export button refreshes, Lela completion logs, and `_end_run`
     behavior.

## Suggested Final Shape

- `src/Tools/Stats/ui/stats_window_pipeline.py` as a facade or thin mixin that
  composes/re-exports smaller mixins.
- `src/Tools/Stats/ui/stats_window_run_state.py`
- `src/Tools/Stats/ui/stats_window_precheck.py`
- `src/Tools/Stats/ui/stats_window_reporting.py`
- `src/Tools/Stats/ui/stats_window_workers.py`
- `src/Tools/Stats/ui/stats_window_controller_adapter.py`
- `src/Tools/Stats/ui/stats_window_step_config.py`
- `src/Tools/Stats/ui/stats_window_results.py`

Avoid circular imports with `stats_controller.py`; helper mixins should depend
on common types from `Tools.Stats.common.stats_core` and support utilities, not
on concrete controller internals.

## What Future Agents Should Inspect First

1. `docs/agent/architecture/statistics-tools.md`
2. `src/Tools/Stats/ui/stats_window_pipeline.py`
3. `src/Tools/Stats/ui/stats_window.py`
4. `src/Tools/Stats/ui/stats_main_window.py`
5. `src/Tools/Stats/ui/stats_window_support.py`
6. `src/Tools/Stats/controller/stats_controller.py`
7. Tests that monkeypatch `StatsWindow.start_step_worker`,
   `ensure_pipeline_ready`, or `on_analysis_finished`

Before editing, run:

```powershell
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
```

## Verification Plan

Run targeted pipeline/view tests first:

```powershell
python -m py_compile src\Tools\Stats\ui\stats_window_pipeline.py
python -m pytest tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_condition_selection.py -q
python -m pytest tests\stats\analysis\test_stats_mixed_model_pipeline.py tests\stats\pipeline\test_stats_multigroup_lmm_signoff.py tests\stats\pipeline\test_stats_multigroup_smoke.py -q
python -m pytest tests\stats\pipeline\test_stats_finalize_error_paths.py tests\stats\pipeline\test_stats_export_finalization_release_smoke.py tests\stats\gui\test_stats_window_errors_stats.py -q
python -m pytest tests\stats\reporting\test_stats_reporting_summary_smoke.py tests\stats\reporting\test_stats_rm_anova_summary_reporting.py -q
python .agents\\scripts\\audit\\agent_audit.py --check stats-structure
```

Add pytest-qt smoke coverage when moving methods that update enabled states,
status labels, dialogs, or signal wiring.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Exact methods moved and their old/new module paths.
- Whether `StatsWindowPipelineMixin` remains a facade or still owns behavior.
- Which controller protocol methods were verified.
- Signal wiring, active-worker retention, and result application paths verified.
- Commands run and results.
- Any skipped GUI tests and residual risk.

## Manual Verification Before Activation

This plan was created from read-only inspection of the current mixin: it contains
run-state/logging helpers, settings/precheck helpers, export/reporting helpers,
worker wiring, controller protocol methods, a large `get_step_config`, payload
storage/application helpers, legacy direct-slot handlers, and Lela completion
handlers. Recheck those symbols before activation because Stats UI work may
change the mixin boundaries.
