# QC-21: Complete Fixed-ROI Electrode Coverage

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts. For definition and
source prevalidation, load QC-02, QC-07, QC-10, QC-15, and the QC-20 ledger.
For final coverage, additionally load QC-03, QC-09, QC-16, QC-17, and QC-20's
pre-review state.

**Status:** accepted on 2026-09-03. A primary raw ROI result requires its
complete, prespecified electrode set. Successful interpolation restores an
electrode for this purpose and remains visible in provenance. Whole-scalp-
normalized ROI derivatives also require their complete frozen normalization
set.

## Accepted Behavior

1. Validate each project ROI as a nonempty ordered set of unique canonical
   BioSemi64 scalp labels. Normalize case and whitespace, but reject blank,
   unknown, or repeated electrodes and ambiguous duplicate ROI names before
   analysis. Never count one physical electrode twice. One electrode may still
   belong intentionally to more than one separately named ROI.
   Freeze the exact effective ROI snapshot in project analysis/export
   provenance for each analysis identity. The v3 application-level ROI editor
   remains the source for now, but a later global settings edit cannot
   silently alter an existing result: it makes a proposed rerun a new/stale
   analysis identity requiring explicit execution. Independently editable
   per-project ROI settings remain a separate future product decision.
2. After QC-15 validates the complete 64-channel acquisition and applies any
   explicit locked channel limit, validate every active spectral workbook as
   containing exactly one row for each member of that run's frozen eligible
   scalp set. Permit only explicitly declared auxiliary rows outside scalp
   calculations. A downstream electrode exclusion does not excuse a missing
   source row: validate source integrity first, then apply exclusions. A
   missing, duplicate, unknown, or nonfinite required source row is a technical
   integrity failure owned by QC-10/QC-20; it cannot silently become a smaller
   ROI.
3. Include a successfully interpolated electrode in its prespecified ROI. Mark
   it as interpolated and link its QC-02/QC-07 repair outcome and burden in
   provenance and review. Do not exclude it again merely because it was
   reconstructed; interpolation exists to restore the intended channel set.
4. For each recording, condition, and ROI, require every configured unique
   electrode to remain eligible with finite selected-harmonic values. Replace
   the current intersection-and-average behavior with exact membership
   validation before computing the primary ROI mean.
5. When a valid, explicitly scoped downstream decision excludes an ROI member,
   mark only that affected recording-condition-ROI value unavailable. Show the
   expected set and excluded member/reason, and state that no primary value was
   produced. Do not calculate a reduced-electrode mean, fill a value, remove the electrode
   from another condition, or convert the whole participant to a complete-case
   exclusion automatically. QC-20 and the selected statistical design decide
   how the unavailable cell affects later analysis.
   When the complete pre-exclusion value exists, retain it only as clearly
   labeled audit evidence with the exclusion metadata; do not expose it as the
   canonical eligible value.
6. Keep the project ROI definition identical across conditions and
   participants. A one-electrode prespecified ROI is valid and has complete
   coverage at one of one. Do not invent a universal percentage such as 80%.
   Any future reduced-mask sensitivity analysis must be separately named,
   versioned, reported, and approved; it cannot replace the canonical result.
   Always report the ROI-specific interpolation burden as
   `interpolated/configured`. If every configured member was interpolated,
   raise a prominent manual-review warning even when the overall QC-07 burden
   is at or below 5%. This warning does not itself invalidate an otherwise
   complete ROI. Invalid interpolation donor geometry remains a technical
   failure.
7. Apply the same canonical uniqueness and source-row checks before all-scalp
   or frozen-mask harmonic selection. For all-retained-scalp scope, the expected
   source set is the run's frozen QC-15 eligible set. After source validation,
   the analysis-eligible set subtracts valid explicit exclusions at that
   recording/condition scope; successfully interpolated electrodes remain
   present. A frozen a-priori mask requires every unique canonical member in
   every contributing workbook rather than shrinking when a member is
   unavailable. A configured ROI/mask member outside the run's intentional
   eligible set is a configuration error requiring correction. Preserve the
   four locked profiles and the rule that nonlegacy selection never uses
   mutable Stats ROIs. QC-21 does not reselect harmonics or alter valid profile
   mathematics.
8. Show concise GUI/report text: **“This ROI requires all configured
   electrodes. Interpolated electrodes are included and identified. If a
   required electrode is unavailable, this participant-condition ROI result is
   not calculated.”** Report expected, observed, excluded, interpolated, and
   used sets and counts for every result.
9. Replace participant-wide implicit removal in Stats with the accepted
   recording/condition coverage records. Fixed, adaptive, repeated-session,
   export, and provenance paths consume the same saved membership outcome and
   must not independently rebuild available intersections.

## Required Execution Sequence

1. In wave 1, persist and validate the project ROI snapshot and source-row
   contract without applying QC-17 decisions.
2. In wave 4, validate complete pre-review ROI inputs and provide those values
   to QC-20's pre-review readiness gate and then QC-17.
3. Apply reviewed decisions, then rerun QC-21 coverage to determine canonical
   raw ROI availability.
4. Only after that final coverage state may QC-20 release harmonic selection,
   Stats, reports, and exports. If QC-17 evidence changes after the canonical
   harmonic list is recomputed, follow QC-17's bounded re-review rule.

## Settled Normalized-Outcome Rule

The fixed raw ROI mean depends only on electrodes inside that ROI. A complete
raw ROI therefore remains available when a valid exclusion affects only an
electrode outside it. Some exported derivatives divide every ROI by a shared
whole-scalp value, so an exclusion anywhere in that frozen normalization set
changes every normalized ROI's denominator.

If any member of the frozen whole-scalp normalization set is excluded or
otherwise unavailable for one recording-condition, mark every whole-scalp-
normalized ROI derivative for that recording-condition **not calculated**.
Do not silently renormalize over a smaller set and do not retain a primary
normalized result that still uses data declared excluded. Preserve any
complete pre-exclusion number only as labeled audit evidence. A successfully
interpolated electrode remains present, so ordinary upstream channel repair
does not trigger this rule.

## Migration, Provenance, and Owners

On migration, preserve original ROI definitions and derived outputs for audit.
Canonicalize harmless case/whitespace differences. Require correction of
blank, unknown, or duplicate members before a new analysis, and mark prior
partial-membership or double-weighted results legacy/stale rather than silently
relabeling them. Preserve valid explicit electrode exclusions at their
accepted recording/condition scope.
Snapshot each existing project's effective ROI definition into the next new
analysis provenance and record that it came from application-global settings.
Preserve current editor ownership while QC-21 prevents later live global
settings from changing an already produced result. A separately developed
visual editor must consume the same snapshot contract if integrated later.

Fingerprint the ordered canonical ROI definition, montage version, workbook
and electrode-row identity, canonical harmonic list, expected/observed/used
sets, interpolation and exclusion states, recording/condition identity,
coverage decision, and downstream missing-data policy. Changed membership or
eligibility invalidates the ROI result and dependents.

Primary owners are the GUI ROI selector/settings and immutable analysis
snapshot; Stats ROI resolution and aggregation, including
`analysis/dv_policy_fixed_predefined.py`,
`analysis/dv_policy_group_significant.py`, and legacy-compatible aggregation;
analysis-ready workbook export; harmonic-selection input validation; Stats
experimental QC, Plot Generator, Ratio Calculator, and any other consumer that
independently derives ROI/normalized values; QC/freshness provenance; and
Stats/reporting surfaces.
Reuse QC-15's canonical BioSemi64 identity and do not add another
electrode-name authority.

## Verification and Scientific Boundary

Cover full fixed ROIs; a one-electrode ROI; case normalization; blank, unknown,
and duplicate configured labels; duplicate/missing/unknown workbook rows;
successfully interpolated members; a valid condition-specific exclusion;
an entirely interpolated small ROI; nonfinite source values; no-overlap and
partial-overlap cases; unchanged other conditions; all-scalp and frozen-mask
validation; an outside-ROI exclusion that preserves the raw ROI but invalidates
all shared-normalized derivatives; successful interpolation that preserves
normalization; legacy partial/double-weighted
results; fingerprints; and exact report counts. Prove no partial primary mean
or duplicate weighting can be produced and valid complete results remain
numerically unchanged. Run focused non-GUI Stats, export, project-I/O, and
processing checks; use CI-only Qt coverage and a documented visible smoke path.

Update the Stats ROI/normalization and harmonic-selection contracts, GUI ROI
settings guidance, analysis-ready and tool export documentation, and the user
methods/QC guidance when implementation lands.

Fixed electrode sets are established FPVS practice, while spherical
interpolation is an estimate that repopulates the intended channel set rather
than ground truth. Report both the fixed membership and repaired electrodes
([Poncet et al., 2019](https://doi.org/10.1016/j.neuropsychologia.2019.03.006),
[PREP](https://doi.org/10.3389/fninf.2015.00016),
[Perrin et al., 1989](https://pubmed.ncbi.nlm.nih.gov/2464490/)).
