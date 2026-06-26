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
  metadata, participant hard-exclusion recommendations, and remaining
  suspicious findings before processing starts.
- `src/Main_App/gui/manual_removed_electrodes_dialog.py`: modal table for
  project-level manual removed-electrode metadata.
- `src/Main_App/gui/manual_participant_exclusions_dialog.py`: modal table for
  project-level manual participant exclusions.
- `src/Main_App/processing/raw_channel_qc.py`: raw BDF sampling, montage
  neighbor lookup, participant-level hard-exclusion rules, and pipeline result
  payloads.
- `src/Main_App/gui/settings_panel.py`: Advanced Settings control and info
  dialog text import.
- `tests/processing/test_removed_electrode_detection.py`: focused tests for the
  calibration surface.
- `tests/processing/test_raw_channel_qc.py`: integration tests for raw-QC
  participant behavior.

Keep future threshold tuning in `removed_electrode_detection.py` unless the
sampling strategy, montage geometry, or participant exclusion rules themselves
must change.

Keep raw spectral preflight threshold tuning in `raw_spectral_qc.py`. This
screen is intentionally conservative and should prioritize participant-level
review of extreme artifacts over channel-level automatic removal.

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

Use the confirmed physically removed electrodes as positives. Treat clean,
confirmed plugged-in electrodes as the main negative class. Keep "looked funny
but left in" electrodes and kurtosis-rejected plugged-in electrodes as stress
sets, not as clean negatives.

## Metrics To Extract

For every labeled electrode, calculate the same raw-window metrics used by the
detector:

- Standard deviation in microvolts.
- 99 percent peak-to-peak amplitude in microvolts.
- Ratios against the participant's robust good-channel baseline.
- Spatial predictability or inconsistency scores from local montage neighbors.
- Persistence across sampled windows when adding a new window-level rule.

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

Report isolated-electrode detection separately from participant-level hard
exclusions such as hemisphere failure, more than 50 percent bad electrodes, and
connected bad-channel clusters.

## Tuning Rules

The automatic mode is intentionally conservative. Prefer leaving an uncertain
electrode in the dataset over auto-removing a plugged-in electrode.

When tuning:

- Start from `DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION`.
- Adjust one decision branch at a time: low variance, high amplitude, then
  spatial predictability.
- Confirm that the method still has very high specificity before improving
  sensitivity.
- Do not tune thresholds directly against the target channel list for one study
  without validating against a holdout participant or study when available.
- Keep manual metadata as the highest-authority input. In Manual list mode,
  manual removed-electrode metadata overrides automatic detection for that
  participant and should be used as the ground truth reference when calibrating
  future automatic thresholds.

## Verification Commands

Activate the repo environment first. Examples use the documented `.venv1` path;
use the active local virtual environment path when a checkout differs.

```powershell
.\.venv1\Scripts\Activate.ps1
python -m pytest tests\processing\test_removed_electrode_detection.py tests\processing\test_raw_channel_qc.py -q
python -m pytest tests\processing\test_preprocessing_settings.py tests\processing\test_preproc_persistence.py -q
python -m pytest tests\processing\test_process_runner_epoch_contract.py -q
python -m py_compile src\Main_App\processing\removed_electrode_detection.py src\Main_App\processing\raw_channel_qc.py src\Main_App\gui\settings_panel.py
ruff check src\Main_App\processing\removed_electrode_detection.py src\Main_App\processing\raw_channel_qc.py src\Main_App\gui\settings_panel.py tests\processing\test_removed_electrode_detection.py tests\processing\test_raw_channel_qc.py
python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
python .agents\scripts\audit\agent_audit.py
```

Do not run offscreen Qt or pytest-qt workflows locally. For the Advanced
Settings info dialog and Manual list modal, use the visible GUI smoke path
documented in
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
