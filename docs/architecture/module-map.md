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
- `src/Main_App/PySide6_App/Backend/`: project model, project manager, preprocessing settings, preprocessing implementation, and processing coordination.
- `src/Main_App/PySide6_App/adapters/`: current-app adapter layer for runtime-used migration-boundary behavior such as post-export handling.
- `src/Main_App/PySide6_App/workers/`: Qt workers and multiprocessing bridge code.
- `src/Main_App/PySide6_App/utils/`: audit, path, operation guard, theme, and settings helpers.
- `src/Main_App/PySide6_App/diagnostics/`: processing diagnostics and event-time lock reporting.
- `src/Main_App/Performance/`: process-runner and multiprocessing support; imports shared FFT crop helpers.
- `src/Main_App/Shared/`: shared current-app settings, FFT crop helpers, and migration-bridge post-processing helpers.
- `src/Main_App/Legacy_App/`: temporary migration boundary for runtime-used behavior. Targeted edits are allowed for migration only when processing order, data formats, and exports remain unchanged.

Current `Legacy_App` runtime couplings to account for before renaming or deleting modules:

- `post_process` and `post_process_excel`: still drive Excel export behavior directly or through adapters.
- `processing_utils`, `file_selection`, and `debug_utils`: still consumed by the PySide6 main window shell.
- `eeg_preprocessing`, `load_utils`, and `settings_manager`: have current-app replacements or bridges, but compatibility imports and transitive legacy callers still need cleanup.

Compatibility wrappers:

- `fft_crop_utils.py`: thin wrapper for `Main_App.Shared.fft_crop_utils`; current runtime imports should use the shared module.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function. Removed `Tools.Stats.PySide6` and `Tools.Stats.Legacy` import paths are not supported.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/`: legacy average-preprocessing behavior.
- `src/Tools/Image_Resizer/`: image resizing utility.

## Dead Or Quarantined

- Source Localization/eLORETA: removed from active runtime; `src/Tools/SourceLocalization/**` must remain empty of source files unless restoration is explicitly scoped.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
