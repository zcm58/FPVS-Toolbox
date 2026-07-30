# Standard FPVS Screening

The Stats package implements a locked, first-round FPVS screening workflow.
Active code imports from `Tools.Stats.<area>`; `Tools.Stats.StatsWindow` remains
the public GUI entry point.

Standard screening is intentionally narrower than a general statistical
workbench. It uses finite available Summed BCA observations without imputation,
fits a participant-random-intercept LMM as the primary factorial analysis for
balanced and incomplete data, tests positive responses one-sided (`> 0`), and
uses fixed Holm family-wise correction for named primary families. It is not a
substitute for a study-specific final model.

Single-group screening fits `Condition * ROI`. Exactly-two-group screening fits
`Group * Condition * ROI`, always runs fitted-LMM Group A minus Group B
contrasts in every estimable Condition x ROI cell, and reports broader
group-pattern blocks separately. Corrected LMM interaction evidence controls
automatic interaction explanation. Explanatory contrasts are
LMM-derived, model-estimated, two-sided asymptotic Wald contrasts.

ANOVA is compatibility-only and runs automatically only for an exactly
complete, unique declared matrix; multi-group compatibility also requires
equal group sizes. Robust and leave-one-out checks are optional secondary
sensitivities. Max-|t| is unavailable in the locked available-observation
screen because the current implementation requires a complete
participant-by-cell matrix.

The GUI does not offer competing profile, missing-data scope, response
direction, correction, or strict-family choices. Multi-group projects that do
not contain exactly two canonical groups need a custom multi-group analysis.

## Active Layout

- `ui/`, `controller/`, `workers/`, and `widgets/` — PySide6 presentation,
  run coordination, non-blocking worker boundaries, and widgets.
- `analysis/inference_contracts.py`, `design_audit.py`, and
  `prepared_analysis.py` — locked screening settings, available-observation
  design audit, and the shared prepared payload.
- `analysis/mixed_effects_model.py`, `multigroup_model.py`, and
  `lmm_contrasts.py` — primary single/multi LMMs, hierarchy-preserving ML
  likelihood-ratio blocks, final REML estimates, and fitted-model contrasts.
- `analysis/baseline_vs_zero.py` and `multiple_comparisons.py` — one-sided
  positive-response tests and named Holm families.
- `analysis/anova_compatibility.py` and `repeated_m_anova.py` — automatic,
  nonfatal, secondary exact-balance compatibility checks.
- `analysis/robust_tests.py` and `stability.py` — secondary sensitivities.
- `analysis/dv_policy_*`, `canonical_harmonics.py`, `full_snr.py`, and
  `noise_utils.py` — Summed BCA policy, authoritative harmonic consumption,
  and frequency-domain helpers.
- `data/` — Stats adapters over the shared project dataset index, project
  context, and ROI resolution.
- `qc/` — QC, outlier, and manual exclusion helpers.
- `reporting/` — concise non-expert screening summary, detailed workbook,
  source-result sheets, formatting, logging, and run reports.
- `common/` — shared enums, dataclasses, constants, and lightweight runtime
  types.
- `io/` — Excel/dataframe I/O and additive Stats-ready export helpers.

`analysis/posthoc_tests.py`, `group_comparisons.py`, and `resampling.py` retain
legacy APIs for compatibility, detailed exports, or focused tests. They are not
primary Standard FPVS Screening routes: paired post-hocs and standalone Welch
cell comparisons have been replaced by fitted-LMM contrasts, and max-|t| is not
queued by the locked available-observation workflow.

## Removed Namespaces

- `Tools.Stats.PySide6` and `Tools.Stats.Legacy` are unsupported.
- Removed CustomTkinter Stats UI source is not active architecture; use Git
  history only when historical context is explicitly needed.

## Adding Statistical Features

- Preserve the locked screening contract unless a user explicitly scopes a
  statistical-method change and the architecture, methods guide, reports, and
  focused tests are updated together.
- Add DV behavior to focused `analysis/dv_policy_*` modules and re-export stable
  functions through `analysis/dv_policies.py`.
- Keep worker/UI imports on public facades rather than private helpers.
- Preserve DataFrame columns, metadata keys, workbook sheets, and correction
  family provenance unless the feature explicitly changes them.
- Put project discovery in the shared dataset index, not a Stats-local scanner.
- Keep project I/O, QC, reporting, and common contracts in their owning
  functional subpackages.

Structural checks:

```powershell
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
```
