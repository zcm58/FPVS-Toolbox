# Verification Gates

Use the narrowest executable gate that can prove the change first, then broaden when the change touches shared behavior. Prefer skill-local scripts over manually reading broad folders.

For a compact command map, use `docs/agent/agent-index.md`.

## Command Boundaries

- Do not run exploratory commands without a bounded timeout. Use short bounds
  for import probes and audits, and stop rather than letting a command run
  indefinitely.
- Avoid broad "import every GUI/tool module" sweeps as verification. GUI imports
  can cascade into optional analysis dependencies, windows, process launchers,
  or slow scientific library initialization.
- Prefer targeted pytest files, skill-local audits, `py_compile`, and narrow
  subprocess import probes for the exact public API being changed.
- If an import probe exceeds its expected runtime or reaches an unrelated
  optional dependency failure, stop and report the attempted command, first
  failing module, and safer replacement check.
- Do not combine many high-risk imports into one long process. Probe one import
  surface or one small module group at a time so failures are attributable and
  interruptible.
- Do not run offscreen Qt workflows in this repo. Do not set
  `QT_QPA_PLATFORM=offscreen`, do not run pytest-qt/offscreen GUI tests, and do
  not launch ad-hoc offscreen Qt scripts; they can freeze or hang indefinitely
  in this Windows environment. For GUI work, use non-GUI checks plus a
  documented visible/manual smoke path unless the user explicitly approves a
  safe visible GUI test environment.

## Standard Commands

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/scripts/audit/agent_audit.py --check garbage-collection
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python -m pytest -q
ruff check .
```

## Targeted Checks

- GUI changes: do not run pytest-qt/offscreen tests locally. Use `py_compile`,
  focused `ruff`, `audit_gui_imports.py`, and `agent_audit.py --check gui`;
  document the visible/manual smoke path for behavior that requires a window.
- Project path or file I/O changes: add or run tests with `tmp_path`; do not depend on a developer machine path.
- Legacy-boundary changes: activate `.\.venv1`, then run `python .agents/scripts/audit/agent_audit.py --check protected` and confirm retired `Legacy_App` paths were not recreated; any historical behavior cleanup must preserve the processing pipeline.
- Source Localization/eLORETA changes: activate `.\.venv1`, then run `python .agents/scripts/audit/agent_audit.py --check source-localization`; it should remain removed from active runtime unless explicitly restored.
- Processing pipeline changes: verify processing order, output filenames, sheets, and formats remain compatible.
- Garbage collection: activate `.\.venv1`, then run `python .agents/scripts/audit/agent_audit.py --check garbage-collection` to catch visible cache/temp artifacts, new inline debt markers, and broad production exception handlers.

## Reporting Failures

If a command cannot run, report:

- exact command attempted;
- failure reason or first relevant error;
- whether the failure appears related to the change;
- residual risk.
