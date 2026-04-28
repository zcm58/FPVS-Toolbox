# Project I/O Architecture

Project-aware workflows should resolve paths from the active project root, not from the process current directory or a developer-machine path.

Primary paths:

- `src/Main_App/PySide6_App/Backend/project.py`
- `src/Main_App/PySide6_App/Backend/project_manager.py`
- `src/Main_App/PySide6_App/Backend/project_metadata.py`
- `src/Main_App/PySide6_App/config/projects_root.py`
- tool modules that import, export, or generate files under `src/Tools/`

Rules:

- Preserve existing output formats, filenames, sheet names, and folder layout unless explicitly asked to change them.
- Use `tmp_path` in tests instead of hard-coded local paths.
- Handle `QFileDialog` Cancel without exceptions or stale UI state.
- Treat repeated operations and existing output files as normal user behavior.

Useful checks:

```powershell
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python scripts/agent_audit.py --check paths
python -m pytest tests/test_project_settings_roundtrip.py tests/test_project_results_layout.py -q
```

Run the skill-local script before manually searching for hard-coded paths across the repo.
