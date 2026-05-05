# Module Map

Use this as a quick orientation map before opening files. Run the relevant audit script first when the task matches a skill; use this file to choose the next narrow file or doc to open.

Common first commands:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Main App

- `src/Main_App/PySide6_App/GUI/main_window.py`: main PySide6 shell and current refactor hotspot.
- `src/Main_App/PySide6_App/GUI/event_map.py`: event-map row construction, binding, Enter-key handling, and entry adapters used by `MainWindow` wrappers.
- `src/Main_App/PySide6_App/GUI/`: menus, header/sidebar assembly, settings panel, style tokens, and shell-specific widgets.
- `src/Main_App/PySide6_App/widgets/`: reusable PySide6 presentation primitives.
- `src/Main_App/PySide6_App/Backend/`: project model, project manager, preprocessing settings, active preprocessing implementation, and processing coordination. `preprocess.py` is the active preprocessing owner; `loader.py` is only a compatibility wrapper for the shared BDF loader.
- `src/Main_App/PySide6_App/adapters/`: current-app adapter layer for runtime-used migration-boundary behavior such as post-export handling.
- `src/Main_App/PySide6_App/workers/`: Qt worker and multiprocessing bridge implementations. Active imports should prefer `Main_App.workers`.
- `src/Main_App/PySide6_App/utils/`: audit, path, operation guard, theme, and settings helpers.
- `src/Main_App/PySide6_App/diagnostics/`: processing diagnostics and event-time lock reporting.
- `src/Main_App/Performance/`: process-runner and multiprocessing support; imports shared FFT crop helpers.
- `src/Main_App/processing/`: canonical import surface for active EEG preprocessing. It delegates to the existing PySide6 backend implementation during the package-layout migration.
- `src/Main_App/io/`: canonical import surface for active BDF loading. It delegates to the existing shared loader implementation during the package-layout migration.
- `src/Main_App/workers/`: canonical import surface for Qt workers, process runner, and multiprocessing environment helpers. It delegates to existing PySide6 worker and Performance implementations during the package-layout migration.
- `src/Main_App/Shared/`: shared current-app settings, user-message helpers, BDF loader, processing mixin, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Legacy_App/`: temporary migration boundary for runtime-used behavior. Targeted edits are allowed for migration only when processing order, data formats, and exports remain unchanged.

Current `Legacy_App` runtime couplings to account for before renaming or deleting modules:

- `settings_manager`: has a current-app shared implementation, but compatibility imports still need cleanup.

Inactive legacy code:

- `eeg_preprocessing.py`: active runtime callers now use `src/Main_App/processing/preprocess.py`; keep the legacy file untouched until a later deletion or wrapper slice is explicitly scoped.

Compatibility wrappers:

- `fft_crop_utils.py`: thin wrapper for `Main_App.Shared.fft_crop_utils`; current runtime imports should use the shared module.
- `post_process.py`: thin wrapper for `Main_App.Shared.post_process`; current runtime imports should use the shared module.
- `post_process_excel.py`: thin wrapper for `Main_App.Shared.post_process_excel`; current runtime imports should use the shared module.
- `file_selection.py`: no longer inherited by `MainWindow`; retained only for stale compatibility and uses PySide6 dialogs.
- `processing_utils.py`: thin wrapper for `Main_App.Shared.processing_mixin`; current runtime imports should use the shared module.
- `load_utils.py`: thin wrapper for `Main_App.Shared.load_utils`; current runtime imports should use `Main_App.io.load_utils`.
- `src/Main_App/PySide6_App/Backend/loader.py`: thin wrapper for `Main_App.Shared.load_utils`; current runtime imports should use `Main_App.io.load_utils`.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function. Removed `Tools.Stats.PySide6` and `Tools.Stats.Legacy` import paths are not supported.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`: UI-agnostic average-preprocessing behavior used by the PySide6 tool.
- `src/Tools/Image_Resizer/`: image resizing utility.

## Dead Or Quarantined

- Source Localization/eLORETA: removed from active runtime; `src/Tools/SourceLocalization/**` must remain empty of source files unless restoration is explicitly scoped.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
