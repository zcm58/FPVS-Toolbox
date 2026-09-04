# Kurtosis Screening Calibration

Use this guide when evaluating the QC-16 kurtosis screen or proposing a method
or authority change. The shipped method is an EEGLAB-inspired, versioned
10-percent-trimmed normalized excess-kurtosis screen. It is not an exact
EEGLAB port. Its current corroborator registry is empty, so a non-manual
kurtosis finding always requires explicit GUI review.

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
empty registry and GUI review requirement. The tests in
`tests/processing/test_kurtosis_qc.py`,
`tests/processing/test_preprocess_kurtosis_gate.py`, and
`tests/processing/test_kurtosis_review_scan.py` validate software behavior;
they do not establish detector accuracy.
