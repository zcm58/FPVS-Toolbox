# QC-20: Complete and Fresh Recording-by-Condition Outputs

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts. Build the wave-1
expected ledger from QC-02/QC-19 identity without QC-21. For wave-3 receipts,
also load QC-10 through QC-15. QC-21 source prevalidation then consumes that
ledger; only afterward does QC-20's pre-review gate consume the QC-21 result.
For the final release gate, additionally load QC-03, QC-17, and QC-21 final
coverage.

**Status:** implementation and orchestration completed on 2026-09-04 across
the wave-1 ledger, wave-3 receipts, wave-4 pre-review/final-release gates, and
downstream enforcement. Every recording and condition expected by the project
must be accounted for. A workbook is not required for a condition that is
explicitly excluded or unavailable.

## Accepted State Model

1. Build the expected recording-by-condition matrix from canonical project
   identity and the processing plan before processing starts. Never derive the
   expected cells from whichever workbooks happen to exist.
2. Track every planned condition occurrence first. Each records one outcome:
   retained with its exact analyzed span; explicitly excluded with decision and
   reason; explicitly unavailable with reason and evidence; or
   failed/unresolved. Occurrence decisions roll up only to their own recording
   and condition.
3. Assign each expected recording-condition cell one outcome:
   - `ready`: every planned and observed occurrence was retained and
     contributed to a fresh validated workbook, with no omitted occurrence;
   - `partially_retained`: at least one occurrence was retained, every omitted
     occurrence is explicitly excluded or unavailable, and a fresh validated
     workbook contains only the retained occurrences;
   - `excluded`: no workbook is required because every occurrence was
     explicitly excluded;
   - `unavailable`: no workbook is required because no occurrence is usable and
     every nontechnical absence has a recorded, acknowledged reason; or
   - `blocked`: a technical failure, unexplained omission, count mismatch,
     missing/stale workbook, or failed schema/content validation remains.
   If excluded and unavailable occurrences coexist with none retained, preserve
   both counts/reasons and roll the cell up as unavailable. A technical failure
   remains blocked until corrected or separately converted to an explicit user
   exclusion while preserving the original failure evidence.
4. A `ready` or `partially_retained` cell requires proof that the current run
   wrote the workbook and it passed schema, electrode-identity, finite-data for
   every computable value, structured method-availability, protocol, and
   freshness validation. An explicitly unavailable frequency inside an
   otherwise valid workbook does not make the whole recording-condition
   unavailable. File existence alone is never proof.
   Capture the pre-run artifact identity. If a rerun fails, preserve the earlier
   file for history, mark it prior/stale, and do not let it satisfy the new run.
5. Apply two gates. The **pre-review readiness gate** runs before QC-03/QC-17:
   it validates the current expected matrix, input receipts, schemas, and
   explicitly documented no-output states. Blocked cells may be shown
   diagnostically, but no frequency score or review decision can finalize from
   them. After QC-17 decisions and QC-21 final coverage, the **final release
   gate** requires every expected cell to be accounted for and none blocked
   before harmonic selection, Stats, or primary exports finalize. Both gates
   consume ledger outcomes rather than skipping absent/unreadable files or
   converting an unexplained absence to NaN. Explicit excluded/unavailable
   cells remain legitimate, reported missing observations under the selected
   analysis design.
6. A `partially_retained` output records planned, observed, retained, excluded,
   unavailable, and failed occurrence counts and identities. Its workbook
   aggregates only retained exact intervals. Changing an occurrence decision
   invalidates that workbook and every dependent QC/analysis artifact.
7. Accounting does not make an analysis estimable. A declared group-condition
   cell with zero retained recordings remains a hard failure for group harmonic
   selection and inference even when every individual absence is explained.
   Do not impute or silently remove that declared cell. Participant-specific
   missing conditions remain allowed when the selected downstream method
   supports them; report its actual contributors and missing-data policy.
8. Implement this action in stages. Build the expected ledger and occurrence
   state model in wave 1, add current-run atomic receipts and core cell outcomes
   in wave 3, run the pre-review readiness gate before QC-03/QC-17, and defer
   the final release gate until wave 4 after QC-17 decisions and QC-21 final
   coverage are recorded. The earlier stages do not declare final frequency QC
   or Stats ready.

## Provenance, Migration, and Reporting

Persist the run ID; canonical recording/session/participant/group/condition
IDs; raw-file identity; processing/protocol/montage/method fingerprints;
expected occurrence plan and exact retained spans; every occurrence outcome,
reason, evidence, reviewer, and time; cell roll-up; fresh workbook path,
hash/write receipt, and validation result; prior artifact identity; and every
downstream invalidation.

Preserve historical workbooks and explicit manual exclusions during migration.
Do not infer completion from legacy file presence. A legacy cell without
trustworthy run identity, occurrence accounting, and validation becomes
`legacy_unknown`/stale and blocks new finalization until regenerated or handled
by a versioned legacy-validation path. Never describe it as output of a newly
attempted run.

Reports show by recording-condition and group-condition: expected recordings;
ready, partially retained, excluded, unavailable, and blocked recordings;
contributors; and planned, observed, retained, excluded, unavailable, and
unresolved occurrences. Show reasons for every non-retained item and the exact
sample size used downstream. Never call an accounted unavailable cell passed or
clean.

## Owners and Acceptance

### Missing-condition recovery (2026-09-05)

Settings → Harmonics → Review FFT Crop Exclusions also shows **No condition
output** rows when the last Processing run planned zero occurrences and reported
`condition_input`. Users may explicitly exclude that condition or restore a
complete source recording, then rerun Processing before post-processing. Missing
start markers cannot be reconstructed. New missing rows start unchecked; prior
condition exclusions remain editable. Whole-recording exclusions, removed project
identities, write failures, and missing previously written files are not offered
as absent-source condition choices. Review-only rows have no synthetic workbook
or FFT grid and never affect grid reference/compatibility arithmetic. Saving
choices preserves the existing invalidation path; it does not update readiness
or bypass the processing outcome gate.

Backend/AST coverage: `test_missing_condition_outputs.py` and the zero-occurrence
case in `test_expected_processing_ledger.py`. Visible manual smoke (Qt is
CI-only locally): open the review after a missing-input run; confirm the missing
row is unchecked, check only its condition, save, and verify rerun guidance with
no automatic post-processing. Rerun Processing and confirm the explicit exclusion
is accounted for while other conditions retain their normal output requirements.
Reopen to verify the saved exclusion, and cancel a change to verify it persists.

### Reviewed condition exclusion recovery (2026-09-07)

- [x] Diagnose the reported participant-condition failure read-only: its workbook exists
  and has a ready receipt; a saved `exclude_condition` decision removes it from
  analysis. Pre-review coverage incorrectly continued requiring it in the
  provisional harmonic pool.
- [x] Remove only explicitly reviewed excluded conditions from that pool's
  expected-source map; report them as excluded by review, not missing files.
- [x] Correct final ROI coverage's pair-set/serialized-row decision adapter so
  whole-condition exclusions survive release and other conditions remain usable.
- [x] Reject older hash-valid final coverage whose whole-condition exclusion
  flags contradict its canonical saved decisions; rebuilding post-processing
  repairs this without invalidating unaffected coverage.
- [x] Verify release consistency, normal review/reconfirmation completion,
  missing-source protection, no imputation, exact pooling values/weights and
  participant/recording/condition scopes. Processing gate: **1,284 passed,
  5 skipped**; the extended resume/reconfirmation regression also passed.
  Ruff/compile/protected/Stats-structure checks passed. Repository precommit
  remains blocked by eight pre-existing paths in unrelated untracked `outputs/`.

The bounded real-project probe now yields 142 eligible sources from 143 validated
sources, omitting the reviewed participant-condition pair and retaining its other five conditions.
No user project metadata, workbooks, companions, or EEG samples were rewritten.
After restarting the application, resume reviewed post-processing to rebuild
coverage/selection; no EEG preprocessing is required for this exclusion fix.
Visible/manual smoke: exclude one condition, apply/continue, complete any normal
re-review, and confirm post-processing proceeds with that condition recorded as
unavailable and the participant's other conditions present. Qt remains CI-only.

Current owners (reviewed 2026-10-18) are
`processing/expected_processing_ledger.py` for the frozen expected matrix;
`processing/processing_ledger.py` for run accounting and persisted reconciliation;
`processing/recording_condition_outcomes.py` for receipt-backed cell outcomes
and the pre-review readiness gate; and `workers/process_runner.py` for occurrence
outcomes. `exports/post_process.py`, `exports/post_export_adapter.py`, and
`exports/post_process_excel.py` produce structured atomic export receipts.
`workers/post_processing_pipeline_worker.py` invokes the pre-review gate and
records the final release through `processing/roi_coverage.py` after reviewed
QC-03/QC-17 decisions and QC-21 coverage. Dataset discovery, harmonic-selection,
Stats inputs and QC reporting consume these authorities; a legacy
`condition_completeness=partial` flag never substitutes for current receipts or
final-release readiness.

Cover a fully successful matrix; an excluded or acknowledged-unavailable cell
without a workbook; partial occurrence retention with correct output/counts;
an unexplained missing occurrence; no-data, calculation, and write failures; an
older workbook during a failed rerun; atomic preservation of the prior file;
invalid output; changed occurrence decisions; repeated sessions; restart/reopen
of a valid run; legacy migration; and a wholly absent group-condition cell.
Prove only current `ready`/`partially_retained` artifacts enter numerical
consumers, explicit no-output states stay visible, blocked cases stop
finalization, and reported sample sizes match contributors. Run focused
non-GUI processing, project-I/O, export, frequency-QC, harmonic-selection,
Stats-input, and reporting checks. Qt behavior remains CI-only with a documented
visible rerun/review smoke path.

The implementation updates the processing-ledger, post-processing/export,
dataset-index, Stats input, user troubleshooting/QC, and methods-reporting
documentation.
