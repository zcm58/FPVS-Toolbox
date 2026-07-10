---
name: pyside6-gui-cleanup
description: Use for Windows-oriented PySide6 GUI cleanup, widget refactors, layout polish, QAction fixes, theme-token usage, worker wiring, and non-blocking status or error UX in FPVS Toolbox.
---

# PySide6 GUI Cleanup

## Overview

Use this workflow when changing PySide6 widgets, dialogs, menus, toolbar actions, layouts, status messages, workers, or theme usage. Keep the cleanup behavior-preserving unless the user explicitly asks for a behavior change.

## Workflow

1. Activate `.\.venv1` or use `.\.venv1\Scripts\python.exe` when that environment exists; otherwise use the `.venv` equivalents.
2. Run `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` before broad manual inspection.
3. Read only the focused docs or files needed by the task or by script failures.
4. Identify the smallest GUI cleanup that satisfies the task.
5. Preserve existing user flows, processing order, object names used by tests, and data formats.
6. Keep UI code separate from processing logic.
7. Use PySide6 only. Do not introduce other GUI toolkits or PyQt.
8. Import `QAction` only from `PySide6.QtGui`.
9. Do not run long work on the UI thread.
10. Use `QThread` or `QRunnable` with `QThreadPool` for long work.
11. Ensure workers emit signals for progress, errors, and completion.
12. Keep workers from reading or mutating widgets directly.
13. Reuse existing style tokens, layout conventions, and status/error UX.
14. Use structured logging for production diagnostics.
15. PySide6/pytest-qt execution is CI-only by default. Do not set
    `QT_QPA_PLATFORM=offscreen` or launch ad-hoc offscreen Qt scripts locally;
    they can freeze in this Windows environment.
16. Add or update registered pytest-qt smoke coverage when useful. Run it
    locally only when the user explicitly approves a safe visible environment.
17. Document the visible/manual smoke path and why automated GUI execution was
    skipped.

## Checks

- Use `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` instead of manually searching all GUI imports.
- Confirm no new `print` calls were added in production code.
- Confirm long-running processing is not started directly from a slot on the UI thread.
- Run local checks through `python .agents/scripts/verify.py --scope gui --tier
  focused`; the driver applies the Qt guard and safe static/import checks.

## Response Requirements

- List exact files changed.
- State verification commands run and results.
- Include visible/manual smoke steps for GUI behavior that was not executed
  locally.
