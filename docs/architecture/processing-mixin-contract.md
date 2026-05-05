# Processing Mixin Contract

This page documents the current single/legacy processing path now owned by `src/Main_App/Shared/processing_mixin.py`. Refactors must preserve the processing pipeline, event handling, progress behavior, output formats, and post-processing exports unless a future task explicitly changes behavior.

## Entry Contract

`ProcessingMixin.start_processing()` expects the host window to provide:

- `data_paths`, `validated_params`, `gui_queue`, `settings`, `save_folder_path`, and `preprocessed_data`.
- GUI hooks: `_validate_inputs()`, `_set_controls_enabled(enabled)`, `_animate_progress_to(value)`, `after(delay_ms, callback)`, `log(message, ...)`, and `post_process(labels)`.
- Progress state fields such as `_current_progress`, `_target_progress`, `_max_progress`, `_processed_count`, `_start_time`, `busy`, and optional `remaining_time_var`.

The mixin prevents duplicate active processing threads, blocks processing while event detection is active, disables controls before starting, and schedules periodic queue polling with the host window's Qt-backed `after()` helper.

## Processing Order

For each selected data file, the worker thread preserves this order:

1. Load the EEG file through `Main_App.Shared.load_utils.load_eeg_file(self, file_path)`.
2. Preprocess a raw copy with `perform_preprocessing(...)`.
3. Extract events from annotations for `.set` files or `mne.find_events(...)` for other files.
4. Compute FFT crop diagnostics with `compute_fft_crop_from_events(...)`.
5. Build per-condition `mne.EpochsArray` objects using 55-on-bin crops when available, otherwise fixed-epoch fallback.
6. Run post-processing/export through the host `post_process(labels)` callback.
7. Clean per-file memory and emit progress.

The mixin writes FFT crop diagnostics under `Logs/fft_crop_debug_*.txt` below the current save folder when available. It preserves `quality_review_suggestions.txt` output for files that exceed the configured bad-channel alert threshold.

## Queue And Completion Behavior

Worker messages use the existing `gui_queue` message types:

- `log`: append message to the GUI log.
- `progress`: update processed count and animate progress.
- `post`: temporarily swap `preprocessed_data` and run post-processing for the supplied labels.
- `error`: log thread errors and finalize as unsuccessful.
- `done`: finalize the processing run.

Finalization preserves the existing success/error/cancel behavior, resets processing state, re-enables controls, clears `data_paths`, resets progress fields, clears `preprocessed_data`, and logs readiness for the next run.

## Preservation Rules

- Do not change load, preprocessing, event extraction, FFT crop, epoching, post-processing, or cleanup order.
- Do not change generated files, sheet names, output paths, quality review file format, or FFT crop log format.
- Do not reintroduce Tkinter, CustomTkinter, or CTkMessagebox; user messages must use `Main_App.Shared.user_messages`.
- `src/Main_App/Legacy_App/processing_utils.py` may remain as a compatibility wrapper, but active callers should import `Main_App.Shared.processing_mixin`.
