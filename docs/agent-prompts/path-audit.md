# Path Audit Prompt Template

Use `$project-path-audit`.

Goal: review or change project-root file I/O without changing data formats.

Checks:

```powershell
python scripts/agent_audit.py --check paths
python -m pytest <nearest project/path tests> -q
```

Requirements:

- Use active project-root-relative paths.
- Handle dialog Cancel and repeated operations.
- Use `tmp_path` for tests.
