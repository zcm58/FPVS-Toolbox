---
name: pyside6-gui-cleanup
description: Use for FPVS Toolbox PySide6 desktop layouts, shared widgets, actions, theme usage, worker wiring, and UI copy.
---

# PySide6 GUI Cleanup

## Work on the owning surface

Use the existing `.venv1` or `.venv` from the
[development guide](../../../docs/agent/guides/development.md#local-environment).
Run the import audit before broad inspection.

```console
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
```

Start with the affected tool's scoped `AGENTS.md` and the
[Toolbox product scope](../../../docs/agent/product-specs/fpvs-toolbox.md).
Keep the edit within the owning page, dialog, controller, or component. The
`main_window.py` shell requires explicit scope for added functions or refactors.
Preserve existing workflows, test-facing object names, processing order, and
formats unless the task changes them.

- Use PySide6, import `QAction` from `PySide6.QtGui`, and reuse tokens and
  building blocks from `Main_App.gui.components`. Use shared
  `SubsectionHeaderLabel` styling and flat sections.
  [GUI layout and components](../../../docs/agent/architecture/gui.md#visual-layout-rules)
- Keep the 1200 × 800 shell minimum. New or substantially revised embedded
  pages must fit the 1280 × 900 workspace without page-level scrolling. Check
  that controls remain reachable at 1200 × 800. Split controls into tabs or
  pages when space is tight. Tables, text viewers, and focused dialogs can
  scroll within their bounds.
- Use copy that helps users interpret evidence, make a choice, act, or recover.
  Omit text that repeats headings, labels, or routine feedback. Keep meaningful
  uncertainty and missing-data states visible, with methods and provenance in
  details when needed.
- Keep prompts, navigation, and worker lifetimes in the desktop. Pass choices as
  ordinary Python values to the project, processing, or tool backend. Reuse the
  signal-driven `QThread` or `QRunnable`/`QThreadPool` path for long work and
  keep widgets on the GUI thread. Use structured logging for diagnostics.
  [Workflow ownership](../../../docs/agent/architecture/gui-backend.md)

For hardware, montage, or Studio controls, use the backend-resolved capabilities
and preserve the locked processing order. [Shared roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)

## Verify the workflow

Use the affected [focused scope](../../../docs/agent/quality/test-selection.md#scope-map)
for local static and backend checks. Use `gui` for shared desktop surfaces.

```console
python .agents/scripts/verify.py --scope gui --tier focused
```

Use [pytest-qt-smoke](../pytest-qt-smoke/SKILL.md) when the change needs Qt
coverage. Local Qt execution requires explicit approval for a safe visible
environment. Never use offscreen Qt locally. Document the visible workflow and
report the verification results and any pending GUI checks.
