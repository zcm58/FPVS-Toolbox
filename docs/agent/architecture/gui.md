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
  orchestration and the confirmed active-project processing-cache reset used by
  `MainWindow` compatibility wrappers.
- `src/Main_App/gui/processing_workflows.py`: processing run start/stop,
  queue polling, worker completion/error, and finalization GUI orchestration
  used by `MainWindow` compatibility wrappers.
- `src/Main_App/gui/frequency_domain_qc_dialog.py`: modal review dialog shown
  after workbook processing and before final harmonic selection when
  project-wide summed-BCA frequency-domain QC finds automatic hard exclusions,
  strong warnings, or repeated warning patterns. The dialog presents a
  participant summary first, optional flagged-cell details second, and lets the
  user add manual participant-level frequency-domain exclusions before
  processing resumes. Participant and detail rows show the canonical project
  group label resolved from manifest membership; an unknown participant or
  missing grouped assignment blocks the review instead of displaying inferred
  membership.
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
  processing continues. Raw preflight results retain canonical `group_id`
  provenance, and every file/participant review table plus live scan status
  displays the manifest group label. Exclusion and removed-electrode settings
  remain keyed by globally unique participant ID. The normal scan passes the
  active project root and complete event map to the GUI-neutral worker so the
  condition-aware v3 path and its project-local cache are used. Live status
  distinguishes planning, condition/time-block scanning, exact on-bin spectral
  scanning, cache reuse, and participant completion while the progress value
  counts completed participant files. The GUI caps the displayed worker count
  at the backend's four-participant QC limit. The backend independently caps
  BDF readers and spectral evaluators at two each. Cancellation requests are
  relayed through the worker and take effect between condition reads,
  time-domain blocks, FFT channel batches, and cache writes; widgets remain
  signal consumers and never read BDF data directly.
- `src/Main_App/gui/signal_review_model.py` and `signal_review_panel.py`:
  presentation-only Step 7 signal-review browser. The workflow attaches short
  type, condition, occurrence, and channel fields while collecting the existing
  four- or seven-column review rows; the complete original rows and workbook
  export remain unchanged. A compact tree groups items by their full recording
  identity, with text search and finding-type filters. Its resizable evidence
  pane shows the selected item's complete text. Disabled and unevaluated checks
  are assessment statuses, not detected signal problems; repeated findings are
  retained. The browser temporarily replaces the shared status narrative and
  table, restoring their visibility on Continue, Cancel, or failure. A compact
  workbook action opens the exact saved active-project report through the
  cross-platform path helper and reports open/save failures inline.
- `src/Main_App/gui/post_export_workflows.py`: GUI-side post-processing worker
  launch, worker error routing, and export completion handling used by
  `MainWindow` compatibility wrappers.
- `src/Main_App/gui/tool_workflows.py`: settings-dialog, update-check, and
  about-dialog helpers used by `MainWindow`. Settings editing lives in
  `settings_panel.py` and is routed through the main workspace stack.
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
- `src/Main_App/gui/processing_log_dialog.py`: focused modal viewer for the
  persistent Main App processing log. The home page keeps only a **View Log**
  action so the Conditions editor can use the full remaining height.
- `src/Main_App/updates/`: non-GUI updater backend. It owns GitHub Release
  selection, typed update contracts, installer downloads, and installer launch.
  This package must not import Qt widgets or create windows.
- `src/Tools/*/`: tool-specific embedded PySide6 pages, workers, and processing
  helpers. Active user-facing tools do not launch through standalone subprocess
  or command-line entry points.

The main app shell uses the outer `MainWindow.stacked` widget for landing vs
application shell navigation. Inside the application shell, `workspace_stack`
switches the right-hand workspace content while preserving the persistent
sidebar and project header. The preprocessing page remains `homeWidget`; the
Settings page, Standard FPVS Screening, Sensitivity Analysis, SNR Plot Generator,
Free Harmonic Clustering Analysis, Individual Detectability, and Ratio Calculator
are embedded in this workspace stack.

The Settings page groups project processing values under Preprocessing, the
project-wide presentation/oddball protocol under Protocol, project-specific
harmonic selection and summation under Harmonics, analysis defaults under
Stats, ROI definitions under ROIs, project-owned review controls under
Experimental, and app-level toggles such as Debug Mode and Beta Tools under
Advanced. Experimental uses three flat sub-tabs: **Electrodes** contains
kurtosis interpolation, the explicit On/Off choice for the lab-calibrated
automatic removed-electrode detector, and its independently enabled manual
removed-electrode lists; **Raw-Spectral Review** contains the review switch
and expandable read-only thresholds; **Summed-BCA Screening** contains the
versioned review limits. Each section has its own vertical space within the
supported workspace, including when raw-spectral details are expanded.
Settings tab panes stay unframed around their section cards, and each main tab
keeps Change Projects Root, Save, and Cancel on one bottom action row. Invalid
summed-BCA input reveals its sub-tab before focusing the affected field.
Advanced retains manual participant-level processing exclusions and shows
read-only frequency-domain QC
thresholds and active frequency-domain exclusions; changing manual
frequency-domain exclusions marks downstream frequency-domain outputs stale and
requires regeneration. Do not put app-level visibility or diagnostics toggles
in the Preprocessing tab.

The Protocol tab edits only the active project's versioned FPVS protocol. It
accepts a presentation rate plus either an every-N-stimuli recurrence or a
direct oddball rate that resolves to a whole-stimulus recurrence, shows the
canonical oddball rate, stores a positive expected analyzed oddball-cycle
count, derives duration read-only, and stores the project oddball marker code.
Existing projects without trustworthy protocol metadata show proposed legacy
rates but remain unconfirmed until the user supplies the cycle count and saves
from Protocol. Marker-less v1.0 records keep their known rates and cycle fields
while requiring marker confirmation; records without a cycle count still
require one. Saving from another unchanged Settings tab leaves either
unresolved form untouched; it does not turn a
proposal into project provenance.
Processing input validation consumes the resulting frozen project protocol,
derives the temporary numeric compatibility fields from it, and blocks before
QC when the protocol is unconfirmed, incomplete, invalid, or uses the same code
for an oddball marker and condition onset. Saving one project never changes
another project's protocol or the application-level rate defaults.

The project-specific **Harmonic Selection and Summation** card on the dedicated
Harmonics tab edits
the processing-owned method profile rather than creating a Stats-local policy.
Its profile choices and stable backend IDs are:

- **Dzhelyova/Poncet — stop after two consecutive failures (recommended)**,
  `dzhelyova_poncet_two_consecutive_failures`;
- **Fixed / preregistered harmonic domain**,
  `fixed_preregistered_domain`;
- **Significant-only (exploratory)**,
  `significant_only_exploratory`; and
- **Legacy FPVS Toolbox — through highest with isolated-peak guard**,
  `legacy_fpvs_toolbox`.

The card must expose only scientifically valid controls for the selected
profile. Fixed mode chooses an exact Hz list, upper oddball-harmonic index, or
upper frequency in Hz and always excludes dynamically identified base-rate
overlaps; this exclusion is displayed as a locked rule, not an optional
setting. Non-legacy adaptive modes use all retained scalp
electrodes or a nonempty frozen selection mask; mutable ROI-union scope is
available only for Legacy. The visible explanation must distinguish locally
detected harmonics from the exact included Summed-BCA list and identify
same-sample adaptive profiles as exploratory.

Applying a project method change requires confirmation and starts background
recalculation plus selection-dependent post-processing. The UI must report that
this uses existing FullFFT/BCA workbooks and does not rerun EEG preprocessing.
For a Save-triggered immediate rebuild, the embedded Settings page remains
alive and guarded in the background while `workspace_stack` shows the shared
`processing_page`. The grid audit begins with indeterminate progress; harmonic
selection and selection-dependent publication then use the normal spinner,
progress bar, phase title, step count, and status message. The processing action
is disabled and labelled as in progress because this worker has no cooperative
cancel action. A successful run closes the Settings workflow and returns Home.
The explicit **Recalculate Harmonics** action may remain Settings-local and use
its inline status banner instead of changing workspace pages.

Before either workflow starts, Settings snapshots project preprocessing, app
analysis/ROI settings, and its project cache. A validation or save failure,
failed/incompatible grid review, user cancellation of the exclusion-review
dialog, or pre-persistence selection failure restores that snapshot. A
Save-triggered activity page then returns to the still-live Settings page so
the user can review or correct the inputs. Derivative freshness is not changed
merely because the worker starts. Once a replacement selection is persisted,
Settings cannot be closed or rejected and shell navigation remains locked until
publication finishes; a publication failure returns to Settings with the new
method committed and its dependent outputs marked stale or failed. Project
switching must not retain another project's method, activity-page state, or
worker state.

The sidebar's default tool list is Free Harmonic Clustering Analysis and SNR
Plots, in that order. Scalp Maps, Standard FPVS Screening, Sensitivity
Analysis, LORETA Visualizer, Sequence Figure, Ratio Calculator, and Individual
Detectability are beta tools: they remain
embedded workspace pages, but the sidebar appends them beneath a visible
**Beta Tools** subsection only when the global Settings option
`tools.enable_beta_tools` is enabled and the app has been restarted.

The Beta Tools registry owns the shared gate: every entry in `BETA_TOOL_SPECS`
is connected through `MainWindow._open_beta_tool`, so adding a beta tool to the
registry must not require per-tool warning code. Before that tool's opener runs
for the first time in each app session, show an OK-only warning titled `Beta
Tool` with the text `This tool is currently in beta. Features are subject to
change.` Track acknowledgement separately for each beta registry role.

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

New or substantially revised embedded tool pages must fit the supported
1280x900 workspace without a page-level `QScrollArea`. If one coherent surface
cannot fit without clipping, split the workflow into purpose-based tabs or
progressive pages and keep each page visually flat. Scrolling remains
appropriate inside content-native widgets such as tables, log/text viewers,
and focused dialogs; this rule prevents the tool page itself from becoming a
long document.

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

`PostProcessingRequiredDialog` is the shared downstream-tool recovery prompt.
It explains the stale reason, states that existing processed workbooks are
reused and EEG preprocessing is not rerun, and offers **Run Post-processing**
or **Not Now**. Tools report the affected project identity and reason; the Main
App shell verifies that identity against the active project and owns the call
to the existing post-processing workflow. Tool pages must not start their own
post-processing workers.

`ActionRow` is now used by the main shell, Settings, Plot Generator, Ratio
Calculator, Stats, and focused dialogs.
When migrating more action rows, preserve button labels, order, variants,
enabled states, signal connections, and object names, then add focused smoke
coverage for the touched surface.

`ToolInfoContent`, `ToolInfoDialog`, `make_info_button`, and `show_tool_info`
provide the shared modal information-dialog path for tool-level explanatory
copy. Keep the modal shell, browser/link behavior, close-button behavior, icon
button properties, and theme-facing presentation in `Main_App.gui.components`;
keep each tool's editable user-facing text in a small tool-local Python content
module. `ToolInfoTab` and the optional `ToolInfoContent.tabs` tuple provide a
backward-compatible tabbed layout for tools whose explanatory material is too
complex for one page; content without tabs retains the original single-browser
dialog.

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
4. It can be covered by locally safe contract tests or CI-only pytest-qt smoke
   coverage.
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

Focused local verification:

```console
python .agents/scripts/verify.py --scope gui --tier focused
```

The driver runs the safe import/static checks. Main-window and dialog pytest-qt
coverage is CI-only by default; document a visible/manual smoke path for the
changed interaction. Run the GUI audit directly only as an initial diagnostic
before manually searching broad GUI folders.

For the Step 7 signal-review browser, open a project at 1280x900, reach Review
Signal Flags, and confirm the recording groups, filters, evidence pane, workbook
action, and Continue/Cancel buttons fit without page-level scrolling. Select
findings using both mouse and keyboard; check complete evidence and identity for
multiple recordings of the same participant. Search for a channel and condition,
filter by assessment status, and clear a search with no matches. Open the saved
workbook and compare its rows with the full displayed evidence. Confirm Continue
returns to the normal processing table, and Cancel followed by another QC run
does not retain the previous browser or hide the shared status/table widgets.
The registered `tests/gui/test_signal_review_panel_qt.py` owns CI-only interaction
and layout coverage; widget-free identity coverage lives in
`tests/gui/test_signal_review_model.py`.

For processing readiness changes, use a project with a declared condition that
has no start marker. In Step 3, verify that the missing condition appears
unchecked and cannot be skipped; Cancel must stop the run without saving an
exclusion. Save an intentional condition exclusion and verify a subsequent run
can complete with the existing ledger checks. Repeat with two recordings of
one participant and check the selected recording/all-visits scope. Trigger a
required post-processing failure and verify that progress and completion say
incomplete, display the concrete reason, and that opening SNR shows the same
reason. After successful core post-processing, SNR must open normally; an
optional source-map export failure must not block it. Qt execution is CI-only;
local regression checks execute the orchestration functions with widget-free
doubles plus the pure preflight and recording-condition models.

For Protocol-tab changes, the visible smoke path is: open two projects in turn,
save distinct recurrence/direct-Hz protocols, reopen each project and verify its
own values; confirm that direct-Hz entry displays the implied integer recurrence
and derived duration; save an unrelated tab in an old unconfirmed project and
verify the proposed protocol stays unconfirmed; confirm an unchanged imported
marker retains its Studio source; verify an old unconfirmed project and a new
project with no cycle count cannot start processing; and verify a marker code
matching a condition-onset code is rejected. Keep Qt execution in CI unless the
user has approved a visible local Qt session.

For Experimental-tab changes, open a project at 1280x900 and visit all three
Experimental sub-tabs. Confirm every label and threshold field is readable
without clipping, including all eight read-only Raw-Spectral Advanced rows,
and the bottom action row remains visible. Repeat with the supported display
scaling settings on Windows and Linux. Confirm automatic detection has only
Off and On choices, manual lists can be edited and enabled independently,
and all eleven summed-BCA thresholds survive switching sub-tabs, Save, and
reopen. Enter an invalid summed-BCA value, switch to Electrodes, and Save:
after dismissing the warning, Summed-BCA Screening must be visible with the
invalid field selected. For an older project with no saved detector choice,
verify the prompt and warning fit, and saving another setting leaves the
choice pending. Check Preprocessing, Protocol, Harmonics, Stats, ROIs, and
Advanced retain their controls above the compact footer. Qt execution remains
CI-only unless a safe visible local session is explicitly approved.
