# Stats Package Instructions

The active Stats surface is **Standard FPVS Screening**. It is a transparent
first-round screen, not a general model builder and not a guarantee that every
result needed for a publication-quality manuscript has been modeled. The
workbook provides a detailed audit trail; study-specific covariates, random
slopes, longitudinal structure, more than two groups, and other confirmatory
questions require a planned custom analysis.

The Main App exposes this surface through the optional **Beta Tools** section.
That product classification must not change the locked calculations, exports,
or the stable `Tools.Stats.StatsWindow` import surface.

## Locked Standard Screening Contract

- Summed BCA is the dependent variable.
- Freeze the QC/manual-eligible cohort first, then use every finite selected
  observation without imputation. Do not silently drop a participant to rescue
  a Condition.
- User exclusion explanations are optional; blank explanations on explicitly
  excluded imported rows become `No reason provided`. Preserve required
  machine-generated QC evidence and exclusion decisions.
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

Optional finite-DV extreme flags follow the project's experimental
`stats_dv_screening_enabled` switch in Settings > Experimental > Post-processing
QC. New projects start off; legacy defaults remain on. Single- and multi-group
preparation read the committed setting. Nonfinite-value handling, manual
exclusions, the frozen cohort and inference methods remain mandatory and
unchanged. The tool displays the setting but does not maintain a competing toggle.

The processing-owned harmonic selection is versioned. New projects explicitly
default to `dzhelyova_poncet_two_consecutive_failures` v1 using all retained
scalp electrodes. Existing projects without a versioned profile retain
`legacy_fpvs_toolbox` v1. The other supported profiles are
`fixed_preregistered_domain` and `significant_only_exploratory`.

Only Legacy uses mutable ROI-union selection, equal-available-workbook pooling,
fill-through-highest summation, and the one-pass greater-than-10 isolated-peak
gap guard. Adaptive non-legacy profiles use complete declared group x condition
cells, equal group and condition weighting, and all retained scalp electrodes
or one frozen a-priori mask. The literature profile stops after two consecutive
eligible non-base harmonics with `z <= 1.64`; the significant-only profile
retains strict `z > 1.64` detections only. Fixed mode uses its exact declared
domain. Every profile excludes base overlaps and preserves the locked local
noise calculation. See the root `AGENTS.md` and
`docs/agent/architecture/statistics-tools.md` for the complete contract.

Preserve the exact-column, common-harmonic-list, project-protocol oddball
spacing, neighboring-noise, population-SD, gap-guard, protocol/eligibility and
cache fingerprints, persistence, frequency-domain QC, and participant-condition
exclusion rules documented in `docs/agent/architecture/statistics-tools.md`.
Stats consumes the exact durable included list and selection fingerprint through
`Main_App.processing.canonical_harmonics`; it must not reselect, refill, or
truncate that list. Shared settings live in `Main_App.processing.harmonic_settings`;
the former Stats modules are compatibility exports.

FullFFT inputs use the shared `Main_App.io` companion-aware readers. A declared
NumPy companion owns the complete spectrum; a missing or invalid companion
must not fall back to an Excel notice or partial data. Source fingerprints and
in-memory/persisted harmonic caches include its validated identity. Legacy
Excel-only inputs retain their existing source identity and numerical behavior.
Compact BCA/SNR/Z/FFT values and technical eligibility use the shared condition
companion readers, with legacy Excel fallback only when no companion is
declared. Include the validated condition companion in source and DV cache
identities; preserve saved values and exact columns rather than recalculating
metrics from FullFFT. Long/wide statistical workbooks remain Excel exports.

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

## Hardware And Studio Boundary

Hardware and Studio integration follow the
[shared roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md).
New montage support must supply qualified electrode/ROI coverage and canonical
identities through shared owners; it must not silently shrink ROIs, change the
locked selection profiles, or expand the supported statistical design. A
successful Studio project import alone does not qualify these analyses.

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

Use the active environment selected by the root agent policy.

```console
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use audit output to choose focused tests and documentation. Do not run local
offscreen Qt workflows.
