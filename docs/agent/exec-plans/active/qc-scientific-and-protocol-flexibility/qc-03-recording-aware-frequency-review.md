# QC-03: Review Frequency-QC Findings by Recording

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts. Load QC-10 and
QC-20's pre-review readiness gate before finalizing this review.


**Status:** implemented on the active QC branch on 2026-09-04. The local
non-Qt and static-GUI checks pass; CI-only Qt execution and the visible smoke
path remain release verification rather than implementation authority.

### Problem and Accepted Solution

Repeated-session frequency-QC reports set `identity_scope=recording`, populate
`recording_summaries`, and leave `participant_summaries` empty
(`frequency_domain_qc.py`, around lines 265-290). The dialog reads participant
summaries for its main table and counts, omits recording/session identity from
details, and exposes only participant-level manual decisions. A report can
therefore show an empty main table despite recording-level findings; legacy
backend automatic recording exclusions can still be applied even when the GUI
does not expose their recording scope.

Show each affected recording with its participant and session. Let the user
exclude that recording across its conditions without automatically excluding
the participant's other recordings. Use the existing backend's recording
scope; retain its numerical thresholds and separate whole-participant controls.
This is a workflow correction independent of stimulus rates and duration.

### Implementation Shape

1. Select summary rows, review counts, automatic-action fields, and wording
   from the report's identity scope. Repeated-session summaries and details
   must show participant, recording, session/phase, and visit identity where
   available. Use recording IDs as control keys; multiple recordings can
   share a participant or session label.
2. Collect recording-specific manual reasons and pass them through the
   backend's existing `manual_recording_reasons` argument. Keep ordinary
   participant-level reports and callers working. Preserve only automatic
   actions independently authorized by their owning QC policy and display
   their actual scope. QC-17 summed-BCA findings are review-only; migrate
   legacy BCA-derived automatic exclusions to preserved suggestions requiring
   review rather than applying them here.
3. Preserve existing whole-participant exclusions and their separate management.
   Show their broader effect when relevant. Do not widen a recording decision
   into a participant decision. Existing downstream complete-pair requirements
   still determine which observations can enter a paired analysis.
4. On Cancel, save no new decisions and preserve the existing pending/stale
   post-processing behavior. On Apply, retain recording/participant/session
   association, reason, source, timestamps, decision fingerprint, and reviewed
   report; then resume the established post-processing sequence.
5. Restore actual saved exclusions and reasons on reopening. Current apply
   logic merges existing exclusions; do not imply that unchecking a saved
   exclusion clears it. Preserve explicit clearing through its existing
   management path and the resulting review invalidation.

### Owners, Validation, and Documentation

- `src/Main_App/gui/frequency_domain_qc_dialog.py`: identity-aware summaries,
  details, counts, manual controls, and user-facing scope.
- `src/Main_App/gui/processing_workflows.py`: carry the selected identity and
  manual recording reasons into decision persistence.
- `src/Main_App/processing/frequency_domain_qc.py`: reuse current recording
  decision support; change only necessary adapters/validation, without new
  exclusion rules.

Meaningful checks must cover two recordings from one participant with a flag
only in one recording, multiple recordings with the same session label,
independently authorized recording-electrode versus whole-recording actions,
legacy BCA automatic suggestions that no longer apply automatically, saved
participant-wide exclusions, reasons on reopening, Cancel, and the existing
single-session path. Verify that the selected recording ID alone receives a
new manual recording exclusion and that no unrelated sibling decision changes.

Extend existing non-GUI tests in
`tests/processing/test_repeated_session_frequency_domain_qc.py` and
`tests/processing/test_frequency_domain_qc.py` as needed. Add CI-only Qt
coverage for visible rows/labels/control-to-recording mapping and result
submission. Run processing and GUI focused verification through the repository
driver; keep local execution non-GUI. Document a visible smoke path for the
same repeated-session cases, including any preserved whole-participant state.

The implementation reconciles this change with the active repeated-session
project plan and updates
`docs/agent/architecture/post-processing-export-contract.md` plus the relevant
user QC instructions. Preserve canonical project
identity, original workbooks, and harmonic-selection contracts. No new
scientific threshold calibration is required for correcting the identity
wiring; QC-10, QC-14, and QC-17 own the authority and applicability of the
underlying findings.

### Implementation Evidence

`processing/frequency_domain_qc.py` now uses the existing canonical recording
identity, persists exact recording/condition/electrode decisions, keeps the
whole-participant choice explicit, requires reasons for exclusions, and exposes
one condition-aware coverage-decision resolver for QC-20/QC-21. Legacy
summed-BCA machine exclusions migrate to inactive suggestions. The review
dialog and processing workflow show and submit recording/session identity
without widening a choice to sibling recordings.

Focused processing tests cover two visits for one participant, repeated
session labels, exact condition/electrode scope, reopening saved decisions,
required reasons, legacy migration, and review fingerprints. Static GUI tests
cover the recording-aware rows and no-default decision contract. The visible
release smoke path is to review two recordings from one participant, exclude a
single condition/electrode in one recording, reopen the dialog, and verify that
the saved reason and scope return while the sibling recording remains retained.
