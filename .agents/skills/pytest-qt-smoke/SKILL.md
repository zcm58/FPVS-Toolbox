---
name: pytest-qt-smoke
description: Use when adding or updating pytest-qt smoke tests for changed PySide6 widgets, dialogs, signals, controller bindings, worker signals, enabled states, tooltips, status text, or non-blocking UI behavior.
---

# Pytest-Qt Smoke

## Overview

Use this workflow when a GUI change needs lightweight coverage. Prefer a smoke test that proves the widget can be instantiated and that the changed signal, state, or text path works.

## Workflow

1. Activate `.\.venv1` or use `.\.venv1\Scripts\python.exe` for Python commands.
2. Read `AGENTS.md`, `ARCHITECTURE.md`, `docs/agent/agent-index.md`, and the nearest existing pytest-qt tests in `tests/`.
3. Instantiate the changed widget or window with the smallest practical setup.
4. Register widgets with `qtbot.addWidget`.
5. Use fake controllers, lightweight payloads, or signals instead of real processing.
6. Emit or click the relevant signal path.
7. Assert visible labels, enabled states, checked states, tooltips, status text, or emitted signals.
8. Avoid real file I/O unless using `tmp_path`.
9. Avoid depending on protected legacy internals.
10. Keep the test deterministic and focused on the changed behavior.

## Checks

- Confirm the test fails or would have failed for the original bug when practical.
- Confirm the test does not start real long-running processing.
- Run the new or changed test directly before broader pytest.

## Response Requirements

- Name the smoke test added or updated.
- State what GUI behavior it proves.
- Include verification commands and results.
- If no automated smoke test was added, document manual smoke steps and the reason.
