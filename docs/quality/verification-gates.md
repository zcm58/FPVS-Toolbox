# Verification Gates

Use the narrowest executable gate that can prove the change first, then broaden when the change touches shared behavior. Prefer skill-local scripts over manually reading broad folders.

For a compact command map, use `docs/agent-index.md`.

## Standard Commands

```powershell
python scripts/audit/agent_audit.py
python scripts/audit/agent_audit.py --check garbage-collection
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python -m pytest -q
ruff check .
mypy src --strict
```

## Targeted Checks

- GUI changes: run the nearest pytest-qt smoke test, usually a `tests/test_*gui*` or `tests/test_*window*` target.
- Project path or file I/O changes: add or run tests with `tmp_path`; do not depend on a developer machine path.
- Legacy-boundary changes: run `python scripts/audit/agent_audit.py --check protected` and confirm retired `Legacy_App` paths were not recreated; any historical behavior cleanup must preserve the processing pipeline.
- Source Localization/eLORETA changes: run `python scripts/audit/agent_audit.py --check source-localization`; it should remain removed from active runtime unless explicitly restored.
- Processing pipeline changes: verify processing order, output filenames, sheets, and formats remain compatible.
- Garbage collection: run `python scripts/audit/agent_audit.py --check garbage-collection` to catch visible cache/temp artifacts, new inline debt markers, and broad production exception handlers.

## Reporting Failures

If a command cannot run, report:

- exact command attempted;
- failure reason or first relevant error;
- whether the failure appears related to the change;
- residual risk.
