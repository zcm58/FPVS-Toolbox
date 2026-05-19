---
name: pytest-qt-smoke
description: Use when adding or updating pytest-qt smoke tests for changed PySide6 widgets, dialogs, signals, controller bindings, worker signals, enabled states, tooltips, status text, or non-blocking UI behavior.
---

# Pytest-Qt Smoke

## Overview

Use this workflow when a GUI change needs lightweight coverage definitions.
In this repo, do not execute pytest-qt/offscreen GUI tests locally unless the
user explicitly approves a safe visible GUI test environment.

## Workflow

1. Activate `.\.venv1` or use `.\.venv1\Scripts\python.exe` for Python commands.
2. Read `AGENTS.md`, `ARCHITECTURE.md`, `docs/agent/agent-index.md`, and the nearest existing pytest-qt tests in `tests/`.
3. Add or update the smallest practical pytest-qt smoke test when useful for
   future CI or manual GUI verification.
4. Do not run the pytest-qt/offscreen test locally. Do not set
   `QT_QPA_PLATFORM=offscreen`.
5. Use fake controllers, lightweight payloads, or signals instead of real processing.
6. Assert visible labels, enabled states, checked states, tooltips, status text, or emitted signals.
8. Avoid real file I/O unless using `tmp_path`.
9. Avoid depending on protected legacy internals.
10. Keep the test deterministic and focused on the changed behavior.

## Checks

- Confirm the test would have failed for the original bug when practical by
  inspecting the assertion and changed code path.
- Confirm the test does not start real long-running processing.
- Verify with non-GUI checks instead: `py_compile`, focused `ruff`, GUI import
  audit, and `agent_audit.py --check gui`.

## Response Requirements

- Name the smoke test added or updated.
- State what GUI behavior it proves.
- Include verification commands and results.
- Document that pytest-qt/offscreen execution was skipped locally and include
  visible/manual smoke steps.
