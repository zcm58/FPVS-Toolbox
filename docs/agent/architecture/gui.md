# GUI Architecture

The active desktop UI is PySide6.

Primary paths:

- `src/Main_App/gui/`: canonical active import surface for main-window,
  settings-panel, menu, sidebar, icon, style-token, theme, widget, and
  update-manager imports.
- `src/Main_App/gui/components/`: canonical shared component layer for new
  and migrated GUI surfaces. It re-exports presentation widgets and adds
  standard window/dialog shells, action rows, surface sizing, and message
  helpers.
- `src/Main_App/gui/widgets/`: shared PySide6 presentation primitives for
  reusable buttons, cards, form rows, the busy spinner, the welcome brain
  animation, and inline status widgets.
- `src/Main_App/gui/theme.py`: shared FPVS light palette and stylesheet helpers
  used by the main app and tool windows.
- `src/Main_App/gui/op_guard.py`: non-blocking re-entrancy guard for
  GUI-triggered operations.
- `src/Main_App/gui/project_workflows.py`: project open/create/load/save GUI
  orchestration used by `MainWindow` compatibility wrappers.
- `src/Main_App/gui/processing_workflows.py`: processing run start/stop,
  queue polling, worker completion/error, and finalization GUI orchestration
  used by `MainWindow` compatibility wrappers.
- `src/Main_App/gui/processing_inputs.py`: processing input validation,
  single/batch mode UI state, `.bdf` file selection, start-button readiness,
  trigger-detection placeholder behavior, and preprocessing parameter assembly
  used by `MainWindow` compatibility wrappers.
- `src/Main_App/gui/post_export_workflows.py`: GUI-side post-processing worker
  launch, worker error routing, and export completion handling used by
  `MainWindow` compatibility wrappers.
- `src/Main_App/gui/tool_workflows.py`: settings, update-check, tool-launcher,
  help/about, and auxiliary-window actions used by `MainWindow` compatibility
  wrappers.
- `src/Main_App/gui/shell_status.py`: launch reveal, status bar, busy
  indicator, GUI log routing, and processing-start notice helpers used by
  `MainWindow` compatibility wrappers.
- `src/Tools/*/`: tool-specific PySide6 windows and launchers.

## Component Layer

New and migrated GUI surfaces should import shared UI building blocks from
`src/Main_App/gui/components/`. This is the canonical component layer for
windows, dialogs, action rows, message helpers, and reusable presentation
widgets.

Lower-level PySide6 primitives live in `src/Main_App/gui/widgets/`. Keep this
package focused on presentation-only widgets such as reusable buttons, cards,
form rows, animation widgets, the busy spinner, and inline status widgets.
`components/` may re-export these widgets so tool windows can migrate to one
stable import surface without duplicating style or geometry decisions.

The component layer is intentionally thin. It should centralize shared shell
and presentation conventions, not own backend processing, file export behavior,
project mutation, or tool-specific orchestration.

The main app shell is the visual source of truth. Shared component defaults should mirror the main window's current-project shell, card, form, status, and action-button styling through `apply_fpvs_theme()` in `src/Main_App/gui/theme.py` and the tokens in `src/Main_App/gui/style_tokens.py`.

`src/Main_App/gui/main_window.py` has been appropriately refactored and downsized into the shell/coordinator for the main window. Do not choose it as a future refactor target just to reduce size. Further `main_window.py` refactors require explicit user direction and a concrete clarity or feature-maintenance benefit.

Shell-specific implementations live under `src/Main_App/gui/`, including the main window assembly, event-map row behavior, header bar, sidebar, menus, navigation icons, style tokens, and update manager. Project workflow orchestration is split into `Main_App.gui.project_workflows`, processing input orchestration is split into `Main_App.gui.processing_inputs`, processing run orchestration is split into `Main_App.gui.processing_workflows`, post-export completion handling is split into `Main_App.gui.post_export_workflows`, tool/menu action orchestration is split into `Main_App.gui.tool_workflows`, and shell/status feedback is split into `Main_App.gui.shell_status`, while `MainWindow` keeps public wrapper methods for actions and tests.

General GUI utilities should live under `Main_App.gui` when they coordinate UI-facing behavior. Non-GUI resource/path helpers should live under `Main_App.Shared`.

Widgets must not own backend processing, file export behavior, project mutation, or dialog orchestration. Keep those responsibilities in GUI controllers, backend modules, workers, or tool-specific code.

Rules:

- Keep widgets, layouts, signals, and user feedback in GUI modules.
- For new GUI surfaces, start from `Main_App.gui.components` before adding
  local geometry, action rows, dialogs, or message boxes.
- Keep processing and file format logic in backend, worker, or tool-core modules.
- Import `QAction` from `PySide6.QtGui`.
- Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports in repo code; the active UI toolkit is PySide6.
- Do not run long work in slots on the UI thread.

Useful checks:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/scripts/audit/agent_audit.py --check gui
python -m pytest tests/gui/test_ui_components_smoke.py -q
python -m pytest tests/gui/test_main_window_layout_smoke.py -q
```

Run the skill-local script before manually searching GUI imports or reading broad GUI folders.
