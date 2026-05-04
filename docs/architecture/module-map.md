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

- `src/Main_App/PySide6_App/GUI/main_window.py`: main PySide6 window shell.
- `src/Main_App/PySide6_App/GUI/menu_bar.py`: top-level menu actions.
- `src/Main_App/PySide6_App/GUI/style_tokens.py`: shared GUI styling tokens.
- `src/Main_App/PySide6_App/Backend/project.py`: project model and manifest behavior.
- `src/Main_App/PySide6_App/Backend/processing.py`: processing coordination surface.
- `src/Main_App/PySide6_App/workers/`: worker and multiprocessing bridge code.
- `src/Main_App/Shared/source_localization_optional.py`: disabled Source Localization availability shim.

## Tools

- `src/Tools/Stats/`: active statistics UI, pipeline, analysis engines, reporting, I/O, CLI, and shared helpers grouped by function.
- `src/Tools/Stats/PySide6/` and `src/Tools/Stats/Legacy/`: temporary compatibility namespaces; do not add new active implementation here.
- `src/Tools/Plot_Generator/`: SNR/FFT plot generation.
- `src/Tools/Ratio_Calculator/`: ratio computation, export, and plotting.
- `src/Tools/Individual_Detectability/`: individual-level detectability workflow.
- `src/Tools/Average_Preprocessing/New_PySide6/`: active PySide6 average-preprocessing UI.
- `src/Tools/Average_Preprocessing/Legacy/`: legacy average-preprocessing behavior.
- `src/Tools/Image_Resizer/`: image resizing utility.

## Dead Or Quarantined

- `src/Tools/SourceLocalization/**`: must not contain active source files.
- `src/quarantine/**`: ignored quarantine tree retained outside active runtime.
