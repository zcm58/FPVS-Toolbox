# GUI Architecture

The active desktop UI is PySide6.

Primary paths:

- `src/Main_App/PySide6_App/GUI/`: main window, menus, panels, icons, and style tokens.
- `src/Main_App/PySide6_App/Backend/`: project and processing coordination used by the GUI.
- `src/Tools/*/`: tool-specific PySide6 windows and launchers.

Rules:

- Keep widgets, layouts, signals, and user feedback in GUI modules.
- Keep processing and file format logic in backend, worker, or tool-core modules.
- Import `QAction` from `PySide6.QtGui`.
- Do not introduce CustomTkinter in current PySide6 code.
- Do not run long work in slots on the UI thread.

Useful checks:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python scripts/agent_audit.py --check gui
python -m pytest tests/test_main_window_layout_smoke.py -q
```

Run the skill-local script before manually searching GUI imports or reading broad GUI folders.
