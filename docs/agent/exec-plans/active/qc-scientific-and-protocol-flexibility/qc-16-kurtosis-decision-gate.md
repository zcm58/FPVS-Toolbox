# QC-16: Kurtosis Corroboration and GUI Decision Gate

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-06, and QC-15.

**Status:** implemented on the active QC branch. Kurtosis plus an eligible
independent channel-health method permits automatic interpolation. The initial
registry remains empty. The GUI also offers the user-approved experimental
absolute-normalized-score > 10.0 rule; other kurtosis-only findings require
manual review. Representative-data calibration remains follow-up evidence.

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
   The GUI also offers the separately labeled experimental `|normalized score|
   > 10.0` rule for valid pending findings. It defaults on for this review, can
   be disabled, and creates versioned experimental receipts rather than manual
   approvals. Exactly 10.0 stays manual. This does not populate the registry
   or establish scientific validation of the cutoff.
5. Outside that enabled experimental rule, when kurtosis is the sole eligible
   reason, stop before interpolation and
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
7. Report candidate, corroborated-auto, experimental-auto, user-approved, user-rejected,
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
successful/failed interpolation. Verify no kurtosis-only channel without a current manual or qualifying
experimental receipt can reach `raw.info["bads"]` or interpolation. GUI behavior receives static checks,
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
and the no-default/reason-required contract for manual decisions. Qt execution remains the
CI gate. The visible smoke path is: open a project containing a recording with
a known kurtosis-only channel; start preprocessing; verify the review lists its
recording, analyzed occurrences, metrics, raw-QC context, trace, and full-recording
repair scope; verify close/cancel stops; then rerun Approve and Reject choices
separately and confirm only the accepted, current receipt reaches processing.


### Compact review update (2026-09-04)

Implemented the user-approved experimental cutoff using **absolute normalized
score > 10.0**, retaining the scoring calculation and processing order. Seven
columns replace the fourteen-column table and recording-wide text dump. One
selected-row evidence/trace panel replaces per-row trace widgets; fixed row
heights avoid repeated content measurement. Automatic rows are hidden by default
and can be shown. Disabling the option restores manual choices without rescoring.
Automatic receipts retain the same recording, evidence, geometry, and analyzed
span checks as manual receipts and persist their distinct experimental authority.

Visible smoke (Qt execution is CI-only locally): at 1280x900, open a review with
both score ranges; confirm the automatic/manual counts, seven readable columns,
row-specific evidence and trace. Toggle Show automatic and the experimental rule,
verify manual choices/reasons survive toggling, and verify all-automatic findings
can continue with Apply decisions. Exactly +/-10.0 must remain manual; missing
manual choices/reasons must block and select the relevant row. Cancel must save
nothing. Rerun with unchanged evidence to confirm receipts are reused.


Verification for the compact review update: `verify.py --scope gui --tier focused`
passed; `verify.py --scope processing --tier focused` passed (498 tests, one
skip). Explicit pytest coverage for `test_kurtosis_qc`,
`test_preprocess_kurtosis_gate`, `test_kurtosis_review_scan`,
`test_kurtosis_audit_provenance`, `test_kurtosis_ledger_provenance`, and
`test_kurtosis_review_dialog_static` passed (68 tests). An AST comparison against
the previous commit confirms `evaluate_kurtosis_qc` is unchanged. The repo
precommit gate is blocked by eight pre-existing local-path findings under
untracked `outputs/`; those files were left untouched. Visible Qt validation
remains pending via the smoke path above, per the local Qt execution restriction.


### Immediate stale-review failure and scan runtime repair (2026-09-04)

Fixed two metadata mismatches: the scanner added a source path to the selected
span identity that the runner omitted, and single-session recordings used the
participant ID in the scanner but `None` in the runner. Both now use the same
participant/recording identity, with separate receipt-level source-path checks.
When experimental removed-electrode detection is on, the scanner recomputes the
same direct bad-channel decisions on current analyzed intervals as the runner.
The scoring formula, thresholds, filtering order, and stale-evidence guards are
unchanged. The runner now preserves the underlying preprocessing failure reason.

Ordinary file failures update rows/logs and remain in the ledger/report; they
produce one final summary instead of per-file fatal dialogs that prematurely
unlocked the batch. Review scans can run two recordings concurrently under a
conservative memory budget and distinct-memmap-name check, reuse owned Raw data,
and log load/events/preprocessing/scoring durations. Synthetic two-recording
FIR/resample/kurtosis benchmark: 30.02s serial versus 15.04s parallel with exactly
equal outputs. Kurtosis alone was already vectorized (~0.20s for 64 channels ×
184,320 samples). These are synthetic timings, not a rerun of the user's batch.

Regression checks exercise real scanner-to-runner preprocessing for single and
named sessions, condition exclusions, filtering/downsampling, detector-on direct
bads, and genuine threshold changes; additional checks cover ordered parallel
results, callback thread, cancellation/Raw cleanup, and aggregated batch errors.
Visible smoke (not run locally under the Qt restriction): restart the app, rerun
QC, apply current approvals, and confirm preprocessing advances. Run two failing
files plus a valid one: failed rows should update without OK prompts, controls
stay locked until completion, and one summary retains the original error reasons.


Validation: GUI focused audit/lint/compile passed. Processing focused gate:
498 passed, one existing skip. Explicit kurtosis/scanner/provenance and non-Qt
GUI routing checks: 76 passed. Real preprocessing integration checks: 28 passed
(short synthetic filter fixtures emit expected filter-length warnings). The
numerical `evaluate_kurtosis_qc` AST matches the committed implementation exactly.
Precommit remains blocked by the eight existing path findings in untracked
`outputs/`; these were not edited. Qt execution and the full user batch were
not run locally.

Files changed for this repair (relative to the repo root):

- Runtime: `src/Main_App/processing/kurtosis_review_scan.py`,
  `src/Main_App/processing/preprocess.py`,
  `src/Main_App/Performance/process_runner.py`,
  `src/Main_App/workers/mp_runner_bridge.py`,
  `src/Main_App/gui/processing_workflows.py`,
  `src/Main_App/gui/processing_completion.py`.
- Tests: `tests/processing/test_kurtosis_review_scan.py`,
  `tests/processing/test_preprocess_kurtosis_gate.py`,
  `tests/processing/test_mp_runner_bridge_full_pipeline_smoke.py`,
  `tests/gui/test_processing_failure_routing_static.py`.
- Docs: this QC-16 module, `docs/agent/architecture/preprocessing-contract.md`,
  `docs/agent/architecture/workers-threading.md`.

Protected-boundary audits passed; retired `Legacy_App` and `PySide6_App` paths
were not affected. Prior dialog/experimental-cutoff edits remain in place.
