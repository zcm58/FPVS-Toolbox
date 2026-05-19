# GUI Change Prompt Template

Use `$pyside6-gui-cleanup`. Use `$pytest-qt-smoke` only to update smoke test
coverage; do not run pytest-qt/offscreen GUI tests locally.

Goal: change only the requested PySide6 GUI behavior.

Checks:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/scripts/audit/agent_audit.py --check gui
python -m py_compile <changed Python files>
ruff check <changed Python files>
```

Requirements:

- Preserve existing user flows, processing order, project paths, and export formats.
- Avoid card-within-card layouts unless the user explicitly asks for them.
  `SectionCard` should frame a top-level subsection; parent tab pages,
  splitters, and setup containers should stay visually flat when they contain
  subsection cards.
- Keep long work off the UI thread; use `QThread` or `QRunnable`/`QThreadPool` for long work.
- Workers must not touch widgets directly; communicate through signals.
- Import `QAction` from `PySide6.QtGui` only.
- Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports.
- Do not set `QT_QPA_PLATFORM=offscreen`, run pytest-qt/offscreen GUI tests, or
  launch ad-hoc offscreen Qt scripts. Document visible/manual smoke steps for
  GUI behavior that cannot be verified with non-GUI checks.
