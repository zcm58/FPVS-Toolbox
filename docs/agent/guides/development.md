# Development Notes

Use this page for local setup, release notes, and validation commands that are
not part of the end-user documentation.

## Local Environment

Development and source execution may occur on Windows 11 or CachyOS (Arch
Linux). Keep virtual environments machine-local; never copy one between
operating systems. Prefer an existing `.venv1`, fall back to an existing
`.venv`, and do not create a duplicate merely to match an example.

Windows PowerShell setup:

```powershell
python -m venv .venv1
.\.venv1\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

CachyOS/Bash setup:

```bash
python -m venv .venv1
source .venv1/bin/activate
python -m pip install -r requirements.txt
```

After activation, shared cross-platform commands use `python` and
repository-relative forward-slash paths. If an IDE loses its interpreter, select
`.venv1/Scripts/python.exe` or `.venv/Scripts/python.exe` on Windows and
`.venv1/bin/python` or `.venv/bin/python` on CachyOS.

Shared development decisions must work on both platforms. Prefer `pathlib`,
Python/PySide6 APIs, and one portable code path; add a platform branch only
when an OS-specific installer or system integration makes it unavoidable.

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

Windows releases provide an Inno Setup installer. Build and installer smoke
work therefore runs on Windows 11; CachyOS development does not need to
duplicate Windows-only packaging tooling. Running the installer creates a
folder containing `FPVS_Toolbox.exe`, required DLLs, and configuration files.
Release packaging definitions live in `scripts/packaging/`.

The supported maintainer workflow is script-driven. Do not open the Inno Setup
GUI for normal releases. Do not add or maintain ad-hoc PyInstaller compiler
helpers under `src/`; packaging changes belong in `scripts/packaging/`.

```powershell
.\scripts\packaging\build_release.ps1 -SkipInstall -SkipSmoke
```

Use `-SkipInstall` only when the available repo environment already has
`requirements.txt` installed. Omit it when building from a fresh environment. Use
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

### Publishing from private source

Keep `origin` pointed at private `zcm58/FPVS-Toolbox-Repo`. Publish built assets
to public `zcm58/FPVS-Toolbox-Releases` explicitly; never push source refs to the
public repository or rely on an inferred repository in a release command.
Build-time GitHub authentication belongs on the maintainer's machine or in
private CI secrets only. The installed main application and updater do not
need credentials.

After the required release checks, use an authenticated GitHub CLI (`gh`) to
create a draft in the public repository. This example assumes a full installer
without patches; set the actual release version and reviewed notes file:

Enable GitHub immutable releases on `zcm58/FPVS-Toolbox-Releases` before future
publication. Attach every asset to the draft before publishing; an immutable
published release cannot receive replacement or additional assets. This setting
applies to future releases and does not lock historical installers retrospectively.
The maintainer enabled it on October 8, 2026 and verified `enabled: true`; no
existing release, tag or asset changed during that setting update.

```powershell
$releaseVersion = '3.0.0'
$releaseRepo = 'zcm58/FPVS-Toolbox-Releases'
gh release create "v$releaseVersion" --repo $releaseRepo --target main --draft `
  --title "FPVS Toolbox $releaseVersion" --notes-file build/release-notes.md `
  "installers/FPVSToolbox-$releaseVersion-setup.exe" `
  "installers/FPVSToolbox-$releaseVersion-setup.exe.sha256" `
  "installers/FPVSToolbox-Update-$releaseVersion.json" `
  "installers/FPVSToolbox-Update-$releaseVersion.json.sha256"
```

For supported direct patches, also explicitly attach each generated patch
`.exe` and its `.sha256` sidecar to that same draft. Upload only the files named
by the verified target release; do not use a broad folder wildcard. Check the
uploaded filenames, sizes and GitHub SHA-256 digests against the local files,
and confirm every patch named in the update JSON is present before publishing:

```powershell
gh release edit "v$releaseVersion" --repo $releaseRepo --draft=false --latest
gh release verify "v$releaseVersion" --repo $releaseRepo
gh release verify-asset "v$releaseVersion" `
  "installers/FPVSToolbox-$releaseVersion-setup.exe" --repo $releaseRepo
```

The public tag is created on the public repository's `main` branch. Preserve
the private source commit and authenticated ownership inventories in private
release records. Do not upload source ZIPs, raw `.py` files, internal logs or
inventories, and do not mirror private tags into the public repository.

GitHub's immutable-release attestation binds the public tag and exact assets;
the release-only tag does not identify the private source build. Retain the
exact private source commit/build association in the release record. The local
packaging scripts build artifacts and do not publish them. See
[GitHub release verification](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

The 2026-10-07 repository migration does not publish 3.0.0. Historical installers
remain unchanged; users of 2.1.2 and earlier need to manually install 3.0.0
when available before automatic updates work at the new address.

GitHub unpublished the documentation site when the source became private. The
user chose to leave it unpublished for now. `.github/workflows/docs.yml` keeps
strict documentation validation with read-only permissions and does not deploy.
Restore public documentation hosting only when explicitly requested.

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

The experimental LORETA Visualizer uses MNE to fetch fsaverage when needed.
Automatic fetches target the ignored repository-root cache
`.fpvs_cache/mne/MNE-fsaverage-data/`. Do not add fsaverage MRI/template data
to `src/`, `docs/`, package data, or quarantine paths. If a stale generic MNE
subjects-dir setting points into `src` or `docs`, the visualizer ignores that
candidate and continues to the root-local cache; an explicit
`FPVS_FSAVERAGE_SUBJECTS_DIR` override must point to an untracked subjects
directory outside those forbidden paths.

## Debug Logging

The toolbox routes messages through Python's `logging` module. At startup the
MNE-Python logger is set to `WARNING` to reduce output. Enable **Debug** mode
in the settings window and restart the application to raise the global log
level to `DEBUG`. When debug mode is active, the MNE logger is increased to
`INFO` so detailed processing information is visible.

## Validation

Use the narrowest relevant scope first. See
`docs/agent/quality/test-selection.md` for the scope map.

Common gates:

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```
