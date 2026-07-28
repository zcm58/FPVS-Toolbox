# Post-Processing Export Contract

This page documents the current post-processing and Excel export behavior before direct callers are migrated away from historical package paths. Refactors must preserve these outputs exactly unless a future task explicitly changes the processing pipeline.

## Entry Contract

Active post-export adapter imports should use `Main_App.exports.post_export_adapter`.

`post_process(app, condition_labels_present)` expects an app-like object with:

- `preprocessed_data`: mapping of condition label to MNE `Epochs` or `Evoked` objects.
- `save_folder_path.get()`: output root folder.
- `data_paths`: source data paths used for PID and event lookup.
- `settings`: `SettingsManager`-like object or dict for analysis settings.
- `log(message)`: logging callback.

The function logs start/end status, skips conditions without data, and logs a warning if no Excel files are saved.

## Source-Ready Time-Domain Sibling Export

The Hauk source-PSD features do not change this Excel adapter or any workbook
formula. After a successful Excel export, the process runner may pass the same
resident condition Epochs to the GUI-neutral source time-domain derivative
writer. That writer averages repetitions in signed volts, keeps EEG only, and
atomically writes Raw FIF/provenance under the active project root at
`6 - Source Localization/Source-Ready Time Domain v1/`.
Artifact pairs use
`<condition label>/[<group>/]<participant>_<condition_id>_avg_raw.fif` and a
sibling `_avg_raw.json`; participant commit manifests use
`manifests/[<group>/]<participant>.json` and are published last.

Downstream source-map orchestration may mark a completed participant as
source-ineligible when any canonical condition is missing or the processing
ledger explicitly records an incomplete source derivative. That omission is
complete-case across all source conditions and must be reported separately
from general project/QC exclusions. The retained manifest set remains strict;
missing or corrupt artifacts recorded as complete are not skipped.

The current L2-MNE cortical and eLORETA volume source-PSD exporters consume the
same retained FIF/cohort/harmonic/bin contract and apply the same FPVS
neighboring-bin z-score algorithm. They remain independent numerical
consumers: eLORETA applies its own volume inverse and computes its own source
power, participant z-score, cache, and volume-cluster arrays rather than reusing
L2-MNE values. Normal manual and post-processing rebuilds target both methods.
Neither current exporter reads FullFFT amplitude workbooks or uses them as a
fallback; legacy amplitude-derived manifests remain importable only under
their existing method identities.

This is a sibling generated output, not an alternate `post_process()` entry
point. It must reuse the already-validated exact `55_onbin` crop metadata and
must not calculate FFT amplitudes, neighboring-bin metrics, source estimates,
or modify the existing Excel output paths/sheets.

## Analysis Settings

Target frequencies come from `settings["analysis"]`, `settings.get("analysis", key, fallback)`, flat dict keys, or attributes:

- `oddball_freq`, locked at `config.DEFAULT_ODDBALL_FREQ` (`1.2` Hz).
- `bca_upper_limit`, default `config.DEFAULT_BCA_UPPER_LIMIT`.

The resolved frequencies come from `config.update_target_frequencies(oddball_freq, bca_upper_limit)`.
Non-1.2 Hz `oddball_freq` values are hard failures. The BCA upper limit only
sets the highest 1.2 Hz harmonic exported; it must not be used as oddball
spacing or as a fallback when exact harmonic columns are missing.

## PID And Output Naming

PID resolution order:

1. `app.pid_for_group` when present.
2. First path in `app.data_paths`, using `P\d+`, `Sub\d+`, or `S\d+` if present.
3. Filename stem with common EEG suffixes stripped.
4. `UnknownPID`.

For advanced per-participant output, when `app.group_name_for_output == condition_label`, output is:

- folder: sanitized recipe name;
- filename: `{pid}_{sanitized_recipe_name}.xlsx`.

For the single-file/current app path, output is:

- folder: sanitized condition label;
- filename: `{pid}_{sanitized_condition_label}_Results.xlsx`.

Folders are created under `save_folder_path.get()`. If subfolder creation fails, the workbook is written to the parent folder.

## Metrics And Sheets

For every valid data object:

- Pick EEG channels, excluding bad channels for non-evoked objects.
- Average epochs across repetitions when the object is `Epochs`.
- Convert averaged data to microvolts before FFT and SNR metrics.
- Use 64-channel default electrode ordering only when the channel set matches `DEFAULT_ELECTRODE_NAMES_64`.
- Skip objects with mismatched channel count or order after the first valid object.

Workbook sheets and column behavior must remain:

- `FFT Amplitude (uV)`
- `SNR`
- `Z Score`
- `BCA (uV)`
- `FullSNR`, interpolated from 0.5 Hz to the configured upper limit in 0.01 Hz steps when full-spectrum SNR is available.
- `FFT and neighbors`, only when neighbor rows are non-empty.

All metric sheets insert `Electrode` as the first column. Target-frequency columns are formatted as `{frequency:.4f}_Hz`.

## FFT Neighbor Export

The `FFT and neighbors` sheet uses these columns in this exact order:

`file_name`, `condition_label`, `condition_id`, `repetition_index`, `channel_or_roi`, `target`, `fs`, `N`, `T_sec`, `df_hz`, `k0`, `f_bin_hz`, `crop_mode`, `n55`, `first55_samp`, `last55_samp`, `N_step`, `N_mod_step`, `fallback_reason`, `amp_m11` through `amp_m1`, `amp_p1` through `amp_p11`, `warning`.

The target label is `1.2Hz`. Neighbor amplitudes are exported for +/-11 FFT bins around the target bin, excluding the center bin. Out-of-range neighbor bins are `NaN` and set a warning string.

`build_fft_neighbors_rows(...)` returns one row per electrode/channel. It resolves `k0` by the exact target-bin formula, records `fs`, `N`, `T_sec`, `df_hz`, and crop metadata, and raises if the target frequency is not exactly on an FFT bin. It must not fall back to the nearest frequency bin. `crop_mode` must be `55_onbin` and `N_step` must be present; fixed-epoch FFT fallback is not valid for normal post-export.

`write_results_workbook(...)` writes each provided metric DataFrame to its existing sheet name with no index column, freezes the header row, center-aligns cells vertically and horizontally, and sets each column width from the maximum header/data string length plus four characters. The optional `FFT and neighbors` sheet is written only when the neighbor DataFrame is present and non-empty.

Column-width measurement may process adjacent columns in bounded DataFrame
blocks, but it must preserve the exact per-column `str(...)` length maximum and
the existing `+ 4` width. When the workbook destination is on a different
Windows volume from the system temporary directory, the final XLSX container
is assembled on the temporary volume, copied sequentially to a same-directory
temporary file beneath the intended project output folder, and atomically
replaced into place. The staging file is ephemeral: every durable file and the
publish temporary remain confined to the active project output path, and a
failed staged write must leave an existing workbook untouched.

During one `PostProcessingPipelineWorker.run()` call, repeated exact selected
reads from source XLSX workbooks may share a run-scoped cache. Cache identity
must include the resolved workbook path, size, nanosecond modification time,
filesystem ctime/creation identity, device/file identity, worksheet,
requested-column order, missing-column policy, electrode filter, and
electrode-column name. Processed input workbooks are immutable during these
scoped phases; concurrent same-file in-place edits are outside this boundary.
Cached frames are returned as defensive copies, and a pre/post signature check
prevents a read changed in flight from being stored. The scope is closed on
success, error, and the early frequency-domain-QC review return; reads outside
that explicit worker scope remain uncached. Process-global or cross-run
workbook caches are not allowed. On the normal path it is released after
Stats-ready export and before the memory-intensive time-domain source-map
producers, which do not consume the selected-XLSX reader.

## Preservation Rules

- Do not change metric formulas, FFT bin selection, noise-window logic, sheet names, column names, filename/folder naming, channel ordering, logging semantics, or completion/error behavior.
- Do not change workbook formatting, freeze panes, writer engine behavior, or the rule that omits `FFT and neighbors` when no neighbor rows exist.
- Do not change the 55-on-bin metadata handling; see `docs/agent/architecture/fft-crop-method.md`. Missing locked FFT crop metadata, `fixed_epoch_fallback`, or off-bin target frequencies must be hard failures, not warnings or nearest-bin fallbacks.
- Legacy compatibility wrappers have been deleted; runtime callers should use the current shared owner.
