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

## Analysis Settings

Target frequencies come from `settings["analysis"]`, `settings.get("analysis", key, fallback)`, flat dict keys, or attributes:

- `oddball_freq`, default `config.DEFAULT_ODDBALL_FREQ`.
- `bca_upper_limit`, default `config.DEFAULT_BCA_UPPER_LIMIT`.

The resolved frequencies come from `config.update_target_frequencies(oddball_freq, bca_upper_limit)`.

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

## Preservation Rules

- Do not change metric formulas, FFT bin selection, noise-window logic, sheet names, column names, filename/folder naming, channel ordering, logging semantics, or completion/error behavior.
- Do not change workbook formatting, freeze panes, writer engine behavior, or the rule that omits `FFT and neighbors` when no neighbor rows exist.
- Do not change the 55-on-bin metadata handling; see `docs/agent/architecture/fft-crop-method.md`. Missing locked FFT crop metadata, `fixed_epoch_fallback`, or off-bin target frequencies must be hard failures, not warnings or nearest-bin fallbacks.
- Legacy compatibility wrappers have been deleted; runtime callers should use the current shared owner.
