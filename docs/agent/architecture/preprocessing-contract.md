# Preprocessing Contract

This page records the active preprocessing owner and the behavior that must stay
stable during Main App refactors. Treat it as the regression lock for the EEG
preprocessing path.

## Current Decision

`src/Main_App/processing/preprocess.py` is large because it preserves a
behavior-sensitive pipeline, not because it is automatically a refactor target.
Do not refactor it for size alone. Prefer documentation, characterization tests,
and focused regression checks unless there is a concrete bug, behavior change,
or maintenance task that requires code movement.

If the pipeline is working and no near-term preprocessing change is planned, the
lowest-risk maintenance path is:

1. Keep this contract current.
2. Add focused tests before any behavior-sensitive edit.
3. Split code only when the extraction boundary is obvious and fully covered.

## Active Owner

`src/Main_App/processing/preprocess.py` is the canonical active implementation
owner for EEG preprocessing.

Current app processing must call:

```python
from Main_App.processing.preprocess import perform_preprocessing
```

Compatibility paths such as `Main_App.perform_preprocessing` and
`Main_App.Shared.processing_mixin` may delegate to this import surface, but
active runtime code must not import retired `Main_App.Legacy_App` preprocessing
paths.

The public preprocessing surface is:

- `begin_preproc_audit(raw, params, filename)`
- `perform_preprocessing(raw_input, params, log_func, filename_for_log)`
- `finalize_preproc_audit(before, raw, params, filename, events_info=..., fif_written=..., n_rejected=...)`

Callers should not depend on private helpers or split-stage internals.

## Processing Route

The canonical file-level process runner is
`src/Main_App/Performance/process_runner.py`. Its single-file worker route is:

1. Exclude header-only BioSemi recordings before load.
2. Check the strict project-root preprocessed Raw cache.
3. On cache miss, load BDF through `Main_App.io.load_utils.load_eeg_file`.
4. Run raw channel-health QC for hard participant exclusions.
5. Capture pre-state with `begin_preproc_audit`.
6. Run `perform_preprocessing`.
7. Store a cache entry only after successful preprocessing.
8. Extract events from the configured stim channel.
9. Build epochs per event-map label.
10. Run post-export through `Main_App.exports.post_export_adapter`.
11. Finalize the preprocessing audit with `finalize_preproc_audit`.
12. Clean up worker memory and temporary memmap paths.

GUI processing must route through the active process runner. Single-file runs use
the same runner with `max_workers=1`. Do not add a fallback path that bypasses
the process runner or calls retired legacy preprocessing.

Before the processing ledger plan is chosen, the GUI may run the embedded
preflight QC workflow in `src/Main_App/gui/preprocessing_qc_workflow.py`. This
workflow is review-first: it scans the selected BDF pool for BioSemi
recording-not-started files, loads eligible raw files in a `QThread` for
conservative removed-electrode/raw-channel/spectral QC summaries, asks the user
to confirm the manual removed-electrode table, offers participant-level
exclusions, and reports remaining suspicious findings. Accepted manual
removed-electrode and participant-exclusion decisions are saved to project
preprocessing settings before `classify_processing_inputs()` runs. Confirmed
recording-not-started files are passed to the process runner through
`_fpvs_preflight_recording_not_started_files` so they can be recorded as
`recording_not_started` exclusions without creating child-process work. The raw
BDF files are never modified.

Epoch building in the process runner must preserve locked FFT crop behavior.
When valid `55_onbin` repetition crops exist for a condition, those repetitions
must keep `N % N_step == 0` and metadata `N_mod_step == 0`. Do not downgrade
the whole condition or any repetition to fixed-epoch fallback. Do not silently
skip fallback repetitions. If a selected repetition cannot produce a valid
`55_onbin` crop, the normal processing run must fail before post-export.
Downstream `FullFFT Amplitude (uV)` columns are expected to include the exact
nominal oddball harmonics from this crop behavior.

The process runner logs `[TIMING] file=... section=... elapsed_ms=...` for
cache lookup, load, pre-audit, preprocessing, cache store, events, epochs,
export, post-audit, and cleanup when those stages run. The returned per-file
result includes `timings_ms` and `preproc_cache_status` so users can compare
first-run and cache-hit runtimes.

The preprocessed Raw cache version is
`preprocessed-raw-v7-manual-removed-electrode-qc`.
The project processing-ledger and Stats group-harmonic cache processing
fingerprints use `processing_fingerprint_v6_manual_removed_electrode_qc`. The
raw channel-health QC threshold, removed-electrode QC mode, and per-file manual
removed-electrode list are part of the cache payload so changes to those
settings invalidate cached preprocessed Raw files. The v7 cache metadata also
persists raw-QC, manual removed-electrode, kurtosis, and interpolated
bad-channel names so cache-hit runs can still produce participant QC summaries.

## Raw QC Hard Exclusions

`src/Main_App/processing/raw_channel_qc.py` owns pre-preprocessing
removed-electrode detection and hard exclusions for raw channel-health failures.
It runs after a BDF is loaded and before `begin_preproc_audit` so interpolation
cannot hide a dead or disconnected channel cluster.
The calibration surface for automatic removed-electrode detection lives in
`src/Main_App/processing/removed_electrode_detection.py`. Keep threshold
constants, user-facing method wording, and low-variance, high-amplitude, and
spatial-predictability decision rules there so future training-data updates have
one obvious adjustment point. Use
`docs/agent/quality/removed-electrode-detection-calibration.md` before changing
those defaults.

`src/Main_App/processing/preflight_qc.py` coordinates the embedded GUI preflight
scan without importing Qt. It reuses `raw_channel_qc.py` for removed-electrode,
hemisphere, bad-fraction, and connected-cluster decisions. It also calls
`src/Main_App/processing/raw_spectral_qc.py`, a deliberately conservative raw
off-harmonic spectral screen intended to surface very large participant-level
artifacts before full preprocessing. Raw spectral preflight flags are review
signals; accepted participant exclusions are still saved through the manual
participant exclusion setting. The deeper per-file raw preflight scan may run
with bounded parallel workers using the same resolved worker limit as the
processing run; output ordering must remain deterministic for reporting.

The project preprocessing setting `removed_electrode_detection_mode` defaults
to `auto` and is exposed in Settings > Advanced > Processing QC as Off,
Conservative auto-detect, or Manual list. The legacy
`auto_detect_removed_electrodes` boolean is retained for compatibility and is
`True` only when the mode is `auto`. When conservative auto-detect is enabled,
persistently flat/very low-variance scalp channels can be automatically added to
`raw.info["bads"]` before preprocessing. The second-pass raw-QC detector adds
flag-only candidate lists for extreme high-amplitude outliers and spatially
inconsistent channels. Those second-pass candidates are reported for review but
are not automatically added to the interpolation target list. Spatial channels
are only flagged when local predictability is both low and a robust outlier
within the participant's own montage. Low-variance raw-QC bad channels are
excluded from kurtosis donor/pick calculations and are included in the later
spherical interpolation target list.

Manual list mode stores `manual_removed_electrodes` as a PID-to-electrode map in
project preprocessing settings. Manual entries supersede automatic detection for
that participant: only the manually listed valid scalp electrodes are treated as
removed-electrode raw-QC candidates, added to `raw.info["bads"]`, excluded from
kurtosis donor/pick calculations, and included in the later spherical
interpolation target list. Manual entries still participate in the same
participant-level hard-exclusion checks for bad-channel count, bad-channel
fraction, hemisphere failure, and connected bad-channel clusters. When the mode
is Off, broad low-variance hard-exclusion checks still run, but isolated
low-variance channels are not auto-marked for interpolation and the local
cluster warning/exclusion rule is not applied.

The project preprocessing setting `manual_excluded_participants` stores
participant IDs that should be skipped without removing their raw `.bdf` files
from the project. These exclusions are edited in Settings > Advanced >
Processing QC and may also be populated by downstream QC tools such as the SNR
Plot Generator when a whole-participant spectral failure is detected. The
process runner resolves the PID through the same participant/file mapping used
for manual removed-electrode metadata and records an `excluded` preflight result
with reason `manual_participant_exclusion`. Parent-side parallel processing
handles these manual exclusions before child-process submission, so excluded
participants do not pay the BDF load/preprocessing cost and the worker pool can
move directly to eligible files.

The default `max_bad_chans` is `20`. A raw file is excluded when any of these
rules trigger on the BioSemi 64 scalp surface:

- More channels than `max_bad_chans` are flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- More than 50 percent of scalp channels are flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- At least 50 percent of a hemisphere is flat, very low amplitude, extreme
  high-amplitude outliers, or spatially inconsistent.
- When removed-electrode auto-detection is enabled, the largest connected
  bad-channel cluster on the scalp montage has at least six electrodes.

When the largest connected raw-QC candidate cluster has at least four but fewer
than six electrodes, the participant is not hard-excluded. The run records a
`possible_bad_channel_cluster` warning so the participant can be reviewed before
group analysis.

The hemisphere rule is intentionally separate from the global fraction rule so a
left- or right-side equipment failure is excluded even when the full-scalp
fraction is below or equal to 50 percent. The cluster rule uses montage geometry
to find connected bad-channel components; it is intended to stop local blocks of
four or more removed/flat electrodes from being interpolated as if they were
isolated channels. The raw BDF is never modified. The per-file result uses
status `excluded`, stage `raw_qc`, reason `raw_channel_qc_failure`, and includes
a `raw_channel_qc` payload with bad channel counts, hemisphere counts, bad
channel names, interpolation candidates, largest cluster details, triggered
rules, and thresholds.

At the end of a GUI processing run, excluded files are reported in a modal
summary alongside header-only BioSemi recordings. The summary must state that
the final processed dataset excludes those files and that the raw BDF files were
not altered. The processing ledger records excluded participants and removes
their expected managed Excel outputs so downstream Excel-based tools do not
silently include stale workbooks from an earlier run.

The GUI finish handler also writes
`Quality Check/Processing_QC_Summary.xlsx` under the active project root. The
workbook has one row per participant in the processing plan and reports the PID,
manually removed electrodes, auto-detected low-SD removed-electrode candidates,
auto-detected high-amplitude removed-electrode candidates, auto-detected
spatial-consistency removed-electrode candidates, kurtosis-rejected electrodes,
final interpolated electrodes, total rejected/interpolated electrode count,
raw-QC warning rules, missing condition outputs, and whether that participant is
included in the final processed dataset. It also includes an exclusion reason
column for excluded or failed participants.
This export is generated from the current per-file results plus the processing
ledger so incremental runs can include participants completed in earlier runs.

Future calibration changes that can alter which raw files or channels enter the
processed dataset must update focused tests and bump the preprocessing cache and
processing-fingerprint labels listed in the calibration guide.

If a worker reports success and at least one, but not all, expected condition
workbooks exist, the processing ledger records that participant as `completed`
with `condition_completeness` set to `partial` and `completion_warning` set to
`missing_expected_outputs`. The available condition workbook(s) are preserved and
remain part of the processed dataset; missing conditions are flagged in the GUI
run summary and in `Processing_QC_Summary.xlsx`. This is a condition-completeness
warning, not a hard participant exclusion. If no expected condition workbook is
created for a successful worker result, the ledger records a failure with reason
`no_expected_outputs` because there is no usable condition-level export for that
participant.

## Pipeline Order

This order is locked behavior. It matches the project decision to align the
Toolbox preprocessing sequence with the Volfart et al. (2021) FPVS
implementation: FIR filtering happens before downsampling. Do not change this
order during ownership, file-organization, performance, cache, GUI, or
documentation refactors:

1. Initial reference using the selected reference pair.
2. Drop the selected reference pair channels.
3. Optional channel limit through `max_idx_keep`, preserving the stim channel
   when needed.
4. FIR filter using the current PySide6/legacy-parity cutoff mapping.
5. Downsample when requested.
6. Kurtosis-based bad-channel rejection and interpolation.
7. Final average reference.

The order is part of the app contract. A refactor that preserves each individual
operation but reorders stages is a statistical-method behavior change. Any
future reorder requires an explicit user request, a fingerprint/cache version
bump, updates to this page and `docs/user/reference/methods-reporting-checklist.md`,
and focused tests equivalent to `tests/processing/test_filter_downsample_order.py`.

## Locked Behavior

`perform_preprocessing` mutates the incoming `raw_input` object in place and
returns the processed `Raw` object plus the number of kurtosis-identified bad
channels. On critical errors caught by its outer guard it returns
`(None, num_kurtosis_bads_identified)`.

The `params` dictionary is also mutable during a run:

- `_fpvs_initial_ref_ok` and `_fpvs_initial_ref_pair` are removed at run start.
- On successful selected-pair referencing, those audit keys are written back.
- The filter fingerprint is computed from the preprocessing order version,
  `high_pass`, `low_pass`, `downsample_rate` or `downsample`, `reject_thresh`,
  reference channels, and stim channel.

Invalid filter cutoff ordering is intentionally fail-fast: if both cutoffs are
present and `high_pass >= low_pass`, `perform_preprocessing` raises
`ValueError` before entering the broad pipeline error guard.

Several stage failures currently warn and continue instead of aborting:

- Initial selected-pair reference failure.
- Resampling failure.
- FIR filter failure.
- Bad-channel interpolation failure.
- Final average-reference failure.

That continuation behavior is historical pipeline behavior. Do not convert it to
fail-fast behavior without an explicit behavior-change request and focused tests.

## Stage Details

Reference handling:

- Default reference channels are `EXG1` and `EXG2` when params do not provide
  `ref_channel1` and `ref_channel2`.
- Selected reference channels are coerced to EEG type when MNE requires it.
- Selected reference channels are dropped after initial referencing if present.
- The audit layer relies on `_fpvs_initial_ref_ok` and
  `_fpvs_initial_ref_pair` when the selected pair is applied successfully.

Channel limiting:

- `max_idx_keep` limits channels by current channel order after reference-channel
  drop.
- The configured stim channel is appended to the keep list when it would
  otherwise be dropped.
- Current behavior uses `raw.pick_channels(final_keep, ordered=False)`.
- The process runner requests a loader subset of the first 64 BDF channels plus
  the selected reference pair and stim channel. This keeps the current BioSemi
  64-channel EEG surface plus `EXG1`/`EXG2` references and avoids loading
  unused `EXG3` through `EXG8` before the existing channel-drop stage.

Filtering:

- `l_freq` is `high_pass` when `high_pass > 0`; otherwise it is `None`.
- `h_freq` is `low_pass`.
- Filtering uses MNE FIR settings:
  `method="fir"`, `phase="zero-double"`, `fir_window="hamming"`,
  `fir_design="firwin"`, `l_trans_bandwidth=0.1`,
  `h_trans_bandwidth=0.1`, `skip_by_annotation="edge"`.
- The historical `filter_length=8449` sample kernel is preserved at the
  downsample target rate. When filtering now runs before downsampling, the
  sample count is scaled to the current sampling rate to preserve the same
  filter duration and MNE transition-band validity.
- The code logs filter snapshot, mutation, Nyquist, range, applied-cutoff, and
  mismatch diagnostics. These messages are part of the current regression
  surface because they help diagnose accidental cutoff changes.

Downsampling:

- Downsampling runs after filtering.
- It runs only when `downsample_rate` is truthy and the current sampling
  frequency is greater than the requested target.
- It uses MNE `raw.resample(..., npad="auto", window="hann", verbose=False)`.

Kurtosis rejection and interpolation:

- Kurtosis runs only when `reject_thresh` is truthy.
- EEG picks exclude existing bads and exclude the stim channel when the stim
  channel exists and is not typed as EEG.
- Kurtosis uses `scipy.stats.kurtosis(data, axis=1, fisher=True, bias=False)`.
- NaN values are normalized with `np.nan_to_num`.
- The current trimmed normalization removes 10 percent from each side when
  enough channels are available.
- Bad channels are selected with `abs(z_score) > reject_thresh`.
- Newly detected bads are appended to `raw.info["bads"]`.
- Interpolation runs only when bads exist and a montage is present, using
  `raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)`.
- If no montage is present, bads remain and a warning is logged.

Final average reference:

- Final average reference is attempted after kurtosis/interpolation.
- It runs only when at least one good EEG channel is available.
- It uses `raw.set_eeg_reference(ref_channels="average", projection=True)` and
  then `raw.apply_proj(verbose=False)`.

Stim-channel preservation:

- The configured stim channel defaults to `config.DEFAULT_STIM_CHANNEL`.
- The optional channel-limit stage must preserve it when present.
- The pipeline logs whether the stim channel is present at the very end.

## Audit Contract

`begin_preproc_audit` captures the pre-state before preprocessing mutates the
`Raw` object. `finalize_preproc_audit` computes the post-state, compares it with
the pre-state, and logs either `preproc_audit` or `preproc_audit_mismatch`.

Audit payload behavior currently covered by tests:

- The final sampling frequency reflects downsampling.
- The stim channel is reported.
- `sha256_head` is populated.
- `fif_written` is reported as an integer flag.
- `save_preprocessed_fif` is not copied into the audit payload.
- A clean synthetic round trip reports no audit problems.

Audit logging should not change pipeline behavior. Existing defensive logging
guards are allowed to keep audit/logging failures from changing preprocessing
results.

## Regression Rules

- Do not change filtering math, reference handling, rejection thresholds, event
  handling, output data shapes, export inputs, or processing order unless the
  user explicitly requests a behavior change.
- Do not change the mutability contract of `raw_input` or `params` without a
  migration plan and tests.
- Do not remove or rename the public preprocessing functions without updating
  all active callers and compatibility exports.
- Do not add `Legacy_App` or `PySide6_App` preprocessing imports.
- Do not introduce GUI toolkit dependencies into preprocessing.
- Do not convert unrelated warning-and-continue stages to hard failures without
  explicit approval. The locked FFT crop contract is the exception already
  approved here: missing `55_onbin` behavior must hard-fail.
- If an internal mode cannot use the active process runner, fail clearly rather
  than silently falling back to legacy preprocessing.
- Refactors may split or move files only after focused tests prove the public
  behavior and generated outputs are unchanged.

## Focused Verification

Use these checks for preprocessing ownership, routing, or behavior changes:

```powershell
python -m py_compile src\Main_App\processing\preprocess.py src\Main_App\processing\raw_channel_qc.py src\Main_App\processing\removed_electrode_detection.py src\Main_App\Performance\process_runner.py src\Main_App\Shared\processing_mixin.py src\Main_App\gui\main_window.py src\Main_App\__init__.py
.\.venv1\Scripts\python -m pytest tests\processing\test_removed_electrode_detection.py tests\processing\test_raw_channel_qc.py -q
.\.venv1\Scripts\python -m pytest tests\processing\test_filter_downsample_order.py tests\processing\test_process_runner_epoch_contract.py -q
.\.venv1\Scripts\python -m pytest tests\processing\test_single_file_process_mode.py tests\gui\test_main_window_processing.py -q
.\.venv1\Scripts\python -m pytest tests\processing\test_preproc_audit.py tests\processing\test_fif_flag_audit.py -q
python .agents\\scripts\\audit\\agent_audit.py
python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```

For documentation-only edits to this contract, confirm the diff only touches
docs unless the user explicitly asked for implementation changes.
