# Experimental condition-specific interpolation

Approved scope: allow artifact-confirmed electrode repairs in one condition;
never exclude individual electrodes or whole ROIs downstream.

- [x] Default-off setting and QC review action with brief artifact confirmation.
- [x] Apply repairs at the existing interpolation/reference stage within exact
  reviewed analyzed intervals; preserve untouched condition artifacts.
- [x] Persist source-bound approvals, pending/completed receipts, audit history,
  safe retries, and normal-run snapshot reuse. Recompute QC/harmonics afterward.
- [x] Headless numeric/core, state/executor, and source-merge regression checks.
- [ ] Visible smoke: enable option, repair one electrode/condition, confirm the
  shell remains visible and final QC refreshes; retry an interrupted repair;
  disable option and confirm existing repairs remain applied.

Local Qt execution remains CI-only. No real project data was modified during
automated checks. This is an intentional, outcome-informed experimental repair;
it is not a claim of parity for the repaired condition.

Verification (2026-09-07): processing focused gate **1,368 passed, 5 skipped**;
GUI focused gate **184 passed**. The final focused repair, execution, QC, worker,
and source-export suite passed **101 tests**, including the later snapshot/source
guards and forcing full QC after a repair during an export-only continuation.
The numeric reference checks preserve trigger/sample coordinates and unaffected
sample bits; repaired intervals match joint MNE interpolation and average reference.
Ruff, compilation, protected-path and GUI audits passed. Repository precommit
still stops at eight pre-existing path findings in unrelated untracked `outputs/`.
No retired runtime packages or standalone scripts were accessed or changed.
The final source-reassignment and selective source-export checks also passed
**17 tests**; an approval does not follow a participant to a different BDF.
After wiring the current-source guard into both parent and child runners,
**21 core tests** and **29 execution/QC-policy tests** passed; Ruff passed.

Runtime owners: project `experimental_qc_settings.py`; GUI `settings_panel.py`,
`frequency_domain_qc_dialog.py`, `frequency_domain_qc_review_model.py`, and
`processing_workflows.py`; processing `frequency_domain_qc.py`,
`condition_electrode_interpolation.py`, `condition_interpolation_state.py`,
`condition_interpolation_executor.py`, `preprocess.py`, `processing_ledger.py`,
and `roi_coverage.py`; `Performance/process_runner.py`; `Shared/post_process.py`;
`exports/source_time_domain_export.py`; and `workers/post_processing_pipeline_worker.py`.
All new artifacts use the active project root. Existing processing/export formats
remain intact; the additional project-local snapshot preserves reviewed timing.
