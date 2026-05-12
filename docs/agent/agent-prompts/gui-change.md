# GUI Change Prompt Template

Use `$pyside6-gui-cleanup` and `$pytest-qt-smoke`.

Goal: change only the requested PySide6 GUI behavior.

Checks:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/scripts/audit/agent_audit.py --check gui
python -m pytest <nearest pytest-qt test> -q
```

Requirements:

- Preserve existing user flows, processing order, project paths, and export formats.
- Keep long work off the UI thread; use `QThread` or `QRunnable`/`QThreadPool` for long work.
- Workers must not touch widgets directly; communicate through signals.
- Import `QAction` from `PySide6.QtGui` only.
- Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports.
- Add or update a pytest-qt smoke test, or document manual smoke steps when automation is not practical.
