# Preprocessing Contract

This page records the active preprocessing owner and the behavior that must stay
stable during Main App refactors.

## Active Owner

`src/Main_App/PySide6_App/Backend/preprocess.py` owns active EEG
preprocessing.

Current app processing must call:

```python
from Main_App.PySide6_App.Backend.preprocess import perform_preprocessing
```

Compatibility paths such as `Main_App.perform_preprocessing` and
`Main_App.Shared.processing_mixin` may delegate to this owner, but active
runtime code must not import `Main_App.Legacy_App.eeg_preprocessing`.

`src/Main_App/Legacy_App/eeg_preprocessing.py` remains on disk only as inactive
legacy code until a later deletion or compatibility-wrapper slice is explicitly
scoped.

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

## Preservation Rules

- Do not change filtering math, reference handling, rejection thresholds, event
  handling, output data shapes, export inputs, or processing order unless the
  user explicitly requests a behavior change.
- GUI processing must route through the PySide6 process runner; single-file runs
  use the same runner with `max_workers=1`.
- If an internal mode cannot use the PySide6 process runner, fail clearly rather
  than silently falling back to legacy preprocessing.
- Refactors may split or move files only after focused tests prove the public
  behavior and generated outputs are unchanged.

## Focused Verification

Use these checks for preprocessing ownership/routing changes:

```powershell
python -m py_compile src\Main_App\PySide6_App\Backend\preprocess.py src\Main_App\Shared\processing_mixin.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\__init__.py
.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py tests\test_main_window_processing.py -q
.venv\Scripts\python -m pytest tests\test_preproc_audit.py tests\test_fif_flag_audit.py tests\test_process_runner_epoch_contract.py -q
python scripts\agent_audit.py
python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```
