# Independent Toolbox updater handoff

Implemented on `codex/standalone-updater`, based on Toolbox `56392587`, in an
isolated worktree. The existing Toolbox checkout and its unrelated uncommitted
work were preserved. Version remains 3.0.0; no release or production installation
was performed. See [the updater architecture](../architecture/updater.md) for
contracts, migration, packaging and manual acceptance.

## Verification on Windows, 2026-09-15

The existing Toolbox Python 3.13 environment was used. Qt checks used the
previously approved native visible session, never offscreen execution.

| Command/check | Result |
| --- | --- |
| `python .agents/scripts/verify.py --scope updates --tier focused` | 430 passed; 4 symlink-privilege skips; GUI/path audits, Ruff and compilation passed |
| `python .agents/scripts/verify.py --scope gui --tier focused` | 472 passed; audit, Ruff and compilation passed |
| `python -m pytest tests/gui/test_update_dialog.py tests/gui/test_update_manager_manual_force.py -q` with `FPVS_ALLOW_QT_TESTS=1` | 69 passed, including final Toolbox copy, minimum-size layout, cancel/shutdown, repair and active-work guards |
| `build_updater.ps1 -Python <Toolbox Python> -AllowVisibleGui` | Built independent helper; frozen version 3.0.0, protocol 1, no GUI/scientific imports in worker diagnostic; native visible repair/progress smoke passed without network/install |
| `check_installer_compile.py --inno-compiler <ISCC.exe>` | Native Inno script compiled |
| `check_patch_installer_lifecycle.py --inno-compiler <ISCC.exe> --execute` | 15 scenarios passed: initial full migration without historical ownership, baseline corruption/collisions/links, patch parity, upgrade, failure recovery, repair and uninstall; user sentinels and production registration preserved |
| Live PowerShell build-script version guard, four disposable fixtures | Matching bundle/helper-only accepted; mismatched or missing main version metadata rejected without relabeling main files |
| `python .agents/scripts/verify.py --scope repo --tier precommit` | All audits, changed-file Ruff and compilation passed; non-Qt suite: 4,904 passed, 11 skipped, 1 failed on Windows access-denied replacing a temporary Stats project manifest |
| `python -m pytest tests/stats/data/test_group_harmonic_cache.py -q` | All 16 passed on immediate rerun; failing source and test files were unchanged |
| Final `agent_audit.py`, `git diff --check`, changed PowerShell parser checks | Passed |

The full precommit invocation was not wholly green: its one transient-looking
Windows file-access failure is recorded above, and the entire suite was not
repeated after the affected file passed. Do not report this as an entirely
clean precommit run. No Stats code was changed to suppress the failure.

The compiled helper and isolated native fixtures are development verification
artifacts. A complete scientific application bundle, upgrade on a disposable
real installation, clean-machine execution, and genuine all-users UAC/restart
acceptance remain release checks. The native elevation adapter was tested with
mock Windows API outcomes, including cancellation and process-handle cleanup.
No real administrator installation was performed.

## Changed files

Paths below are repository-relative. The list excludes ignored build/test
artifacts; the completed temporary execution plan was removed.

- `.agents/verification.toml`
- `ARCHITECTURE.md`
- `docs/agent/agent-index.md`
- `docs/agent/architecture/gui.md`
- `docs/agent/architecture/updater.md`
- `docs/agent/reviews/independent-updater.md`
- `scripts/packaging/FPVS Toolbox Setup Script.iss`
- `scripts/packaging/FPVS_Toolbox.spec`
- `scripts/packaging/FPVS_Updater.spec`
- `scripts/packaging/build_installer.ps1`
- `scripts/packaging/build_installer_inventory.py`
- `scripts/packaging/build_patch.py`
- `scripts/packaging/build_release.ps1`
- `scripts/packaging/build_updater.ps1`
- `scripts/packaging/check_installer_compile.py`
- `scripts/packaging/check_installer_tree.py`
- `scripts/packaging/check_patch_installer_lifecycle.py`
- `scripts/packaging/owned_files.iss`
- `scripts/packaging/patch_upgrade.iss`
- `scripts/packaging/updater_cache.iss`
- `scripts/packaging/updater_metadata.py`
- `scripts/packaging/updater_qt_runtime.py`
- `src/Main_App/__init__.py`
- `src/Main_App/gui/update_dialog.py`
- `src/Main_App/gui/update_install_guard.py`
- `src/Main_App/gui/update_lifecycle.py`
- `src/Main_App/gui/update_manager.py`
- `src/Main_App/gui/updater_presentation.py`
- `src/Main_App/gui/updater_window.py`
- `src/Main_App/updater_main.py`
- `src/Main_App/updates/__init__.py`
- `src/Main_App/updates/application.py`
- `src/Main_App/updates/cache.py`
- `src/Main_App/updates/cache_io.py`
- `src/Main_App/updates/downloader.py`
- `src/Main_App/updates/elevation.py`
- `src/Main_App/updates/github_releases.py`
- `src/Main_App/updates/helper_client.py`
- `src/Main_App/updates/helper_protocol.py`
- `src/Main_App/updates/helper_runtime.py`
- `src/Main_App/updates/helper_service.py`
- `src/Main_App/updates/installer.py`
- `src/Main_App/updates/models.py`
- `src/Main_App/updates/patches.py`
- `src/Main_App/updates/process_launch.py`
- `src/Main_App/updates/validation.py`
- `src/updater.py`
- `tests/gui/test_update_dialog.py`
- `tests/gui/test_update_manager_manual_force.py`
- `tests/qt_test_files.txt`
- `tests/updates/conftest.py`
- `tests/updates/test_installer_inventory.py`
- `tests/updates/test_patch_packaging.py`
- `tests/updates/test_toolbox_adapter.py`
- `tests/updates/test_update_cache.py`
- `tests/updates/test_update_check.py`
- `tests/updates/test_update_download.py`
- `tests/updates/test_update_helper.py`
- `tests/updates/test_update_patch.py`
- `tests/updates/test_updater_main.py`
