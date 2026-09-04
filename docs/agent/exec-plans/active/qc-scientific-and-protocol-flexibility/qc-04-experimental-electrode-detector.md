# QC-04: Experimental, Opt-In Removed-Electrode Detection

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** software behavior implemented on the active QC branch. The detector
is project-owned, experimental, Off by default for new projects, independent
from manual channel authority, and restricted to analyzed intervals. The
historical percentages are now named as sensitivity, specificity, and positive
predictive value from an earlier in-lab dataset. Current-method recalibration
remains blocked on the versioned labeled dataset and is recorded explicitly in
the pending receipt; no current or external-validation claim is made. Here,
recording-level amplitude describes the scope of the finding, not permission to
score the entire file.

### Problem and Accepted Direction

The automatic detector uses signal patterns calibrated on the development
lab's recordings. The present controls do not reliably reflect whether it is
enabled: preflight forces Auto, review can replace the saved mode with Manual,
and some automatically derived processing-time burden checks remain under Off.

Label automatic removed-electrode detection **experimental**. Default it to
Off for new projects and allow users to enable it explicitly. Respect the
saved choice in preflight, review, and processing. Keep manually entered
removed-electrode lists available independently. Signal-based suggestions
remain distinct from experimenter-confirmed physical removal.

Place this project-owned control in the dedicated **Experimental settings**
section shared with QC-17. Its Off-by-default policy remains independent of
QC-17's review-only summed-BCA screen.

### Accepted Existing-Project Migration

- Preserve valid saved modes or legacy booleans, manual-list contents, and
  their existing application state. Map Manual to automatic detection off
  with manual lists active; do not activate previously dormant stored lists.
- Inspect original manifest values/aliases before normalization. Missing
  settings currently normalize to Auto, and project loading replaces the
  in-memory preprocessing fields (`preprocessing_settings.py`, around lines
  98 and 653; `project.py`, around line 376). A saved Auto value is a recorded
  configuration, not proof of an explicit historical opt-in.
- Preserve existing processed outputs and recorded decisions; do not present
  migrated Auto as newly confirmed opt-in.
- When neither a valid mode nor legacy boolean was saved, ask once before
  the next processing run, recommending Off. Opening/viewing existing results
  remains available. Persist the choice and migration provenance so the
  question does not recur.

### Implementation Shape and Settled Control Map

1. Establish one project-owned automatic-detection choice and pass it unchanged
   through settings normalization, GUI review, workers, preflight, and the
   process runner. Replace unconditional preflight Auto and review mode changes
   with behavior consistent with that choice. Keep manual-list application
   separate and preserve participant/recording identity and provenance.
2. Enforce the accepted Off behavior for inferred low-variance, high-amplitude,
   rare-burst, and spatial candidates: no automatic removed-electrode prefill,
   interpolation, or count/fraction/hemisphere/cluster exclusions based on
   those guesses. Manual-channel burden safeguards may use confirmed active
   manual entries independently. QC-08 owns the provisional burden thresholds
   and review-only authority. Keep general amplitude QC separate and
   independently identified; QC-05 makes its severe result a review flag and
   QC-06 restricts its measurements to analyzed intervals.
3. Keep header/file integrity and event/crop correctness separate. Preserve
   QC-01's separately named transient-review scope regardless of this detector
   setting. When the detector is Off, shared measurements may appear only under
   QC-01/QC-05; do not label them detector evidence or interpolation
   suggestions. Do not change numerical thresholds or persistence rules under
   this feature labeling/control decision alone. QC-06 separately authorizes
   replacing whole-recording six-window sampling with analyzed-interval inputs.
4. Implement the accepted existing-project migration above. Read original saved
   values before defaults are materialized and support valid legacy aliases.
   Do not delete prior user-confirmed decisions or reinterpret saved Auto as
   fresh user consent.
5. Version the control/migration provenance and include effective settings in
   appropriate preflight and processing identities. Disabling detection must
   not reapply unaccepted cached suggestions. Reuse existing stale-output and
   fingerprint mechanisms when effective channel/exclusion behavior changes;
   do not silently regenerate existing EEG results merely on project open.
6. Keep the reported approximately 60% sensitivity, greater-than-99%
   specificity, and 99.7% positive predictive value only as results of internal
   validation on the development lab's dataset. Use those metric names rather
   than calling positive predictive value general accuracy. State the evaluated
   sample, equipment, protocol range, detector version, and uncertainty beside
   the detailed claim; the short settings text may link to those details.
7. Commit a reproducible calibration receipt before shipping the claim. Record
   labeled connected/removed counts, participant and recording counts,
   prevalence, confusion matrix, threshold-selection procedure, held-out or
   cross-validation design, point estimates with confidence intervals, dataset
   version/hash, and exact analysis code/environment. If the same observations
   tuned and evaluated the rules, label the numbers development-sample results
   rather than internal validation.
8. Recalculate the metrics with the final implementation after QC-01's window
   change, QC-06's analyzed-interval scope, and QC-15's BioSemi64 geometry. Show
   the newly reproduced estimates if they differ; do not preserve an old number
   merely for continuity. A public, appropriately governed dataset release may
   be linked for independent validation. Availability enables external
   validation but is not itself evidence that external validation occurred.

When the detector is On, apply this complete authority map:

| Finding | Default GUI treatment | Repair/exclusion authority |
| --- | --- | --- |
| Persistent low variance in every evaluated occurrence | Clearly labeled, preselected **proposed interpolation** requiring affirmative Apply | May repair after that user decision; automatic corroboration only if QC-16 later registers this exact scope after joint calibration; no automatic exclusion |
| Persistent high amplitude or rare burst | Visible, unselected evidence | No repair or exclusion alone; possible future QC-16 eligibility requires rule-specific calibration and registry approval |
| Spatial-predictability outlier | Visible, unselected evidence only with valid QC-15 geometry | No repair or exclusion alone; possible future QC-16 eligibility requires geometry-specific calibration and registry approval |
| Candidate count/fraction, hemisphere burden, or connected cluster | QC-08 recording-review flag, no preselected exclusion | No repair; explicit user retain/exclude decision only |
| QC-01 transient finding | Separate condition/occurrence review evidence | No repair or exclusion |
| QC-05 severe amplitude | Independent prominent review flag under On or Off | No repair; explicit user retain/exclude decision only |

An experimenter-confirmed manual/physical bad channel remains an interpolation
decision under On or Off and does not require detector or kurtosis support. It
does not by itself force a recording exclusion. The initial QC-16 automatic
corroborator registry is empty; shipping a populated registry requires the
calibration and versioned approval defined there.

The accepted separation preserves general amplitude measurement even when the
experimental detector is Off. It does not authorize keeping exclusions derived
from disabled removed-electrode guesses under a different label. QC-01's
transient findings remain separate review signals, and confirmed manual entries
retain their independent application and provenance.

### Owners, Verification, and Documentation

Primary owners are `src/Main_App/projects/preprocessing_settings.py`,
`src/Main_App/projects/project.py`,
`src/Main_App/gui/settings_panel.py`,
`src/Main_App/gui/preprocessing_qc_workflow.py`,
`src/Main_App/processing/preflight_qc.py`,
`src/Main_App/processing/raw_channel_qc.py`, and
`src/Main_App/processing/removed_electrode_detection.py`. Follow the effective
settings through `src/Main_App/Performance/process_runner.py` and existing
cache/ledger owners only where required by the accepted control map.

Validate a new project with default Off, explicit opt-in, Off retained after
scan/review/reopen, independent manual lists, and the approved legacy migration
cases. For each rule in this control map, verify whether it can generate
a suggestion, interpolation target, or exclusion under each effective setting.
Include cached-result reuse/invalidation and participant/recording overrides.
These are behavior tests, not proof of detector sensitivity or specificity.
Add a reproducible calibration check that rebuilds the confusion matrix and
metrics from the versioned in-lab reference dataset and fails on unexplained
drift from the displayed values.

Run the processing and project-I/O focused verification scopes; add GUI-static
checks for changed controls and CI-only Qt coverage. Document a visible smoke
path for the settings, preflight review, and saved-state round trip. Update
the preprocessing contract, calibration guide, and relevant user QC/methods
instructions with the approved control matrix and migration. Retain the locked
preprocessing order and harmonic-selection contracts.

### Implementation Evidence

The project schema, migration prompt, Settings control, preflight cache,
review workflow, processing inputs, per-recording manual override, and final
processing authority now consume one saved detector choice. Focused tests cover
new-project Off, explicit On, legacy choices, unresolved-project prompting,
manual-only operation, analyzed-condition restriction, and separation of
review-only flags from interpolation/exclusion authority.

`docs/agent/quality/removed-electrode-detection-calibration-pending-receipt.json`
preserves the three historical in-lab estimates while leaving unknown
denominators, uncertainty, sample identity, and validation split null. This is
deliberate evidence of the remaining data dependency, not a completed receipt.
Replace it with a reproducible current-method receipt only after the user makes
the labeled development-lab dataset available and the participant-split rerun
is independently checked.
