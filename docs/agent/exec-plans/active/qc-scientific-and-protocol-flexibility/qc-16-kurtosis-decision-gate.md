# QC-16: Kurtosis Corroboration and GUI Decision Gate

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-06, and QC-15.

**Status:** implemented on the active QC branch. Kurtosis plus an eligible
independent channel-health method permits automatic interpolation. The initial
registry is empty, so kurtosis alone requires manual review in the GUI before
interpolation. Representative-data calibration remains follow-up evidence and
does not expand automatic authority.

## Accepted Behavior

1. Keep the current kurtosis feature at its locked point after filtering and
   downsampling. QC-06 supplies only the analyzed samples for scoring while the
   accepted fixed channel repair remains applied to continuous Raw. Identify
   the calculation as an EEGLAB-inspired, versioned variant rather than an
   exact EEGLAB port.
2. Store each channel's raw kurtosis, signed normalized score, threshold,
   trimmed reference distribution, analyzed condition/occurrence spans,
   filter/downsample identity, and finite/validity state. Never convert an
   undefined statistic to an ordinary zero score. Require a positive finite
   threshold and enough valid reference channels with nondegenerate scale.
3. Define a versioned registry of eligible corroborating methods. Agreement
   means a separately calculated, validated channel-health rule identifies the
   same channel within the same analyzed condition/occurrence evidence where
   temporal attribution is available. A duplicate transform of kurtosis does
   not count. A flag that another approved action defines as review-only cannot
   silently gain automatic authority by co-occurring with kurtosis. Confirmed
   manual/physical bad channels retain their existing direct authority and do
   not need kurtosis. Start the registry empty: separate calculations are not
   evidence of statistical independence or adequate joint performance. Add a
   method only through a later versioned approval supported by joint
   calibration on the intended scope.
4. When kurtosis and an eligible corroborator agree, add the channel to the
   automatic interpolation set and record both reasons. Show the result in the
   GUI/report even though no decision is required. The enabled experimental
   detector can corroborate only after its relevant rule and BioSemi64
   calibration are accepted for that authority under QC-04/QC-15.
   With the initial empty registry, every non-manual kurtosis finding therefore
   goes to GUI review rather than automatic interpolation.
5. When kurtosis is the sole eligible reason, stop before interpolation and
   present it in the GUI review. Processing cannot treat timeout, dialog close,
   CLI/non-GUI execution, missing evidence, or an old decision as approval.
   Users may approve or reject each channel; persist the choice by recording
   and evidence fingerprint. Evidence changes require renewed review.
6. The GUI must show participant, recording/session, electrode, affected
   condition/occurrence evidence, raw kurtosis, signed z, threshold, other
   detector results, and a compact signal view. State plainly that approval
   applies one fixed repair to the full processed recording and list every
   analyzed condition receiving that repaired channel. Preserve QC-09's clear
   distinction when evidence occurred in only one condition.
7. Report candidate, corroborated-auto, user-approved, user-rejected,
   attempted, successful, and failed interpolation states separately. Feed
   only successful repairs into QC-07's burden calculation. Include the method,
   threshold, evidence, decision, geometry, and outcome in cache, processing
   ledger, workbook, and provenance identities.
8. Preserve any legacy kurtosis-only automatic decision and resulting output
   for audit, but label its old method/authority explicitly and mark it stale
   for a new run. Migration cannot reinterpret it as a current reviewed or
   corroborated decision.

## Workflow and Owners

Use the existing preprocessing-QC GUI workflow. Its worker-side scan must
calculate evidence with the same shared preprocessing stages and function used
by final processing, stopping before interpolation/final reference. Actual
processing recomputes or verifies the fingerprint and refuses to apply a stale
decision. Do not create a second numerical kurtosis implementation or allow a
worker to touch widgets.

Primary owners are project preprocessing settings, processing-input assembly,
the preprocessing-QC workflow and workers, `processing/preprocess.py`, raw
channel QC/corroborator ownership, processing ledger/cache, diagnostics, and
QC summary export. QC-02 owns truthful outcome labels; QC-04/QC-05/QC-08/QC-09
retain their separate detector authority and presentation contracts.

## Validation and Calibration

Cover kurtosis-only approve/reject, eligible same-channel corroboration,
different-channel and different-occurrence non-corroboration, review-only flags,
the initially empty registry, manual channels, experimental detector Off,
legacy kurtosis-only automatic outputs, invalid/nonfinite statistics,
threshold validation, dialog close, stale evidence, worker cancellation, and
successful/failed interpolation. Verify no unreviewed kurtosis-only channel can
reach `raw.info["bads"]` or interpolation. GUI behavior receives static checks,
CI-only Qt tests, and a documented visible smoke path.

Calibrate signed score, threshold, temporal persistence, and downstream
SNR/BCA sensitivity against blinded expert-reviewed FPVS BioSemi64 recordings
across intended rates, cycle counts, filter settings, and interpolation
burdens. Until that evidence supports more authority, retain the accepted
review/corroboration policy. Update the preprocessing contract, calibration
guide, GUI/user QC guide, and methods-reporting checklist.

Scientific basis: EEGLAB provides trimmed normalized kurtosis as a channel
screen, while its own guidance emphasizes inspecting whether corruption is
transient; comparative work finds that multimetric channel-health methods can
outperform kurtosis alone
([EEGLAB implementation](https://raw.githubusercontent.com/sccn/eeglab/develop/functions/sigprocfunc/rejkurt.m),
[EEGLAB channel guidance](https://eeglab.org/tutorials/06_RejectArtifacts/Channel_rejection.html),
[PREP](https://doi.org/10.3389/fninf.2015.00016),
[Kumaravel et al., 2022](https://doi.org/10.3390/s22197314)).

## Implementation Evidence

`processing/kurtosis_qc.py` owns the numerical evidence, empty corroborator
registry, decision receipts, and fail-closed authority check.
`processing/kurtosis_review_scan.py` runs the shared preprocessing stages to
the review boundary in a worker-safe scanner. The preprocessing QC workflow
runs that scanner in a `QThread`, reuses only fingerprint-current receipts,
opens `KurtosisReviewDialog` for every new or stale kurtosis-only finding, and
persists only the current recording/channel decisions before processing.
Cancel, close, scan error, missing receipt, or changed evidence blocks the run.

Focused numerical and static GUI tests cover approve/reject receipts,
staleness, invalid evidence, cancellation, display-only raw-QC context,
zero-based occurrence storage with one-based display, fixed repair wording,
and the no-default/reason-required dialog contract. Qt execution remains the
CI gate. The visible smoke path is: open a project containing a recording with
a known kurtosis-only channel; start preprocessing; verify the review lists its
recording, analyzed occurrences, metrics, raw-QC context, trace, and full-recording
repair scope; verify close/cancel stops; then rerun Approve and Reject choices
separately and confirm only the accepted, current receipt reaches processing.
