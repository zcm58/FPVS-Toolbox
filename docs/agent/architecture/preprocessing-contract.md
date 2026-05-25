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

1. Check the strict project-root preprocessed Raw cache.
2. On cache miss, load BDF through `Main_App.io.load_utils.load_eeg_file`.
3. Capture pre-state with `begin_preproc_audit`.
4. Run `perform_preprocessing`.
5. Store a cache entry only after successful preprocessing.
6. Extract events from the configured stim channel.
7. Build epochs per event-map label.
8. Run post-export through `Main_App.exports.post_export_adapter`.
9. Finalize the preprocessing audit with `finalize_preproc_audit`.
10. Clean up worker memory and temporary memmap paths.

GUI processing must route through the active process runner. Single-file runs use
the same runner with `max_workers=1`. Do not add a fallback path that bypasses
the process runner or calls retired legacy preprocessing.

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

## Pipeline Order

Do not change this order during ownership or file-organization refactors:

1. Initial reference using the selected reference pair.
2. Drop the selected reference pair channels.
3. Optional channel limit through `max_idx_keep`, preserving the stim channel
   when needed.
4. Downsample when requested.
5. FIR filter using the current PySide6/legacy-parity cutoff mapping.
6. Kurtosis-based bad-channel rejection and interpolation.
7. Final average reference.

The order is part of the app contract. A refactor that preserves each individual
operation but reorders stages is a behavior change.

## Locked Behavior

`perform_preprocessing` mutates the incoming `raw_input` object in place and
returns the processed `Raw` object plus the number of kurtosis-identified bad
channels. On critical errors caught by its outer guard it returns
`(None, num_kurtosis_bads_identified)`.

The `params` dictionary is also mutable during a run:

- `_fpvs_initial_ref_ok` and `_fpvs_initial_ref_pair` are removed at run start.
- On successful selected-pair referencing, those audit keys are written back.
- The filter fingerprint is computed from `high_pass`, `low_pass`,
  `downsample_rate` or `downsample`, `reject_thresh`, reference channels, and
  stim channel.

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

Downsampling:

- Downsampling runs before filtering.
- It runs only when `downsample_rate` is truthy and the current sampling
  frequency is greater than the requested target.
- It uses MNE `raw.resample(..., npad="auto", window="hann", verbose=False)`.

Filtering:

- `l_freq` is `high_pass` when `high_pass > 0`; otherwise it is `None`.
- `h_freq` is `low_pass`.
- Filtering uses MNE FIR settings:
  `method="fir"`, `phase="zero-double"`, `fir_window="hamming"`,
  `fir_design="firwin"`, `l_trans_bandwidth=0.1`,
  `h_trans_bandwidth=0.1`, `filter_length=8449`,
  `skip_by_annotation="edge"`.
- The code logs filter snapshot, mutation, Nyquist, range, applied-cutoff, and
  mismatch diagnostics. These messages are part of the current regression
  surface because they help diagnose accidental cutoff changes.

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
python -m py_compile src\Main_App\processing\preprocess.py src\Main_App\Performance\process_runner.py src\Main_App\Shared\processing_mixin.py src\Main_App\gui\main_window.py src\Main_App\__init__.py
.venv\Scripts\python -m pytest tests\processing\test_single_file_process_mode.py tests\gui\test_main_window_processing.py -q
.venv\Scripts\python -m pytest tests\processing\test_preproc_audit.py tests\processing\test_fif_flag_audit.py tests\processing\test_process_runner_epoch_contract.py -q
python .agents\\scripts\\audit\\agent_audit.py
python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```

For documentation-only edits to this contract, confirm the diff only touches
docs unless the user explicitly asked for implementation changes.
