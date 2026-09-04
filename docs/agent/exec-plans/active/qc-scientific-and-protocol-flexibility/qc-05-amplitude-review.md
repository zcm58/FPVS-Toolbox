# QC-05: Severe Raw-Amplitude Review Flag and Brief GUI Explanation

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** accepted on 2026-09-03. The user explicitly requested a flag with
short, understandable GUI text explaining the concept and linking to BioSemi.
Implementation waits for the completed cumulative plan.

### Current Behavior and Scientific Basis

Current rules in `removed_electrode_detection.py`, around lines 55-58, and
`raw_channel_qc.py`, around lines 1107-1120:

| Level | Scalp-median channel metrics | Behavior before this planned change |
| --- | --- | --- |
| Warning | STD >= 2,000 uV OR P2P99 >= 10,000 uV | Warning/review finding |
| Severe | STD >= 10,000 uV AND P2P99 >= 100,000 uV | V3 preflight: review only; processing runner: automatic recording exclusion |

P2P99 is percentile 99.5 minus percentile 0.5. These are variability/range
metrics, not mean voltage or a prestimulus baseline. The runner measures them
before the configured initial reference, filtering, downsampling, and
interpolation, and can return an excluded result before those stages
(`process_runner.py`, around lines 1268-1315). V3 and runner sampling currently
differ; accepted QC-06 addresses that dependency.

Extreme raw amplitude warrants investigation, but the present thresholds alone
do not establish irrecoverable analyzed-data failure. BioSemi explains that
saved raw channels retain shared common-mode signals which digital referencing
can remove. This does not imply that referencing repairs clipping, missing
measurements, or every hardware problem. No empirical false-exclusion rate
has been established for this toolbox during this audit.

### Accepted Behavior and Proposed GUI Copy

Keep severe amplitude as an identifiable review flag. It must not automatically
exclude a recording or preselect exclusion solely on this finding. A user may
continue with the flag retained or explicitly exclude the affected recording
through the existing review controls. Preserve independent technical failures
and previously confirmed exclusions. Avoid adding a second mandatory dialog
when the existing QC review phase can convey the finding and decision.

Proposed concise phase text:

> Large raw signals detected. Referencing may reduce shared electrical noise.
> Review before excluding this recording.

Place this short explanation directly beside the amplitude finding in the
preflight QC GUI. Provide a clearly labeled clickable link:

- [BioSemi: referencing and shared noise](https://www.biosemi.com/faq/cms%26drl.htm)

Optional expanded help may also link to
[BioSemi: checking electrodes](https://www.biosemi.com/faq/check_electrodes.htm).
Keep the default visible text brief; put metric definitions, measured values,
thresholds, and interval details in the existing details surface. Label the
finding as high raw signal amplitude, avoiding unsupported claims that the
recording is necessarily unusable or that interpolation cannot rescue it.

### Implementation Shape

1. Remove this criterion's independent authority to set recording exclusion in
   the raw-QC runner and compatibility paths. Preserve severity, metrics, and
   provenance. Do not suppress other triggered rules or manually requested
   exclusions when both occur in the same result.
2. Make preflight, later processing, logs, and QC reports agree that this is a
   review finding. A later runner pass must not silently override the user's
   decision to continue on amplitude alone. Keep review decisions scoped to
   recording identity where available and retain the reason/source.
3. Replace amplitude-specific hard-failure wording and "hard exclusion"
   threshold labels with review/severity wording. Reuse shared PySide6 status
   and link components; open BioSemi help only when the user clicks. Normal
   processing must not depend on network access or a successful help-page load.
4. Version affected result/provenance and invalidate stale automatic outcomes
   through existing cache/ledger mechanisms. Preserve manual decisions and
   original EEG/workbooks. Coordinate final fingerprint changes with QC-04
   because both can affect recording eligibility.
5. Retain numerical screening values provisionally pending calibration on the
   analyzed intervals accepted in QC-06.
   Keep STD and P2P99 paired with their actual condition occurrence: do not
   combine maxima from different occurrences to invent a severe conjunction.

### Owners, Validation, and Documentation

Primary owners are `src/Main_App/processing/raw_channel_qc.py`,
`src/Main_App/processing/preflight_qc.py`,
`src/Main_App/Performance/process_runner.py`, and
`src/Main_App/gui/preprocessing_qc_workflow.py`; update shared text/calibration
and reporting/cache adapters only as required. Reuse existing manual
recording-exclusion controls; QC-03 supplies the consistent identity principle
but its post-processing frequency-QC dialog is not the preflight phase.

Verify that an amplitude-only severe result remains flagged and can continue,
explicit manual exclusion works, independent hard failures still take effect,
cached legacy outcomes do not reinstate automatic amplitude rejection, and
flat/repeated-session identities remain correct. Test warning/severe boundaries
and occurrence provenance without asserting that the thresholds are universally
valid. Keep the configured referencing and preprocessing order unchanged.

Run processing focused verification plus relevant static GUI checks; add
CI-only Qt coverage for concise copy, correct link targets, details, and
continue/exclude behavior. Document a visible smoke path with the BioSemi link
and offline help failure. Update the preprocessing contract, calibration guide,
and user QC/methods guidance; QC-02's preprocessing report must carry the flag
and any actual reviewed exclusion accurately.
