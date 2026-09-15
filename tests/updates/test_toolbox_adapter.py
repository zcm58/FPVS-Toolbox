"""Toolbox-specific registration, scope, source entry and metadata boundaries."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.updates import helper_runtime, installer
from Main_App.updates.application import APP_VERSION, source_version
from Main_App.updates.models import DownloadedInstaller, InstallerAsset, UpdateError


def test_source_helper_starts_from_unrelated_working_directory(tmp_path):
    command = helper_runtime.helper_command("--packaging-check", str(tmp_path / "report.json"))
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["version"] == APP_VERSION
    assert not report["gui_loaded"] and not report["analysis_loaded"]


@pytest.mark.parametrize("machine", [False, True])
def test_registry_preserves_existing_installation_scope(tmp_path, monkeypatch, machine):
    root = tmp_path / "installation"
    root.mkdir()

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def open_key(hive, *_):
        if machine and hive == 1:
            raise FileNotFoundError
        assert hive == (2 if machine else 1)
        return Key()

    registry = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        HKEY_LOCAL_MACHINE=2,
        KEY_READ=1,
        KEY_WOW64_64KEY=2,
        REG_SZ=1,
        OpenKey=open_key,
        QueryValueEx=lambda _key, field: (str(root) if field == "InstallLocation" else "3.0.0", 1),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(sys, "platform", "win32")
    installed = helper_runtime.registered_installation()
    assert installed.root == root and installed.version == "3.0.0"
    assert installed.all_users is machine


def test_all_users_install_uses_elevation_only_after_integrity_check(tmp_path, monkeypatch):
    payload = b"inert installer fixture"
    name = "FPVSToolbox-3.1.0-setup.exe"
    digest = hashlib.sha256(payload).hexdigest()
    asset = InstallerAsset(
        name,
        f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v3.1.0/{name}",
        len(payload),
        digest,
        "3.1.0",
        123,
    )
    file = tmp_path / name
    file.write_bytes(payload)
    downloaded = DownloadedInstaller(file, len(payload), digest, asset)
    commands = []
    monkeypatch.setattr(installer, "launch_elevated_installer", lambda command: commands.append(command))
    root = tmp_path / "installed app"
    installer.launch_installer(downloaded, managed=True, install_root=root, all_users=True)
    assert commands[0][-1] == "/ALLUSERS"
    assert f"/DIR={root}" in commands[0] and "/NOLAUNCH=1" in commands[0]
    file.write_bytes(b"x" * len(payload))
    with pytest.raises(UpdateError):
        installer.launch_installer(downloaded, managed=True, install_root=root, all_users=True)
    assert len(commands) == 1


def test_config_remains_the_single_source_version_owner():
    config = Path(__file__).resolve().parents[2] / "src/config.py"
    assert APP_VERSION == source_version(config)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UAC API adapter")
@pytest.mark.parametrize("wait_result", [0, 0xFFFFFFFF])
def test_elevated_setup_waits_and_closes_its_process_handle(monkeypatch, wait_result):
    import ctypes
    from Main_App.updates import elevation

    captured = {}
    closed = []

    def execute(pointer):
        info = pointer._obj
        captured.update(
            verb=info.lpVerb, file=info.lpFile, args=info.lpParameters, directory=info.lpDirectory, flags=info.fMask
        )
        info.hProcess = 123
        return True

    def wait(handle, timeout):
        assert handle == 123 and timeout == 0xFFFFFFFF
        return wait_result

    def exit_code(handle, pointer):
        assert handle == 123
        pointer._obj.value = 42
        return True

    def close(handle):
        closed.append(handle)
        return True

    shell = SimpleNamespace(ShellExecuteExW=execute)
    kernel = SimpleNamespace(WaitForSingleObject=wait, GetExitCodeProcess=exit_code, CloseHandle=close)
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_: shell if name == "shell32" else kernel)
    monkeypatch.setattr(elevation, "independent_dll_search", nullcontext)
    command = [r"C:\update cache\setup.exe", r"/DIR=C:\Program Files\FPVS Toolbox", "/ALLUSERS"]
    process = elevation.launch_elevated_installer(command)
    assert captured == dict(
        verb="runas",
        file=command[0],
        args=subprocess.list2cmdline(command[1:]),
        directory=str(Path(command[0]).parent),
        flags=0x140,
    )
    if wait_result:
        with pytest.raises(UpdateError, match="wait"):
            process.wait()
    else:
        assert process.wait() == 42
    assert closed == [123]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UAC API adapter")
def test_uac_cancellation_is_an_explicit_error(monkeypatch):
    import ctypes
    from Main_App.updates import elevation

    def canceled(_pointer):
        return False

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: SimpleNamespace(ShellExecuteExW=canceled))
    monkeypatch.setattr(elevation, "independent_dll_search", nullcontext)
    with pytest.raises(UpdateError, match="Administrator approval was canceled"):
        elevation.launch_elevated_installer([r"C:\cache\setup.exe"])
