# Stats Controller Refactor

## Status

Future plan. This work has not started.

## Target

`src/Tools/Stats/controller/stats_controller.py`

## Summary

`stats_controller.py` coordinates Stats pipeline runs. It owns the view protocol,
section run state, step maps, public run entry points, Lela/cross-phase setup,
between-process job spec handling, step completion/error handling, and pipeline
finalization. The file slows future Stats workflow work because it mixes
pipeline state-machine code with specialized cross-phase and process-mode
helpers.

Do not change statistical computations in this plan. Those live in worker and
analysis modules.

## Behavior To Preserve

- `StatsController`, `SectionRunState`, and `StatsViewProtocol` remain importable
  from `Tools.Stats.controller.stats_controller` until callers are migrated.
- Public controller methods keep their current names and semantics:
  `run_single_group_analysis`, `run_single_group_*_only`,
  `run_between_group_analysis`, `run_between_group_*_only`,
  `run_harmonic_check_only`, `run_lela_mode_analysis`, and `is_running`.
- Default step ordering and `WORKER_FN_BY_STEP` mappings remain unchanged.
- Unsupported between-group ANOVA and harmonic-check requests stay blocked with
  the same user-facing warning behavior.
- Busy-state transitions, pipeline started/finished notifications, export and
  summary finalization, blocked payload handling, and error logging remain
  stable.
- Lela/cross-phase mode keeps its current phase-folder prompts, filename parse
  behavior, job JSON shape, output filenames, and QThreadPool worker launch.

## Suggested Seams

Prefer one seam per PR. Keep `StatsController` as the public facade.

1. Protocols, state, and constants:
   - Move `StatsViewProtocol`, `SectionRunState`, `SINGLE_PIPELINE_STEPS`,
     `BETWEEN_PIPELINE_STEPS`, `STEP_LABELS`, and `WORKER_FN_BY_STEP` to
     `src/Tools/Stats/controller/pipeline_state.py`.
   - Re-export from `stats_controller.py` during migration.
   - Preserve imports used by tests that currently import `WORKER_FN_BY_STEP`
     and `SINGLE_PIPELINE_STEPS`.

2. Step construction and run entry-point helpers:
   - Move `_build_steps` and the public one-step convenience selection logic to
     `src/Tools/Stats/controller/pipeline_steps.py` only if the helper can stay
     pure and not own view state.
   - Keep unsupported-step blocking in the controller until tests pin all
     warning/finalization behavior.

3. Generic pipeline lifecycle:
   - Move `_start_pipeline`, `_run_next_step`, `_on_step_finished`,
     `_on_step_error`, `_complete_pipeline`, and `_finalize_pipeline` to
     `src/Tools/Stats/controller/pipeline_lifecycle.py` as functions that accept
     the controller or a small context object.
   - This is high-risk because callback ordering drives UI state. Do it after
     smoke tests cover success, blocked, handler-failure, worker-error, export
     failure, and summary failure paths.

4. Between-process compatibility:
   - Move `_build_between_job_spec`, `_deserialize_between_payload`,
     `_on_between_process_message`, `_on_between_process_finished`,
     `_on_between_process_error`, and `_start_between_process_pipeline` to
     `src/Tools/Stats/controller/between_process.py`.
   - Preserve current "unsupported in supported multigroup workflow" blocking
     behavior unless a separate plan reactivates process mode.

5. Lela/cross-phase workflow:
   - Move `_ensure_phase_subject_data`, `run_lela_mode_analysis`,
     `_on_lela_worker_finished`, `_on_lela_worker_error`,
     `_resolve_stats_output_dir`, and `_find_project_root` to
     `src/Tools/Stats/controller/lela_workflow.py`.
   - Preserve phase label uniquing, phase-code logging, selected folder
     behavior, manifest Excel fallback, output filenames, and busy reset on
     success/error.

6. Small utility helpers:
   - Move `_subject_data_has_files` and `_unique_label` only with their owning
     workflows. `_unique_label` has direct tests and should remain re-exported
     until callers/tests are migrated.

## Suggested Final Shape

- `src/Tools/Stats/controller/stats_controller.py` as a facade owning the
  public `StatsController` class.
- `src/Tools/Stats/controller/pipeline_state.py`
- `src/Tools/Stats/controller/pipeline_steps.py`
- `src/Tools/Stats/controller/pipeline_lifecycle.py`
- `src/Tools/Stats/controller/between_process.py`
- `src/Tools/Stats/controller/lela_workflow.py`

Avoid circular imports with `StatsWindowPipelineMixin`. Controller helpers should
depend on the protocol/state objects, not on concrete UI classes.

## What Future Agents Should Inspect First

1. `docs/architecture/statistics-tools.md`
2. `src/Tools/Stats/controller/stats_controller.py`
3. `src/Tools/Stats/common/stats_core.py`
4. `src/Tools/Stats/ui/stats_window_pipeline.py`
5. `src/Tools/Stats/workers/stats_workers.py`
6. Tests that import controller constants or exercise Stats pipeline flows

Before editing, run:

```powershell
python scripts/audit/agent_audit.py --check stats-structure
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
```

## Verification Plan

Run targeted controller and pipeline tests first:

```powershell
python -m py_compile src\Tools\Stats\controller\stats_controller.py
python -m pytest tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\analysis\test_stats_mixed_model_pipeline.py tests\stats\pipeline\test_stats_finalize_error_paths.py -q
python -m pytest tests\stats\pipeline\test_stats_export_finalization_release_smoke.py tests\stats\gui\test_stats_window_errors_stats.py -q
python -m pytest tests\stats\analysis\test_stats_lela_labels.py tests\stats\analysis\test_lela_filename_parser.py -q
python -m pytest tests\stats\analysis\test_baseline_vs_zero.py tests\stats\analysis\test_stats_harmonics_integration.py tests\stats\pipeline\test_stats_multigroup_smoke.py -q
python scripts\audit\agent_audit.py --check stats-structure
```

Broaden to layout smoke tests when callback wiring or view protocol assumptions
change.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Which controller methods/constants moved and whether they are still re-
  exported from `stats_controller.py`.
- Any view protocol expectations added or changed.
- Success, blocked, error, export, and summary finalization paths verified.
- Commands run and results.
- Any skipped tests and residual risk.

## Manual Verification Before Activation

This plan was created from read-only inspection of the current controller: it
contains `StatsViewProtocol`, `SectionRunState`, step constants/maps, public run
entry points, Lela/cross-phase workflow, between-process helpers, generic
pipeline lifecycle handlers, and finalization helpers. Recheck those symbols
before activation because Stats workflow work may change controller boundaries.
