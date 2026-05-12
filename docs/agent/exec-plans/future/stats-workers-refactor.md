# Stats Workers Refactor

## Status

Future plan. This work has not started.

## Target

`src/Tools/Stats/workers/stats_workers.py`

## Summary

`stats_workers.py` is the largest active Python module in the repo. It currently
combines the Qt worker wrapper, shared DV/QC preparation helpers, between-group
DV-contract diagnostics, individual statistical job functions, harmonic jobs,
and the between-group subprocess runner. The file is a development bottleneck
because unrelated Stats work has to pass through one high-risk module.

Do not refactor this file for size alone. Activate this plan only when Stats
worker changes are already needed or when adding characterization tests for the
existing worker contracts.

## Behavior To Preserve

- `StatsWorker` must remain a `QRunnable` that emits the same `progress`,
  `message`, `error`, `report_ready`, and `finished` signals.
- Public job function names and payload shapes must remain stable for
  `StatsController` and `StatsWindowPipelineMixin` callers.
- Existing DV policies, Rossion/shared-harmonic behavior, outlier/QC/manual
  exclusion rules, LMM diagnostics, workbook outputs, report text, and progress
  messages must remain unchanged unless explicitly scoped as behavior changes.
- Keep Stats code PySide6-only. Do not introduce Tkinter, CustomTkinter, PyQt,
  or legacy Stats import namespaces.
- Preserve between-group subprocess isolation and stdout message streaming.

## Suggested Seams

Prefer one seam per PR. Keep `stats_workers.py` as a compatibility facade until
callers are migrated and tests prove behavior is unchanged.

1. Worker infrastructure:
   - Move `StatsWorker` and its nested `Signals` class to
     `src/Tools/Stats/workers/qt_worker.py`.
   - Re-export `StatsWorker` from `stats_workers.py` and/or
     `src/Tools/Stats/workers/__init__.py`.
   - This is the lowest-risk first slice because it should not touch stats
     math or dataframes.

2. Shared dataframe and exclusion preparation:
   - Move `_long_format_from_bca`, `_apply_qc_screening`,
     `_apply_manual_exclusions`, `_apply_outlier_exclusion`,
     `_extract_required_exclusions`, and empty/report summary helpers to
     `src/Tools/Stats/workers/prep.py` or, if they become GUI-independent
     enough, a focused `src/Tools/Stats/analysis/prep.py`.
   - Keep payload schemas and `StatsRunReport` construction unchanged.

3. Between-group DV contract and diagnostics:
   - Move `_prepare_supported_multigroup_dv_contract`,
     `_supported_multigroup_prepared_metrics`,
     `_emit_supported_multigroup_prepared_diag`,
     `_build_supported_multigroup_empty_prepared_reason`,
     `_build_lmm_blocked_payload`, merge-key helpers, subject-normalization
     helpers, and DV-column audit helpers to
     `src/Tools/Stats/workers/between_group_contract.py`.
   - Keep `LMM_DIAGNOSTIC_WORKBOOK` and diagnostic workbook sheet contents
     stable.

4. Analysis job functions:
   - Move `run_rm_anova`, `run_between_group_anova`, `run_lmm`, `run_posthoc`,
     `run_baseline_vs_zero`, and `run_group_contrasts` to
     `src/Tools/Stats/workers/analysis_jobs.py`.
   - These functions are high-risk because they define worker payloads consumed
     by the controller and UI. Move only after tests pin payload keys and
     representative dataframe schemas.

5. Harmonic job functions:
   - Move `run_harmonics_preview`, `run_shared_harmonics_worker`,
     `run_fixed_harmonic_dv_worker`, and `run_harmonic_check` to
     `src/Tools/Stats/workers/harmonic_jobs.py`.
   - Preserve Rossion preview payloads, shared-harmonic export fields, and fixed
     harmonic DV payload keys.

6. Between-group subprocess task:
   - Move `_progress_from_stage` and `run_between_group_process_task` to
     `src/Tools/Stats/workers/between_group_process.py`.
   - Preserve `BETWEEN_STAGE_ORDER`, subprocess invocation, JSON summary
     handling, progress mapping, and streamed messages.

## Suggested Final Shape

- `src/Tools/Stats/workers/qt_worker.py`
- `src/Tools/Stats/workers/prep.py`
- `src/Tools/Stats/workers/between_group_contract.py`
- `src/Tools/Stats/workers/analysis_jobs.py`
- `src/Tools/Stats/workers/harmonic_jobs.py`
- `src/Tools/Stats/workers/between_group_process.py`
- `src/Tools/Stats/workers/stats_workers.py` as a temporary compatibility
  facade during migration, then either a thin facade or deleted after callers
  use the smaller modules.

## What Future Agents Should Inspect First

1. `docs/agent/architecture/statistics-tools.md`
2. `docs/agent/exec-plans/future/stats-ready-pipeline-exports.md` if export behavior
   is touched
3. `src/Tools/Stats/workers/stats_workers.py`
4. `src/Tools/Stats/controller/stats_controller.py`
5. `src/Tools/Stats/ui/stats_window_pipeline.py`
6. Relevant tests under `tests/stats/**/test_stats_*`, especially DV, QC, LMM, harmonic,
   group-contrast, and pipeline smoke tests

Before editing, run:

```powershell
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
```

## Verification Plan

Run the narrowest tests for the moved slice first, then broaden:

```powershell
python -m py_compile src\Tools\Stats\workers\stats_workers.py
python -m pytest tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\gui\test_stats_layout_smoke.py -q
python -m pytest tests\stats\analysis\test_stats_dv_policy.py tests\stats\analysis\test_stats_dv_variants.py tests\stats\qc\test_stats_qc_exclusion.py tests\stats\qc\test_stats_outlier_exclusion.py -q
python -m pytest tests\stats\analysis\test_stats_mixed_model_pipeline.py tests\stats\analysis\test_stats_between_group_blocked_payload.py tests\stats\analysis\test_stats_group_contrasts_validation.py -q
python -m pytest tests\stats\analysis\test_stats_shared_harmonics.py tests\stats\analysis\test_stats_fixed_harmonics_dv.py tests\stats\analysis\test_stats_harmonics_integration.py -q
python .agents\\scripts\\audit\\agent_audit.py --check stats-structure
python .agents\\scripts\\audit\\agent_audit.py --check stats-reporting-legibility
```

Use additional focused tests when the touched function already has a dedicated
test file.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Exact functions moved and their old/new module paths.
- Whether `stats_workers.py` remains a compatibility facade.
- Any public payload keys or dataframe schemas explicitly verified.
- Commands run and results.
- Any skipped tests and the residual risk.

## Manual Verification Before Activation

This plan was created from a read-only inspection of the current file structure:
`StatsWorker` lives near the middle of `stats_workers.py`; shared DV/QC helpers
surround the worker; RM-ANOVA, between-group ANOVA, LMM, posthoc, baseline,
group-contrast, harmonic, and subprocess job functions all live in the same
module. Recheck those boundaries before activating because Stats work is moving
quickly.
