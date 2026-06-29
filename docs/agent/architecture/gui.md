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
- `src/Main_App/gui/typography.py`: canonical font family, role sizes, font
  weights, monospace font, and QSS font helpers used by the main app,
  component layer, and migrated tool windows.
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
- `src/Main_App/gui/preprocessing_qc_workflow.py`: embedded preprocessing
  data-quality review phases. It scans for BioSemi recordings that were never
  started, reviews auto-detected physically removed electrodes in the manual
  removed-electrode table, offers participant-level hard exclusions, and reports
  suspicious findings before the processing ledger plan is chosen. Important
  user-facing instructions are first shown in modal dialogs, then the embedded
  processing activity page groups the step into "what to do now", "checks in
  this step", live status, and progress sections so users have a clear visual
  path through the scan. Editable or reviewable tables are shown only when the
  current step needs a user decision, and the main window continues
  repainting/responding during scan handoffs. Review-only findings are saved
  under the active project's
  `Quality Check/Data_Quality_Check_Review_Flags.xlsx` workbook before
  processing continues.
- `src/Main_App/gui/post_export_workflows.py`: GUI-side post-processing worker
  launch, worker error routing, and export completion handling used by
  `MainWindow` compatibility wrappers.
- `src/Main_App/gui/processing_snr_qc_workflow.py`: post-processing automatic
  SNR plot generation and final spectral QC launch. It reuses the Plot
  Generator worker and keeps final spectral QC reports under the active
  project's `Quality Check` folder.
- `src/Main_App/gui/tool_workflows.py`: update-check, tool-launcher,
  help/about, and auxiliary-window actions used by `MainWindow` compatibility
  wrappers. Settings editing lives in `settings_panel.py` and is routed through
  the main workspace stack by `MainWindow`.
- `src/Main_App/gui/update_dialog.py`: user-facing update check, release-note
  preview, installer download progress, final install confirmation, and
  install busy guard.
- `src/Main_App/gui/update_manager.py`: compatibility facade for startup/manual
  update checks. It preserves debounce and pytest startup skip while delegating
  update metadata, download, and install work to `Main_App.updates` and
  `update_dialog.py`.
- `src/Main_App/gui/shell_status.py`: launch reveal, GUI log routing, and
  embedded processing activity-page helpers used by `MainWindow` compatibility
  wrappers. GUI log formatting and backend/IDE routing policy are delegated to
  `Main_App.diagnostics.log_router`.
- `src/Main_App/updates/`: non-GUI updater backend. It owns GitHub Release
  selection, typed update contracts, installer downloads, and installer launch.
  This package must not import Qt widgets or create windows.
- `src/Tools/*/`: tool-specific PySide6 windows and launchers.

The main app shell uses the outer `MainWindow.stacked` widget for landing vs
application shell navigation. Inside the application shell, `workspace_stack`
switches the right-hand workspace content while preserving the persistent
sidebar and project header. The preprocessing page remains `homeWidget`; the
Settings page, Statistical Analysis, SNR Plot Generator, Individual
Detectability, Ratio Calculator, and Epoch Averaging are embedded in this
workspace stack.

The Settings page groups project processing values under Preprocessing,
analysis defaults under Stats, ROI definitions under ROIs, and app-level
toggles such as Debug Mode and Beta Tools under Advanced. Advanced also hosts
the project preprocessing QC toggle for auto-detecting removed electrodes,
manual removed-electrode metadata, and manual participant-level processing
exclusions because those controls are intentionally more specialized than the
primary preprocessing fields. Do not put app-level visibility or diagnostics
toggles in the Preprocessing tab.

The sidebar's default tool list is Statistical Analysis, SNR Plots, Scalp Maps,
LORETA Visualizer, and Sequence Figure, in that order. Publication Report,
Ratio Calculator, Individual Detectability, and Epoch Averaging are beta tools:
they remain embedded workspace pages, but the sidebar appends them only when
the global Settings option `tools.enable_beta_tools` is enabled and the app has
been restarted.

When the active project changes through create/open/import/path workflows, the
main shell must return to Home and discard project-bound embedded page instances.
Tools should be recreated from the new `currentProject` on the next sidebar
open so stale project roots, default folders, and settings editors cannot
survive a project switch.

The main shell default and minimum size is `1280x900` to provide enough
workspace area for embedded tools without requiring individual pop-out windows.

## Visual Layout Rules

Use cards as first-level subsection boundaries, not as wrappers around other
cards. A `SectionCard` should usually represent one coherent subsection such as
File I/O, Plot Parameters, Advanced settings, Log Output, Included Conditions,
or Review. Do not place `SectionCard` widgets inside another visible card,
card-styled tab pane, bordered setup container, or other framed parent unless
the user explicitly requests that nested-card look.

When a screen needs tabs, splitters, or setup pages that contain subsection
cards, keep the parent page visually flat: no pane border, filled background,
or rounded outer frame around the child cards. The SNR Plot tool is the current
reference pattern for embedded tool layout: dedicated subsection cards sit
directly on the workspace background with normal spacing between them.

Before adding a new card-like wrapper, ask whether it communicates a distinct
top-level group. If it only exists to hold other cards or to make a tab page
look enclosed, use an unframed `QWidget` plus layout spacing instead.

## Component Layer

New and migrated GUI surfaces should import shared UI building blocks from
`src/Main_App/gui/components/`. This is the canonical component layer for
windows, dialogs, action rows, message helpers, and reusable presentation
widgets.

Canonical public import forms:

```python
from Main_App.gui import components
from Main_App.gui.components import SectionCard, make_action_button
```

Prefer `Main_App.gui.components` for FPVS-specific shells, action buttons,
action rows, section cards, subsection headers, path rows, status banners,
message helpers, window/dialog sizing, and typography helpers. `SectionCard`
titles and local subsection headings must use `SubsectionHeaderLabel` so font,
size, color, and weight stay editable from one shared component/style contract.
Direct imports from `Main_App.gui.widgets` should stay inside the component
layer or existing compatibility code unless a surface has a specific reason to
depend on a lower-level widget implementation.

Typography presentation is owned by `src/Main_App/gui/typography.py` and
re-exported through `Main_App.gui.components`. To change the global app font
family, base font size, role-specific sizes, role weights, tab fonts, sidebar
fonts, header fonts, action-button emphasis, or fixed-width log font, edit the
typography role tokens and helpers there. Runtime surfaces should use
`apply_font_role()`, `font_for_role()`, or `fixed_width_font()` instead of
locally constructing `QFont`, calling `setPointSize()`, or embedding
hard-coded `font-size`/`font-weight` QSS. Style builders such as `theme.py`,
`style_tokens.py`, and `labels.py` should consume typography helpers rather
than own independent font values.

Subsection header presentation is owned by
`Main_App.gui.typography` for size/weight and
`src/Main_App/gui/widgets/labels.py` for the `subsectionHeader` widget/QSS
selector contract. Runtime surfaces should import `SubsectionHeaderLabel` from
`Main_App.gui.components`.

`Main_App.gui.components.__all__` is the public component export contract.
Changing that list is a shared-GUI API change: update component smoke tests,
keep imports side-effect free, and record the decision in the active component
layer plan.

`ActionRow` is now used by the main shell, Settings, Plot Generator, Ratio
Calculator, Stats, Average Preprocessing, and focused dialogs.
When migrating more action rows, preserve button labels, order, variants,
enabled states, signal connections, and object names, then add focused smoke
coverage for the touched surface.

`ToolInfoContent`, `ToolInfoDialog`, `make_info_button`, and `show_tool_info`
provide the shared modal information-dialog path for tool-level explanatory
copy. Keep the modal shell, browser/link behavior, close-button behavior, icon
button properties, and theme-facing presentation in `Main_App.gui.components`;
keep each tool's editable user-facing text in a small tool-local Python content
module.

`PathPickerRow` is used by Plot Generator and Individual Detectability.
`StatusBanner` is used by Stats, Ratio Calculator, and Individual Detectability.
Keep path defaults, filters, settings keys,
project-root behavior, and file-dialog Cancel no-op behavior owned by the
surface workflow; the shared widgets are presentation contracts, not I/O
policy owners.

The component contract suite in `tests/gui/test_ui_components_smoke.py` now
pins shared component imports, object names, signal emission, invalid variants,
enabled-state preservation, theme selectors, and basic layout sizing. Extend
that suite before changing shared component behavior so migrated surfaces get a
single stable contract.

Lower-level PySide6 primitives live in `src/Main_App/gui/widgets/`. Keep this
package focused on presentation-only widgets such as reusable buttons, cards,
form rows, animation widgets, the busy spinner, and inline status widgets.
`components/` may re-export these widgets so tool windows can migrate to one
stable import surface without duplicating style or geometry decisions.

The component layer is intentionally thin. It should centralize shared shell
and presentation conventions, not own backend processing, file export behavior,
project mutation, or tool-specific orchestration.

Allowed direct Qt composition:

- Use direct `QLabel`, `QLineEdit`, `QComboBox`, `QCheckBox`, `QTableWidget`,
  `QTreeWidget`, splitters, and simple layouts when the control is local and
  has no durable FPVS-specific behavior.
- Do not wrap a one-off Qt control just to make imports look uniform.
- Keep domain-specific surfaces local when they own non-reusable behavior such
  as sidebar selection, color swatches, result tables, export details, or
  tool-specific logs.

Promote a local GUI pattern to `Main_App.gui.components` only when all of these
are true:

1. The pattern is duplicated in at least two surfaces, or a planned surface is
   likely to reuse it.
2. It encodes FPVS-specific styling, object names, geometry, project-path
   behavior, validation, messaging, or signal wiring.
3. It can be introduced without changing labels, defaults, processing behavior,
   generated data, persisted settings, or output formats.
4. It can be covered with focused pytest-qt smoke or contract tests.
5. It does not import retired paths, start workers, touch project state, access
   the filesystem at import time, or create windows as an import side effect.

The main app shell is the visual source of truth. Shared component defaults should mirror the main window's current-project shell, card, form, status, and action-button styling through `apply_fpvs_theme()` in `src/Main_App/gui/theme.py` and the tokens in `src/Main_App/gui/style_tokens.py`.

`src/Main_App/gui/main_window.py` has been appropriately refactored and downsized into the shell/coordinator for the main window. Do not choose it as a future refactor target just to reduce size. Further `main_window.py` refactors require explicit user direction and a concrete clarity or feature-maintenance benefit.

Shell-specific implementations live under `src/Main_App/gui/`, including the main window assembly, event-map row behavior, header bar, sidebar, menus, navigation icons, style tokens, and update manager. Project workflow orchestration is split into `Main_App.gui.project_workflows`, processing input orchestration is split into `Main_App.gui.processing_inputs`, processing run orchestration is split into `Main_App.gui.processing_workflows`, post-export completion handling is split into `Main_App.gui.post_export_workflows`, tool/menu action orchestration is split into `Main_App.gui.tool_workflows`, and shell feedback is split into `Main_App.gui.shell_status`, while `MainWindow` keeps public wrapper methods for actions and tests.

General GUI utilities should live under `Main_App.gui` when they coordinate UI-facing behavior. Non-GUI resource/path helpers should live under `Main_App.Shared`.

Updater boundary:

- `Main_App.gui.update_manager` schedules startup checks and opens the update
  dialog for manual checks or installable startup updates.
- `Main_App.gui.update_dialog` owns the visible dialog, progress bar, final
  confirmation, and busy-processing install guard.
- `Main_App.updates.github_releases`, `downloader`, and `installer` own
  network metadata, installer cache writes, and subprocess installer launch.
- A failed check, missing asset, ambiguous asset, download failure, or launch
  failure must surface as an error/no-install state. Do not silently open the
  GitHub release page as a fallback update path.

Widgets must not own backend processing, file export behavior, project mutation, or dialog orchestration. Keep those responsibilities in GUI controllers, backend modules, workers, or tool-specific code.

## Component Boundaries

Black-box and retired paths:

- Do not add new GUI components under `src/Main_App/Legacy_App/**`,
  `src/Main_App/PySide6_App/**`, or `src/Tools/SourceLocalization/**`.
- Do not import active GUI code from those retired paths.
- If old behavior is needed for compatibility, consume it through the current
  purpose-based APIs or a thin adapter outside protected folders.

Qt import rules:

- Import `QAction` only from `PySide6.QtGui`.
- Do not introduce Tkinter, CustomTkinter, CTkMessagebox, PyQt, or mixed-toolkit
  compatibility shims in active GUI code.

Worker and signal boundaries:

- Components and widgets are presentation-only. They must not start long work,
  read or mutate worker internals, or inspect backend dataframes.
- Long-running EEG, plotting, export, statistics, and resize work must remain
  in `QThread`, `QRunnable`, `QThreadPool`, process-runner code, or the
  existing tool worker owner.
- Embedded preprocessing data-quality checks load raw BDFs in a `QThread` through
  `preprocessing_qc_workflow.py`; the review dialogs only consume completed
  scan summaries and must not perform raw loading on the UI thread.
- Automatic post-processing SNR plot/QC generation uses the Plot Generator
  `_Worker` in `QThread` and must not duplicate Excel parsing or rendering code
  in the Main App GUI.
- Workers must communicate progress, errors, completion, and reports through
  signals or existing message callbacks. Workers must not read or mutate Qt
  widgets directly.

Project-path discipline:

- Shared path components may present a path field and button, but the owning
  workflow must preserve current project-root resolution, file-dialog filters,
  default directories, settings keys, and Cancel no-op behavior.
- Project I/O must remain under the active project root or an explicitly
  user-selected path already allowed by the existing surface.
- Do not hard-code user, machine, or study paths in GUI components.

Error UX and logging:

- Prefer non-blocking inline status for recoverable validation, missing-path,
  busy, and completion state.
- Preserve modal `QMessageBox` behavior where it is already part of a
  confirmation, destructive action, or completion workflow unless the slice
  explicitly changes and tests that behavior.
- Production error paths should use structured logging with the operation name,
  relevant project/path context, and exception details. Do not add `print` or
  silent `pass` patterns.

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
