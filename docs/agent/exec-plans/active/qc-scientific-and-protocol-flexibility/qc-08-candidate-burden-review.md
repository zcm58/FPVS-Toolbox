# QC-08: Candidate-Burden Flags and Evidence-Based Recording Review

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** implementation and report/ledger orchestration completed on
2026-09-04 in the shared signal-review and preflight/runner paths. Local
repository verification is complete; CI-only Qt and visible smoke checks remain.

### Implementation Progress

- Count (`>`), fraction (`>`), hemisphere (`>=`), and BioSemi64 connected-
  cluster (`>=`) crossings are structured review-only findings with observed
  values, denominators, thresholds, comparators, channels, candidate sources,
  and rule version.
- None of these findings sets automatic exclusion or adds amplitude, burst, or
  spatial candidates to interpolation. Each candidate row starts with no
  exclusion selected; the user can keep or exclude rows independently and can
  choose recording or participant scope when repeated recordings exist.
  Closing or continuing without changes excludes nothing.
- Focused tests cover count/fraction boundaries, hemisphere equality, four-,
  five-, and six-channel clusters, six manual targets, six high-amplitude
  candidates, cache round-trip, and continuation into preprocessing. These
  tests do not validate the provisional scientific thresholds.
- Visible GUI smoke for CI/manual validation: open a review with at least two
  candidate recordings; verify every Decision starts at **No exclusion
  selected**, exclude only one row, leave or keep the other, apply the review,
  and confirm only the chosen recording/participant enters project exclusions.
  Close and reopen once without applying and confirm nothing is added.

### Accepted Behavior and Boundaries

1. Convert candidate count, fraction, hemisphere burden, and connected-cluster
   threshold crossings into recording-level review findings. Preserve their
   numerical values, electrode names/locations, candidate sources, severity,
   denominators, thresholds, and rule version. Keep the present thresholds as
   provisional screening triggers; this change does not validate or recalibrate
   them. No automatic or preselected recording exclusion solely on these rules.
2. Make the findings available in the existing preflight review, where the user
   can explicitly exclude the recording or continue processing. The current
   condition-aware preflight omits cluster evaluation while the runner enforces
   it; use a shared burden result so the review exposes the applicable findings
   and the runner honors continuation. Findings first available during the run
   must remain visible in the report/downstream review without reinstating
   automatic rejection. Preserve separate explicit whole-participant controls.
3. Keep suspected problems separate from interpolation selection. Continuing
   does not promote every amplitude, transient, or spatial candidate to an
   interpolation target. Respect QC-04's experimental opt-in/manual choices
   and QC-06's analyzed-interval scoring. Preserve the accepted fixed spatial
   interpolation application, pipeline order, and existing technical handling
   under item 16. This approval does not settle the independent kurtosis rule.
4. Carry the original findings into QC-02's truthful preprocessing report and
   QC-07's downstream review of actual successful interpolation. Show whether
   processing occurred, which channels were repaired, and any failed/unknown
   outcomes. A low percentage is not proof that a flagged recording is sound,
   and a high percentage is not proof that it is unusable. Present the same
   evidence and criteria consistently across recordings; record the user's
   inclusion/exclusion decision and reason separately from machine findings.
5. Use canonical recording identity and QC-03's repeated-session scope. A flag
   or decision for one recording must not silently exclude its siblings. Keep
   original BDFs and retain processed outputs for flagged/continued recordings;
   a heuristic flag alone must no longer invoke excluded-recording output
   deletion. Explicit exclusions continue through the established workflow.

### Ownership, Persistence, and Migration

Use `raw_channel_qc.py` for the shared structured findings, `preflight_qc.py`
and `gui/preprocessing_qc_workflow.py` for review delivery, and
`Performance/process_runner.py` for enforcement of the accepted authority.
Carry the results through `processing_ledger.py`, the Raw cache, the QC report,
and the existing downstream review persistence. Reuse the recording identity
and decision-provenance work in QC-03 rather than creating another exclusion
store. Keep the signal evidence, interpolation selection, and recording decision
as distinct fields.

Version the changed QC result, policy, processing fingerprint, and relevant
caches. Also update ledger reuse explicitly: unchanged raw files currently
reuse excluded entries before comparing fingerprints. Reopen only exclusions
attributable to the changed automatic heuristic policy for renewed review;
preserve explicit manual exclusions and independent technical failures.
Coordinate combined amplitude/burden reasons with QC-05. Incomplete historical
provenance requires review rather than assuming a manual decision or silently
restoring every excluded recording. Previously deleted outputs require
reprocessing; migration cannot claim they were restored merely by changing
metadata. Retain original reasons and the subsequent decision as audit history.

Bind review provenance to the recording/input identity, analyzed intervals,
detector settings, and QC policy version. Materially changed evidence must be
shown as needing renewed review instead of silently carrying over an old
acceptance. Do not remove or overwrite explicit manual decisions merely because
the software policy version changed.

### Acceptance Checks and Delivery

- Cover all four threshold boundaries, four/five/six-channel clusters, and
  overlapping candidate origins. These cases validate software behavior, not
  the clinical or scientific accuracy of the screening thresholds.
- Verify that six connected manual targets can continue after review, and
  that six connected high-amplitude candidates can be flagged without becoming
  six interpolation targets. Keep manual detector choices and opt-out intact.
- Verify that a flag alone cannot return a raw-QC excluded result or delete
  expected outputs; explicit exclusion remains effective and scoped correctly.
- Cover preflight/runner agreement, continued processing, newly surfaced
  findings, confirmed versus unavailable interpolation outcomes, reopening,
  Cancel, persisted reasons, and independent repeated-session recordings.
- Cover reuse/migration of legacy heuristic-only, amplitude-plus-burden,
  explicit manual, technical-failure, and uncertain-provenance exclusions.
  Confirm that a fingerprint bump alone cannot leave obsolete heuristic
  exclusions silently active, and that stale processed outputs are not treated
  as freshly regenerated evidence.

Implement shared span/provenance dependencies and coordinate this action with
QC-02 through QC-07. Run focused processing and applicable non-GUI project-I/O
and static GUI checks through the verification driver. Qt execution remains
CI-only; document a visible manual smoke path for early exclusion, continuation,
and downstream review. Update the preprocessing/reporting contract, condition-
aware preflight documentation, calibration guide, and user methods/QC guidance
as part of the implementation.
