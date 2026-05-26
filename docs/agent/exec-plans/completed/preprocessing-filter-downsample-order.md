# Preprocessing Filter And Downsample Order

## Status

Completed on `codex/Edit-Pipeline-Order`.

Activated after review on 2026-05-26. The user approved changing the pipeline
order and requested numerical before/after comparison with no other processing
changes.

## Completion Notes

- The locked preprocessing order is now: initial reference, drop selected
  references, optional channel limit preserving stim, FIR filter, downsample,
  kurtosis/interpolation, final average reference.
- The FIR filter still uses the same cutoff mapping, transition bandwidths,
  window/design, phase, and skip-by-annotation behavior. The historical
  8449-point kernel duration is preserved at the requested downsample rate by
  scaling the point count when filtering happens at the original sampling rate
  before downsampling.
- Preprocessed Raw cache version is now
  `preprocessed-raw-v2-filter-then-downsample`.
- Processing ledger fingerprint version is now
  `processing_fingerprint_v2_filter_then_downsample`.
- Synthetic comparison with identical settings preserved shape `(5, 10240)`,
  channel list `['E1', 'E2', 'E3', 'E4', 'Status']`, sampling rate `256 Hz`,
  and rejected-channel count `0`, while the numerical head hash changed from
  `d5613c4d7988f72f` to `a109e4dc8b357ccf`; `diff_l2` was
  `4.102142580322e-06`.
- Focused FFT crop tests still pass; locked crop metadata tests preserve
  `crop_mode == "55_onbin"` and `N_mod_step == 0`.

## Target

- `src/Main_App/processing/preprocess.py`
- `src/Main_App/Performance/process_runner.py`
- `src/Main_App/Shared/processing_mixin.py`
- `src/Main_App/projects/preprocessing_settings.py`
- `docs/agent/architecture/preprocessing-contract.md`
- `docs/agent/architecture/fft-crop-method.md`
- `docs/user/study/processing-pipeline.md`
- Focused tests under `tests/processing/`

## Pre-Change State

The active normal-processing route is:

1. Load `.bdf`.
2. Apply initial selected reference pair, default `EXG1` and `EXG2`.
3. Drop the selected reference channels.
4. Optionally limit channels while preserving the stim channel.
5. Downsample when requested.
6. Apply FIR band-pass filtering.
7. Run kurtosis-based bad-channel detection and interpolation.
8. Apply final common average reference.
9. Extract events.
10. Build condition epochs with locked `55_onbin` FFT crop behavior.
11. Average epochs and run FFT/BCA/SNR/Z export.

This order is documented as a locked preprocessing contract. Changing the
relative order of downsampling and filtering is a behavior change, not a
refactor.

## Goal

Evaluate and, if approved, change the preprocessing order so FIR band-pass
filtering runs before downsampling. The motivation is to align the Toolbox
methods description more closely with published FPVS pipelines that report
filtering before downsampling, while preserving the user's scoped decisions:

- no continuous-block alignment step;
- no 50 Hz or 60 Hz notch filter when using a 0.1-50 Hz band-pass filter;
- no ICA decomposition or blink-component removal;
- no change to kurtosis bad-channel detection and interpolation;
- no change to final common average reference;
- no change to locked 1.2 Hz oddball crop behavior or 144-cycle FFT-bin-locked
  processing.

## Non-Goals

- Do not implement continuous-block alignment for voltage drift during pauses.
- Do not add a notch filter.
- Do not add ICA, EOG regression, blink detection, or component rejection.
- Do not change reference-channel defaults, reference-channel dropping, or
  BioSemi channel loading policy.
- Do not change kurtosis trimming, z-threshold behavior, interpolation mode, or
  final average-reference behavior.
- Do not change event extraction, condition event maps, `55_onbin` crop math,
  cycle count rules, FFT bin locking, workbook sheet names, or Stats harmonic
  policy.
- Do not silently keep stale preprocessed cache entries across a processing-order
  change.

## Open Decisions Before Activation

Resolved on activation:

1. Filtering moves before downsampling for the active preprocessing owner.
2. Preprocessed Raw cache and processing ledger fingerprint versions are bumped
   so old-order artifacts are stale even when numeric settings are unchanged.
3. No new UI or project metadata is exposed; the order version is carried by
   diagnostic preprocessing fingerprints plus cache/ledger versions.
4. Numerical comparison uses identical synthetic input and settings, expects
   stable shape/channel/sampling metadata, and expects numerical values to
   differ because the order changed.
5. Average Preprocessing compatibility routes inherit the change through
   `Main_App.processing.preprocess.perform_preprocessing`; no separate
   compatibility implementation was added.

## Suggested Slices

1. Baseline evidence capture:
   - Confirm current order from `preprocess.py` and
     `docs/agent/architecture/preprocessing-contract.md`.
   - Run focused preprocessing tests before edits.
   - Save a short methods-order note in the implementation PR or change log.

2. Characterization tests:
   - Add or update tests proving the current stage order around downsample and
     FIR filter.
   - Add a cache/fingerprint test that will fail if the order changes without
     invalidating stale preprocessed artifacts.
   - Keep tests non-GUI; do not run offscreen Qt workflows locally.

3. Order change:
   - Move FIR filtering before downsampling inside
     `Main_App.processing.preprocess.perform_preprocessing`.
   - Preserve current FIR cutoff mapping, logging content where practical, and
     continuation behavior on stage failures. Preserve the historical 8449-point
     filter duration at the downsample target by scaling the point count when
     filtering at the original sampling rate.
   - Preserve the stim-channel and channel-limit behavior before both stages.

4. Cache and audit updates:
   - Update preprocessing fingerprints or processing-fingerprint versioning so
     old cached `.fif` files and ledger entries are treated as stale.
   - Update audit/log labels if they currently imply the old order.
   - Confirm first-run and cache-hit paths both report the new order clearly.

5. Documentation updates:
   - Update `docs/agent/architecture/preprocessing-contract.md` with the new
     locked order.
   - Update user-facing processing/methods docs to describe filtering before
     downsampling.
   - If implementation touches shared compatibility behavior, update the nearest
     scoped `AGENTS.md` or architecture page.

6. Output validation:
   - Reprocess a small known input or synthetic fixture.
   - Confirm locked crop metadata still reports `crop_mode == "55_onbin"`,
     `N_mod_step == 0`, and exact nominal 1.2 Hz harmonic columns.
   - Treat changed numerical outputs as expected for this behavior change, but
     confirm output shapes, sheets, filenames, and condition folders are stable.

## Verification Plan

Use focused checks first:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\processing\preprocess.py src\Main_App\Performance\process_runner.py src\Main_App\Shared\processing_mixin.py
.\.venv1\Scripts\python.exe -m pytest tests\processing\test_preproc_audit.py tests\processing\test_preprocessing_settings.py tests\processing\test_process_runner_epoch_contract.py -q
.\.venv1\Scripts\python.exe -m pytest tests\processing\test_fft_crop_utils.py tests\processing\test_post_process_target_freqs.py -q
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
ruff check src\Main_App\processing\preprocess.py src\Main_App\Performance\process_runner.py src\Main_App\Shared\processing_mixin.py tests\processing
```

If GUI-adjacent settings or processing controls change, add GUI import audits
and a documented visible/manual smoke path. Do not set `QT_QPA_PLATFORM=offscreen`.

## Reporting Requirements

Future agents using this plan must report:

- Whether the order was changed or manuscript wording was updated instead.
- The exact locked preprocessing order after the work.
- Whether cache/ledger fingerprints were invalidated for the behavior change.
- Tests and audits run, with pass/fail results.
- Whether output workbook shapes and locked FFT crop metadata were preserved.
- Any skipped visible/manual smoke and residual risk.
