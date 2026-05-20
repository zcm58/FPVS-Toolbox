# Auto Update Installer Workflow

## Status

Completed in commit `090b3136` (`feat: add auto update release workflow`).
The plan now lives under `docs/agent/exec-plans/completed/`; future updater
work should start from the active architecture docs and this completion record,
not from the implementation checklist below as if it were pending.

## Completion Snapshot

Landed files and ownership:

- `src/Main_App/updates/`: non-GUI updater backend for typed release metadata,
  GitHub Releases selection, installer downloads, and installer launch.
- `src/Main_App/gui/update_dialog.py`: user-facing update dialog, download
  progress, install confirmation, and busy-work install guard.
- `src/Main_App/gui/update_manager.py`: startup/manual update scheduling facade
  with debounce and pytest startup skip preserved.
- `scripts/packaging/build_exe.ps1`, `build_installer.ps1`, and
  `build_release.ps1`: script-driven PyInstaller and Inno release workflow.
- `scripts/packaging/FPVS Toolbox Setup Script.iss`: installer relaunch support
  through `/RELAUNCH=1`.
- `tests/updates/test_update_check.py`, `tests/updates/test_update_download.py`,
  and `tests/gui/test_update_manager_manual_force.py`: focused updater
  coverage.

Resolved decisions:

- Installer asset contract is `FPVSToolbox-<version>-setup.exe`.
- Backend update logic lives under `Main_App.updates`; GUI scheduling and
  presentation live under `Main_App.gui.update_manager` and
  `Main_App.gui.update_dialog`.
- The first implementation keeps the existing install-root behavior and
  installed executable name `FPVS_Toolbox.exe`.
- Release builds are driven by PowerShell scripts under `scripts/packaging/`
  invoking `ISCC.exe`; maintainers should not use the Inno GUI for normal
  releases.
- User-facing docs are not advertised as automatic install/relaunch proof until
  a released installer smoke proves the flow.

## Target

Upgrade FPVS Toolbox from "check GitHub and open the release page" to a
Studio-style in-app installer update flow:

```text
installed FPVS Toolbox
  -> check GitHub Releases
  -> show available version and release-note preview
  -> download the matching Windows installer to a user-writable cache
  -> ask for final confirmation
  -> launch the installer with a relaunch flag
  -> close FPVS Toolbox
  -> installer replaces app files
  -> installer relaunches FPVS Toolbox
```

The same effort must also add a Studio-style script-driven release workflow:
one PowerShell entrypoint should build the PyInstaller executable bundle and
then compile the Inno installer, suitable for running from PyCharm as an
external tool. Maintainers should not need to open the Inno Setup GUI to create
an `.exe` bundle or installer.

## Scanned Baseline

Toolbox files inspected:

- `src/Main_App/gui/update_manager.py`
- `src/Main_App/gui/tool_workflows.py`
- `src/Main_App/gui/main_window.py`
- `src/main.py`
- `src/config.py`
- `tests/gui/test_update_manager_manual_force.py`
- `docs/agent/guides/development.md`
- `docs/agent/architecture/gui.md`
- `docs/agent/architecture/workers-threading.md`
- `docs/agent/quality/verification-gates.md`
- `scripts/packaging/FPVS_Toolbox.spec`
- `scripts/packaging/FPVS Toolbox Setup Script.iss`

FPVS Studio files inspected as the reference implementation:

- `src/fpvs_studio/updates/models.py`
- `src/fpvs_studio/updates/github_releases.py`
- `src/fpvs_studio/updates/downloader.py`
- `src/fpvs_studio/updates/installer.py`
- `src/fpvs_studio/gui/update_dialog.py`
- `src/fpvs_studio/gui/controller.py`
- `src/fpvs_studio/gui/main_window.py`
- `tests/unit/test_update_check.py`
- `tests/unit/test_update_download.py`
- `tests/gui/test_update_dialog.py`
- `packaging/inno/fpvs_studio.iss`
- `scripts/build_exe.ps1`
- `scripts/build_installer.ps1`
- `scripts/build_release.ps1`
- `docs/PACKAGING.md`
- `docs/exec-plans/planned/patch-update-workflow.md`

## Original Pre-Implementation Baseline

- `MainWindow.__init__` calls
  `Main_App.gui.update_manager.check_for_updates_on_launch(self)` after a
  one-second `QTimer`.
- Manual `File > Check for Updates` routes through
  `src/Main_App/gui/tool_workflows.py` and calls
  `check_for_updates_async(..., silent=False, force=True)`.
- `src/Main_App/gui/update_manager.py` used a `QRunnable` on the global
  `QThreadPool` to query `FPVS_TOOLBOX_UPDATE_API`, then the GitHub
  `/releases/latest` endpoint.
- Update state was only `_UpdateInfo(latest, url)`. The user could open the GitHub
  release page, but the app did not select an installer asset, download it,
  launch it, or relaunch after install.
- Startup checks are debounced through `SettingsManager` key
  `updates.last_checked_utc`; checks are skipped under pytest.
- `src/config.py` owns `FPVS_TOOLBOX_VERSION`, `FPVS_TOOLBOX_UPDATE_API`, and
  `FPVS_TOOLBOX_REPO_PAGE`.
- The Inno script output
  `installers\FPVSToolbox-<version>-setup.exe`, installs `FPVS_Toolbox.exe`,
  and always offered a normal postinstall launch. It did not support a
  `/RELAUNCH=1` command-line mode like FPVS Studio.
- The Inno script scan found `#define MyAppVersion "1.7.0` without a closing
  quote before implementation. The completed release workflow now passes the
  app version into Inno from `FPVS_TOOLBOX_VERSION`.

## Studio Behavior To Mirror

FPVS Studio separates update work into a non-GUI backend and a GUI dialog:

- `fpvs_studio.updates.models` defines typed update contracts.
- `fpvs_studio.updates.github_releases` fetches the full GitHub Releases list,
  ignores drafts, handles prerelease eligibility, parses PEP 440 versions,
  chooses a single matching installer asset, and fails closed on ambiguous
  installer assets.
- `fpvs_studio.updates.downloader` downloads the installer to a user-writable
  cache, writes through a `.part` file, reuses an already-complete file, rejects
  non-HTTPS URLs and path-like filenames, and checks asset size when available.
- `fpvs_studio.updates.installer` launches the downloaded installer with
  `/RELAUNCH=1`.
- `fpvs_studio.gui.update_dialog.UpdateDialog` checks, downloads, shows progress,
  enables `Install and Restart` only after a successful download, asks for final
  confirmation, launches the installer, then quits the app.
- `scripts/build_release.ps1` is the one-command release entrypoint. It calls
  `scripts/build_exe.ps1` and then `scripts/build_installer.ps1`.
- `scripts/build_exe.ps1` verifies the packaging Python environment, refreshes
  editable packaging dependencies unless `-SkipInstall` is passed, removes stale
  PyInstaller outputs inside the repo, runs PyInstaller from the `.spec`, and
  verifies bundled package metadata.
- `scripts/build_installer.ps1` resolves `ISCC.exe` from `-InnoCompiler`,
  `ISCC_EXE`, PATH, or common install locations, validates the existing bundle,
  optionally runs a packaged-app smoke check, and invokes `ISCC.exe` with
  command-line defines and output options. It does not open the Inno Setup GUI.
- Startup update checks are silent unless an eligible update with an installer
  asset is available. Manual checks show no-update and error states.
- `packaging/inno/fpvs_studio.iss` handles `/RELAUNCH=1` through a `[Code]`
  function and a second `[Run]` entry that launches the installed app after an
  updater-driven install.

## Success Criteria

- Manual `File > Check for Updates` opens a Toolbox update dialog, not a browser
  prompt.
- Startup update checks remain silent unless an update is available.
- No-update, update-available, network-error, missing-installer, ambiguous-asset,
  download-error, and installer-launch-error states are distinct and visible in
  the manual dialog.
- The app downloads exactly one eligible Windows installer asset for the target
  release.
- The installer download lands in a user-writable update cache, never in the
  install folder, project folders, or repo source tree.
- `Install and Restart` asks for final confirmation, launches the installer with
  `/RELAUNCH=1`, and exits FPVS Toolbox.
- A maintainer can run one PowerShell script from PyCharm to build the
  PyInstaller bundle and Inno installer.
- The release scripts fail fast on missing Python, PyInstaller, Inno Setup,
  bundle outputs, smoke-check failures, or missing installer outputs.
- The Inno installer is compiled by script through `ISCC.exe`; the workflow does
  not require manually opening or operating the Inno Setup application.
- The Inno installer relaunches `FPVS_Toolbox.exe` only for updater-driven
  installs; normal first-time installs keep the current postinstall launch UX.
- Processing, post-processing, statistics, plotting, and other long-running
  work are not interrupted silently. If the app is busy, the update install
  path blocks with a clear message.
- User projects, settings, logs, generated outputs, and project roots remain
  outside the installer replacement scope.
- No silent fallback opens the release page as if an update was installed.

## Non-Goals

- No differential or patch update system in the first Toolbox implementation.
  The full Inno installer remains the only update artifact.
- No forced background update and no auto-install without user confirmation.
- No custom update server; use GitHub Releases.
- No code signing work in this plan. If signing is added later, make it a
  separate release-engineering plan.
- No installer-driven project or settings migration unless explicitly scoped.
- No revival of retired `Legacy_App` or `PySide6_App` paths.

## Target Architecture

Prefer the same separation as Studio while preserving Toolbox import stability:

```text
src/Main_App/updates/
  __init__.py
  models.py
  github_releases.py
  downloader.py
  installer.py

src/Main_App/gui/
  update_dialog.py
  update_manager.py     # compatibility facade / startup scheduler
```

`Main_App.updates` should own pure update contracts and side-effecting
download/installer helpers. It must not import widgets or create windows.

`Main_App.gui.update_dialog` should own user-facing update controls, progress,
buttons, modal confirmation, and thread wiring.

`Main_App.gui.update_manager` should either remain as a thin facade for existing
callers or be reduced to startup/manual orchestration. Keep these public entry
points until all current callers and tests are migrated:

- `check_for_updates_async(...)`
- `check_for_updates_on_launch(app)`
- `cleanup_old_executable()`

If future agents decide to remove or rename those functions, update
`MainWindow`, `tool_workflows`, tests, and architecture docs in the same PR.

## Release Asset Contract

Use the existing Toolbox installer filename for the first implementation unless
the release workflow is deliberately renamed:

```text
FPVSToolbox-<version>-setup.exe
```

Candidate regex:

```python
r"^FPVSToolbox-.+-setup\.exe$"
```

Selection rules:

- Fetch from the full releases endpoint, not only `/releases/latest`, so stable
  vs prerelease eligibility can be handled correctly.
- Ignore draft releases.
- Stable installed versions ignore prereleases by default.
- Prerelease installed versions may see newer prereleases.
- Parse release tags after stripping a leading `v`.
- Require the selected release version to be greater than
  `FPVS_TOOLBOX_VERSION`.
- Require one matching installer asset with an HTTPS `browser_download_url`.
- If multiple installer assets match, prefer the single asset whose filename
  contains the normalized version or release tag. If that does not produce
  exactly one asset, fail closed with a clear error.
- If no installer asset is present, show "update metadata is incomplete" rather
  than opening a browser as a fake updater path.

If the maintainer chooses to rename release assets to mirror Studio more
literally, use this instead and update all release docs/scripts together:

```text
FPVS-Toolbox-Setup-<version>.exe
```

Do not support both names long-term unless there is a documented migration
reason. Multiple accepted patterns make release mistakes harder to catch.

## Implementation Phases

These phases are retained as historical implementation evidence. They are not
pending future work.

### Phase 1 - Packaging Baseline

Goal: create a Studio-style release workflow that builds the executable bundle
and installer from PowerShell, then make the installer support updater-driven
relaunch before the GUI depends on it.

Completed tasks:

- Repair and validate `scripts/packaging/FPVS Toolbox Setup Script.iss`.
- Stop hard-coding the version in two places. Prefer passing
  `FPVS_TOOLBOX_VERSION` into Inno from a build script, similar to Studio's
  `/DAppVersion=...` pattern.
- Added `scripts/packaging/build_exe.ps1`.
  - Resolve the Python executable from `.venv1\Scripts\python.exe`, then fall
    back to `python` only if the project venv is unavailable.
  - Optionally refresh packaging dependencies unless `-SkipInstall` is passed.
  - Remove stale PyInstaller outputs only inside the repo after resolving paths.
  - Run PyInstaller with `scripts/packaging/FPVS_Toolbox.spec`.
  - Verify `dist\FPVS Toolbox\FPVS_Toolbox.exe` or the exact bundle path
    produced by the spec exists.
  - Fail fast on version drift between `src/config.py`, bundled metadata when
    available, and the installer version passed forward.
- Added `scripts/packaging/build_installer.ps1`.
  - Accept `-InnoCompiler` and `-SkipSmoke`.
  - Resolve `ISCC.exe` from `-InnoCompiler`, `ISCC_EXE`, PATH, and common Inno
    Setup install locations.
  - Validate the PyInstaller bundle exists before compiling the installer.
  - Optionally run a packaged-app smoke check before compiling.
  - Invoke `ISCC.exe` directly with command-line options such as
    `/DAppVersion=<version>`, `/O<output-dir>`, and `/F<installer-base-name>`.
  - Verify the expected installer file exists after compilation.
- Added `scripts/packaging/build_release.ps1`.
  - This is the single PyCharm-friendly entrypoint.
  - It calls `build_exe.ps1` and then `build_installer.ps1`.
  - It accepts pass-through options for `-SkipInstall`, `-InnoCompiler`, and
    installer smoke behavior.
  - It prints the final installer path for GitHub Release upload.
- Do not require maintainers to open the Inno Setup GUI. The only supported
  release path for this plan is the PowerShell script calling `ISCC.exe`.
- Added `/RELAUNCH=1` handling to the Inno script:

```pascal
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName,'&','&&')}}"; Flags: nowait postinstall skipifsilent; Check: not RelaunchRequested
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifsilent; Check: RelaunchRequested

[Code]
function RelaunchRequested: Boolean;
begin
  Result := Pos('/RELAUNCH=1', Uppercase(GetCmdTail)) > 0;
end;
```

- Review whether `CloseApplications=force` should be softened to
  `CloseApplications=yes`. The app should quit itself before mutation, so the
  installer should not need to force-close the main process in the normal path.
- Preserve `UsePreviousAppDir=yes` so an update installs over the existing app
  location.
- Preserve the current installed executable name `FPVS_Toolbox.exe` unless a
  separate packaging rename is explicitly requested.
- Required script shape:

```text
scripts/packaging/build_exe.ps1
scripts/packaging/build_installer.ps1
scripts/packaging/build_release.ps1
```

Keep the scripts under `scripts/packaging/` for Toolbox. If maintainers later
want root-level `scripts/build_release.ps1` parity with Studio, add a thin
forwarding wrapper rather than moving the implementation.

Verification for this phase:

```powershell
.\.venv1\Scripts\Activate.ps1
python -m py_compile src\config.py src\main.py
python .agents\scripts\audit\agent_audit.py
.\scripts\packaging\build_exe.ps1 -SkipInstall
.\scripts\packaging\build_installer.ps1 -SkipSmoke
```

Manual release smoke on Windows:

```powershell
.\scripts\packaging\build_release.ps1 -SkipInstall
& "installers\FPVSToolbox-<version>-setup.exe" /RELAUNCH=1
```

Confirm the installed app relaunches after the installer completes.

### Phase 2 - Typed Update Backend

Goal: move release selection and installer metadata out of GUI code. Status:
complete.

Added `src/Main_App/updates/models.py` with Studio-equivalent contracts:

- `UpdateError`
- `InstallerAsset`
- `UpdateCheckResult`
- `CandidateRelease`
- `DownloadedInstaller`

Added `src/Main_App/updates/github_releases.py`:

- `DEFAULT_RELEASES_API_URL = "https://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases"`
- `INSTALLER_ASSET_PATTERN`
- `check_for_updates(current_version=FPVS_TOOLBOX_VERSION, releases_api_url=..., include_prereleases=None)`
- `fetch_release_metadata(...)`
- `select_update_from_releases(...)`
- `parse_release_version(...)`
- `summarize_release_notes(...)`

Behavior to copy from Studio:

- HTTPS-only metadata URL.
- GitHub `Accept` and Toolbox `User-Agent` headers.
- Bounded timeout.
- JSON shape validation.
- Draft release skip.
- PEP 440 version parsing.
- Beta/prerelease eligibility based on installed version unless explicitly
  overridden.
- Compact release-note summary.
- Fail closed on ambiguous installer assets.

Do not keep using `/releases/latest` for the final updater. That endpoint cannot
express prerelease/stable selection as clearly as Studio's full-release scan.

Focused tests to add:

- stable installs ignore prereleases by default
- prerelease installs can see prerelease updates
- drafts are ignored
- current version reports no update and no installer asset
- missing installer asset returns no installable update or a clear incomplete
  metadata state
- ambiguous installer assets raise `UpdateError`
- release notes summary is compact
- invalid installed version raises `UpdateError`

### Phase 3 - Download And Installer Helpers

Goal: download and launch the installer without GUI dependencies. Status:
complete.

Added `src/Main_App/updates/downloader.py`:

- `default_update_cache_dir()` returns
  `%LOCALAPPDATA%\FPVS Toolbox\updates` when `LOCALAPPDATA` exists, otherwise a
  temp-folder fallback.
- `download_installer(asset, destination_dir=None, progress_callback=None)`.
- Download in chunks to `<installer>.part`, then atomically replace the final
  path.
- Reuse an existing complete file when `asset.size_bytes` matches.
- Reject non-HTTPS download URLs.
- Reject non-`.exe` assets.
- Reject filenames containing `/` or `\`.
- Validate final size when GitHub asset size is available.
- Delete partial files on failed download.

Added `src/Main_App/updates/installer.py`:

- `launch_installer(installer_path, relaunch_after_install=True)`.
- Require an existing `.exe` path.
- Launch with `subprocess.Popen([path, "/RELAUNCH=1"], close_fds=True)` when
  relaunch is requested.

Focused tests to add:

- downloader writes bytes and reports progress
- downloader reuses complete cached installer
- downloader rejects HTTP URLs
- downloader rejects path-like asset names
- downloader removes partial files on failure
- launcher rejects missing or non-EXE paths
- launcher passes `/RELAUNCH=1`

### Phase 4 - Update Dialog

Goal: replace release-page prompting with an in-app update dialog. Status:
complete.

Added `src/Main_App/gui/update_dialog.py`.

Use Studio's dialog behavior, adapted to Toolbox styling:

- Title: `FPVS Toolbox updates`
- Status label
- Current version label
- Latest version label
- release-notes preview
- `View Full Release Notes`
- progress bar hidden until download starts
- `Check Again`
- `Download Update`
- `Install and Restart`
- `Close` / `Remind Me Later`

Use existing Toolbox GUI conventions:

- Import reusable dialog/action/button primitives from
  `Main_App.gui.components` where they already fit.
- Use `apply_fpvs_theme()` or the current theme surface instead of local styling
  forks.
- Do not create a card-within-card layout.
- Ensure buttons fit their labels at compact widths.

Threading:

- Do not run network checks or downloads in the UI thread.
- Use either Studio's `QThread` + worker object pattern or the existing
  `QRunnable` pattern. Pick one and keep it consistent inside the dialog.
- Workers must emit results through Qt signals and never touch widgets.
- Disable action buttons while a check/download is running.

Install guard:

- Before launching the installer, check for active processing and export work:
  `busy`, `processing_thread`, `detection_thread`, `_post_worker`,
  `_post_thread`, and any other active long-running handles still present at
  implementation time.
- If work is active, block install with a clear message asking the user to stop
  or finish the running operation first.
- Do not force-cancel analysis work from the updater.
- If future code adds a real dirty-project state, route through the existing
  save workflow before install. Do not invent a parallel project-save path in
  the updater.

Install flow:

1. User clicks `Install and Restart`.
2. Dialog asks: `FPVS Toolbox needs to close to install the update. Install the update and restart FPVS Toolbox?`
3. If the install guard passes, launch the downloaded installer with
   `/RELAUNCH=1`.
4. Accept/close the dialog.
5. Quit the `QApplication`.

Manual error behavior:

- Check failure: show a retry-later status and the actual error text.
- Download failure: keep `Check Again` enabled and `Install and Restart`
  disabled.
- Installer launch failure: show a modal warning and keep the app open.

No silent fallback:

- `View Full Release Notes` may open the browser.
- A failed update check/download/install must not automatically open the
  release page as a substitute for installation.

### Phase 5 - Startup And Menu Integration

Goal: keep the existing entry points but route them through the richer dialog.
Status: complete.

Updated `src/Main_App/gui/update_manager.py`:

- Preserve `cleanup_old_executable()` until its actual need is confirmed. If it
  is removed, document why and add a regression test or packaging note.
- Preserve debounce through `SettingsManager`.
- Preserve pytest skip for startup checks.
- For startup checks, run the backend in the background and show
  `UpdateDialog(auto_check=False, initial_result=result, parent=app)` only when
  `result.update_available` and `result.installer_asset` are both true.
- Startup no-update and startup error paths should log only.
- For manual checks, open `UpdateDialog(parent=host, auto_check=True)`.
- Keep `tool_workflows.check_for_updates(...)` as the menu-facing helper.

Updated tests that monkeypatch `check_for_updates_on_launch` in main-window
smoke tests only as needed. Do not broaden GUI test scope just for the updater.

### Phase 6 - Release Documentation

Updated agent-facing docs:

- `docs/agent/guides/development.md`: release build, installer asset name,
  update cache, GitHub Release requirements, and manual update smoke.
- `docs/agent/architecture/gui.md`: note that GUI update orchestration lives in
  `Main_App.gui.update_dialog` / `update_manager`, while backend update logic
  lives in `Main_App.updates`.
- `docs/agent/architecture/module-map.md`: add the new backend package if
  `Main_App.updates` is introduced.
- `docs/agent/quality/verification-gates.md`: add updater-specific non-GUI
  checks if they become durable.

User-facing docs remain intentionally deferred until a released installer proves
the flow:

- `docs/user/start/getting-started.md`
- `docs/user/study/troubleshooting.md`
- `README.md`

Do not advertise automatic install/relaunch before a released installer proves
the flow.

## Verification Plan

Local non-GUI checks:

```powershell
.\.venv1\Scripts\Activate.ps1
python -m py_compile src\Main_App\updates\models.py src\Main_App\updates\github_releases.py src\Main_App\updates\downloader.py src\Main_App\updates\installer.py
python -m py_compile src\Main_App\gui\update_dialog.py src\Main_App\gui\update_manager.py src\Main_App\gui\tool_workflows.py src\Main_App\gui\main_window.py
python -m pytest tests\gui\test_update_manager_manual_force.py -q
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
python .agents\scripts\audit\agent_audit.py
ruff check src\Main_App\updates src\Main_App\gui\update_dialog.py src\Main_App\gui\update_manager.py tests\gui\test_update_manager_manual_force.py
```

Add focused pure tests for the backend and run them locally:

```powershell
python -m pytest tests\updates\test_update_check.py tests\updates\test_update_download.py -q
```

GUI tests:

- Add pytest-qt coverage for the dialog state machine if the repo's GUI test
  suite remains the accepted CI coverage path.
- Do not run pytest-qt/offscreen GUI tests locally in this Windows environment.
  Follow the repo rule: use non-GUI checks plus a visible/manual smoke path
  unless the user explicitly approves a safe visible GUI test environment.

Manual visible smoke:

```powershell
.\.venv1\Scripts\Activate.ps1
python src\main.py
```

Then confirm:

- `File > Check for Updates` opens the update dialog.
- No-update state reports the current version and keeps install disabled.
- Available-update state shows release-note preview and enables download.
- `View Full Release Notes` opens the GitHub release URL.
- Download progress moves and `Install and Restart` remains disabled until the
  installer is fully downloaded.
- Cancel/close leaves the app running.
- Busy processing/export state blocks install.

Release smoke on a clean Windows machine or VM:

- install previous public FPVS Toolbox release
- launch from Start Menu or Desktop shortcut
- use `File > Check for Updates`
- download the newer release installer
- click `Install and Restart`
- confirm FPVS Toolbox exits
- confirm Inno installs over the previous app directory
- confirm FPVS Toolbox relaunches
- confirm `About` or status bar shows the new `FPVS_TOOLBOX_VERSION`
- confirm existing user settings, projects, outputs, and logs remain intact
- repeat manual installer run without `/RELAUNCH=1` and confirm the normal
  postinstall launch checkbox still behaves as expected

## Resolved Decisions

- Kept existing artifact name `FPVSToolbox-<version>-setup.exe`.
- Kept Toolbox's existing install-root behavior for the first updater PR.
- Kept backend code under `Main_App.updates` to keep release selection,
  downloads, and installer launch testable without widgets.
- Kept release implementation under `scripts/packaging/` rather than adding
  root-level build wrappers.
- Did not add a hidden packaged-smoke CLI mode in this slice.

## What Agents Should Inspect First

Toolbox:

1. `src/Main_App/gui/update_manager.py`
2. `src/Main_App/gui/main_window.py`
3. `src/Main_App/gui/tool_workflows.py`
4. `src/Main_App/gui/components/`
5. `src/config.py`
6. `src/main.py`
7. `scripts/packaging/FPVS Toolbox Setup Script.iss`
8. `scripts/packaging/FPVS_Toolbox.spec`
9. `tests/gui/test_update_manager_manual_force.py`
10. `docs/agent/guides/development.md`
11. `docs/agent/architecture/gui.md`
12. `docs/agent/architecture/workers-threading.md`

FPVS Studio reference:

1. `src/fpvs_studio/updates/models.py`
2. `src/fpvs_studio/updates/github_releases.py`
3. `src/fpvs_studio/updates/downloader.py`
4. `src/fpvs_studio/updates/installer.py`
5. `src/fpvs_studio/gui/update_dialog.py`
6. `src/fpvs_studio/gui/controller.py`
7. `src/fpvs_studio/gui/main_window.py`
8. `packaging/inno/fpvs_studio.iss`
9. `docs/PACKAGING.md`
10. `tests/unit/test_update_check.py`
11. `tests/unit/test_update_download.py`
12. `tests/gui/test_update_dialog.py`

Before editing, run:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents\scripts\audit\agent_audit.py
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
```

## Future Reporting Requirements

Agents changing this completed updater flow must report:

- The selected installer asset filename contract.
- Whether the Inno `/RELAUNCH=1` path was added and manually smoke-tested.
- Whether startup checks remain silent for no-update and error states.
- Whether manual checks show clear no-update, update, and error states.
- Whether installer downloads are cached outside install/project folders.
- Whether ambiguous or missing installer assets fail closed.
- Whether active processing/export state blocks install.
- Which docs were updated and why.
- Commands run and results.
- Any skipped GUI/package tests and residual risk.

## Manual Verification Notes

Recheck the listed files before future updater changes because release scripts,
installer asset names, GitHub Release metadata shape, and GUI component
contracts may change.
