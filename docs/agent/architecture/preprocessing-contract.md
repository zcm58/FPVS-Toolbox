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

`src/Main_App/processing/fft_multinotch.py` owns the internal, versioned
frequency-domain line-noise mask and application helper. It has no settings or
GUI responsibilities; `preprocess.py` remains the public pipeline orchestrator
and decides whether and where the helper runs.

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
11. When post-export succeeds, publish the source-ready signed time-domain EEG
    derivative from the already-built condition epochs. This serialization step
    performs no new preprocessing, FFT, or source estimation.
12. Finalize the preprocessing audit with `finalize_preproc_audit`.
13. Clean up worker memory and temporary memmap paths.

GUI processing must route through the active process runner. Single-file runs use
the same runner with `max_workers=1`. Do not add a fallback path that bypasses
the process runner or calls retired legacy preprocessing.

Before the processing ledger plan is chosen, the GUI may run the embedded
preflight QC workflow in `src/Main_App/gui/preprocessing_qc_workflow.py`. This
workflow is review-first: it scans the selected BDF pool for BioSemi
recording-not-started files, loads eligible raw files in a `QThread` for
conservative removed-electrode/raw-channel/spectral QC summaries, compares one
locked FFT-grid observation per participant-condition against a unique strict
majority when one exists, asks the user to confirm any participant-condition
grid exclusions, asks the user to confirm the manual removed-electrode table,
offers participant-level exclusions, and reports remaining suspicious
findings. The grid identity is the sampling-rate-independent integer count of
1.2-Hz oddball cycles in the planned crop; the review does not hard-code 120
seconds or alter the locked shortest-common crop calculation. Incremental raw
observations are compared with header-only observations from the active,
completed processed-workbook cohort; the current raw plan replaces an older
workbook observation for the same participant-condition. Ledger-incomplete and
frequency-domain-excluded participants do not define the reference. When valid
grids are tied, the review shows each cohort without guessing which one to
preselect. Accepted manual
removed-electrode, participant-condition, and participant-exclusion decisions
are saved to project preprocessing settings before
`classify_processing_inputs()` runs. Confirmed
recording-not-started files are passed to the process runner through
`_fpvs_preflight_recording_not_started_files` so they can be recorded as
`recording_not_started` exclusions without creating child-process work. The raw
BDF files are never modified.

Incremental processing runs classify the selected BDF pool before embedded
preflight QC and only scan files whose ledger state is new, stale, incomplete,
or missing expected outputs. Files already recorded as completed or excluded
for the current raw-file metadata and processing fingerprint keep their prior
QC decisions. If preflight QC adds participant-specific project metadata for
new files, the GUI carries forward still-valid completed states and refreshes
only skipped ledger fingerprint metadata so later runs do not rescan old files.
Settings provides a separate processed-workbook FullFFT-grid review for already
completed files. It reads workbook headers on a worker thread, uses the same
active harmonic-selection cohort and strict-majority oddball-cycle identity,
retains already excluded pairs for editing, and lets the user add or clear
participant-condition exclusions. Valid tied grids are shown without an
automatic choice, and recalculation remains blocked until the proposed included
cohort has exactly one valid FFT grid.

Epoch building in the process runner must preserve locked FFT crop behavior.
When valid `55_onbin` repetition crops exist for a condition, those repetitions
must keep `N % N_step == 0` and metadata `N_mod_step == 0`. Do not downgrade
the whole condition or any repetition to fixed-epoch fallback. Do not silently
skip fallback repetitions. If a selected repetition cannot produce a valid
`55_onbin` crop, the normal processing run must fail before post-export.
Downstream `FullFFT Amplitude (uV)` columns are expected to include the exact
nominal oddball harmonics from this crop behavior.

The source-ready derivative uses those same aligned `55_onbin` epochs. It
averages repetitions sample-by-sample in signed volts and preserves exact `N`,
sampling frequency, crop/bin metadata, EEG channel order, montage, bad-channel
provenance, and final average-reference state. It must not introduce a second
crop plan, nearest-bin fallback, spectral window, rectification, or magnitude
operation.

The process runner logs `[TIMING] file=... section=... elapsed_ms=...` for
cache lookup, load, pre-audit, preprocessing, cache store, events, epochs,
export, post-audit, and cleanup when those stages run. The returned per-file
result includes `timings_ms` and `preproc_cache_status` so users can compare
first-run and cache-hit runtimes.

The preprocessed Raw cache version is
`preprocessed-raw-v9-fft-multinotch`.
The project processing-ledger and Stats group-harmonic cache processing
fingerprints use `processing_fingerprint_v9_source_ready_time_domain`. The
raw channel-health QC threshold, removed-electrode QC mode, per-file manual
removed-electrode list, baseline raw-amplitude metadata, and rare-burst
candidate list are part of the cache payload so changes to those settings
invalidate cached preprocessed Raw files. The downstream-only
`manual_excluded_participant_conditions` setting is deliberately omitted from
the raw-processing fingerprint: it does not change EEG preprocessing or
workbook generation. It remains part of the Stats harmonic-cache signature so
changing the included workbook cohort requires harmonic recalculation. The
cache identity also includes the
line-noise-filter enabled state, selected 50 or 60 Hz mains frequency, method
version, half-width, and component count. The v9 cache metadata also persists
raw-QC, manual removed-electrode, kurtosis, and interpolated bad-channel names
plus requested, applied, and skipped FFT multi-notch centers so cache-hit runs
can still produce complete participant QC and preprocessing provenance.

After frequency-domain QC is accepted, processing completion calculates the
project-wide significant-harmonic list once through
`Main_App.processing.harmonic_selection_qc`, persists its exact fingerprinted
selection in `project.json`, and writes
`Quality Check/Harmonic_Selection_Summary.xlsx`. Active downstream project
tools load this processing-time selection. They must stop with reprocessing or
Settings-recalculation guidance when it is missing or stale rather than
calculating another list.

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
scan without importing Qt. The normal GUI route supplies an explicit active
project root and condition event map, which enables condition-aware preflight
QC v2. The compatibility v1 route remains available to callers that do not
supply both inputs.

V2 reads the complete configured Status channel to plan events, then requests
EEG samples only from each configured condition onset through the earliest of
the planned condition completion, the next configured condition onset, or the
recording boundary. The configured epoch end is the minimum completion. When
the shared locked FFT plan proves that normal processing will use a longer
interval, completion extends through that exact spectral span rather than
following a discontinuous oddball stream beyond the crop. It never scores EEG
outside those intervals. Time-domain
QC examines every consecutive 10-second block plus the final partial block and
retains exact float64 full-condition metrics plus transient worst-block
provenance. Only channels classified consistently across every relevant
condition occurrence are participant-persistent and feed the existing removed-
electrode confirmation table; condition-specific and 10-second-block findings
remain separately identified provenance. A channel's quietest 10-second block
is recorded, but the persistent relative low-variance calibration is not
misapplied to that isolated block as a removed-electrode flag. Extreme
high-amplitude and rare-burst block findings remain review signals.

V2 spectral QC uses the same shared per-condition, shortest-repetition,
integer-oddball-cycle FFT span planner as normal processing. It evaluates the
Hann-windowed FFT for every channel in deterministic memory-bounded batches;
focused parity tests require byte-identical per-channel amplitudes relative to
the all-channel formula. Evaluation continues through the configured retained
upper band, bounded by the source and configured downsample-target
Nyquist frequencies. The configured downsample target remains 256 Hz by
default; 128 Hz is only that target's Nyquist frequency and no 128 Hz
resampling is introduced. Neighboring noise explicitly uses +/-12 FFT bins,
excludes the target and immediately adjacent bins, and removes one global
minimum and maximum, leaving 20 bins for the mean and population standard
deviation. Expected FPVS harmonics, effective configured mains-notch centers,
their collisions, and unexpected off-harmonic peaks are reported separately.

Condition-aware findings are review-only in preflight v2. They do not create a
new hard-exclusion rule; the established hard raw-channel rules remain
unchanged in the normal process runner. A review-only condition finding can
therefore be deferred to the existing processing-time decision rather than
silently changing that calibrated rule. V2 caps participant workers at four,
simultaneous BDF reads at two, and simultaneous spectral evaluators at two. A
condition buffer larger than 256 MiB is filled in 10-second chunks into a
temporary condition-only float64 memmap; no full-recording preflight memmap is
created. V2 preserves deterministic result order and checks cancellation
between condition reads, time blocks, FFT channel batches, and cache writes.
Successful participant results
are cached atomically under the active project root at
`.fpvs_processing/preflight_qc/v2`; a missing, corrupt, or fingerprint-stale
entry is a cache miss. The key includes raw path/size/mtime, relevant settings,
method and dependency versions, and the resolved event/span plan.

The project lifecycle action **File > Reset Project Processing Cache...**
forces the next run through a cold data-quality, raw-preprocessing, and
incremental-planning path. It removes the preflight cache above, the
preprocessed-Raw cache at
`.fpvs_cache/preprocessed`, and the incremental completion ledger at
`.fpvs_processing/processing_ledger.json` (plus a leftover ledger temporary
file). Clearing the ledger is required because input classification occurs
before preflight QC and otherwise omits completed files from the scan. The
action preserves raw data, `project.json`, manual QC settings, current outputs,
review workbooks, and `.fpvs_processing/processing_runs.jsonl`. It does not
attempt to flush operating-system filesystem caches. Once the following run
begins, normal participant-output cleanup replaces the outputs being
recomputed.

Downstream tool caches, including Stats harmonic-selection caches, are outside
this raw-processing reset and retain their normal fingerprint invalidation.

`src/Main_App/processing/preflight_qc_plan.py` owns the condition/event plan,
and `src/Main_App/processing/preflight_qc_cache.py` owns the GUI-neutral cache
primitive. `raw_channel_qc.py` and `raw_spectral_qc.py` retain their existing v1
APIs alongside their versioned condition-aware evaluators. Output ordering must
remain deterministic for reporting.
For grouped projects, `HeaderOnlyPreflight` and `PreflightQcFileResult` retain
the canonical `group_id` from `RawFileInfo`. The GUI resolves that ID through
`ProjectGroupContext` and shows the configured group label in live scan status,
empty-recording review, removed-electrode review, hard-exclusion review and
details, and remaining review flags. A missing or unknown grouped assignment is
an error; folder names are not a membership fallback. Participant exclusions
and removed-electrode maps remain keyed by project-wide unique participant ID.

The project preprocessing setting `removed_electrode_detection_mode` defaults
to `auto` and is exposed in Settings > Advanced > Processing QC as Off,
Conservative auto-detect, or Manual list. The legacy
`auto_detect_removed_electrodes` boolean is retained for compatibility and is
`True` only when the mode is `auto`. When conservative auto-detect is enabled,
persistently flat/very low-variance scalp channels can be automatically added to
`raw.info["bads"]` before preprocessing. The second-pass raw-QC detector adds
flag-only candidate lists for extreme high-amplitude outliers, rare-burst
channels, and spatially inconsistent channels. High-amplitude and rare-burst
candidates are prefilled into the preflight removed-electrode review as FPVS
Toolbox flagged candidates so users can accept or reject them, but they are not
automatically added to the interpolation target list without that review.
Spatial channels are only flagged when local predictability is both low and a
robust outlier within the participant's own montage. Low-variance raw-QC bad
channels are excluded from kurtosis donor/pick calculations and are included in
the later spherical interpolation target list.

Raw channel QC also records participant-level baseline raw-amplitude medians.
A file is hard-excluded before preprocessing when both the scalp-channel median
STD is at least 10,000 uV and the scalp-channel median P2P99 is at least
100,000 uV. A softer warning is recorded when the median STD is at least
2,000 uV or the median P2P99 is at least 10,000 uV. Baseline metrics and status
are exported to `Quality Check/Processing_QC_Summary.xlsx` and stored in cache,
audit, and ledger payloads so skipped incremental files retain prior results.

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

During embedded preflight QC, the removed-electrode review keeps provenance
separate from the final compatibility map. It stores the original FPVS
Toolbox-flagged set, the subset the user accepts, any auto flags the user
rejects, manual additions for physically removed electrodes missed by automatic
review, the final confirmed set, the manual-only auto misses, auto/manual
overlap, and an agreement status. The final confirmed set is still saved to
`manual_removed_electrodes` so preprocessing behavior stays compatible. The
provenance fields are copied into per-file audit, raw-QC exclusion payloads,
preprocessed-cache metadata, and processing-ledger entries; skipped incremental
runs can therefore still report the prior auto/manual comparison without
rescanning already-current files.
The saved `Data_Quality_Check_Review_Flags.xlsx` workbook uses the canonical
`PID`, `Group`, `Source File`, and `Flagged Item` columns so its group label is
visible and `qc_summary_export` can merge its flags through the existing named
columns.

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
preflight auto/manual removed-electrode comparison fields,
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
5. Optional smart FFT Hann multi-notch filtering of retained mains components.
6. Downsample when requested.
7. Kurtosis-based bad-channel rejection and interpolation.
8. Final average reference.

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
  reference channels, stim channel, line-noise-filter enabled state, selected
  mains frequency, and the versioned FFT multi-notch constants.

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

FFT multi-notch line-noise filtering:

- The optional line-noise stage runs after the existing FIR and immediately
  before downsampling. It does not move or change any existing pipeline stage.
- New project settings default to the filter enabled at a 60 Hz mains
  frequency. The alternative is 50 Hz.
- The requested components are the fundamental plus two harmonics:
  50, 100, and 150 Hz or 60, 120, and 180 Hz.
- `fft_hann_multinotch_v1` uses an FFT-domain Hann notch with a 0.5 Hz
  half-width around each effective center. The center gain is zero and the
  mask returns to unity at the center plus or minus 0.5 Hz.
- The stage is smart: it applies only requested components whose notch support
  overlaps frequencies retained by the preceding FIR and that fit below the
  raw-data Nyquist limit. For example, a 1--100 Hz FIR retains the 50 Hz
  fundamental and the supported portion of the 100 Hz notch for the 50 Hz
  setting, while it retains the 60 Hz fundamental but not 120 or 180 Hz for the
  60 Hz setting. When no requested component remains effective, FFT/IFFT
  processing is skipped.
- When `line_noise_filter_enabled` is false, the helper is not called and no
  FFT data round trip occurs. The EEG processing result therefore follows the
  pre-feature numerical path unchanged.
- The enabled state, selected mains frequency, method version, half-width, and
  component count are processing provenance and cache-invalidating inputs.

Evidence and implementation rationale:

- Retter and Rossion's FPVS preprocessing used a 0.1--120 Hz band-pass followed
  by an FFT multi-notch described as 0.5 Hz wide at the first three 50 Hz
  harmonics ([Neuropsychologia 91, 9--28, 2016](https://doi.org/10.1016/j.neuropsychologia.2016.07.028)).
- The Letswave preprocessing guide explicitly omits a 50 Hz notch when its
  0.05--30 Hz band-pass has already excluded that contamination
  ([Letswave preprocessing tutorial](https://letswave.cn/tu_ch1_2)). This is the
  basis for skipping a requested notch whose complete support is above the
  preceding FIR transition.
- The paper supplies the 0.5 Hz numeric precedent and three-component harmonic
  count; `fft_hann_multinotch_v1` makes the otherwise ambiguous width semantics
  reproducible by defining 0.5 Hz as the Hann half-width. This Toolbox-specific
  definition must be reported as such rather than attributed verbatim to the
  paper.
- Edge-annotated spans are transformed independently, matching MNE's documented
  rule that filtering on either side of an `edge` annotation treats the spans
  as independent signals
  ([MNE `Raw.filter` documentation](https://mne.tools/stable/generated/mne.io.Raw.html#mne.io.Raw.filter)).

Downsampling:

- Downsampling runs after the FIR and optional FFT multi-notch stages.
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

Use the processing scope for preprocessing ownership, routing, or behavior
changes. The driver selects `.venv1` or `.venv` and excludes Qt execution
locally:

```powershell
python .agents/scripts/verify.py --scope processing --tier focused
```

Processing-window pytest-qt coverage runs in CI only by default. For GUI wiring
changes, also document a visible/manual processing smoke path.

For documentation-only edits to this contract, confirm the diff only touches
docs unless the user explicitly asked for implementation changes.
