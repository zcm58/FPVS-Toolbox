# Project I/O Architecture

Project-aware workflows should resolve paths from the active project root, not from the process current directory or a developer-machine path.

Primary paths:

- `src/Main_App/projects/` is the canonical active import surface for project
  model, metadata, manager, projects-root, and preprocessing-settings behavior.
  It owns those implementations.
- `src/Main_App/Shared/settings_paths.py`
- tool modules that import, export, or generate files under `src/Tools/`

## Settings Storage

FPVS Toolbox uses a strict hybrid settings model:

- App-level settings use `FPVS_CONFIG_HOME` when set, otherwise the user-writable app config root under `%LOCALAPPDATA%\FPVS Toolbox\settings\` on Windows.
- `Main_App.Shared.settings_manager.SettingsManager` is the single active writer for app-level settings.
- Project-specific settings stay in the active project's `project.json`.
- `%APPDATA%\FPVS_Toolbox\*.ini` files and old Qt `QSettings` locations are legacy migration inputs only; do not add new writers there.
- Do not write settings to the install directory, repo directory, `Program Files`, or the process current working directory.

Rules:

- Preserve existing output formats, filenames, sheet names, and folder layout unless explicitly asked to change them.
- Active callers should import project model/settings/manager helpers through
  `Main_App.projects`.
- Use `tmp_path` in tests instead of hard-coded local paths.
- Handle `QFileDialog` Cancel without exceptions or stale UI state.
- Treat repeated operations and existing output files as normal user behavior.
- File-selection dialogs must use PySide6 `QFileDialog`. Single-file mode accepts only `.bdf` files inside the active project's input folder and updates `data_paths`, `_selected_bdf`, the input line edit, logs, and Start enabled state without changing project paths.
- User-facing warnings/errors must use PySide6-safe message helpers, not Tk dialogs. Worker/background callers should log rather than block on a GUI popup.

Useful checks:

```powershell
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/scripts/audit/agent_audit.py --check paths
python -m pytest tests/project_io/test_project_settings_roundtrip.py tests/project_io/test_project_results_layout.py -q
```

Run the skill-local script before manually searching for hard-coded paths across the repo.
