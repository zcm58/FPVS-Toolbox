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

- `src/Main_App/PySide6_App/GUI/main_window.py`: main PySide6 shell and current refactor hotspot; event-map row behavior is the next planned extraction.
- `src/Main_App/PySide6_App/GUI/`: menus, header/sidebar assembly, settings panel, style tokens, and shell-specific widgets.
- `src/Main_App/PySide6_App/widgets/`: reusable PySide6 presentation primitives.
- `src/Main_App/PySide6_App/Backend/`: project model, project manager, preprocessing settings, preprocessing implementation, and processing coordination.
- `src/Main_App/PySide6_App/adapters/`: current-app adapter layer for runtime-used migration-boundary behavior such as post-export handling.
- `src/Main_App/PySide6_App/workers/`: Qt workers and multiprocessing bridge code.
- `src/Main_App/PySide6_App/utils/`: audit, path, operation guard, theme, and settings helpers.
- `src/Main_App/PySide6_App/diagnostics/`: processing diagnostics and event-time lock reporting.
- `src/Main_App/Performance/`: process-runner and multiprocessing support; currently still imports legacy FFT crop helpers.
- `src/Main_App/Shared/`: shared current-app settings, source-localization availability, and migration-bridge post-processing helpers.
- `src/Main_App/Legacy_App/`: temporary migration boundary for runtime-used behavior. Targeted edits are allowed for migration only when processing order, data formats, and exports remain unchanged.

Current `Legacy_App` runtime couplings to account for before renaming or deleting modules:

- `post_process` and `post_process_excel`: still drive Excel export behavior directly or through adapters.
- `processing_utils`, `file_selection`, and `debug_utils`: still consumed by the PySide6 main window shell.
- `fft_crop_utils`: used by performance processing and post-processing bridges.
- `eloreta_launcher`: still referenced by the Tools menu, while Source Localization remains unavailable/quarantined.
- `eeg_preprocessing`, `load_utils`, and `settings_manager`: have current-app replacements or bridges, but compatibility imports and transitive legacy callers still need cleanup.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function. Removed `Tools.Stats.PySide6` and `Tools.Stats.Legacy` import paths are not supported.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/`: legacy average-preprocessing behavior.
- `src/Tools/Image_Resizer/`: image resizing utility.

## Dead Or Quarantined

- `src/Tools/SourceLocalization/**`: must not contain active source files.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
