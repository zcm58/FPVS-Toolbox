---
name: pytest-qt-smoke
description: Use when defining CI-only pytest-qt smoke coverage for a changed FPVS Toolbox desktop workflow or shared PySide6 component.
---

# Pytest-Qt Smoke

## Define focused coverage

- Read the owning tool's scoped `AGENTS.md` and the nearest existing smoke
  coverage. Test one changed user action or component contract through its
  normal entry point. Assert the visible state, accessible controls, emitted
  signals, or failure/cancellation behavior that matters to the task.
- Use existing Qt fixtures, lightweight test inputs, and fake work at the
  backend boundary. Wait for the relevant signal or state. Keep real file
  operations inside `tmp_path` and backend assertions runnable without Qt.
- Register each Qt-dependent test module in
  [tests/qt_test_files.txt](../../../tests/qt_test_files.txt). The registry
  guards imports before collection. Include new tests in their owning scope
  or existing CI workflow where needed.

## Verify locally and in CI

Run non-GUI checks with the smallest affected
[focused scope](../../../docs/agent/quality/test-selection.md#scope-map), using
`gui` for shared desktop workflows. Use `--list` to preview selected commands.
After registry changes, run `python .agents/scripts/verify.py --check-config`.

The configured [CI Qt job](../../../.github/workflows/python-package.yml) runs
registered widget tests. Local Qt execution requires explicit user approval for
a safe visible environment. Never run offscreen Qt locally, including through
`QT_QPA_PLATFORM=offscreen`. The
[verification gates](../../../docs/agent/quality/verification-gates.md#command-boundaries)
own this distinction.

Record a visible smoke path in the applicable verification scope. Include the
starting state, the user action, and its expected result. For layout changes,
cover the relevant 1200 × 800 shell and 1280 × 900 workspace checks. Report
which tests ran, which are defined for CI, and any pending visible checks.
