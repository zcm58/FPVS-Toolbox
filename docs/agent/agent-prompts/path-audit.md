# Path Audit Prompt Template

Use `$project-path-audit`.

Goal: review or change project-root file I/O without changing data formats.

Checks:

```powershell
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/scripts/audit/agent_audit.py --check paths
python -m pytest <nearest project/path tests> -q
```

Requirements:

- Use active project-root-relative paths and the active `Main_App.projects` import surface for project model/settings/manager behavior.
- Preserve existing output formats, filenames, sheet names, folder layouts, and repeated-operation behavior unless explicitly asked to change them.
- Handle `QFileDialog` Cancel and repeated operations without stale UI state.
- Use PySide6-safe message helpers for user-facing warnings/errors; worker/background callers should log rather than block on popups.
- Use `tmp_path` for tests instead of hard-coded local paths.
