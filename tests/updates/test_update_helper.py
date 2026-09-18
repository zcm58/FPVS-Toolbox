"""Independent updater tests: synthetic packages/processes, never real setup or network."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from Main_App.updates import (
    helper_client,
    helper_protocol,
    helper_runtime,
    helper_service,
    process_launch,
)
from Main_App.updates.cache_io import CacheDirectory, locked_cache
from Main_App.updates.helper_runtime import InstalledApplication, PreparedInstall
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCacheBusy,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
)


def _asset() -> InstallerAsset:
    name = "FPVSToolbox-2.0.0-setup.exe"
    return InstallerAsset(
        name,
        f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v2.0.0/{name}",
        9,
        hashlib.sha256(b"installer").hexdigest(),
        "2.0.0",
        123,
    )


def _downloaded(root: Path) -> DownloadedInstaller:
    asset = _asset()
    path = root / asset.name
    path.write_bytes(b"installer")
    return DownloadedInstaller(path, 9, asset.sha256 or "", asset)


def _result() -> UpdateCheckResult:
    return UpdateCheckResult("1.0.0", "2.0.0", True, None, "New version", _asset(), False)


@pytest.fixture(autouse=True)
def _forbid_external_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("A helper unit test attempted real installation or network access")

    monkeypatch.setattr(helper_runtime, "launch_installer", forbidden)
    monkeypatch.setattr(helper_runtime, "fetch_release_metadata", forbidden)
    monkeypatch.setattr(helper_runtime, "registered_installation", forbidden)
    monkeypatch.setattr(helper_service, "check_update_candidate", forbidden)
    monkeypatch.setattr(helper_service, "download_installer", forbidden)
    monkeypatch.setattr(helper_service, "registered_installation", forbidden)


def test_protocol_round_trip(tmp_path: Path) -> None:
    assert helper_protocol.result_from_dict(helper_protocol.result_to_dict(_result())) == _result()
    downloaded = _downloaded(tmp_path)
    assert (
        helper_protocol.download_from_dict(helper_protocol.download_to_dict(downloaded))
        == downloaded
    )
    raw = helper_protocol.encode_message("phase", text="Downloading…")
    assert helper_protocol.read_message(io.BytesIO(raw))["text"] == "Downloading…"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"protocol":1,"protocol":1,"kind":"ready"}\n',
        b'{"protocol":true,"kind":"ready"}\n',
        b'{"protocol":2,"kind":"ready"}\n',
        b"[]\n",
        b'{"protocol":1,"kind":"ready"}',
        b"x" * (helper_protocol.MAX_MESSAGE_BYTES + 1),
    ],
    ids=["duplicate", "bool-version", "future-version", "non-object", "incomplete", "oversize"],
)
def test_protocol_refuses_ambiguous_unbounded_or_unsupported_messages(raw: bytes) -> None:
    with pytest.raises(UpdateError):
        helper_protocol.read_message(io.BytesIO(raw))


@pytest.mark.parametrize(
    "change", [{"size_bytes": True}, {"kind": "shell"}, {"name": "../bad.exe"}]
)
def test_protocol_refuses_invalid_asset_identity(change: dict) -> None:
    value = helper_protocol.asset_to_dict(_asset())
    value.update(change)
    with pytest.raises(UpdateError):
        helper_protocol.asset_from_dict(value)


def test_service_uses_installed_version_not_updater_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        helper_service, "registered_installation", lambda: InstalledApplication(tmp_path, "1.0.0")
    )
    calls = []
    monkeypatch.setattr(
        helper_service, "check_update_candidate", lambda **kwargs: calls.append(kwargs) or _result()
    )
    assert helper_service.check_update() == _result()
    assert calls[0]["current_version"] == "1.0.0"
    assert calls[0]["install_root"] == tmp_path
    helper_service.check_update("1.9.0")
    assert calls[1]["current_version"] == "1.9.0"
    assert calls[1]["install_root"] is None


def test_service_download_skips_only_baseline_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        helper_service, "download_installer", lambda asset, **kwargs: calls.append((asset, kwargs))
    )
    helper_service.download_update(_asset())
    assert calls[0][0] == _asset()
    assert calls[0][1]["verify_patch_files"] is False


def test_staging_is_independent_bounded_and_preserves_unknown_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "helpers"
    cache.mkdir()
    keep = cache / "user-note.txt"
    keep.write_text("keep")
    monkeypatch.setattr(helper_runtime, "helper_cache_dir", lambda: cache)
    helper = tmp_path / "FPVS Toolbox Updater.exe"
    helper.write_bytes(b"first helper")
    first = helper_runtime.stage_helper(helper)
    assert first.parent == cache
    assert first.read_bytes() == b"first helper"
    assert helper_runtime.stage_helper(helper) == first
    helper.write_bytes(b"second helper")
    second = helper_runtime.stage_helper(helper)
    assert second != first and not first.exists()
    assert second.read_bytes() == b"second helper"
    assert keep.read_text() == "keep"
    assert not list(cache.glob("*.part"))


def test_staging_refuses_corrupted_existing_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper_runtime, "helper_cache_dir", lambda: tmp_path / "helpers")
    helper = tmp_path / "FPVS Toolbox Updater.exe"
    helper.write_bytes(b"helper")
    staged = helper_runtime.stage_helper(helper)
    staged.write_bytes(b"tamper")
    with pytest.raises(UpdateError, match="differs"):
        helper_runtime.stage_helper(helper)


def test_staging_cancel_does_not_modify_bundled_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper_runtime, "helper_cache_dir", lambda: tmp_path / "helpers")
    helper = tmp_path / "FPVS Toolbox Updater.exe"
    helper.write_bytes(b"helper")
    cancel = Event()
    cancel.set()
    with pytest.raises(UpdateCancelled):
        helper_runtime.stage_helper(helper, cancel_event=cancel)
    assert helper.read_bytes() == b"helper"


@pytest.mark.parametrize("abandoned_partial", [False, True])
def test_staging_refuses_bytes_when_retention_cannot_be_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, abandoned_partial: bool
) -> None:
    cache = tmp_path / "helpers"
    cache.mkdir()
    if abandoned_partial:
        (cache / ("updater-" + "1" * 32 + ".part")).write_bytes(b"partial")
    else:
        for digit in ("1", "2"):
            (cache / ("updater-" + digit * 64 + ".exe")).write_bytes(b"running")
    helper = tmp_path / "FPVS Toolbox Updater.exe"
    helper.write_bytes(b"new updater")
    monkeypatch.setattr(helper_runtime, "helper_cache_dir", lambda: cache)
    before = {path.name: path.read_bytes() for path in cache.iterdir()}
    original = CacheDirectory.remove

    def blocked(self, name):
        if name in before:
            raise PermissionError("Synthetic sharing violation")
        return original(self, name)

    monkeypatch.setattr(CacheDirectory, "remove", blocked)
    with pytest.raises((UpdateError, OSError)):
        helper_runtime.stage_helper(helper)
    after = {path.name: path.read_bytes() for path in cache.iterdir() if path.name in before}
    assert after == before
    assert len(list(cache.glob("*.exe"))) == (0 if abandoned_partial else 2)


def test_staged_helper_tamper_before_spawn_never_executes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(helper_runtime, "helper_cache_dir", lambda: tmp_path)
    path = tmp_path / ("updater-" + hashlib.sha256(b"original").hexdigest() + ".exe")
    path.write_bytes(b"tampered")
    monkeypatch.setattr(
        helper_runtime.subprocess, "Popen", lambda *a, **k: pytest.fail("Tampered helper executed")
    )
    with pytest.raises(UpdateError, match="changed before"):
        helper_runtime.spawn_helper_command([str(path)], stdio=True)


def _publish(monkeypatch: pytest.MonkeyPatch, asset: InstallerAsset, **overrides) -> None:
    raw = {
        "name": asset.name,
        "id": asset.asset_id,
        "size": asset.size_bytes,
        "digest": f"sha256:{asset.sha256}",
        "browser_download_url": asset.download_url,
        **overrides,
    }
    monkeypatch.setattr(
        helper_runtime,
        "fetch_release_metadata",
        lambda *_a, **_k: [{"tag_name": "v2.0.0", "assets": [raw]}],
    )


def test_prepare_reauthenticates_official_asset_and_cache_before_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    monkeypatch.setattr(helper_runtime, "default_update_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        helper_runtime,
        "registered_installation",
        lambda: InstalledApplication(tmp_path / "install", "1.0.0"),
    )
    _publish(monkeypatch, downloaded.asset)
    prepared = helper_runtime.prepare_install(downloaded)
    assert prepared.parent is None
    prepared.close()
    _publish(monkeypatch, downloaded.asset, digest="sha256:" + "0" * 64)
    with pytest.raises(UpdateError, match="official GitHub"):
        helper_runtime.prepare_install(downloaded)


def test_prepare_rejects_changed_cached_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    monkeypatch.setattr(helper_runtime, "default_update_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        helper_runtime,
        "registered_installation",
        lambda: InstalledApplication(tmp_path / "install", "1.0.0"),
    )
    _publish(monkeypatch, downloaded.asset)
    downloaded.path.write_bytes(b"corrupted")
    with pytest.raises(UpdateError, match="SHA-256"):
        helper_runtime.prepare_install(downloaded)


def test_run_waits_for_parent_and_other_instances_before_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installation = InstalledApplication(tmp_path, "1.0.0")
    events = []
    parent = SimpleNamespace(
        wait=lambda event: events.append("wait"), close=lambda: events.append("close")
    )
    monkeypatch.setattr(helper_runtime, "registered_installation", lambda: installation)
    monkeypatch.setattr(
        helper_runtime, "application_is_running", lambda exe: events.append("other") or True
    )
    prepared = PreparedInstall(_downloaded(tmp_path), installation, parent)
    with pytest.raises(UpdateError, match="Another Toolbox window"):
        prepared.run()
    assert events == ["wait", "other", "close"]


def test_run_ignores_cancellation_after_setup_and_restarts_only_verified_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installation = InstalledApplication(tmp_path, "1.0.0")
    executable = tmp_path / "FPVS_Toolbox.exe"
    executable.write_bytes(b"synthetic application; never executed")
    installed = [installation, replace(installation, version="2.0.0")]
    monkeypatch.setattr(helper_runtime, "registered_installation", lambda: installed.pop(0))
    monkeypatch.setattr(helper_runtime, "application_is_running", lambda exe: False)
    calls = []
    cancel = Event()

    def launch(downloaded, **kwargs):
        calls.append(kwargs)
        cancel.set()
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(helper_runtime, "launch_installer", launch)
    monkeypatch.setattr(
        helper_runtime.subprocess, "Popen", lambda command, **kwargs: calls.append(command)
    )
    phases = []
    PreparedInstall(_downloaded(tmp_path), installation, None).run(
        cancel_event=cancel, phase_callback=phases.append
    )
    assert calls[0]["managed"] is True
    assert calls[0]["verify_patch_files"] is False
    assert calls[0]["relaunch_after_install"] is False
    assert calls[1] == [str(executable)]
    assert len([phase for phase in phases if phase.install_committed]) == 1


def test_install_session_lock_stays_held_while_setup_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installation = InstalledApplication(tmp_path, "1.0.0")
    monkeypatch.setattr(helper_runtime, "default_update_cache_dir", lambda: tmp_path / "updates")
    monkeypatch.setattr(helper_runtime, "registered_installation", lambda: installation)
    monkeypatch.setattr(helper_runtime, "application_is_running", lambda _: False)

    def wait():
        with pytest.raises(UpdateCacheBusy):
            with locked_cache(tmp_path / "updater-install"):
                pytest.fail("A second installation acquired the session lock")
        return 1

    monkeypatch.setattr(
        helper_runtime, "launch_installer", lambda *a, **k: SimpleNamespace(wait=wait)
    )
    with pytest.raises(UpdateError, match="exit code 1"):
        PreparedInstall(_downloaded(tmp_path), installation, None).run()
    with locked_cache(tmp_path / "updater-install"):
        pass


@pytest.mark.parametrize("exit_code, target", [(1, "2.0.0"), (0, "1.0.0")])
def test_run_never_restarts_failed_or_unregistered_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exit_code: int, target: str
) -> None:
    installation = InstalledApplication(tmp_path, "1.0.0")
    states = [installation, replace(installation, version=target)]
    monkeypatch.setattr(helper_runtime, "registered_installation", lambda: states.pop(0))
    monkeypatch.setattr(helper_runtime, "application_is_running", lambda exe: False)
    monkeypatch.setattr(
        helper_runtime, "launch_installer", lambda *a, **k: SimpleNamespace(wait=lambda: exit_code)
    )
    monkeypatch.setattr(
        helper_runtime.subprocess, "Popen", lambda *a, **k: pytest.fail("Unexpected restart")
    )
    with pytest.raises(UpdateError):
        PreparedInstall(_downloaded(tmp_path), installation, None).run()


def _pipe():
    read_fd, write_fd = os.pipe()
    return os.fdopen(read_fd, "rb", buffering=0), os.fdopen(write_fd, "wb", buffering=0)


@pytest.mark.parametrize("accept", [True, False])
def test_apply_handoff_requires_matching_accept_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, accept: bool
) -> None:
    downloaded = _downloaded(tmp_path)
    events = []
    prepared = SimpleNamespace(
        run=lambda **k: events.append("run"), close=lambda: events.append("close")
    )
    monkeypatch.setattr(helper_service, "prepare_install", lambda *a, **k: prepared)
    input_stream, sender = _pipe()
    receiver, output_stream = _pipe()
    with input_stream, sender, receiver, output_stream, ThreadPoolExecutor(max_workers=1) as pool:
        helper_protocol.write_message(
            sender,
            "request",
            command="apply",
            downloaded=helper_protocol.download_to_dict(downloaded),
            parent_pid=None,
        )
        future = pool.submit(helper_service.run_apply, input_stream, output_stream)
        ready = helper_protocol.read_message(receiver)
        assert ready["kind"] == "ready"
        assert not events
        helper_protocol.write_message(
            sender, "accept", nonce=ready["nonce"] if accept else "0" * 32
        )
        if accept:
            future.result(timeout=5)
            assert events == ["run", "close"]
        else:
            with pytest.raises(UpdateError, match="did not accept"):
                future.result(timeout=5)
            assert events == ["close"]


def test_apply_cancellation_during_prepare_never_acknowledges_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    observed = Event()

    def prepare(*args, cancel_event, **kwargs):
        assert cancel_event.wait(5)
        observed.set()
        raise UpdateCancelled("Canceled")

    monkeypatch.setattr(helper_service, "prepare_install", prepare)
    input_stream, sender = _pipe()
    receiver, output_stream = _pipe()
    with input_stream, sender, receiver, output_stream, ThreadPoolExecutor(max_workers=1) as pool:
        helper_protocol.write_message(
            sender,
            "request",
            command="apply",
            downloaded=helper_protocol.download_to_dict(downloaded),
            parent_pid=None,
        )
        future = pool.submit(helper_service.run_apply, input_stream, output_stream)
        helper_protocol.write_message(sender, "cancel")
        with pytest.raises(UpdateCancelled):
            future.result(timeout=5)
        assert observed.is_set()
        assert helper_protocol.read_message(receiver)["kind"] == "error"


def test_apply_acceptance_timeout_never_runs_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    monkeypatch.setattr(helper_service, "HANDOFF_ACCEPT_TIMEOUT_SECONDS", 0)
    prepared = SimpleNamespace(
        run=lambda **k: pytest.fail("Unaccepted setup executed"), close=lambda: None
    )
    monkeypatch.setattr(helper_service, "prepare_install", lambda *a, **k: prepared)
    input_stream, sender = _pipe()
    receiver, output_stream = _pipe()
    with input_stream, sender, receiver, output_stream:
        helper_protocol.write_message(
            sender,
            "request",
            command="apply",
            downloaded=helper_protocol.download_to_dict(downloaded),
            parent_pid=None,
        )
        with pytest.raises(UpdateError, match="did not accept"):
            helper_service.run_apply(input_stream, output_stream)


@pytest.mark.parametrize("windowed_stdio", [False, True])
def test_client_round_trip_through_real_private_subprocess(windowed_stdio: bool) -> None:
    if windowed_stdio and sys.platform != "win32":
        pytest.skip("Windowed standard-handle recovery is Windows-specific")
    script = """
import sys
from Main_App.updates import helper_service
from Main_App.updates.models import UpdateCheckResult, UpdatePhase
assert 'PySide6' not in sys.modules
def check(current_version, **kwargs):
    kwargs['phase_callback'](UpdatePhase('Checking metadata'))
    return UpdateCheckResult(current_version, current_version, False, None, '', None, False)
helper_service.check_update = check
raise SystemExit(helper_service.serve_stdio())
"""
    if windowed_stdio:
        script = script.replace(
            "helper_service.check_update = check",
            "sys.stdin = None\nsys.stdout = None\nhelper_service.check_update = check",
        )
    client = helper_client.HelperClient(lambda *args: [sys.executable, "-c", script])
    phases = []
    result = client.check("1.2.3", phase_callback=phases.append)
    assert result.current_version == result.latest_version == "1.2.3"
    assert [phase.text for phase in phases] == ["Checking metadata"]


def test_client_cancellation_reaches_real_subprocess() -> None:
    script = """
from Main_App.updates import helper_service
from Main_App.updates.models import UpdatePhase, UpdateCancelled
def check(current_version, **kwargs):
    kwargs['phase_callback'](UpdatePhase('Ready for cancellation'))
    if kwargs['cancel_event'].wait(5):
        raise UpdateCancelled('Canceled by Toolbox')
    raise RuntimeError('Cancellation never arrived')
helper_service.check_update = check
raise SystemExit(helper_service.serve_stdio())
"""
    client = helper_client.HelperClient(lambda *args: [sys.executable, "-c", script])
    cancel = Event()
    with pytest.raises(UpdateCancelled, match="Canceled by Toolbox"):
        client.check("1.2.3", cancel_event=cancel, phase_callback=lambda _: cancel.set())


def test_client_apply_sends_accept_and_preserves_explicit_no_parent(tmp_path: Path) -> None:
    marker = tmp_path / "accepted.txt"
    script = """
import sys
from pathlib import Path
from Main_App.updates.helper_service import binary_stdio
from Main_App.updates.helper_protocol import read_message, write_message
source, target = binary_stdio()
request = read_message(source)
assert request['command'] == 'apply' and request['parent_pid'] is None
write_message(target, 'ready', nonce='1' * 32)
accept = read_message(source)
assert accept['kind'] == 'accept' and accept['nonce'] == '1' * 32
Path(sys.argv[1]).write_text('accepted synthetic handoff; no installer executed')
"""
    client = helper_client.HelperClient(lambda *args: [sys.executable, "-c", script, str(marker)])
    process = client.launch_install(_downloaded(tmp_path), parent_pid=None)
    assert process.wait(timeout=5) == 0
    assert marker.read_text().startswith("accepted synthetic handoff")


def test_independent_environment_resets_onefile_and_excludes_only_frozen_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "_MEI-fake"
    external = tmp_path / "tools"
    sibling = tmp_path / "_MEI-fake-sibling"
    original_path = os.pathsep.join(map(str, (bundle, bundle / "PySide6", external, sibling)))
    monkeypatch.setattr(process_launch, "sys", SimpleNamespace(frozen=True, _MEIPASS=str(bundle)))
    monkeypatch.setenv("PATH", original_path)
    monkeypatch.setenv("QT_PLUGIN_PATH", str(bundle / "PySide6" / "plugins"))
    monkeypatch.setenv("QML2_IMPORT_PATH", str(external))
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "0")
    environment = process_launch.independent_process_environment()
    assert environment["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert environment["_PYI_PARENT_PROCESS_LEVEL"] == "1"  # Bootloader owns private state.
    assert environment["PATH"] == os.pathsep.join(map(str, (external, sibling)))
    assert "QT_PLUGIN_PATH" not in environment
    assert environment["QML2_IMPORT_PATH"] == str(external)
    assert os.environ["PATH"] == original_path
    assert os.environ["PYINSTALLER_RESET_ENVIRONMENT"] == "0"


class _FakeDllSearch:
    def __init__(self, *, fail_clear=False, fail_restore=False) -> None:
        self.calls = []
        self.fail_clear = fail_clear
        self.fail_restore = fail_restore

    def GetDllDirectoryW(self, size, buffer):
        buffer.value = r"C:\synthetic-helper\_MEI-directory"
        return len(buffer.value)

    def SetDllDirectoryW(self, value):
        self.calls.append(value)
        return not (self.fail_clear if value is None else self.fail_restore)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL search is Windows-specific")
@pytest.mark.parametrize("launch_fails", [False, True])
def test_independent_launch_restores_dll_search_after_success_or_failure(
    monkeypatch: pytest.MonkeyPatch, launch_fails: bool
) -> None:
    kernel = _FakeDllSearch()
    monkeypatch.setattr(process_launch, "sys", SimpleNamespace(frozen=True, platform="win32"))
    monkeypatch.setattr(process_launch, "_windows_dll_api", lambda: kernel)
    marker = object()

    def launch(command, **options):
        assert kernel.calls == [None]
        assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        if launch_fails:
            raise FileNotFoundError("Synthetic process creation failure")
        return marker

    monkeypatch.setattr(process_launch.subprocess, "Popen", launch)
    if launch_fails:
        with pytest.raises(FileNotFoundError, match="Synthetic"):
            process_launch.launch_independent_process(["not-executed.exe"])
    else:
        assert process_launch.launch_independent_process(["not-executed.exe"]) is marker
    assert kernel.calls == [None, r"C:\synthetic-helper\_MEI-directory"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL search is Windows-specific")
def test_failed_dll_reset_prevents_process_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = _FakeDllSearch(fail_clear=True)
    monkeypatch.setattr(process_launch, "sys", SimpleNamespace(frozen=True, platform="win32"))
    monkeypatch.setattr(process_launch, "_windows_dll_api", lambda: kernel)
    monkeypatch.setattr(
        process_launch.subprocess, "Popen", lambda *a, **k: pytest.fail("Unexpected launch")
    )
    with pytest.raises(UpdateError, match="prepare the Windows DLL"):
        process_launch.launch_independent_process(["not-executed.exe"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL search is Windows-specific")
def test_dll_restore_failure_does_not_lose_launched_installer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kernel = _FakeDllSearch(fail_restore=True)
    monkeypatch.setattr(process_launch, "sys", SimpleNamespace(frozen=True, platform="win32"))
    monkeypatch.setattr(process_launch, "_windows_dll_api", lambda: kernel)
    marker = object()
    monkeypatch.setattr(process_launch.subprocess, "Popen", lambda *a, **k: marker)
    assert process_launch.launch_independent_process(["not-executed.exe"]) is marker
    assert "updater_dll_search_restore_failed" in caplog.text


def test_cancel_watchdog_exits_only_stalled_uncommitted_worker() -> None:
    cancel = Event()
    exited = Event()
    watchdog = helper_service._CancellationWatchdog(
        cancel, grace_seconds=0.01, exit_process=lambda code: exited.set()
    )
    cancel.set()
    assert exited.wait(1)
    watchdog._thread.join(timeout=1)
    assert not watchdog._thread.is_alive()


def test_acceptance_disarms_cancel_watchdog_before_installer_ownership() -> None:
    cancel = Event()
    exits = []
    watchdog = helper_service._CancellationWatchdog(
        cancel, grace_seconds=0.01, exit_process=exits.append
    )
    watchdog.disarm()
    cancel.set()
    watchdog._thread.join(timeout=1)
    assert not watchdog._thread.is_alive()
    assert not exits


def test_stalled_real_worker_cancels_before_client_force_stop() -> None:
    script = """
from threading import Event
from Main_App.updates import helper_service
from Main_App.updates.models import UpdatePhase
helper_service.CANCELLED_WORKER_EXIT_SECONDS = 0.05
def check(current_version, **kwargs):
    kwargs['phase_callback'](UpdatePhase('Synthetic stalled DNS'))
    Event().wait(30)
    raise RuntimeError('The cancellation watchdog did not stop this worker')
helper_service.check_update = check
raise SystemExit(helper_service.serve_stdio())
"""
    client = helper_client.HelperClient(lambda *args: [sys.executable, "-c", script])
    cancel = Event()
    started = time.monotonic()
    with pytest.raises(UpdateCancelled):
        client.check("1.2.3", cancel_event=cancel, phase_callback=lambda _: cancel.set())
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("graceful_exit", [False, True])
def test_uncommitted_cleanup_closes_input_and_waits_before_force_stop(graceful_exit: bool) -> None:
    events = []
    waits = []

    def wait(*, timeout):
        events.append("wait")
        waits.append(timeout)
        if not graceful_exit and len(waits) == 1:
            raise subprocess.TimeoutExpired("synthetic helper", timeout)
        return 1

    process = SimpleNamespace(
        stdin=SimpleNamespace(close=lambda: events.append("close-stdin")),
        poll=lambda: None,
        wait=wait,
        terminate=lambda: events.append("terminate"),
        kill=lambda: events.append("kill"),
    )
    helper_client._stop_uncommitted(process)
    assert events == (
        ["close-stdin", "wait"] if graceful_exit else ["close-stdin", "wait", "terminate", "wait"]
    )
    assert waits[0] > helper_service.CANCELLED_WORKER_EXIT_SECONDS
