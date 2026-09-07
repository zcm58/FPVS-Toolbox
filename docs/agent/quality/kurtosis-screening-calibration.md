# Kurtosis Screening Calibration

Use this guide when evaluating the QC-16 kurtosis screen or proposing a method
or authority change. The shipped method is an EEGLAB-inspired, versioned
10-percent-trimmed normalized excess-kurtosis screen. It is not an exact
EEGLAB port. Its current corroborator registry is empty. The GUI additionally
offers an experimental automatic rule for valid pending findings with absolute
normalized score strictly greater than 10.0, with a distinct versioned receipt.
This user-selected cutoff has not established detector accuracy; it changes
decision authority, not the score calculation. Projects may also opt into
experimental automatic interpolation of all valid flags above the configured
absolute normalized-score threshold. This separate default-Off policy takes
precedence over the >10 option; it is not a validated artifact classifier.
Invalid statistics and findings outside enabled policies require review.

## Required Dataset

Use expert-reviewed BioSemi ActiveTwo 64 recordings from the intended FPVS
population. Include clean channels, persistent channel failures, transient
artifacts, successful and failed repairs, different presentation/oddball
rates, analyzed cycle counts, filter settings, and interpolation burdens.
Keep every recording from one participant in the same development or holdout
partition. Treat recording-channel as the prediction unit while also reporting
participant-level and recording-level uncertainty.

The reference labels must record whether a channel should receive one fixed
whole-recording repair. Preserve condition and occurrence annotations so the
evaluation can distinguish persistent evidence from a transient finding. A
review-only detector flag is context, not an independent ground-truth label or
an eligible corroborator.

## Frozen Inputs and Outputs

Before running a calibration, freeze and record:

- dataset identifier/version, acquisition hardware, label protocol, reviewers,
  adjudication rule, participant split, and all denominators;
- Toolbox commit, BioSemi64 geometry fingerprint, analyzed-span planner,
  filter/downsample identity, kurtosis method/threshold, minimum reference
  size, trim rule, and corroborator-registry fingerprint;
- per-channel raw kurtosis, signed normalized score, validity state, decision,
  attempted/successful interpolation, and downstream SNR/BCA change; and
- sensitivity, specificity, positive and negative predictive value, confidence
  intervals, review burden, and errors grouped by artifact type and protocol.

Write a machine-readable receipt beside the study report. It must contain the
frozen identities above, exact source hashes or an immutable dataset release,
sample counts, metrics with confidence intervals, and the command/environment
needed to reproduce them. Do not publish a percentage without its numerator,
denominator, and target estimand.

## Approval Boundary

Calibration evidence may support a threshold adjustment or adding a separately
calculated method to the corroborator registry. It does not itself change code
or authority. Such a change requires an explicitly approved statistical-method
update, new method/registry versions, cache invalidation, preprocessing-contract
and methods-checklist updates, and focused tests proving that different-channel,
different-scope, stale, invalid, and review-only findings cannot authorize an
automatic repair.

Until representative holdout evidence supports a change, keep the current
empty registry and retain manual review outside the optional experimental
policies; evaluate each policy separately from individually reviewed decisions. The tests in
`tests/processing/test_kurtosis_qc.py`,
`tests/processing/test_preprocess_kurtosis_gate.py`, and
`tests/processing/test_kurtosis_review_scan.py` validate software behavior;
they do not establish detector accuracy.

## MNE review adapters and shadow evidence

The preprocessing review viewer adds `mne_amplitude_review_shadow_v1` in
`Main_App.processing.qc_review_diagnostics`. It reuses MNE's public
`annotate_amplitude` implementation for consecutive-sample flat/peak support.
The toolbox adapter supplies exact occurrence boundaries, channel identity,
bounded chunks, provisional duration/robust-scale settings, and a descriptive
candidate-clipping label for extreme repeated plateaus. It records the MNE
version and input-sample fingerprints. MNE annotations and returned bad names
are not applied to the production Raw object.

Optional held-out spatial checks reuse `Raw.interpolate_bads` on copied,
bounded samples with known unusable donors excluded. They report observed vs
predicted agreement at withheld usable sensors, not known truth at damaged
sensors. Nearest-donor diagrams describe location support, not spline weights.

This is method reuse with separately unvalidated threshold/authority choices.
The existing registry remains empty. Same-pattern recurrence somewhere in
every analyzed occurrence does not establish continuous electrode failure;
flatness, amplitude, plateau, kurtosis and spatial agreement are not treated
as independent votes. Missing, truncated, nonfinite or insufficient evidence
must remain explicit. Lack of a displayed pattern is not a clean classification.

Before automatic promotion, compare the complete frozen adapter against
independent expert labels with all visits from each participant kept in one
partition and a held-out project/protocol evaluation. Include unflagged
recordings in adjudication, record reviewer disagreement, and assess errors at
both event and whole-recording-channel repair scope. Report confidence
intervals, false repairs/exclusions, missed artifacts, downstream BCA/SNR
distortion and review time. Threshold selection and evaluation must use
separate data; any clinical/population/protocol performance claim requires its
own representative evidence. Unit/synthetic MNE parity tests are not that
calibration receipt.
