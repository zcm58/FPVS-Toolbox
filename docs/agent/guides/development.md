# Development Notes

Use this page for local setup, release notes, and validation commands that are
not part of the end-user documentation.

## Main branch

`main` is the default development branch and contains the consolidated v3
release work. The retired development branches were removed on 2026-10-18;
release tags remain available. Start future changes from `main`. Documentation,
Windows packaging, and isolated Qt workflow branch filters now target `main`.

The published v3.0.0 installer is bound to its release tag. Later cleanup or
feature branches are source changes until separately merged, built, qualified,
and released. Hardware/montage expansion and complete FPVS Studio compatibility
follow the [shared roadmap](../architecture/hardware-pipeline-studio-roadmap.md);
they are not already shipped capabilities.

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

The example's `-SkipSmoke` produces development artifacts only. Release
qualification requires the native packaged-app and installer acceptance workflow;
do not treat a skipped smoke as a releasable build or launch local GUI smoke
without the approved visible-environment scope.

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

### Publishing open-source releases

Keep `origin` pointed at `zcm58/FPVS-Toolbox`, the canonical public source
and release repository. Publish new releases there explicitly rather than
relying on an inferred repository in a release command. Preserve historical
tags and assets in `zcm58/FPVS-Toolbox-Releases`; that repository is an archive,
not the destination for new releases. Build-time GitHub authentication belongs
on the maintainer's machine or in CI secrets only. The installed main
application and updater do not need credentials.

After the required release checks, use an authenticated GitHub CLI (`gh`) to
create a draft whose tag identifies the exact source commit used for the build.
Push that reviewed commit to the release branch first. This example assumes
that the current clean checkout is the tested build commit and a full installer
without patches; set the actual release version and reviewed notes file:

Verify that GitHub immutable releases are enabled on
`zcm58/FPVS-Toolbox` before publication. The previous setting on the
release-only repository does not configure this repository. Attach every asset
to the draft before publishing; an immutable published release cannot receive
replacement or additional assets. The setting applies to future releases and
does not lock historical installers retrospectively. See GitHub's
[immutable release workflow](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

```powershell
$releaseVersion = '<next-approved-version>'
$releaseRepo = 'zcm58/FPVS-Toolbox'
$releaseCommit = (git rev-parse HEAD).Trim()
gh release create "v$releaseVersion" --repo $releaseRepo --target $releaseCommit --draft `
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

GitHub's automatic source archives now represent the source commit named by
the release tag. Retain authenticated ownership inventories and build receipts
with that exact commit and the installer hashes in the release record. Do not
upload local logs, participant data, internal inventories or debug artifacts
as release assets.

GitHub's immutable-release attestation binds the public tag and exact assets.
The local packaging scripts build artifacts and do not publish them. See
[GitHub release verification](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

The published `v2.1.2` binary checks the previous private repository, so it cannot
discover the new public release address. Its first v3 upgrade requires a manual
download from the canonical release page. The v3.0.0 native installer lifecycle
qualified that upgrade at its recorded release revision; repeat the relevant
acceptance checks for future artifacts. The first v3 upgrade uses the full installer to establish
the independent updater and owned-file inventory;
future authenticated baselines can support direct patches. Users of builds
that checked the temporary release-only address can install the full package
from the canonical release page.

GitHub Pages publication is separate from repository visibility. The
documentation workflow validates the site; do not describe it as deployed
without checking its deployment and Pages configuration.

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
