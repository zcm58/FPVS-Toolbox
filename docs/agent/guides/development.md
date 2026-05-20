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

Before running repo commands in a shell, activate the environment:

```powershell
.\.venv1\Scripts\Activate.ps1
```

After activation, use `python` in command examples. If PyCharm or another IDE
reports that it did not find the executable, repoint the project interpreter to
`.\.venv1\Scripts\python.exe` and remove stale references to other virtual
environments.

For validation commands, set `PYTHONNOUSERSITE=1` when you need to ensure tests
and import checks do not fall back to user-site packages from the global Python
installation.

## Versioning

The toolbox version is defined in `src/config.py` as `FPVS_TOOLBOX_VERSION`.
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
Release packaging definitions live in `scripts/packaging/`.

The supported maintainer workflow is script-driven. Do not open the Inno Setup
GUI for normal releases.

```powershell
.\scripts\packaging\build_release.ps1 -SkipInstall -SkipSmoke
```

Use `-SkipInstall` only when `.\.venv1` already has `requirements.txt`
installed. Omit it when building from a fresh environment. Use
`-InnoCompiler "C:\Path\To\ISCC.exe"` when `ISCC.exe` is not on PATH or in a
standard Inno Setup 6 location.

The release entrypoint calls:

- `scripts/packaging/build_exe.ps1`: builds `dist\FPVS_Toolbox\FPVS_Toolbox.exe`
  with PyInstaller.
- `scripts/packaging/build_installer.ps1`: compiles
  `installers\FPVSToolbox-<version>-setup.exe` with `ISCC.exe`.

Build scripts locate the repository root automatically before running
PyInstaller/Inno so they work even if launched from PyCharm or another working
directory. The Inno script receives the app version from `FPVS_TOOLBOX_VERSION`
through `/DAppVersion=<version>`.

The updater expects the GitHub Release asset name:

```text
FPVSToolbox-<version>-setup.exe
```

After uploading a release, manually smoke the installer update path on Windows:

```powershell
& "installers\FPVSToolbox-<version>-setup.exe" /RELAUNCH=1
```

Confirm the installer replaces app files, relaunches `FPVS_Toolbox.exe`, and
leaves projects, settings, logs, and generated outputs outside the installer
replacement scope.

## Configuration

The app interface uses constants in `config.py` for release metadata, update
URLs, and selected sizing values. Keep user-visible workflow behavior in the
PySide6 application layer; avoid scattering release or UI constants across
tool modules.

The update check is controlled by:

- `FPVS_TOOLBOX_VERSION`: current running version.
- `FPVS_TOOLBOX_UPDATE_API`: full GitHub Releases API URL queried by
  `Main_App.updates.github_releases`.
- `FPVS_TOOLBOX_REPO_PAGE`: repository release page used for user-facing release
  note links.

Installer downloads are cached under
`%LOCALAPPDATA%\FPVS Toolbox\updates` when `LOCALAPPDATA` is available, or the
system temp directory otherwise. The cache must stay outside the install
folder, project root, and repository source tree.

## Debug Logging

The toolbox routes messages through Python's `logging` module. At startup the
MNE-Python logger is set to `WARNING` to reduce output. Enable **Debug** mode
in the settings window and restart the application to raise the global log
level to `DEBUG`. When debug mode is active, the MNE logger is increased to
`INFO` so detailed processing information is visible.

## Validation

Use the narrowest relevant check first. See `docs/agent/quality/test-selection.md`
for pytest marker guidance and focused test commands.

Common gates:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python -m pytest -q
ruff check .
```
