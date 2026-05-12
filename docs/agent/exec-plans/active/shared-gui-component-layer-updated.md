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
| 0. Inventory shared and duplicated UI patterns | Pending | Inventory of current component exports, direct widget helpers, duplicated FPVS-specific patterns, current users, risk-ranked migration candidates, and intentionally local patterns | Agent audit; GUI import audit; targeted `rg`; no code changes |
| 1. Document component hub contract | Pending | `docs/agent/architecture/gui.md` and nearest agent guidance updated with import rules, promotion decision tree, invariants, and examples | Agent audit; docs review; no runtime code changes |
| 2. Normalize component exports | Pending | Stable exports from `Main_App.gui.components`; no import side effects; compatibility shims where needed; component smoke tests | `python -m pytest tests/gui/test_ui_components_smoke.py -q`; GUI import audit; import cycle check |
| 3. Consolidate action and message patterns | Pending | Opportunistic migration of touched surfaces to shared action rows/buttons/message helpers while preserving labels, shortcuts, object names, enabled states, and signal wiring | Focused pytest-qt smoke tests for touched surfaces; re-entrancy and Cancel checks |
| 4. Consolidate section/status/path patterns | Pending | Opportunistic migration of touched surfaces to shared cards/status/path-picker helpers while preserving project-root behavior and file dialog semantics | Focused pytest-qt smoke tests; project-path audit when file paths are touched |
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
- Existing consumers still import successfully.
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
