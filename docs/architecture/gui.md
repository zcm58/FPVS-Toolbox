# GUI Architecture

The active desktop UI is PySide6.

Primary paths:

- `src/Main_App/PySide6_App/GUI/`: main window, menus, panels, icons, and style tokens.
- `src/Main_App/PySide6_App/widgets/`: shared PySide6 presentation primitives.
- `src/Main_App/PySide6_App/Backend/`: project and processing coordination used by the GUI.
- `src/Tools/*/`: tool-specific PySide6 windows and launchers.

## Component Layer

Shared PySide6 primitives live in `src/Main_App/PySide6_App/widgets/`. Use this layer for reusable buttons, cards, form rows, and inline status widgets that are presentation-only.

The main app shell is the visual source of truth. Shared component defaults should mirror the main window's current-project shell, card, form, status, and action-button styling through `apply_fpvs_theme()` and the tokens in `src/Main_App/PySide6_App/GUI/style_tokens.py`.

Shell-specific components stay in `src/Main_App/PySide6_App/GUI/`, including the main window assembly, event-map row behavior, header bar, sidebar, menus, navigation icons, and style tokens.

Widgets must not own backend processing, file export behavior, project mutation, or dialog orchestration. Keep those responsibilities in GUI controllers, backend modules, workers, or tool-specific code.

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
python -m pytest tests/test_ui_components_smoke.py -q
python -m pytest tests/test_main_window_layout_smoke.py -q
```

Run the skill-local script before manually searching GUI imports or reading broad GUI folders.
