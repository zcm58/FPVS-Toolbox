# QC-02: Explicit Preprocessing Report and Confirmed Outcomes

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** report-scoping decision accepted on 2026-09-03; implementation
pending until the cumulative review is complete. The user said to label this
as a preprocessing report. The supporting details below implement the reporting
correction discussed in review item 10.

### Problem and Recommended Solution

`qc_summary_export.py` derives "Included in Final Set" from processing
completion or partial-condition availability (around lines 767-825).
`processing_workflows.py` exports that workbook before starting later
post-processing QC (around lines 1527-1569), so the label does not reflect final
analysis-cohort membership.

Use the user-facing name **Preprocessing QC Report** and label inclusion/status
explicitly for that stage. Keep final analysis inclusion in the downstream
analysis-cohort exports. The report should describe confirmed preprocessing
outcomes and retain useful flags, missing-condition information, and reasons.

The related interpolation fields also need truthful provenance: `preprocess.py`
currently records intended targets before `raw.interpolate_bads()` succeeds
(around lines 937 and 985), and catches failures as warnings.
`qc_summary_export.py` additionally fills absent interpolation records from
flagged channels on completed runs (around lines 739-750). Targets and flags
are not proof of successful interpolation.

### Implementation Shape

1. Use **Preprocessing QC Report** in user-facing labels/help/log messages and
   workbook labeling. Replace "Included in Final Set" with an explicitly
   preprocessing-stage status. Distinguish completed, completed with missing
   conditions, excluded before preprocessing, failed, and unavailable/pending
   outcomes from the actual ledger/result state as applicable. Preserve the
   reason and missing-condition fields.
2. Keep the existing project-local `Quality Check/Processing_QC_Summary.xlsx`
   path for compatibility; correct its displayed purpose and column semantics.
   Check existing consumers before changing workbook labels/headers. Do not
   move this report to the final analysis stage or duplicate analytical-cohort
   decisions inside its processing-stage status.
3. Record interpolation targets, attempted work, successful channels, and
   failed/skipped/not-needed outcomes explicitly. Populate successful channels
   only after the interpolation call succeeds, in both kurtosis-enabled and
   pre-marked-channel paths. Preserve error/missing-montage reasons.
4. Pass explicit outcome provenance through result audits, cache metadata,
   processing ledger, and summary export. Version the added metadata so old
   records can be distinguished from confirmed outcomes. An absent or older
   record must remain not recorded/unknown; do not infer success from flags,
   a completed run, or the previous ambiguous target list.
5. Keep flagged channels and successful interpolation lists distinct, including
   counts/labels derived from them. Do not change thresholds, numerical
   interpolation, preprocessing order, or the existing continue-after-warning
   policy in this reporting item. Do not reprocess historical EEG solely to
   regenerate a label or fabricate missing outcome evidence.

### Owners, Verification, and Documentation

Primary owners are `src/Main_App/processing/qc_summary_export.py`,
`src/Main_App/processing/preprocess.py`, and
`src/Main_App/diagnostics/audit.py`; follow outcome metadata through
`src/Main_App/Performance/process_runner.py`,
`src/Main_App/processing/processing_ledger.py`, and the export caller in
`src/Main_App/gui/processing_workflows.py` only as required.

Focused validation must cover successful interpolation, an interpolation
exception, missing montage, no targets, kurtosis disabled with pre-marked
targets, and older records lacking trustworthy outcomes. Cover completed,
partial-condition, failed, and preprocessing-excluded rows, plus a later
frequency-QC exclusion that does not change the report's historical
preprocessing status. Keep participant/recording identity and current project
paths intact. Numerical EEG results should be unchanged for identical inputs;
only reporting/provenance semantics change.

Extend the relevant coverage in `tests/processing/test_qc_summary_export.py`
and existing non-GUI preprocessing/audit tests. Run
`python .agents/scripts/verify.py --scope processing --tier focused` first;
add only applicable static GUI/project-I/O checks if those owners change.
Document a visible check of the exported workbook's labels and outcomes; do
not launch Qt locally for this plan.

Update `docs/agent/architecture/preprocessing-contract.md`,
`docs/agent/quality/removed-electrode-detection-calibration.md`, and the relevant
user methods/reporting guidance when implementation lands. No scientific
threshold calibration is claimed or required for correcting these reporting
semantics. Item 16 retains the existing continuation policy for this update;
reported failure/skipped outcomes must remain distinguishable from success.
