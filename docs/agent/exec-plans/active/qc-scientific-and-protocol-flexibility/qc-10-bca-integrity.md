# QC-10: Finite BCA Output Integrity Guard

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when implementing
source finite checks. Also load QC-12 and QC-14 when validating spectral
workbooks so intentional method-unavailable frequencies are distinguished from
corrupt numeric cells.


**Status:** implemented on the active QC branch in `d1d5ea30`. New outputs fail
before publication when a method-computable retained BCA cell is nonfinite;
consumers require every selected computable cell and never compare a partial
sum with a review threshold. Structured QC-12/QC-14 unavailability remains a
separate technical state. This is a defensive integrity safeguard, not a
routine bad-electrode or manual artifact-review policy.

### Problem and Accepted Boundary

A successful active pipeline with finite BioSemi input and successful
interpolation should write a finite literal BCA value for every retained,
method-computable electrode-frequency cell. Frequencies intentionally marked
unavailable by QC-12/QC-14 use structured status instead. Bad-channel interpolation does not normally create a
blank. A channel still marked bad after failed/unavailable interpolation is
normally omitted from the active Epochs export rather than represented by an
isolated blank cell. QC-02 and QC-07 own truthful interpolation and retained-
channel outcome reporting.

Post-processing currently has no explicit finite-array gate before writing the
BCA workbook. If an abnormal NaN/Inf value propagates through averaging, FFT,
or interpolation without raising, pandas/XlsxWriter can represent the derived
nonfinite value as a blank. Old, damaged, or externally edited workbooks are
additional possible inputs. Before this action, `frequency_domain_qc.py`
coerced invalid cells to missing and summed remaining harmonics with
`min_count=1`; an all-missing row was skipped. That partial result is not
scientifically comparable with a
complete summed-BCA threshold. There is no evidence from this audit that this
state is routine in current project outputs.

### Implementation and Failure Semantics

1. Before writing active FFT/BCA workbooks, validate that retained input data
   and every value the QC-12/QC-14 eligibility result says is computable are
   finite. Store method-unavailable frequencies in a structured availability
   manifest rather than representing them as unexplained blank numeric cells.
   On failure, stop that condition's export atomically and report the recording,
   condition, electrode, frequency/bin or processing stage, and value category.
   Preserve any previous complete workbook instead of replacing it with an
   incomplete artifact.
2. At the frequency-QC workbook boundary, require every selected, computable
   BCA cell used in each electrode-condition sum to be finite. A present but blank, text,
   NaN, or infinite selected cell makes that score unavailable. Enumerate the
   exact workbook, recording/participant, condition, electrode, and harmonic
   columns. Never fill with zero or compare a partial sum with thresholds.
3. Classify an unexpected nonfinite result as **technical output integrity
   failed / QC incomplete**.
   It cannot generate a clean result or an automatic scientific exclusion.
   Complete rows may be displayed for diagnosis, but the project-wide
   frequency-QC decision cannot be finalized or reused until affected outputs
   are regenerated or the defect is resolved.
4. A QC-12/QC-14 structured `unavailable_by_method` target is not a QC-10
   failure and regeneration with the same settings will not make it finite. It
   remains visible under QC-20. Adaptive methods omit it according to their
   eligibility rule; a fixed/preregistered aggregate that declared it is
   unavailable rather than a partial sum. Keep this separate from an absent
   retained-electrode row, interpolation-outcome reporting, and QC-17's
   scientific BCA review policy. Do not change finite-data
   calculations, selected harmonics, output names, or normal workbook values.
5. Version the frequency-QC method/result and fingerprint the finite-input
   status. Historical or external workbooks receive the same boundary check;
   do not infer why a cell is invalid or silently preserve a previous reviewed
   decision based on a partial sum.

### Owners and Acceptance

Implement source finite checks in `Main_App/Shared/post_process.py` and preserve
the atomic workbook behavior in `Main_App/Shared/post_process_excel.py`.
Implement consumer validation and structured diagnostic results in
`Main_App/processing/frequency_domain_qc.py`; make the worker/GUI present a short
actionable message directing the user to reprocess the affected condition. Keep
the existing full-audit export's nonfinite notes aligned, but do not allow that
later warning to substitute for the earlier integrity gate.

Cover finite normal output, an intentional target/noise-bin notch
unavailability, a fixed profile containing that target, one NaN/Inf source
sample, nonfinite interpolation output that does not raise, one invalid selected workbook cell, all selected
cells invalid in a row, signed partial-sum cancellation, an externally edited
workbook, previous-workbook preservation on failed export, and clean rerun after
regeneration. Verify that no partial score, automatic exclusion, or reusable
review decision is produced and that normal computable numerical values remain
unchanged. Run focused processing, post-processing export, project-I/O,
and safe static GUI checks through the repository driver. Qt execution remains
CI-only; document a visible/manual error-and-rerun path. Update the post-
processing export/report contracts and user troubleshooting/methods guidance
as part of the implementation.
