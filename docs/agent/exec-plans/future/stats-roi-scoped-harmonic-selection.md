# Stats ROI-Scoped Harmonic Selection

## Status

Future plan. Not active implementation work.

This plan records a future statistical-method update for the Stats
group-level significant-harmonics policy. The current implementation remains
the all-scalp grand-average selection described in
`docs/agent/architecture/statistics-tools.md` until this plan is explicitly
activated.

## Rationale

The current default Stats policy selects one common oddball harmonic list from
`FullFFT Amplitude (uV)` after averaging each included workbook across all
scalp electrodes, selected participants, and selected conditions. This is
conservative for a general stats-ready export, but it can dilute focal
responses before z-score based harmonic selection.

A future update should align harmonic-selection scope more closely with
David et al. (2025), *An objective and sensitive electrophysiological marker of
word semantic categorization impairment in Alzheimer's disease*, where
significant responses were identified from FFT spectra over predefined ROIs
rather than an all-scalp average. The parity target is ROI-scoped harmonic
selection using predefined ROI electrodes; it is not a request to change the
locked oddball frequency, exact-bin requirement, z-threshold rule, neighboring
noise-bin math, or baseline-corrected amplitude quantification.

## Scope Decision

Replace the all-scalp grand-average amplitude spectrum used for harmonic
selection with spectra computed from predefined ROI electrodes.

The implementation should support a clear policy choice before coding:

- **ROI-specific selection:** compute significant harmonics separately for each
  predefined ROI and use each ROI's selected list for that ROI's `BCA (uV)`
  summation. This is the closest methodological parity with David et al. 2025.
- **Predefined-ROI union selection:** compute selection from the union of all
  electrodes in the predefined analysis ROIs, then apply one common harmonic
  list to every ROI. This preserves the current one-list stats-ready export
  symmetry while avoiding all-scalp dilution, but it is less direct parity with
  ROI-specific paper workflows.

Do not silently choose between these modes during implementation. The active
execution plan should state the chosen mode, update user-facing wording, and
record the statistical-method rationale.

## Non-Goals

- Do not change the selected-harmonic z threshold from strict `z > 1.64`.
- Do not use `Z Score`, `SNR`, or baseline-corrected amplitude sheets for
  harmonic selection.
- Do not add nearest-column or nearest-bin fallback.
- Do not change integer-cycle FFT crop expectations or exact nominal harmonic
  column requirements.
- Do not change neighboring-bin noise math unless the user explicitly scopes a
  separate method update.
- Do not change final `BCA (uV)` summation math beyond using the selected
  harmonic list dictated by the new ROI-scoped selection policy.

## Target Files

Primary implementation:

- `src/Tools/Stats/analysis/dv_policy_group_significant.py`
- `src/Tools/Stats/analysis/dv_policy_settings.py`
- `src/Tools/Stats/io/stats_ready_export.py`
- `src/Tools/Stats/workers/stats_workers.py`
- `src/Tools/Stats/ui/stats_window_exports.py` if user-facing labels or
  warnings need to describe the changed policy

Primary tests:

- `tests/stats/analysis/test_fixed_predefined_harmonics.py`
- `tests/stats/io/test_stats_ready_export.py`
- Add focused regression coverage for ROI-scoped harmonic selection and
  all-scalp dilution avoidance.

Docs to update when activated:

- `docs/agent/architecture/statistics-tools.md`
- `docs/user/statistics/rossion-harmonic-selection.md`
- `docs/user/statistics/external-statistics-software.md`
- `docs/user/reference/methods-reporting-checklist.md`

## Implementation Outline

1. Add an explicit harmonic-selection scope setting/model value for ROI-scoped
   selection. Do not overload the current `all_scalp_electrodes` constant.
2. Refactor FullFFT grand-average building so it can return one grand-average
   spectrum per predefined ROI, or one spectrum from the predefined-ROI union,
   depending on the chosen policy.
3. Preserve existing exact-column preflight. Every included workbook must still
   contain the candidate and neighboring-noise `FullFFT Amplitude (uV)` columns
   before any expensive row reads.
4. Preserve the current XML selected-column reader fast path. Only the electrode
   filter/scope should change.
5. Preserve current z-score and neighboring-noise calculations exactly.
6. Store selection metadata that makes the scope auditable:
   `selection_scope`, ROI name or union label, ROI electrodes, selected
   harmonics, tested candidate rows, excluded base-rate harmonics, and source
   workbook counts.
7. Update `Stats_Ready_Summed_BCA.xlsx` export sheets so downstream users can
   see whether harmonic selection was ROI-specific or predefined-ROI union.
8. If ROI-specific selection is chosen, ensure `Long_Format` and `Wide_Format`
   rows remain clear about which harmonic list was used for each ROI.

## Verification

Run focused checks first:

```powershell
.\.venv1\Scripts\Activate.ps1
python -m pytest tests\stats\analysis\test_fixed_predefined_harmonics.py tests\stats\io\test_stats_ready_export.py -q
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Add new tests that prove:

- a focal ROI response can be selected when an all-scalp average would dilute
  it below threshold;
- non-ROI scalp electrodes do not influence ROI-scoped selection;
- exact missing `FullFFT Amplitude (uV)` columns still fail before BCA reads;
- selected harmonic metadata names the ROI scope;
- exported stats-ready values remain based on exact selected `BCA (uV)`
  columns with no nearest-bin fallback.

## Migration Notes

This is a statistical-method change, so do not implement it as a quiet speed or
refactor task. When activated, update architecture/user docs and make the
policy visible in export metadata so old all-scalp exports can be distinguished
from ROI-scoped exports.
