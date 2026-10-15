"""Safety and evidence tests; never install or start an application locally."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/packaging"


@pytest.fixture
def acceptance(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("release_acceptance_fixture", SCRIPTS / "check_release_installer.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("environment,platform", [({}, "win32"), ({"CI": "true"}, "win32"),
                         ({"CI": "true", "GITHUB_ACTIONS": "true"}, "linux"),
                         ({"CI": "true", "GITHUB_ACTIONS": "true"}, "win32"),
                         ({"CI": "true", "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "self-hosted"}, "win32")])
def test_real_installer_refuses_local_or_non_windows_execution(acceptance, environment, platform):
    with pytest.raises(RuntimeError, match="disposable GitHub Windows runner"):
        acceptance.require_disposable_runner(environment, platform)


def test_disposable_runner_requires_existing_absolute_root_and_native_qt(acceptance, tmp_path):
    env = {"CI": "true", "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
           "RUNNER_TEMP": str(tmp_path)}
    assert acceptance.require_disposable_runner(env, "win32") == tmp_path.resolve()
    for platform in (*acceptance.HEADLESS_QT_PLATFORMS,
                     *(f"{name}:unused" for name in acceptance.HEADLESS_QT_PLATFORMS)):
        with pytest.raises(RuntimeError, match="native visible"):
            acceptance.require_disposable_runner({**env, acceptance.QT_PLATFORM_ENV: platform}, "win32")
    with pytest.raises(RuntimeError, match="existing absolute"):
        acceptance.require_disposable_runner(dict(env, RUNNER_TEMP="relative"), "win32")


def test_installer_paths_cannot_escape_or_replace_temporary_root(acceptance, tmp_path):
    root = tmp_path / "temporary"
    root.mkdir()
    assert acceptance.require_within(root / "install", root) == root / "install"
    with pytest.raises(ValueError):
        acceptance.require_within(root / ".." / "other", root)
    with pytest.raises(RuntimeError, match="child"):
        acceptance.require_within(root, root)


def test_user_data_evidence_detects_missing_or_modified_sentinels(acceptance, tmp_path):
    expected = acceptance.seed_user_data(tmp_path)
    acceptance.assert_sentinels(expected)
    sample, value = next(iter(expected.items()))
    sample.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed user data"):
        acceptance.assert_sentinels(expected)
    sample.write_bytes(value)
    acceptance.assert_sentinels(expected)
    sample.unlink()
    with pytest.raises(RuntimeError, match="changed user data"):
        acceptance.assert_sentinels(expected)


def test_failed_native_command_retains_failure_log(acceptance, tmp_path):
    import os

    log = tmp_path / "process.log"
    with pytest.raises(RuntimeError, match=r"failed \(7\)"):
        acceptance.run([sys.executable, "-c", "import sys; sys.stderr.write('fixture failure'); sys.exit(7)"],
                       log, env=dict(os.environ))
    assert log.read_bytes() == b"fixture failure"


def test_timed_out_native_command_retains_partial_failure_log(acceptance, tmp_path):
    import os

    log = tmp_path / "timeout.log"
    with pytest.raises(RuntimeError, match="timed out"):
        acceptance.run([sys.executable, "-c", "import time; print('failure evidence', flush=True); time.sleep(10)"],
                       log, env=dict(os.environ), timeout=1)
    assert b"failure evidence" in log.read_bytes()
    assert b"timed out after 1 seconds" in log.read_bytes()


@pytest.mark.parametrize("code", [0xC0000005, 1, None])
def test_observed_window_cannot_hide_an_application_crash_or_running_process(acceptance, code):
    from types import SimpleNamespace

    native = SimpleNamespace(exit_code=lambda _handle: code)
    with pytest.raises(RuntimeError, match="did not exit normally"):
        acceptance.require_clean_app_exits(native, {123: 456})
    native.exit_code = lambda _handle: 0
    assert acceptance.require_clean_app_exits(native, {123: 456}) == {123: 0}
    with pytest.raises(RuntimeError, match="process evidence"):
        acceptance.require_clean_app_exits(native, {})


def test_installed_evidence_checks_bytes_and_registration(acceptance, tmp_path, monkeypatch):
    import build_installer_inventory as inventory

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "FPVS_Toolbox.exe").write_bytes(b"inert test artifact")
    output = tmp_path / "inventory"
    inventory.build_inventories(bundle_root=bundle, app_version="3.0.0", legacy_inventory=None, output_dir=output)
    manifest = output / "current-owned-files.txt"
    (bundle / "fpvs-owned-files-v1.txt").write_bytes(manifest.read_bytes())
    record = {"InstallLocation": str(bundle), "DisplayVersion": "3.0.0"}
    monkeypatch.setattr(acceptance, "registrations", lambda: [record])
    assert acceptance.assert_installed(bundle, manifest, "3.0.0")["owned_files_verified"] == 1
    record["InstallLocation"] = str(tmp_path / "other")
    with pytest.raises(RuntimeError, match="isolated path"):
        acceptance.assert_installed(bundle, manifest, "3.0.0")
    record["InstallLocation"] = str(bundle)
    (bundle / "FPVS_Toolbox.exe").write_bytes(b"changed bytes")
    with pytest.raises(RuntimeError, match="release bytes differ"):
        acceptance.assert_installed(bundle, manifest, "3.0.0")


def test_baseline_catalog_is_independently_checked_against_installed_bytes(acceptance, tmp_path):
    destination = tmp_path / "installed"
    destination.mkdir()
    (destination / "FPVS_Toolbox.exe").write_bytes(b"inert baseline")
    (destination / "unins000.exe").write_bytes(b"inert uninstaller")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "application": "fpvs-toolbox",
        "releases": [{"tag": "v2.1.2", "asset_name": "FPVSToolbox-2.1.2-setup.exe",
                      "asset_id": 450622129, "size_bytes": 141503904, "sha256": acceptance.BASELINE_SHA256}],
        "files": [{"path": "FPVS_Toolbox.exe", "sha256": [hashlib.sha256(b"inert baseline").hexdigest()]}]}))
    assert acceptance.assert_baseline_catalog(destination, catalog)["owned_files_verified"] == 1
    (destination / "unknown.pyd").write_bytes(b"extra legacy extension")
    with pytest.raises(RuntimeError, match="files absent"):
        acceptance.assert_baseline_catalog(destination, catalog)
    (destination / "unknown.pyd").unlink()
    (destination / "FPVS_Toolbox.exe").write_bytes(b"changed bytes")
    with pytest.raises(RuntimeError, match="differs from its ownership catalog"):
        acceptance.assert_baseline_catalog(destination, catalog)


def test_exact_release_metadata_rejects_changed_artifact_bytes(acceptance, tmp_path):
    from build_patch import build_release_manifest

    installer = tmp_path / "FPVSToolbox-3.0.0-setup.exe"
    installer.write_bytes(b"inert acceptance installer")
    metadata = build_release_manifest(target_version="3.0.0", installer_dir=tmp_path, patch_builds=[])
    digests = acceptance.verify_release_metadata(installer, "3.0.0")
    assert set(digests) == {installer.name, metadata.name}
    installer.write_bytes(b"changed after checksum publication")
    with pytest.raises(RuntimeError, match="checksum sidecar differs"):
        acceptance.verify_release_metadata(installer, "3.0.0")
