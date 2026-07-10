---
name: pytest-qt-smoke
description: Use when defining CI-only pytest-qt smoke coverage for changed PySide6 widgets, dialogs, signals, controller bindings, worker signals, enabled states, tooltips, status text, or non-blocking UI behavior.
---

# Pytest-Qt Smoke

## Overview

Use this workflow when a GUI change needs lightweight coverage definitions.
PySide6/pytest-qt execution is CI-only by default. Run it locally only when the
user explicitly approves a safe visible GUI environment.

## Workflow

1. Let `.agents/scripts/verify.py` select `.venv1` or `.venv` for local checks.
2. Read `AGENTS.md`, `ARCHITECTURE.md`, `docs/agent/agent-index.md`, and the nearest existing pytest-qt tests in `tests/`.
3. Add or update the smallest practical pytest-qt smoke test when useful for
   future CI or manual GUI verification.
4. Register the test in `tests/qt_test_files.txt` and leave execution to the
   configured CI Qt job. Do not set `QT_QPA_PLATFORM=offscreen` locally.
5. Use fake controllers, lightweight payloads, or signals instead of real processing.
6. Assert visible labels, enabled states, checked states, tooltips, status text, or emitted signals.
7. Avoid real file I/O unless using `tmp_path`.
8. Avoid depending on protected legacy internals.
9. Keep the test deterministic and focused on the changed behavior.

## Checks

- Confirm the test would have failed for the original bug when practical by
  inspecting the assertion and changed code path.
- Confirm the test does not start real long-running processing.
- Verify locally with `python .agents/scripts/verify.py --scope gui --tier
  focused` and the visible/manual smoke path.

## Response Requirements

- Name the smoke test added or updated.
- State what GUI behavior it proves.
- Include verification commands and results.
- Name the CI Qt coverage and include visible/manual smoke steps used locally.
