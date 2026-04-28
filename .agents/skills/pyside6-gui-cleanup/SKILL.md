---
name: pyside6-gui-cleanup
description: Use for Windows-oriented PySide6 GUI cleanup, widget refactors, layout polish, QAction fixes, theme-token usage, worker wiring, and non-blocking status or error UX in FPVS Toolbox.
---

# PySide6 GUI Cleanup

## Overview

Use this workflow when changing PySide6 widgets, dialogs, menus, toolbar actions, layouts, status messages, workers, or theme usage. Keep the cleanup behavior-preserving unless the user explicitly asks for a behavior change.

## Workflow

1. Run `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` before broad manual inspection.
2. Read only the focused docs or files needed by the task or by script failures.
3. Identify the smallest GUI cleanup that satisfies the task.
4. Preserve existing user flows, processing order, object names used by tests, and data formats.
5. Keep UI code separate from processing logic.
6. Use PySide6 only. Do not introduce CustomTkinter or PyQt.
7. Import `QAction` only from `PySide6.QtGui`.
8. Do not run long work on the UI thread.
9. Use `QThread` or `QRunnable` with `QThreadPool` for long work.
10. Ensure workers emit signals for progress, errors, and completion.
11. Keep workers from reading or mutating widgets directly.
12. Reuse existing style tokens, layout conventions, and status/error UX.
13. Use structured logging for production diagnostics.
14. Add or update a pytest-qt smoke test when behavior or wiring changes.
15. If automated GUI coverage is not practical, document the manual smoke path and why.

## Checks

- Use `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` instead of manually searching all GUI imports.
- Confirm no new `print` calls were added in production code.
- Confirm long-running processing is not started directly from a slot on the UI thread.
- Run the narrowest relevant pytest target first, then broaden as risk requires.

## Response Requirements

- List exact files changed.
- State verification commands run and results.
- Include smoke test steps when GUI behavior cannot be fully asserted.
