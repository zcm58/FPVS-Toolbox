# Independent updater

FPVS Toolbox uses the FPVS Studio independent updater design, including its
September 2026 compact progress workflow, adapted to Toolbox's
purpose-based packages. File > Check for Updates checks and downloads through
a separate process. After Install and Restart, an independent window waits for
Toolbox to close, applies the verified patch or full installer, and restarts
Toolbox. The installed Start menu shortcut **FPVS Toolbox Update & Repair**
also works when the main application cannot start. Users do not download a
helper each time, and updates install compiled files rather than compiling on
the user's computer.

## Ownership and parity

| Owner | Responsibility |
| --- | --- |
| `Main_App.updates.models`, `helper_protocol` | Studio-compatible typed messages and private JSON-lines protocol version 1 |
| `github_releases`, `validation`, `patches` | Strict repository/asset identity, bounded HTTPS metadata, direct-patch selection |
| `downloader`, `cache`, `cache_io` | Streaming SHA-256 verification, download receipts, bounded per-user cache, guarded file access |
| `helper_client`, `helper_service`, `helper_runtime`, `process_launch` | Cancelable subprocess work, staged helper, acknowledged handoff, process/install locks, restart |
| `application`, `elevation`, `installer` | Toolbox identity, canonical version adapter, Windows registration and install scope |
| `gui.update_manager`, `update_dialog`, `update_lifecycle` | Existing startup debounce/manual menu, progress, application-owned workers and safe shutdown |
| `gui.update_install_guard`, `updater_presentation`, `updater_window` | Toolbox active-work checks, shared components/theme, independent repair GUI |
| `src/updater.py`, `Main_App.updater_main` | Lightweight entry point, private worker mode, standalone GUI and packaging diagnostics |
| `diagnostics.packaged_smoke`, `src/main.py` diagnostic dispatch | Isolated main-bundle dependency and explicitly opted-in visible Main Window probes |
| `scripts/packaging/` | Main/helper specs, inventories, direct patches, native setup and lifecycle fixtures |

Keep protocol, asset/result schemas, download integrity, handoff sequencing,
and native ownership/transaction semantics aligned with Studio. Larger ported
security modules retain their original boundaries to keep review and future
extraction into a common backend straightforward. Product names, repo identity,
GUI adapters, version discovery, and registration remain product-specific;
do not couple Toolbox project or EEG contracts to the updater.

Startup checks are registered before the one-second launch timer and run once
per window, subject to the existing 24-hour successful-check debounce. A manual
check cancels and supersedes a pending startup scan; late startup results never
reopen a dismissed manual dialog. Cancellation still drains through the
application-owned lifecycle before worker disposal.

Separate startup housekeeping calls the existing guarded cache cleanup once per
window even when the network check is debounced or superseded. It runs in a
lifecycle-owned worker, cancels with shutdown, and logs failures without
interrupting startup. Manual checks cancel only the network scan. The packaged
Main Window probe suppresses both startup tasks.

The managed apply window uses a 480x140 minimum and 560x160 default. It retains
the target version across technical phase changes, shows indeterminate progress
during installation and completed progress on success, and expands to show the
full error plus Repair/Close when needed. The target version is in-process
presentation data; the private protocol remains version 1. Title-bar Close and
Escape can request cancellation before installation commits; committed setup
continues to completion.

The application-wide `UpdateLifecycle.eventFilter` consumes only application
Quit events while updater jobs need shutdown coordination. Other deliveries
return `False` directly: calling the no-op QObject base filter adds an unnecessary
PySide argument conversion, which failed for an item wrapper reported during
Dataset Exclusions scrolling. Keep ordinary GUI events outside updater work.

`Main_App.Project` remains available through a lazy compatibility attribute.
The updater must not import project models, `config`, NumPy, MNE, analysis tools,
or the main window. `config.py:FPVS_TOOLBOX_VERSION` remains the single source
version owner; the build extracts it without importing config and embeds
`toolbox-updater-version.json` in both frozen applications.

## Toolbox identity and installation

- Repository: `zcm58/FPVS-Toolbox-Repo`.
- Application: `FPVS_Toolbox.exe`; independent helper:
  `Updater/FPVS Toolbox Updater.exe`, with its own Python/Qt runtime.
- Existing Inno AppId is preserved:
  `77E578C2-2B30-4015-AE3F-9CE6191423F4`.
- Existing full installer name is preserved:
  `FPVSToolbox-<version>-setup.exe`.
- Direct patch: `FPVSToolbox-Patch-<from>-to-<to>.exe`;
  metadata: `FPVSToolbox-Update-<version>.json`.
- Windows cache: `%LOCALAPPDATA%/FPVS Toolbox/updates`; helper staging and
  installation locks use sibling updater directories. No project settings or
  analysis outputs belong in this cache.
- Ownership file: `fpvs-owned-files-v1.txt`, header
  `FPVS-TOOLBOX-OWNED-FILES-1`. Never accept Studio ownership as Toolbox ownership.

Registration is read from the existing uninstall key in HKCU or HKLM. The
helper validates the install directory and caller identity. Per-user updates
run without elevation. All-users updates request Windows administrator approval
only for the verified native setup, retain `/ALLUSERS`, and restart from the
unelevated helper. Canceling approval produces an explicit error. The process
handle/wait flags follow Microsoft's
[ShellExecuteEx contract](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-shellexecuteinfow).
Native application replacement is Windows-only; source checks and backend code
remain portable to CachyOS.

## Discovery, download, and handoff

1. Discovery uses release metadata and the installed inventory identity to
   offer a direct patch when supported, or the full installer otherwise. It
   does not repeatedly hash the installed scientific runtime while checking.
2. Download streams into a guarded temporary cache file, reports progress,
   verifies expected size/SHA-256, then publishes the file and receipt.
3. Explicit install confirmation checks Toolbox's processing/export/QC guards,
   including unparented SNR/Scalp workers and globally registered FHC operations.
   Save/Discard/Cancel for project drafts resolves before handoff; saving that
   starts background work blocks installation until it finishes. Draft consent
   applies only during the immediate successful-handoff close call; ordinary
   closes retain their prompt and all existing active-work close guards.
   A staged helper validates the request and acknowledges ownership before
   Toolbox follows its existing close path. Closing an update dialog cancels
   uncommitted work without destroying running Qt threads.
4. The helper waits on the actual parent process, rejects other running
   Toolbox instances, takes the installation lock, and verifies the package
   again immediately before launch. The native patch validates its exact
   baseline after Toolbox exits.
5. Setup completes before restart. Cancellation stops before installation is
   committed; a running installer is never forcibly canceled. A failed patch
   leaves an explicit recovery state and offers the full installer for repair.

The full installer preserves files it cannot prove it owns. Patches verify
baseline hashes, reject unsafe linked/colliding paths, track replacement
transactions, and require a valid target inventory. A patch must not repair an
unknown partial installation by guessing ownership. Invalid metadata,
untrusted URLs, checksum failures, and registration mismatches remain visible
errors rather than silent browser/download fallbacks.

## Packaging and migration

Older Toolbox builds do not bundle this helper or an authenticated ownership
inventory. They need the first full installer containing this implementation.
That installer establishes a baseline for future patches. Do not create
historical ownership by scanning a user's installation or relabeling an old
release. No version bump or public release is part of this implementation.

The normal release wrapper builds the main bundle, independently builds and
checks the helper, generates inventories from the final bundle, and compiles
the full installer. Optional authenticated baseline inventories produce direct
patches. For example, in a safe visible Windows session:

```powershell
./scripts/packaging/build_release.ps1 -AllowVisibleGui
```

For a later patch release, pass matching arrays of `-BaselineInventory` and
`-BaselineInventorySha256` to `build_release.ps1` or `build_installer.ps1`.
Each hash must authenticate the retained published source inventory. The patch
builder verifies the target's bundled version data and inventory before
producing native payloads. Retain each release's
`build/installer-inventory/current-owned-files.txt` with its release provenance;
never substitute a locally installed tree. Publish the generated full setup,
patches, update JSON, and their generated `.sha256` sidecars together. The first release has no
patches unless an eligible published baseline exists.

The helper-only build is:

```powershell
./scripts/packaging/build_updater.ps1 -AllowVisibleGui
```

The packaging check requires correct embedded version, frozen execution,
protocol 1, and no GUI or scientific imports in worker mode. The optional
bounded native GUI check exercises independent progress/repair states without
network traffic or installation. The existing full-app build may need separate
packaged-app validation; compiling the helper alone does not validate the full
scientific bundle.
The helper build preserves and checks the main bundle's build-time version
metadata. A mismatched or older main bundle must be rebuilt; changing helper
metadata cannot relabel an existing main executable.

`smoke_packaged_app.ps1` is mandatory unless the maintainer explicitly requests
the development-only `-SkipSmoke` bypass. Missing/failed smoke is an error.
The default probe launches the frozen main executable in a GUI-free diagnostic
mode, verifies its exact config/embedded version and frozen executable identity,
and imports the scientific dependencies. `-AllowVisibleGui` additionally reaches
the actual Main Window, runs the native event loop and exits deterministically.
Without that opt-in the build explicitly reports visible acceptance as pending;
dependency checks alone never certify GUI or installation behavior. Reports are
written beneath `build/packaged-smoke/` with unique names and bounded process
timeouts. Both modes isolate settings, legacy migration, caches and projects;
the visible probe suppresses startup update/network/old-executable cleanup.

Inno now requires explicit display and numeric Windows versions. The build
derives the latter from the canonical version, so an RC such as `3.0.0rc1`
retains its display/asset identity while Windows file metadata uses `3.0.0.0`.
There is no silent installer-version fallback.

Keep public GitHub release notes to brief, nontechnical changes. Do not include
validation details; for example, "Improved app updates and patch installation."

## Verification and manual acceptance

Scroll regression: in Dataset Exclusions with more than one screen of entries,
scroll the table both ways after editing a scope. Confirm choices and selection
remain intact, no reload/save is triggered, and no event-filter tracebacks appear.
`test_dataset_exclusions_qt.py` exercises 60 visible wheel events against a
54-entry synthetic list with the updater lifecycle installed; the updater GUI
suite replays the reported dispatcher/item callback and verifies Quit handling.

```console
python .agents/scripts/verify.py --scope updates --tier focused
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
python scripts/packaging/check_installer_compile.py --inno-compiler <ISCC.exe>
python scripts/packaging/check_patch_installer_lifecycle.py --inno-compiler <ISCC.exe> --execute
```

Qt coverage is registered in `tests/qt_test_files.txt`. In a user-approved safe
visible session only, run `tests/gui/test_update_dialog.py` and
`tests/gui/test_update_manager_manual_force.py` with `FPVS_ALLOW_QT_TESTS=1`.
Never set the platform to offscreen. Native installer fixtures use a synthetic
AppId and disposable directory, preserve user-data sentinels, and compare
production registration before and after.

Before a public release, use a disposable Windows installation to confirm:

- Open and dismiss File > Check for Updates immediately after launch; verify
  the startup timer/result never creates a second prompt. During handoff, try
  Save, Discard and Cancel with unsaved setup changes; Cancel never launches the
  helper and Discard is not requested again after handoff.
- Check compact managed progress at 480x140 and 560x160 with long version text;
  exercise pre-commit cancellation, committed-close protection, success/restart,
  and expanded failure details with full-installer repair.
- File > Check for Updates stays responsive during discovery/download,
  cancellation and retry; minimum dialog size and long status text fit.
- Processing, export and QC block installation; normal close guards remain
  effective. A second running Toolbox process prevents replacement.
- A supported direct patch installs and restarts; an old installation takes
  the full installer and becomes eligible for the next supported patch.
- Standalone Update & Repair works with the main runtime missing; a failed
  patch can recover through the full installer.
- Per-user and all-users upgrades preserve scope. Exercise genuine UAC
  cancellation and acceptance, app restart, user settings and project sentinels.
- A clean machine can run both the packaged main application and helper.
