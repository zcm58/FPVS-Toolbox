# Updater workflow parity — 2026-09-25

The `codex/studio-style-updates` branch adapts the current FPVS Studio updater
workflow to Toolbox's purpose-based packages. Existing verified download,
patch/full selection, authenticated inventories, independent runtime, scope/UAC,
and repair contracts remain in place. No scientific method or project format
changed, and no release/version bump or production installation was performed.

## Changes

- Compact managed progress retains the target version, shows completion, and
  expands failure details and repair actions. Cancellation remains available
  before installation commits.
- Manual checks supersede startup checks and suppress late duplicate prompts.
  Separate background housekeeping prunes the guarded update cache regardless
  of network debounce, logs failures, and cancels safely with shutdown.
- Project Save/Discard/Cancel resolves before the helper accepts handoff. Active
  tool/project work blocks installation; normal close guards remain effective.
- Packaged smoke is required by default. Dependency-only and visible acceptance
  are distinct; missing/failed smoke cannot silently count as success. Probes
  use disposable settings/projects and never install anything.
- Inno requires canonical display and numeric Windows versions, including RC
  support. The obsolete MNE BDF hidden import uses its current EDF/BDF owner.
- User installation/update/repair instructions are in the docs navigation.

See [updater architecture](../architecture/updater.md) for ownership, migration,
cache paths, and the complete visible smoke sequence. Update data remains in the
application-owned per-user cache; EEG/project I/O remains under each active
`Project.project_root`. No machine-specific path was added. Windows installer
names, AppId, ownership headers, and existing cache identity remain unchanged.

## Verification

- `.venv/Scripts/python.exe .agents/scripts/verify.py --scope updates --tier focused`
  passed 483 tests with four platform skips after final startup-maintenance
  integration. GUI/path audits, changed-file Ruff and compilation passed.
- `--scope repo --tier precommit` passed all audits, Ruff and compilation;
  pytest reported 5,248 passed, 11 skipped and one failure in the unchanged
  FHC analysis-plan preference test: Windows denied replacement of its temporary
  `analysis_plan.json`. The isolated file rerun passed all eight tests. The full
  invocation was not wholly green and was not repeated; final startup-maintenance
  additions were verified by the focused gate above.
- Registered Qt suites and Main Window code passed final Ruff/compilation;
  the earlier safe GUI-focused gate passed 562 non-Qt tests.
- Strict MkDocs build passed using `build/docs-updater-parity`.
- `build_updater.ps1 -Python ./.venv/Scripts/python.exe` built the independent
  helper and passed its frozen diagnostic: version 3.0.0, protocol 1, no GUI or
  analysis imports in worker mode. Build output remains ignored under `dist/`;
  it is not a full application/installer release.
- Packaging PowerShell parser checks passed. Headless tests exercise missing
  smoke, failed/incorrect reports, dependency failures, isolated preferences and
  prerelease numeric versions.
- Independent runtime and packaging reviews found no outstanding actionable
  issue after the independent-helper import boundary was corrected.

`tests/gui/test_update_dialog.py` and
`tests/gui/test_update_manager_manual_force.py` define registered CI-only Qt
coverage. They were compiled but not executed locally. Visible acceptance must
exercise immediate manual/startup overlap, draft Save/Discard/Cancel, active
analysis blockers, compact/long-version progress, cancellation before commit,
committed-close protection, success/restart, and failure/repair. The disposable
packaged Main Window probe is available via `-AllowVisibleGui` in an approved
native session. No offscreen run was performed.

The Inno compiler is absent from PATH and standard installation locations, so
`check_installer_compile.py --inno-compiler <ISCC.exe>` and native full/patch
lifecycle fixtures could not run. A complete rebuilt frozen bundle, clean-machine
execution, installed upgrade/repair, and genuine all-users UAC remain release
acceptance. Source diagnostics and mocked-process tests do not replace them.

## Changed files

- `.agents/verification.toml`
- `docs/agent/architecture/updater.md`
- `docs/agent/exec-plans/active/v3-release-readiness.md`
- `docs/agent/reviews/updater-workflow-parity.md`
- `docs/user/installing-and-updating.md`
- `mkdocs.yml`
- `scripts/packaging/FPVS Toolbox Setup Script.iss`
- `scripts/packaging/FPVS_Toolbox.spec`
- `scripts/packaging/build_installer.ps1`
- `scripts/packaging/build_release.ps1`
- `scripts/packaging/check_installer_compile.py`
- `scripts/packaging/check_patch_installer_lifecycle.py`
- `scripts/packaging/smoke_packaged_app.ps1`
- `scripts/packaging/updater_metadata.py`
- `src/Main_App/diagnostics/packaged_smoke.py`
- `src/Main_App/gui/main_window.py`
- `src/Main_App/gui/update_dialog.py`
- `src/Main_App/gui/update_install_guard.py`
- `src/Main_App/gui/update_manager.py`
- `src/Main_App/gui/updater_window.py`
- `src/Main_App/updates/helper_service.py`
- `src/Main_App/updates/models.py`
- `src/main.py`
- `tests/gui/test_update_dialog.py`
- `tests/gui/test_update_manager_manual_force.py`
- `tests/updates/test_packaged_smoke.py`
- `tests/updates/test_update_helper.py`
- `tests/updates/test_update_install_guard.py`
- `tests/updates/test_update_startup_coordination.py`
