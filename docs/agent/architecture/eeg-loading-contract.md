# BDF Loading Contract

This page documents the BDF loader contract for the active Main App processing
paths. Refactors must preserve supported file type, memmap paths, channel
typing, montage behavior, logging, and return semantics unless a future task
explicitly changes the processing pipeline.

## Entry Contract

`load_eeg_file(app, filepath, ref_pair=None, first_n_channels=None)` expects the
host object to provide:

- `log(message, ...)` for status and warning messages.
- Optional `currentProject.preprocessing` with `ref_channel1`,
  `ref_channel2`, and `stim_channel` values.
- Optional `settings.get(section, key, default)` fallback access.

The canonical active import path is
`Main_App.io.load_utils.load_eeg_file`.

The implementation still lives in `Main_App.Shared.load_utils` during this
layout migration slice. Do not change that implementation as part of
import-surface moves.

`src/Main_App/Legacy_App/load_utils.py` and the old PySide6 backend loader path
have been deleted. `src/Main_App/Shared/load_utils.py` is kept as the temporary
implementation module and must not duplicate logic elsewhere.

## File And Path Behavior

- Supported extension is `.bdf`.
- Unsupported extensions show a user warning and return `None`.
- Before MNE opens a BDF, the loader reads the fixed BDF header. A BioSemi
  file with `num_records == 0` whose file size is only the declared header
  length is treated as a recording-not-started placeholder: the loader logs an
  exclusion warning and returns `None`, while the process runner reports the
  file as `status="excluded"` instead of a processing error.
- BDF files load through `mne.io.read_raw_bdf(...)`.
- `.set`/EEGLAB loading is intentionally unsupported in the active toolbox.
- Disk-backed preload files are created under
  `tempfile.gettempdir()/fpvs_memmap/pid_<process-id>/<file-stem>_raw.dat`.
- Loading does not resample data.
- When `first_n_channels` is provided, the loader performs a header-only BDF
  read, then passes `include=` for the first N channel names plus the selected
  reference pair and resolved stim channel. If subset resolution fails, the
  loader emits `[LOADER CHANNEL SUBSET WARNING]` and loads the full BDF rather
  than silently changing results.

## Channel Behavior

- The stimulus channel resolves from project preprocessing settings, app
  settings, then defaults to `Status`.
- Active use cases contain `EXG1` through `EXG8`.
- `EXG1` and `EXG2` are the reference channels and remain typed as EEG.
- Other present `EXG3` through `EXG8` channels are demoted to `misc`.
- The resolved stimulus channel is typed as `stim` when present.
- EXG and stimulus matching is case-insensitive, while actual channel casing is
  preserved.
- The active process runner currently requests the first 64 BDF channels plus
  `EXG1`/`EXG2` as the selected reference pair and the resolved stim channel.
  This avoids loading unused BioSemi `EXG3` through `EXG8` channels before
  preprocessing drops non-selected EXG channels.

## Montage And Errors

- The loader applies MNE's cached `standard_1005` montage with
  `on_missing="warn"`, `match_case=False`, and `verbose=False`.
- The montage object is cached once per Python worker process with
  `_cached_1010()`. Multiprocessing workers do not share that in-memory cache,
  so a batch with several workers builds the montage once per worker, then
  applies that cached object to each file handled by the worker.
- BioSemi's headcap table lists standard 64-channel caps with `1020`
  layout/labelling, and Brainstorm's BioSemi cap documentation maps BioSemi
  16-, 32-, and 64-electrode cap labels one-to-one to the standard 10-10
  system. For this toolbox, BioSemi ActiveTwo 64-channel BDF files are therefore
  treated as 10-10-positioned recordings.
- MNE does not expose a builtin named `standard_1010`; `standard_1005` is the
  denser standard montage that includes the needed 10-10 positions.
- Missing montage positions must warn for scalp/data channels. The expected
  missing-position warning for selected reference channels such as `EXG1` and
  `EXG2` is suppressed because those channels are kept as EEG only for initial
  referencing and are dropped before downstream interpolation/average reference.
- Montage errors are logged as warnings and do not make loading fail.
- Load failures log `!!! Load Error <filename>: <error>`, try to show a user
  error, and return `None`. Recording-not-started placeholders are not treated
  as load failures; they log `[LOADER EXCLUDED]` and are excluded from
  processing and analysis.

## Preservation Rules

- Do not change supported extension, memmap directory shape, channel subset
  policy, channel typing policy, montage arguments, logging messages, or `None`
  return behavior without an explicitly scoped behavior change.
- Do not restore `.set` support unless it is a new explicitly scoped feature.
- Do not introduce Tkinter, CustomTkinter, or CTkMessagebox; user warnings and
  errors must use `Main_App.Shared.user_messages`.
- Keep all active runtime callers loading through `Main_App.io.load_utils`
  unless the loader contract is intentionally replaced and covered by focused
  tests.

## Online Verification

- BioSemi headcap documentation lists 64-electrode standard headcaps with
  `1020` layout/labelling and provides downloadable position coordinates for
  standard BioSemi headcaps:
  https://www.biosemi.com/headcap2.htm
- Brainstorm's BioSemi cap discussion states that BioSemi 16-, 32-, and
  64-electrode caps have a one-to-one correspondence between BioSemi cap names
  and the standard 10-10 system:
  https://neuroimage.usc.edu/forums/t/icbm152-biosemi-64-10-10-versus-rename-eeg-channels-from-biosemi-caps/43072
- MNE documents `standard_1005` as the builtin montage with dense international
  standard positions, while its 10-20 builtin montage is a smaller set:
  https://mne.tools/stable/auto_tutorials/intro/40_sensor_locations.html
