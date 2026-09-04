# Removed-Electrode Detection Calibration

Use this guide when tuning the automatic detector for electrodes that were
physically removed from the cap before recording, usually to avoid a CMS/DRL
recording error.

## Owner Files

- `src/Main_App/processing/removed_electrode_detection.py`: calibration
  constants, user-facing method warning text, manual PID/electrode metadata
  normalization, and the low-variance, high-amplitude, and
  spatial-predictability decision rules.
- `src/Main_App/processing/preflight_qc.py`: non-GUI orchestration for the
  embedded pre-processing QC scan. It is the place to adjust how raw-channel,
  recording-not-started, and raw spectral summaries are combined before GUI
  review.
- `src/Main_App/processing/raw_spectral_qc.py`: conservative raw off-harmonic
  spectral artifact screen used only for preflight review and participant-level
  recommendations.
- `src/Main_App/gui/preprocessing_qc_workflow.py`: modal embedded workflow that
  presents recording-not-started files, prepopulated manual removed-electrode
  metadata, recording-level signal-review decisions, and remaining scoped
  findings before processing starts.
- `src/Main_App/gui/manual_removed_electrodes_dialog.py`: modal table for
  project-level manual removed-electrode metadata.
- `src/Main_App/gui/manual_participant_exclusions_dialog.py`: modal table for
  project-level manual participant exclusions.
- `src/Main_App/processing/raw_channel_qc.py`: raw BDF sampling, BioSemi64
  neighbor lookup, structured review rules, and pipeline result payloads.
- `src/Main_App/gui/settings_panel.py`: Experimental Settings control and info
  dialog text import.
- `tests/processing/test_removed_electrode_detection.py`: focused tests for the
  calibration surface.
- `tests/processing/test_raw_channel_qc.py`: integration tests for raw-QC
  participant behavior.

Keep future threshold tuning in `removed_electrode_detection.py` unless the
sampling strategy, montage geometry, or review rules themselves must change.

Keep raw spectral preflight threshold tuning in `raw_spectral_qc.py`. This
screen is intentionally conservative and should prioritize participant-level
review of extreme artifacts over channel-level automatic removal.

## Canonical Geometry Boundary

The load-time BioSemi64 header gate and this experimental signal detector answer
different questions. The loader requires a complete, unambiguous supported cap
identity and canonical coordinates; missing labels, unsupported layouts, or
CMS/DRL presented as data channels are technical failures. A physically
disconnected electrode normally remains as a named BDF signal, so the loader
can accept its identity while this detector evaluates its recorded signal for
low variance, extreme amplitude, rare bursts, or poor prediction from nearby
sensors.

Spatial predictability and connected-channel rules must use the canonical MNE
`biosemi64` coordinates supplied by `Main_App.io.eeg_geometry`. The explicit
`biosemi64_1020_ab_v1` mapping is limited to the standard BioSemi 64-channel
10/20 A1-A32/B1-B32 wiring; BioSemi ABC/equiradial and custom layouts are not
supported. Do not infer positions from ordinal channel order or fall back to
`standard_1005`.

The QC-15 synthetic sensitivity diagnostic establishes that template choice
can change interpolation and downstream near-threshold values. It held the bad-
channel list fixed, so it did not measure this detector's sensitivity,
specificity, positive predictive value, or changed spatial nominations. The
reported approximately 60% sensitivity, greater-than-99% specificity, and
99.7% positive predictive value remain development-lab dataset results only.
Reproduce them with the final analyzed-interval sampling and BioSemi64 geometry
before shipping the detailed claim, with denominators, uncertainty, detector
version, and threshold-development/evaluation design. Dataset publication can
enable independent validation; it is not itself external validation.

Use the
[BioSemi64 geometry sensitivity diagnostic](biosemi64-geometry-sensitivity.md)
as the geometry-isolation receipt. A representative labeled lab-data rerun is
still required to estimate how often the geometry correction changes detector
nominations or historical scientific conclusions.

## Current Sampling and Authority

Signal metrics use only exact marker-reviewed analyzed occurrences. Exact
full-occurrence metrics count each sample once. Transient diagnostics use
5-second windows with a nominal 2.5-second hop, including one full tail-aligned
window when needed and one unpadded window for occurrences shorter than 5
seconds. Overlapping flags report the union of flagged-window coverage; that
coverage is not an estimate of artifact duration and overlapping windows are
not independent events.

Low variance in the same category across every evaluated occurrence may be
proposed for removed-electrode review when the experimental detector is
enabled. High amplitude, rare bursts, spatial inconsistency, occurrence-local
findings, and all candidate count/fraction/hemisphere/cluster thresholds are
review evidence only. Severe whole-cap amplitude is also review-only. These
rules preserve measurements for a user decision and do not establish that a
recording is unusable. Their numerical thresholds remain provisional pending
the participant-split empirical evaluation below.

## Calibration Data

Build calibration sets from labeled raw recordings, not from processed Excel
outputs alone.

Required labels:

- PID and raw filename.
- Confirmed physically removed electrodes.
- Electrodes that were plugged in but looked abnormal during setup.
- Header-only or recording-not-started files, kept separate from channel-level
  calibration.
- Participant-level failures such as one side of the cap being absent.

When labels come from experimenter notes, enter them through Settings >
Advanced > Processing QC > Manual list. The manual map is stored as
`manual_removed_electrodes` under project preprocessing settings and is the
highest-authority input for physically removed channels.

The embedded preflight review stores calibration provenance in addition to that
compatibility map. `Quality Check/Processing_QC_Summary.xlsx` includes the
original FPVS Toolbox auto flags, accepted auto flags, rejected auto flags,
manual additions, final confirmed removed electrodes, manual-only misses,
auto/manual overlap, and the agreement status. Use those columns to identify
cases such as a missed `P9` before changing thresholds.

Use the confirmed physically removed electrodes as positives. Treat clean,
confirmed plugged-in electrodes as the main negative class. Keep "looked funny
but left in" electrodes and kurtosis-rejected plugged-in electrodes as stress
sets, not as clean negatives.

## Metrics To Extract

For every labeled electrode, calculate the same raw-window metrics used by the
detector:

- Standard deviation in microvolts.
- 99 percent peak-to-peak amplitude in microvolts.
- 99.9 percent and full-window peak-to-peak amplitude in microvolts when
  checking rare burst behavior.
- Ratios against the participant's robust good-channel baseline.
- Recording-level scalp median STD and P2P99 for warning and severe review.
- Spatial predictability or inconsistency scores from local montage neighbors.
- Full-occurrence category persistence and separate 5-second/50%-overlap
  transient-window provenance.

Report distributions separately for confirmed unplugged electrodes, confirmed
plugged-in clean electrodes, plugged-in setup-warning electrodes, and
kurtosis-rejected plugged-in electrodes.

## Accuracy Report

Before changing defaults, create a confusion-matrix report for the current
training set:

- True positives: confirmed removed electrodes detected by auto QC.
- False positives: confirmed plugged-in electrodes removed by auto QC.
- False negatives: confirmed removed electrodes left in the data.
- True negatives: confirmed plugged-in electrodes left in the data.
- Sensitivity/recall for confirmed removed electrodes.
- Specificity for confirmed plugged-in electrodes.
- Positive predictive value for auto-removed electrodes.
- False-positive and false-negative channel lists by PID.

Report proposed removed electrodes separately from recording-level review
findings for candidate count, fraction, hemisphere concentration, connected
clusters, and severe amplitude. Also report false alerts per clean recording
hour and avoid treating overlapping windows as independent samples.

For transient calibration, compare 5-second/50%-overlap against 5-, 10-, and
15-second non-overlapping arms on independently annotated clean and artifact
intervals. Include 50, 100, and 300 ms synthetic checks only as numerical
verification, not ground truth. Split development and holdout data by
participant or recording, stratify by protocol rates and analyzed duration,
and report event recall, distinct channels flagged, false alerts per recording
and clean hour, and reviewer burden. Publishable in-lab data can support
reproduction; a separate dataset or lab is still needed for external
validation.

## Tuning Rules

The automatic mode is intentionally conservative. Prefer leaving an uncertain
electrode in the dataset over auto-removing a plugged-in electrode. Extreme
whole-cap amplitude requires explicit review because raw BioSemi common-mode
signals may change after reference; the amplitude thresholds alone do not
authorize exclusion.

When tuning:

- Start from `DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION`.
- Adjust one decision branch at a time: participant baseline, low variance,
  high amplitude, rare burst, then spatial predictability.
- Confirm that the method still has very high specificity before improving
  sensitivity.
- Treat high-amplitude and rare-burst electrode rules as review candidates
  unless a calibration report shows they do not add plugged-in clean-channel
  false positives.
- Do not tune thresholds directly against the target channel list for one study
  without validating against a holdout participant or study when available.
- Keep manual metadata as the highest-authority input. When its independent
  switch is enabled, recording-specific entries override participant entries
  and remain active whether automatic detection is On or Off. Under On, retain
  separate manual and automatic provenance. Use confirmed manual metadata as
  the ground-truth reference when calibrating future automatic thresholds.

## Verification Commands

Use the processing scope; the driver selects `.venv1` or `.venv`:

```console
python .agents/scripts/verify.py --scope processing --tier focused
```

Qt execution is CI-only by default. For the Advanced Settings info dialog and
Manual list modal, use the visible GUI smoke path documented in
`docs/agent/quality/test-selection.md`.

## Cache And Fingerprint Updates

If a calibration change can alter which raw files or channels are included in
the processed dataset, bump the preprocessing cache and processing-fingerprint
labels:

- `src/Main_App/Performance/process_runner.py`: `PREPROC_CACHE_VERSION`
- `src/Main_App/processing/processing_ledger.py`:
  `PROCESSING_FINGERPRINT_VERSION`
- `src/Tools/Stats/data/group_harmonic_cache.py`:
  `PROCESSING_FINGERPRINT_VERSION_LABEL`

Then reprocess a labeled calibration project and compare
`Quality Check/Processing_QC_Summary.xlsx` against the manual labels.
Adding or exporting provenance-only comparison metadata does not require a cache
or processing-fingerprint bump when the detector thresholds, preprocessing
order, and final channel inclusion behavior are unchanged.

Current baseline/rare-burst calibration is intentionally narrow. The severe
amplitude review starts when scalp median STD is at least 10,000 uV and scalp
median P2P99 is at least 100,000 uV. The warning review starts at 2,000 uV
median STD or 10,000 uV median P2P99. Neither level automatically excludes a
recording. The rare-burst channel rule
looks for the top-ranked STD outliers with STD at least 8,000 uV and compressed
P2P99 or a very large full-window/P2P99 ratio; those channels are surfaced in
preflight review and QC exports rather than silently interpolated.
