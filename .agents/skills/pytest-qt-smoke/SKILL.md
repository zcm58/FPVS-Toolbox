---
name: pytest-qt-smoke
description: Use when adding or updating pytest-qt smoke tests for changed PySide6 widgets, dialogs, signals, controller bindings, worker signals, enabled states, tooltips, status text, or non-blocking UI behavior.
---

# Pytest-Qt Smoke

## Overview

Use this workflow when a GUI change needs lightweight coverage. Prefer a smoke test that proves the widget can be instantiated and that the changed signal, state, or text path works.

## Workflow

1. Read `AGENTS.md`, `ARCHITECTURE.md`, and the nearest existing pytest-qt tests in `tests/`.
2. Instantiate the changed widget or window with the smallest practical setup.
3. Register widgets with `qtbot.addWidget`.
4. Use fake controllers, lightweight payloads, or signals instead of real processing.
5. Emit or click the relevant signal path.
6. Assert visible labels, enabled states, checked states, tooltips, status text, or emitted signals.
7. Avoid real file I/O unless using `tmp_path`.
8. Avoid depending on protected legacy internals.
9. Keep the test deterministic and focused on the changed behavior.

## Checks

- Confirm the test fails or would have failed for the original bug when practical.
- Confirm the test does not start real long-running processing.
- Run the new or changed test directly before broader pytest.

## Response Requirements

- Name the smoke test added or updated.
- State what GUI behavior it proves.
- Include verification commands and results.
- If no automated smoke test was added, document manual smoke steps and the reason.
