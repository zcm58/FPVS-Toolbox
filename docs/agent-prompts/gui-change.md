# GUI Change Prompt Template

Use `$pyside6-gui-cleanup` and `$pytest-qt-smoke`.

Goal: change only the requested PySide6 GUI behavior.

Checks:

```powershell
python scripts/agent_audit.py --check gui
python -m pytest <nearest pytest-qt test> -q
```

Requirements:

- Preserve existing user flows and processing order.
- Keep long work off the UI thread.
- Add or update a pytest-qt smoke test, or document manual smoke steps.
