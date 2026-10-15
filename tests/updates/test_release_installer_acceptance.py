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
    (destination / "unins001.exe").write_bytes(b"inert second numbered uninstaller")
    (destination / "unins001.dat").write_bytes(b"inert uninstall log")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "application": "fpvs-toolbox",
        "releases": [{"tag": "v2.1.2", "asset_name": "FPVSToolbox-2.1.2-setup.exe",
                      "asset_id": 450622129, "size_bytes": 141503904, "sha256": acceptance.BASELINE_SHA256}],
        "files": [{"path": "FPVS_Toolbox.exe", "sha256": [hashlib.sha256(b"inert baseline").hexdigest()]}]}))
    assert acceptance.assert_baseline_catalog(destination, catalog)["owned_files_verified"] == 1
    (destination / "unknown.pyd").write_bytes(b"extra legacy extension")
    with pytest.raises(RuntimeError, match=r"unexpected paths: \['unknown.pyd'\]"):
        acceptance.assert_baseline_catalog(destination, catalog)
    (destination / "unknown.pyd").unlink()
    # Only numbered root bookkeeping is exempt; nested lookalikes stay visible.
    (destination / "nested").mkdir()
    (destination / "nested/unins001.dat").write_bytes(b"unrelated nested content")
    with pytest.raises(RuntimeError, match="nested/unins001.dat"):
        acceptance.assert_baseline_catalog(destination, catalog)
    (destination / "nested/unins001.dat").unlink()
    (destination / "unins-notes.txt").write_bytes(b"unrelated root content")
    with pytest.raises(RuntimeError, match="unins-notes.txt"):
        acceptance.assert_baseline_catalog(destination, catalog)
    (destination / "unins-notes.txt").unlink()
    (destination / "FPVS_Toolbox.exe").write_bytes(b"changed bytes")
    with pytest.raises(RuntimeError, match="differs from its ownership catalog"):
        acceptance.assert_baseline_catalog(destination, catalog)


def test_uninstaller_uses_the_registered_number_and_rejects_escaped_commands(acceptance, tmp_path):
    executable = tmp_path / "unins001.exe"
    record = {"InstallLocation": str(tmp_path), "UninstallString": f'"{executable}"'}
    assert acceptance.registered_uninstaller(tmp_path, [record, dict(record)]) == executable
    for command in (str(tmp_path.parent / "unins001.exe"), str(tmp_path / "other.exe"),
                    f'"{executable}" /extra', "unins001.exe"):
        with pytest.raises(RuntimeError, match="escaped"):
            acceptance.registered_uninstaller(tmp_path, [{**record, "UninstallString": command}])
    with pytest.raises(RuntimeError, match="one disposable"):
        acceptance.registered_uninstaller(tmp_path, [])
    with pytest.raises(RuntimeError, match="one disposable"):
        acceptance.registered_uninstaller(tmp_path, [record, {**record, "UninstallString": str(tmp_path / "unins000.exe")}])


def test_uninstall_waits_for_the_second_phase_and_has_a_deadline(acceptance, tmp_path, monkeypatch):
    executable = tmp_path / "unins001.exe"
    executable.write_bytes(b"inert uninstaller still finishing")
    data = tmp_path / "unins001.dat"
    data.write_bytes(b"uninstall log still being removed")
    message = tmp_path / "unins001.msg"
    message.write_bytes(b"uninstall language data still being removed")
    notes = tmp_path / "unins-notes.txt"
    notes.write_bytes(b"unrelated user file")
    records = [{}]
    sleeps = []
    monkeypatch.setattr(acceptance, "registrations", lambda: records)
    def finish(_seconds):
        sleeps.append(_seconds)
        if len(sleeps) == 1:
            records.clear()
            executable.unlink()
        else:
            data.unlink()
            message.unlink()
    monkeypatch.setattr(acceptance.time, "sleep", finish)
    acceptance.wait_for_uninstall(tmp_path, executable)
    assert sleeps == [0.1, 0.1]
    assert notes.read_bytes() == b"unrelated user file"
    executable.write_bytes(b"uninstaller did not finish")
    with pytest.raises(RuntimeError, match="in time"):
        acceptance.wait_for_uninstall(tmp_path, executable, timeout=0)
    assert executable.read_bytes() == b"uninstaller did not finish"


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


@pytest.mark.parametrize("message_succeeds", [True, False])
def test_foreign_control_caption_read_is_bounded_and_ignores_failed_buffer(acceptance, message_succeeds):
    import ctypes
    from types import SimpleNamespace

    calls = []

    def send(hwnd, message, count, address, flags, timeout, result):
        calls.append((hwnd, message, flags, timeout))
        assert isinstance(address, int)
        buffer = (ctypes.c_wchar * count).from_address(address)
        buffer.value = "&Next >"
        ctypes.cast(result, ctypes.POINTER(ctypes.c_size_t)).contents.value = len(buffer.value)
        return int(message_succeeds)

    native = acceptance.NativeWindows.__new__(acceptance.NativeWindows)
    native.user32 = SimpleNamespace(SendMessageTimeoutW=send)
    assert native.control_text(123) == ("&Next >" if message_succeeds else "")
    assert calls == [(123, 0x000D, 0x0022, 100)]


def test_control_message_signature_preserves_pointer_width(acceptance, monkeypatch):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    class FakeDLL:
        def __init__(self):
            self.functions = {}

        def __getattr__(self, name):
            return self.functions.setdefault(name, SimpleNamespace())

    user32 = FakeDLL()
    kernel32 = FakeDLL()
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_kwargs: user32 if name == "user32" else kernel32, raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", lambda *_args: object(), raising=False)
    acceptance.NativeWindows()
    assert user32.SendMessageTimeoutW.restype is ctypes.c_ssize_t
    assert user32.SendMessageTimeoutW.argtypes == [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]


# Inno 6.7.1 modern caption captured in run 38786752342; also retain classic spelling.
@pytest.mark.parametrize("next_caption", ["&Next", "&Next >"])
def test_setup_button_selection_retains_foreign_control_diagnostics(acceptance, next_caption):
    import ctypes
    from types import SimpleNamespace

    controls = {
        0: ("&Install", True, True),
        1: ("&Cancel", True, True),
        2: ("&Install", True, False),
        3: ("&Finish", False, True),
        4: (next_caption, True, True),
    }
    clicks = []

    def enumerate_children(_hwnd, callback, data):
        for handle in controls:
            assert callback(handle, data)

    def send(hwnd, _message, count, address, _flags, _timeout, _result):
        (ctypes.c_wchar * count).from_address(address).value = controls[hwnd][0]
        return 1

    def caption(_hwnd, buffer, _count):
        # Simulate an unreadable foreign control caption.
        buffer.value = ""
        return 0

    def class_name(hwnd, buffer, _count):
        buffer.value = "TNewStaticText" if hwnd == 0 else "TNewButton"
        return len(buffer.value)

    native = acceptance.NativeWindows.__new__(acceptance.NativeWindows)
    native.callback_type = lambda callback: callback
    native.last_setup_controls = {}
    native.user32 = SimpleNamespace(
        EnumChildWindows=enumerate_children, SendMessageTimeoutW=send, GetWindowTextW=caption,
        GetClassNameW=class_name, IsWindowVisible=lambda handle: controls[handle][1],
        IsWindowEnabled=lambda handle: controls[handle][2],
        PostMessageW=lambda *args: clicks.append(args) or 1,
    )
    assert native.advance_setup(100) == next_caption.replace("&", "")
    assert clicks == [(4, 0x00F5, 0, 0)]
    assert native.last_setup_controls[100][2] == {
        "class": "TNewButton", "caption": "&Install", "visible": True, "enabled": False,
    }
    assert native.last_setup_controls[100][4]["caption"] == next_caption


def test_relaunch_timeout_retains_control_evidence_and_terminates_fixture_process(acceptance, tmp_path, monkeypatch):
    from types import SimpleNamespace

    controls = {100: [{"class": "TNewButton", "caption": "&Next >", "visible": True, "enabled": False}]}
    process = SimpleNamespace(pid=123, returncode=None)
    process.poll = lambda: process.returncode
    process.kill = lambda: setattr(process, "returncode", 1)
    waits = []
    process.wait = lambda **kwargs: waits.append(kwargs)
    native = SimpleNamespace(last_setup_controls=controls, windows=lambda _pids: [(100, "Setup - FPVS Toolbox 3.0.0")],
                             advance_setup=lambda _hwnd: None)
    monkeypatch.setattr(acceptance, "NativeWindows", lambda: native)
    monkeypatch.setattr(acceptance.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(acceptance.psutil, "Process", lambda _pid: SimpleNamespace(children=lambda **_kwargs: []))
    monkeypatch.setattr(acceptance, "app_processes", lambda _path: [])
    ticks = iter((0, 0, 301))
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)
    # No application windows exist; setup windows belong only to the fixture PID.
    native.windows = lambda pids: [(100, "Setup - FPVS Toolbox 3.0.0")] if pids else []
    with pytest.raises(RuntimeError, match="controls=.*TNewButton"):
        acceptance.visible_relaunch(tmp_path / "setup.exe", tmp_path / "installed", tmp_path, {})
    evidence = json.loads((tmp_path / "relaunch-controls.json").read_text(encoding="utf-8"))
    assert evidence["last_setup_controls"]["100"] == controls[100]
    assert evidence["actions"] == []
    assert process.returncode == 1
    assert waits == [{"timeout": 30}]
