# Development Notes

Use this page for local setup, release notes, and validation commands that are
not part of the end-user documentation.

## Local Environment

Use `.\.venv1` as the canonical repository virtual environment on development
machines. Recreate it locally from that machine's Python interpreter rather
than reusing a copied virtual environment from another computer:

```powershell
python -m venv .venv1
```

Install dependencies with:

```powershell
.\.venv1\Scripts\python.exe -m pip install -r requirements.txt
```

If PyCharm or another IDE reports that it did not find the executable, repoint
the project interpreter to `.\.venv1\Scripts\python.exe` and remove stale
references to other virtual environments.

For validation commands, set `PYTHONNOUSERSITE=1` when you need to ensure tests
and import checks do not fall back to user-site packages from the global Python
installation.

## Versioning

The toolbox version is defined in `config.py` as `FPVS_TOOLBOX_VERSION`.
Scripts that need the version should import that constant rather than hard
coding a string.

```python
from config import FPVS_TOOLBOX_VERSION

cmd = ["pyinstaller", "-n", f"FPVS_Toolbox_{FPVS_TOOLBOX_VERSION}", ...]
```

Updating `FPVS_TOOLBOX_VERSION` is the release version bump.

## Packaging

Releases provide an Inno Setup installer. Running the installer creates a
folder containing `FPVS_Toolbox.exe`, required DLLs, and configuration files.

Build scripts should locate the repository root automatically before running
PyInstaller so they work even if launched from another directory.

## Configuration

The app interface uses constants in `config.py` for release metadata, update
URLs, and selected sizing values. Keep user-visible workflow behavior in the
PySide6 application layer; avoid scattering release or UI constants across
tool modules.

The update check is controlled by:

- `FPVS_TOOLBOX_VERSION`: current running version.
- `FPVS_TOOLBOX_UPDATE_API`: URL queried for the latest release.
- `FPVS_TOOLBOX_REPO_PAGE`: repository or release page opened for updates.

## Debug Logging

The toolbox routes messages through Python's `logging` module. At startup the
MNE-Python logger is set to `WARNING` to reduce output. Enable **Debug** mode
in the settings window and restart the application to raise the global log
level to `DEBUG`. When debug mode is active, the MNE logger is increased to
`INFO` so detailed processing information is visible.

## Validation

Use the narrowest relevant check first. See `docs/quality/test-selection.md`
for pytest marker guidance and focused test commands.

Common gates:

```powershell
python scripts/agent_audit.py
python -m pytest -q
ruff check .
mypy src --strict
```
