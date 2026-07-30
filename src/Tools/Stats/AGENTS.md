# Stats Package Instructions

The active Stats surface is **Standard FPVS Screening**. It is a transparent
first-round screen, not a general model builder and not a guarantee that every
result needed for a publication-quality manuscript has been modeled. The
workbook provides a detailed audit trail; study-specific covariates, random
slopes, longitudinal structure, more than two groups, and other confirmatory
questions require a planned custom analysis.

## Locked Standard Screening Contract

- Summed BCA is the dependent variable.
- Freeze the QC/manual-eligible cohort first, then use every finite selected
  observation without imputation. Do not silently drop a participant to rescue
  a Condition.
- The participant-random-intercept LMM is primary for balanced and incomplete
  data:
  - single: `Summed BCA ~ Condition * ROI + (1 | Participant)`;
  - multi: `Summed BCA ~ Group * Condition * ROI + (1 | Participant)`.
- Final coefficient estimates use REML. Hierarchy-preserving omnibus block
  comparisons refit nested models under ML on the identical observed rows and
  use the asymptotic chi-square reference.
- Positive-response tests are prespecified one-sided `greater than zero`.
  Factorial and fitted-model contrasts are two-sided.
- Primary named families use fixed Holm family-wise correction. The GUI does
  not expose selectable profile, missing-data scope, response direction,
  correction, or strict-omnibus controls.
- A corrected LMM Condition x ROI interaction controls whether the standard
  report explains the interaction. Explanations use
  `LMM-derived model-estimated contrast` rows with asymptotic Wald inference,
  not paired t-tests.
- Standard multi-group screening requires exactly two canonical manifest
  groups. Group A minus Group B contrasts run in every estimable Condition x ROI
  cell and are never gated by a broader group-pattern test.
- ANOVA is secondary compatibility evidence only. It runs automatically when
  the declared matrix is exactly complete and unique; the multi-group check
  additionally requires equal group sizes. It never replaces, validates, or
  gates the primary LMM.
- Available-observation likelihood inference assumes ignorable/MAR missingness
  conditional on modeled variables. Reports must disclose no imputation and
  possible MNAR bias.
- Robust and leave-one-participant-out checks are optional secondary
  sensitivities. The current max-|t| implementation needs a complete
  participant-by-cell matrix and is unavailable in the locked
  available-observation screen.

Legacy `repeated_m_anova.py`, `posthoc_tests.py`, `group_comparisons.py`, and
`resampling.py` entry points remain only where compatibility, detailed exports,
or focused tests require them. Do not route the primary screening conclusion
through legacy paired post-hocs, standalone Welch cell tests, selectable
complete-core inference, or max-|t| resampling.

## Locked Harmonic And QC Contract

The default Summed BCA policy uses the processing-time, group-level
significant-harmonic list calculated over the union of predefined-ROI
electrodes. It detects non-base oddball harmonics with strict `z > 1.64` and
sums eligible non-base harmonics through the highest significant harmonic.
When more than 10 eligible non-base harmonics lie strictly between the two
highest significant peaks, the one-pass gap guard omits the isolated highest
peak and stops summation at the next-highest peak. Base-rate overlaps do not
count; exactly 10 remains allowed. Fixed/predefined harmonic summation remains
an alternate DV policy.

Preserve the exact-column, common-harmonic-list, 1.2-Hz oddball spacing,
neighboring-noise, population-SD, gap-guard, cache-fingerprint, persistence,
frequency-domain QC, and participant-condition exclusion rules documented in
`docs/agent/architecture/statistics-tools.md`. Stats consumes the durable
processing-time selection; it must not calculate a replacement.

## Project And Package Boundaries

- `project.json` is canonical for group assignments. Prefer participant
  `group_id` and resolve display labels through `project.groups`; legacy
  participant `group` values are compatibility input only.
- Processed-workbook discovery must consume
  `Main_App.projects.load_project_dataset_index`. Keep
  `stats_data_loader` functions as thin adapters for established Stats return
  shapes; do not add another scanner, participant-ID parser, or group
  normalizer.
- Never infer group membership from an Excel folder name.
- Project mode is manifest-owned. Do not add an "ignore groups" shortcut. A
  scientifically pooled analysis requires a separately defined single-group
  project.
- Use PySide6 only, keep long work in workers, and communicate with widgets
  through signals.
- Preserve the public `Tools.Stats.StatsWindow` import and functional package
  boundaries.

## Non-Expert Reporting Contract

At a Glance answers the applicable first-round questions in plain language:
positive-response evidence, Condition/ROI pattern, interaction explanation when
supported, direct two-group cell differences, and broader group pattern. It
uses only canonical Holm-adjusted reportable decisions and does not print a
dense p-value inventory. It must not turn nonsignificance into equivalence,
absence, causality, or model validation. Same-sample adaptive harmonic
selection keeps positive-response evidence explicitly exploratory
post-selection. Detailed estimates, intervals, formulas, family metadata,
diagnostics, exclusions, coverage, frozen/contributing Ns, missingness limits,
and source tables remain in the workbook.

## Checks

Prefer `.venv1` when present; otherwise substitute `.venv`.

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use audit output to choose focused tests and documentation. Do not run local
offscreen Qt workflows.
