# Shared GUI Component Layer

## Status

Active plan. Initial planning document added on 2026-05-12. Updated on
2026-05-12 to make the workflow safer for long-running agent execution.

## Target

`src/Main_App/gui/components/` is the canonical import surface for shared FPVS
PySide6 UI primitives.

Related implementation owners:

- `src/Main_App/gui/components/`
- `src/Main_App/gui/widgets/`
- Current and future GUI surfaces under `src/Main_App/gui/` and `src/Tools/`

## Operating Principle

This is an incremental consolidation plan, not a rewrite. Migrate GUI surfaces
only when they are already being touched for feature work, bug fixes, or a
focused cleanup slice. Each slice must preserve processing order, runtime
behavior, object names, persisted settings, project I/O, and generated data
formats unless that slice explicitly scopes and verifies the change.

## Mission

Make `Main_App.gui.components` the stable component hub for reusable FPVS GUI
patterns so future surfaces can start from one shared layer instead of copying
local styling, layout, action, path, message, and status code.

A component should exist only when it removes real duplication, encodes a durable
FPVS convention, or makes future edits safer. Direct Qt widgets remain acceptable
for simple local composition.

## Hard Invariants

These rules apply to every slice and override slice-specific instructions.

- PySide6 only. Do not introduce CustomTkinter, tkinter, or another GUI toolkit.
- `QAction` must be imported with `from PySide6.QtGui import QAction`.
- Do not edit black-box paths:
  - `src/Main_App/Legacy_App/**`
  - `src/Tools/SourceLocalization/**`
- Do not recreate retired runtime paths:
  - `src/Main_App/PySide6_App/**`
- Do not restore Source Localization/eLORETA runtime behavior.
- Do not change the order of processing steps.
- Do not change generated file formats, export schemas, column order, or naming.
- Do not hard-code user, project, or machine paths.
- Do not read from or mutate widgets inside workers.
- Long-running work must stay off the UI thread and report through signals.
- Keep existing labels, defaults, enabled states, tooltips, shortcuts, object
  names, settings keys, and project-path behavior unless the slice explicitly
  includes matching test updates.
- Use non-blocking error UX plus structured logs. Do not use `print` or silent
  catches.

## Component Hub Contract

### Public import rule

Callers should import shared FPVS primitives through:

```python
from Main_App.gui import components
```

or through explicit names exported by:

```python
from Main_App.gui.components import ComponentName
```

Implementation may remain in `Main_App.gui.widgets` when that is the current
owner, but external GUI surfaces should prefer `Main_App.gui.components` after a
primitive is exported there.

### Export rules

- `src/Main_App/gui/components/__init__.py` owns stable public names.
- Exports must be explicit with `__all__` when practical.
- Imports must not create windows, read project state, start workers, touch the
  filesystem, or trigger app initialization.
- Re-export shims are allowed only to preserve compatibility during migration.
- Avoid circular imports by keeping implementation modules purpose-based and
  dependency-light.
- New public component APIs need type hints and docstrings.

### Component categories in scope

- App and dialog shells.
- Section/card containers.
- Action rows, primary/secondary buttons, and action helpers.
- Path picker rows and project-aware file/directory selection helpers.
- Status banners, inline notices, progress indicators, and message helpers.
- Common form layout helpers and theme-token-based style helpers.

### Components not in scope

Do not wrap a Qt widget only to rename it. These remain acceptable as direct Qt
composition when local and simple:

- `QLabel`
- `QLineEdit`
- `QComboBox`
- `QCheckBox`
- `QTableWidget`
- `QTreeWidget`
- One-off widgets used by a single surface with no FPVS-specific convention

## Promotion Decision Tree

Before creating or migrating to a shared component, answer these in order:

1. Is the pattern duplicated in at least two surfaces, or likely to be reused by
   a planned surface?
2. Does it encode FPVS-specific behavior, styling, object names, project-path
   handling, validation, messaging, or signal wiring?
3. Can it be introduced without changing labels, defaults, processing behavior,
   generated data, or persisted settings?
4. Can it be tested with focused pytest-qt smoke coverage?
5. Can it avoid imports from black-box or retired paths?

If any answer from 3 through 5 is no, do not migrate in that slice. Record a
blocker or keep the widget local.

## Behavior To Preserve

- All GUI surfaces remain PySide6-only.
- Existing object names used by tests, styles, and automation remain stable.
- Existing labels, default values, enabled states, tooltips, shortcuts, tab
  order, project-path behavior, settings persistence, generated file formats,
  and user workflows remain unchanged unless explicitly scoped.
- Long-running work remains outside the UI thread with worker signals used for
  `progress(int)`, `error(str)`, and `finished(payload)` or the closest existing
  equivalent.
- Workers must not read from or mutate widgets directly.
- File dialog Cancel is a no-op that preserves existing UI state.
- Invalid or missing paths produce non-blocking UX and structured logs.
- Excel/CSV-related GUI changes preserve centered text, auto column widths, and
  padding conventions.

## Non-Goals

- Do not perform a repo-wide conversion in one pass.
- Do not introduce a parallel UI framework over Qt.
- Do not replace every direct Qt widget construction with a custom wrapper.
- Do not change visual design, processing behavior, exports, or project I/O as
  part of component consolidation unless a specific slice scopes that change.
- Do not move business logic into component classes.
- Do not use this plan to refactor unrelated tool internals.

## Success Criteria

- New and migrated GUI surfaces can start from `Main_App.gui.components`
  without searching multiple widget/helper locations.
- Repeated FPVS UI patterns have one practical owner and focused smoke coverage.
- A future change to shared action buttons, section cards, path pickers, message
  helpers, progress indicators, or status banners updates all migrated surfaces.
- Surfaces that still use direct Qt widgets do so for local composition rather
  than duplicated FPVS-specific styling or behavior.
- Architecture and agent docs point future agents to the component hub before
  adding local UI primitives.
- The final inventory distinguishes centralized patterns from intentionally
  local patterns.

## Slice Status Values

Use only these status values in the tracker:

- `Pending`: not started.
- `In Progress`: current slice being edited.
- `Blocked`: cannot continue without a documented decision or missing dependency.
- `Complete`: implementation, tests, and plan update finished.
- `Skipped - intentionally local`: reviewed and kept local with rationale.

Only one slice should be `In Progress` at a time. Do not start a later slice
until the earlier slice is `Complete`, `Blocked`, or `Skipped - intentionally
local`.

## Slice Tracker

| Slice | Status | Required output | Exit verification |
| --- | --- | --- | --- |
| 0. Inventory shared and duplicated UI patterns | Complete | Inventory of current component exports, direct widget helpers, duplicated FPVS-specific patterns, current users, risk-ranked migration candidates, and intentionally local patterns | Agent audit; GUI import audit; targeted `rg`; no code changes |
| 1. Document component hub contract | Complete | `docs/agent/architecture/gui.md` and nearest agent guidance updated with import rules, promotion decision tree, invariants, and examples | Agent audit; docs review; no runtime code changes |
| 2. Normalize component exports | Complete | Stable exports from `Main_App.gui.components`; no import side effects; compatibility shims where needed; component smoke tests | `python -m pytest tests/gui/test_ui_components_smoke.py -q`; GUI import audit; import cycle check |
| 3. Consolidate action and message patterns | Complete | Opportunistic migration of touched surfaces to shared action rows/buttons/message helpers while preserving labels, shortcuts, object names, enabled states, and signal wiring | Focused pytest-qt smoke tests for touched surfaces; re-entrancy and Cancel checks |
| 4. Consolidate section/status/path patterns | Complete | Opportunistic migration of touched surfaces to shared cards/status/path-picker helpers while preserving project-root behavior and file dialog semantics | Focused pytest-qt smoke tests; project-path audit when file paths are touched |
| 5. Add coverage for component contracts | Pending | Component contract tests for object names, signal behavior, theme-token use, sizing/layout expectations, and basic high-DPI safety | `python -m pytest tests/gui/test_ui_components_smoke.py -q` plus touched-surface tests |
| 6. Completion review | Pending | Final inventory of centralized patterns and intentionally local patterns; plan moved from active to completed only after verification passes | Agent audit; GUI import audit; hardcoded-path audit; selected surface smoke tests |

## Execution Workflow For Each Slice

1. Re-read this plan and select the first `Pending` slice.
2. Mark only that slice as `In Progress`.
3. Run required pre-check commands and save exact command results in the progress
   log.
4. Freeze scope before editing:
   - files allowed for this slice;
   - behavior that must remain unchanged;
   - tests that must pass before marking complete.
5. Edit only files required by the slice.
6. Add or update pytest-qt smoke coverage for changed GUI wiring.
7. Run slice verification commands and any affected surface tests.
8. If all gates pass, mark the slice `Complete` and add a progress-log entry.
9. If a gate fails, fix before shipping or mark the slice `Blocked` with the
   exact blocker. Do not output a failing diff as complete.
10. Stop after one completed slice unless explicitly instructed to continue.

## Stop And Blocker Rules

Stop the slice and record a blocker when any migration would require:

- editing black-box paths;
- recreating retired paths;
- changing processing order;
- changing generated data formats;
- broad redesign outside the slice;
- hidden behavior changes not covered by tests;
- circular imports that cannot be resolved with a small module split;
- wrapping one-off Qt controls only for visual uniformity;
- worker code reading or mutating widgets;
- project I/O outside the active project root;
- blocking dialogs or long work on the UI thread;
- replacing direct Qt composition with a component that makes the surface harder
  to understand.

A blocker entry must include attempted command, failing file or pattern,
observed risk, safest next action, and whether user direction is required.

## Baseline Commands

Run these before Slice 0 and again before Slice 6:

```powershell
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python -m pytest tests/gui/test_ui_components_smoke.py -q
```

Use the project test-selection guide for targeted tests:

```powershell
python -m pytest -q tests/gui/test_ui_components_smoke.py
```

Add focused tests for each touched surface. Use the narrowest relevant test set
from `docs/agent/quality/test-selection.md`.

## Command Boundaries For This Plan

- Keep exploratory verification commands bounded. Use short command timeouts for
  import probes and stop on the first unrelated dependency failure.
- Do not verify the component layer by importing broad GUI or tool-window module
  lists. Those imports can cascade into optional analysis dependencies, tool
  launchers, scientific-library initialization, or app-window setup that is not
  part of the component contract.
- Prefer focused component smoke tests, `py_compile` for touched component
  modules, skill-local audits, and a narrow subprocess import of
  `Main_App.gui.components` when checking import side effects.
- If a broad import probe is accidentally started and runs longer than expected,
  stop the process, record the attempted command and first failing or hanging
  module, and replace it with a narrower gate.

## Inventory Commands

Use these during Slice 0 and repeat selectively in later slices:

```powershell
rg "from Main_App\.gui\.components|from Main_App\.gui\.widgets" src/Main_App/gui src/Tools -g "*.py"
rg "QAction|QMessageBox|QFileDialog|QProgressDialog|statusBar\(|setStyleSheet|setObjectName" src/Main_App/gui src/Tools -g "*.py"
rg "customtkinter|CustomTkinter|tkinter" src -g "*.py"
rg "Main_App\.Legacy_App|Tools\.SourceLocalization|Main_App\.PySide6_App" src -g "*.py"
```

If `rg` is unavailable, use an equivalent Python search and record the exact
alternative command in the progress log.

## Per-Slice Requirements

### Slice 0 - Inventory shared and duplicated UI patterns

Allowed edits:

- This plan.
- Optional inventory document under `docs/agent/exec-plans/active/` if the inventory
  becomes too large for this file.

Required inventory fields:

- Component or pattern name.
- Current owner module.
- Current consumers.
- Duplicate local implementations.
- Object names and signal names that must remain stable.
- Theme tokens or local style strings involved.
- Worker, path, message, or export behavior involved.
- Migration risk: low, medium, high.
- Recommended slice: 2, 3, 4, 5, or intentionally local.

Exit rule: no production code changes in Slice 0.

### Slice 1 - Document component hub contract

Allowed edits:

- `docs/agent/architecture/gui.md`
- nearest relevant agent guidance files
- this plan

Required documentation content:

- Canonical import rule for `Main_App.gui.components`.
- Allowed direct Qt composition rule.
- Promotion decision tree.
- Black-box and retired-path boundaries.
- `QAction` import rule.
- Worker/signal boundary.
- Project-path discipline.
- Error UX and structured logging expectations.

Exit rule: no runtime code changes in Slice 1.

### Slice 2 - Normalize component exports

Allowed edits:

- `src/Main_App/gui/components/**`
- small implementation-owner modules under `src/Main_App/gui/widgets/**` only
  when needed to support existing public components
- component tests
- this plan

Required checks:

- Exported names are stable and explicit.
- Importing `Main_App.gui.components` has no runtime side effects.
- Existing consumer import styles remain available through
  `from Main_App.gui.components import ...`; do not use broad app/tool module
  import sweeps as this slice's gate.
- Re-export shims do not hide circular imports.
- New public APIs have type hints and docstrings.

Exit rule: no broad surface migration in Slice 2.

### Slice 3 - Consolidate action and message patterns

Allowed edits:

- Touched GUI surfaces already in scope for current work.
- Shared action/message components.
- Focused tests for touched surfaces.
- This plan.

Preserve exactly:

- Button labels.
- Shortcut keys.
- Tooltips.
- Object names.
- Enabled/disabled state transitions.
- Signal connections and processing order.
- Modal versus non-modal behavior where already established.

Required checks:

- Repeat clicks are guarded where work can be re-entered.
- Error messages are non-blocking unless the previous behavior was intentionally
  modal and is preserved.
- Structured logs include operation, project context when available, path when
  relevant, elapsed time when available, and exception details.

### Slice 4 - Consolidate section/status/path patterns

Allowed edits:

- Touched GUI surfaces already in scope for current work.
- Shared section/status/path components.
- Focused tests for touched surfaces.
- This plan.

Preserve exactly:

- Visible headings and section order.
- Existing path defaults and settings keys.
- File dialog filters and default directories.
- File dialog Cancel behavior.
- Project-root read/write behavior.
- Status text timing and severity semantics where tested or user-visible.

Required checks:

- All I/O remains under active project root or an explicitly user-selected path
  already allowed by the current surface.
- Invalid paths do not crash the UI.
- Missing permissions report non-blocking UX plus structured logs.

### Slice 5 - Add coverage for component contracts

Allowed edits:

- Component tests.
- Minimal component code only when required to make contracts explicit.
- This plan.

Required coverage:

- Component imports.
- Object names.
- Signal emission and slot wiring.
- Enabled/disabled states.
- File dialog Cancel no-op behavior for path components.
- Missing or invalid path behavior for path components.
- Theme-token application for shared visual primitives.
- Basic layout boot under pytest-qt.

Exit rule: do not use Slice 5 for broad migrations.

### Slice 6 - Completion review

Allowed edits:

- This plan.
- Final inventory summary.
- Move from `docs/agent/exec-plans/active/` to completed location only after all
  verification passes.

Required final record:

- Centralized components and their owner modules.
- Surfaces migrated.
- Patterns intentionally left local and why.
- Tests added or updated.
- Commands run and results.
- Remaining known risks.

Exit rule: do not mark complete while any earlier slice is `Pending` or
`In Progress`.

## Definition Of Done For Every Implementation Slice

All gates must pass before a slice can be marked `Complete`.

| Gate | Required evidence |
| --- | --- |
| 1. Imports resolve on Windows | Exact import command or test result; `QAction` origin confirmed when touched |
| 2. Threading is safe | Workers do not touch widgets; UI updates happen through signals |
| 3. UI integrity and DPI | Widgets are in layouts; shared styles use theme tokens; no fixed-size regressions |
| 4. Legacy boundaries preserved | No edits to black-box paths; retired paths not recreated |
| 5. Project-path discipline | No literal user paths; active project root used for project I/O |
| 6. Error UX and logging | Non-blocking user notice plus structured log context |
| 7. Static hygiene | PEP8, no unused imports or variables, type hints on new public APIs |
| 8. Edge cases handled | Empty selection, repeat click, invalid path, missing path, permission error, Cancel |
| 9. Resource cleanup | Workers stop cleanly; signals disconnected where needed; no orphan threads |
| 10. Excel/CSV behavior preserved | Centering, widths, padding, and data format unchanged when relevant |

If a gate is not relevant to the slice, record `PASS - not touched` with the
reason.

## Required Progress Log Format

Each slice update must append a dated entry with these fields:

- Status.
- Slice number and name.
- Files changed.
- Behavior preserved.
- Public API changes.
- Tests added or updated.
- Commands run with PASS/FAIL result.
- Verification gates result.
- Blockers or risks.
- Next slice.

## Known Current Component-Layer Users

Initial known users:

- `src/Main_App/gui/ui_main.py`
- `src/Main_App/gui/settings_panel.py`
- `src/Tools/Plot_Generator/ui_sections.py`
- `src/Tools/Ratio_Calculator/gui.py`
- `src/Tools/Stats/ui/stats_window_support.py`
- `src/Tools/Image_Resizer/pyside_resizer.py`
- `src/Tools/Individual_Detectability/main_window.py`
- `src/Tools/Average_Preprocessing/New_PySide6/main_window.py`

Known direct Qt composition remains common and is acceptable when local to a
surface. Future slices should focus on duplicated FPVS-specific patterns, not on
eliminating direct `QWidget` usage.

## Risk Register

| Risk | Mitigation |
| --- | --- |
| Circular imports from re-exporting widgets | Keep exports explicit, move shared code to small dependency-light modules, test import-only behavior |
| Visual drift after replacing local widgets | Preserve labels/object names/tooltips and add pytest-qt smoke checks for touched surfaces |
| Hidden behavior change in path pickers | Verify default directories, filters, Cancel behavior, settings keys, and project-root writes |
| Worker/UI boundary regression | Require signal-only worker communication and focused tests for progress/error/finished paths |
| Over-wrapping Qt widgets | Use the promotion decision tree and record intentionally local patterns |
| Broad migration becomes unreviewable | Stop after one slice and one focused surface group unless explicitly directed |

## Progress Log

### 2026-05-12 - Plan Created

- Status: active.
- Files changed: `docs/agent/exec-plans/active/shared-gui-component-layer.md`.
- Decision: centralize reusable FPVS GUI patterns through
  `Main_App.gui.components` incrementally; do not require every GUI control to
  be wrapped.
- Verification: pending after document creation.

### 2026-05-12 - Plan Hardened For Agent Execution

- Status: active.
- Files changed: `docs/agent/exec-plans/active/shared-gui-component-layer.md`.
- Decision: added hard invariants, component hub contract, promotion decision
  tree, slice status rules, blocker rules, per-slice requirements, inventory
  commands, DoD gates, progress-log format, and risk register.
- Behavior preserved: this is a planning update only; no runtime behavior,
  project I/O, generated data, or GUI flow changes are scoped.
- Verification: document consistency review complete; implementation
  verification remains pending for Slice 0.
- Next slice: `0. Inventory shared and duplicated UI patterns`.

### 2026-05-15 - Slice 0 Inventory Complete

- Status: complete.
- Slice number and name: `0. Inventory shared and duplicated UI patterns`.
- Files changed:
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-inventory.md`.
- Behavior preserved: no production code changes; no runtime GUI behavior,
  worker behavior, project I/O, processing order, generated data, or export
  formats changed.
- Public API changes: none.
- Tests added or updated: none; Slice 0 is inventory-only.
- Commands run with PASS/FAIL result:
  - PASS: `python .agents/scripts/audit/agent_audit.py`
  - PASS: `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - PASS: `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - PASS: `python -m pytest tests/gui/test_ui_components_smoke.py -q`
  - PASS: `rg "from Main_App\\.gui\\.components|from Main_App\\.gui\\.widgets" src/Main_App/gui src/Tools -g "*.py"`
  - PASS: `rg "QAction|QMessageBox|QFileDialog|QProgressDialog|statusBar\\(|setStyleSheet|setObjectName" src/Main_App/gui src/Tools -g "*.py"`
  - PASS: `rg "customtkinter|CustomTkinter|tkinter" src -g "*.py"`; matches were standalone/quarantine references, not active GUI imports.
  - PASS: `rg "Main_App\\.Legacy_App|Tools\\.SourceLocalization|Main_App\\.PySide6_App" src -g "*.py"`; no active matches returned.
- Verification gates result:
  - PASS: imports resolve on Windows through component smoke tests.
  - PASS - not touched: threading and worker behavior.
  - PASS - not touched: UI integrity and DPI.
  - PASS: legacy boundaries preserved by agent audit and retired-path search.
  - PASS: project-path discipline preserved by path audit.
  - PASS - not touched: error UX and logging.
  - PASS - not touched: static hygiene beyond docs edits.
  - PASS - not touched: edge cases.
  - PASS - not touched: resource cleanup.
  - PASS - not touched: Excel/CSV behavior.
- Blockers or risks: no blocker. Inventory identified high-risk future work in
  Stats UI, Ratio Calculator run/path workflow, and Plot Generator
  output-sensitive behavior; these should stay in focused future-plan slices.
- Next slice: `1. Document component hub contract`.

### 2026-05-15 - Slice 1 Component Hub Contract Complete

- Status: complete.
- Slice number and name: `1. Document component hub contract`.
- Files changed:
  `docs/agent/architecture/gui.md`,
  `docs/agent/agent-index.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`.
- Behavior preserved: docs-only change; no runtime GUI behavior, worker
  behavior, project I/O, processing order, generated data, or export formats
  changed.
- Public API changes: none.
- Tests added or updated: none; Slice 1 is documentation-only.
- Commands run with PASS/FAIL result:
  - PASS: `python .agents/scripts/audit/agent_audit.py`
  - PASS: `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - PASS: `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - PASS: `python -m pytest tests/gui/test_ui_components_smoke.py -q`
- Manual verification:
  - PASS: reviewed `docs/agent/architecture/gui.md` and confirmed it documents
    the canonical `Main_App.gui.components` import rule, direct Qt composition
    rule, promotion decision tree, retired-path boundaries, `QAction` import
    rule, worker/signal boundary, project-path discipline, and error UX/logging
    expectations.
  - PASS: reviewed `docs/agent/agent-index.md` and confirmed the GUI skill row
    and execution-plan note point agents to the component hub plan before
    reusable GUI primitive work.
  - PASS: reviewed `git diff --stat` and focused diff; changes were limited to
    agent docs and the active plan.
- Verification gates result:
  - PASS: imports resolve on Windows through component smoke tests.
  - PASS - not touched: threading and worker behavior.
  - PASS - not touched: UI integrity and DPI.
  - PASS: legacy boundaries preserved by agent audit.
  - PASS: project-path discipline preserved by path audit.
  - PASS - not touched: runtime error UX and logging.
  - PASS - not touched: static hygiene beyond docs edits.
  - PASS - not touched: edge cases.
  - PASS - not touched: resource cleanup.
  - PASS - not touched: Excel/CSV behavior.
- Blockers or risks: no blocker. Future implementation slices must still avoid
  broad migrations and use the Slice 0 inventory to keep Stats, Ratio
  Calculator, and Plot Generator changes focused.
- Next slice: `2. Normalize component exports`.

### 2026-05-16 - Slice 2 Verification Boundary Correction

- Status: Slice 2 remains in progress.
- Slice number and name: `2. Normalize component exports`.
- Files changed:
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`,
  `docs/agent/quality/verification-gates.md`.
- Behavior preserved: docs-only safety update; no runtime GUI behavior, worker
  behavior, project I/O, processing order, generated data, or export formats
  changed.
- Public API changes: none in this safety update.
- Tests added or updated: none in this safety update.
- Commands run with PASS/FAIL result:
  - FAIL: broad consumer import probe with
    `Main_App.gui.ui_main`, Settings, Plot Generator, Ratio Calculator, Stats,
    Image Resizer, Individual Detectability, and Advanced Averaging modules
    ran too long and was interrupted. This was not an appropriate component
    layer gate.
  - FAIL: a narrower global-Python consumer import probe stopped on pre-existing
    missing optional dependencies (`mne`, then `psutil`) before proving the
    component export contract.
  - PASS: leftover Python processes from the interrupted probe were stopped.
- Verification gates result:
  - PASS: command-boundary guidance now says to avoid broad GUI/tool import
    sweeps for component-layer verification.
  - PASS: Slice 2 checks now require the component import style to remain
    available, not broad app/tool module imports.
- Blockers or risks: broad GUI/tool imports can cascade into optional scientific
  dependencies and long-running initialization unrelated to the component layer.
  Future verification should use `tests/gui/test_ui_components_smoke.py`,
  `py_compile` of touched component modules, skill audits, and a narrow
  `Main_App.gui.components` subprocess import check.
- Next slice: continue `2. Normalize component exports` with bounded checks.

### 2026-05-16 - Slice 2 Normalize Component Exports Complete

- Status: complete.
- Slice number and name: `2. Normalize component exports`.
- Files changed:
  `src/Main_App/gui/components/__init__.py`,
  `src/Main_App/gui/components/messages.py`,
  `tests/gui/test_ui_components_smoke.py`,
  `docs/agent/architecture/gui.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-inventory.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`.
- Behavior preserved: no GUI surface migration; no runtime GUI workflow,
  worker behavior, project I/O, processing order, generated data, or export
  formats changed.
- Public API changes: `Main_App.gui.components.__all__` is now the explicit
  public export tuple for reusable FPVS GUI primitives. Existing component
  import names remain available.
- Tests added or updated:
  `tests/gui/test_ui_components_smoke.py` now checks the explicit export tuple,
  direct consumer import style, and side-effect-free `Main_App.gui.components`
  import behavior in a narrow subprocess.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m pytest tests/gui/test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\components\__init__.py src\Main_App\gui\components\actions.py src\Main_App\gui\components\messages.py src\Main_App\gui\components\surfaces.py src\Main_App\gui\widgets\buttons.py src\Main_App\gui\widgets\cards.py src\Main_App\gui\widgets\forms.py src\Main_App\gui\widgets\status.py tests\gui\test_ui_components_smoke.py`
  - PASS: `$env:PYTHONPATH='src'; .venv1\Scripts\python.exe -c "from PySide6.QtWidgets import QApplication; assert QApplication.instance() is None; import Main_App.gui.components as components; assert QApplication.instance() is None; assert components.__all__[0] == 'ActionRow'; print('component import side effects ok')"`
  - PASS: `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - PASS: `python .agents/scripts/audit/agent_audit.py`
  - PASS: `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - PASS: `.venv1\Scripts\python.exe -m ruff check src\Main_App\gui\components\__init__.py src\Main_App\gui\components\messages.py tests\gui\test_ui_components_smoke.py`
- Verification gates result:
  - PASS: imports resolve on Windows through component smoke tests and narrow
    component subprocess import.
  - PASS - not touched: threading and worker behavior.
  - PASS - not touched: UI integrity and DPI beyond existing component smoke
    coverage.
  - PASS: legacy boundaries preserved by agent audit.
  - PASS: project-path discipline preserved by path audit.
  - PASS - not touched: runtime error UX and logging.
  - PASS: static hygiene covered by `py_compile` and narrow `ruff check`.
  - PASS - not touched: edge cases outside the import/export contract.
  - PASS - not touched: resource cleanup; no workers or windows started.
  - PASS - not touched: Excel/CSV behavior.
- Blockers or risks: no blocker. Avoid broad app/tool import sweeps for this
  plan; they are not needed to prove the component export contract.
- Next slice: `3. Consolidate action and message patterns`.

### 2026-05-16 - Slice 3 Action Row Consolidation Complete

- Status: complete.
- Slice number and name: `3. Consolidate action and message patterns`.
- Files changed:
  `src/Tools/Image_Resizer/pyside_resizer.py`,
  `tests/gui/test_image_resizer_gui.py`,
  `docs/agent/architecture/gui.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-inventory.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`.
- Behavior preserved: Image Resizer button labels, button order, button
  variants, initial enabled states, and signal connections are unchanged. No
  image resizing behavior, worker/thread behavior, file dialog behavior,
  project I/O, processing order, generated data, or export format changed.
- Public API changes: none.
- Tests added or updated:
  `tests/gui/test_image_resizer_gui.py` now asserts the actions panel uses
  `ActionRow` and preserves the `Process`, `Cancel`, and `Open Folder` button
  labels, variants, and initial enabled states.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m pytest tests/gui/test_image_resizer_gui.py tests/gui/test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Image_Resizer\pyside_resizer.py tests\gui\test_image_resizer_gui.py`
  - PASS: `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - PASS: `python .agents/scripts/audit/agent_audit.py`
  - PASS: `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - PASS: `.venv1\Scripts\python.exe -m ruff check src\Tools\Image_Resizer\pyside_resizer.py tests\gui\test_image_resizer_gui.py src\Main_App\gui\components\__init__.py src\Main_App\gui\components\messages.py tests\gui\test_ui_components_smoke.py`
- Verification gates result:
  - PASS: imports resolve on Windows through focused GUI/component smoke tests
    and `py_compile`.
  - PASS: threading is safe; the slice did not change worker construction,
    signal wiring to worker progress/finished, or thread cleanup.
  - PASS: UI integrity preserved; the existing actions card still contains the
    same three buttons in one row.
  - PASS: legacy boundaries preserved by agent audit.
  - PASS: project-path discipline preserved by path audit; no path behavior was
    touched.
  - PASS: error UX and logging preserved; message helper calls were already in
    place and were not changed.
  - PASS: static hygiene covered by `py_compile` and narrow `ruff check`.
  - PASS: edge cases preserved; cancel/open buttons remain disabled initially.
  - PASS - not touched: resource cleanup and worker lifetime.
  - PASS - not touched: Excel/CSV behavior.
- Blockers or risks: no blocker. Larger action/message migrations remain
  future work and should use the Image Resizer row as the low-risk pattern.
- Next slice: `4. Consolidate section/status/path patterns`.

### 2026-05-16 - Slice 4 Section Path Status Contracts Complete

- Status: complete.
- Slice number and name: `4. Consolidate section/status/path patterns`.
- Files changed:
  `src/Tools/Image_Resizer/pyside_resizer.py`,
  `src/Tools/Individual_Detectability/main_window.py`,
  `tests/gui/test_image_resizer_gui.py`,
  `tests/gui/test_individual_detectability_gui_smoke.py`,
  `docs/agent/architecture/gui.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-inventory.md`,
  `docs/agent/exec-plans/active/shared-gui-component-layer-updated.md`.
- Behavior preserved: no visible section headings or order changed; no file
  dialog titles, filters, defaults, Cancel behavior, path writes, worker
  behavior, project I/O, generated data, or export formats changed.
- Public API changes: none.
- Tests added or updated:
  `tests/gui/test_image_resizer_gui.py` and
  `tests/gui/test_individual_detectability_gui_smoke.py` now assert stable
  shared path/status object names, status text and variant, and file-dialog
  Cancel no-op behavior for Image Resizer and Individual Detectability.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m pytest tests/gui/test_image_resizer_gui.py tests/gui/test_individual_detectability_gui_smoke.py tests/gui/test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Image_Resizer\pyside_resizer.py src\Tools\Individual_Detectability\main_window.py tests\gui\test_image_resizer_gui.py tests\gui\test_individual_detectability_gui_smoke.py`
  - PASS: `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - PASS: `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - PASS: `python .agents/scripts/audit/agent_audit.py`
  - PASS: `.venv1\Scripts\python.exe -m ruff check src\Tools\Image_Resizer\pyside_resizer.py src\Tools\Individual_Detectability\main_window.py tests\gui\test_image_resizer_gui.py tests\gui\test_individual_detectability_gui_smoke.py`
- Verification gates result:
  - PASS: imports resolve on Windows through focused GUI/component smoke tests
    and `py_compile`.
  - PASS: threading is safe; worker creation, worker signal wiring, and worker
    lifetime were not changed.
  - PASS: UI integrity preserved; shared path/status widgets now have stable
    object names and existing sections remain present.
  - PASS: legacy boundaries preserved by agent audit.
  - PASS: project-path discipline preserved by path audit and Cancel no-op
    tests.
  - PASS: error UX and logging preserved; message behavior was not changed.
  - PASS: static hygiene covered by `py_compile` and narrow `ruff check`.
  - PASS: edge cases covered for file-dialog Cancel no-op behavior.
  - PASS - not touched: resource cleanup and worker lifetime.
  - PASS - not touched: Excel/CSV behavior.
- Blockers or risks: no blocker. Ratio Calculator, Plot Generator, Stats, and
  Epoch Averaging path/status migrations remain future focused work and should
  preserve their tool-specific path defaults and worker behavior.
- Next slice: `5. Add coverage for component contracts`.
