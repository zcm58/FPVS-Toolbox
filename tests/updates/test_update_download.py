"""Updater download/launch tests: isolated cache, fake HTTPS, and never a real installer."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError

import pytest

from Main_App.updates import cache_io, downloader
from Main_App.updates.cache import cleanup_update_cache, receipt_name, recognized_cache_entry
from Main_App.updates.cache_io import CacheDirectory, locked_cache
from Main_App.updates.downloader import download_installer
from Main_App.updates.installer import launch_installer
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCacheBusy,
    UpdateCancelled,
    UpdateError,
    UpdateIntegrityError,
)


def _asset(version: str = "2.0.0", payload: bytes = b"installer") -> InstallerAsset:
    name = f"FPVSToolbox-{version}-setup.exe"
    return InstallerAsset(
        name,
        f"https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v{version}/{name}",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        version,
        123,
    )


class _FakeResponse:
    def __init__(self, payload: bytes = b"installer", url: str | None = None) -> None:
        self._payload = payload
        self._offset = 0
        self.headers: dict[str, str] = {"Content-Length": str(len(payload))}
        self.url = url or _asset().download_url
        self.closed = False

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def close(self) -> None:
        self.__exit__()

    def geturl(self) -> str:
        return self.url

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)


@pytest.fixture(autouse=True)
def _forbid_real_network_and_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Backend unit tests must not use the network or launch a real installer")

    monkeypatch.setattr(downloader, "urlopen", forbidden)
    monkeypatch.setattr("Main_App.updates.installer.subprocess.Popen", forbidden)


def _serve(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse | None = None) -> _FakeResponse:
    response = response or _FakeResponse()
    monkeypatch.setattr(downloader, "urlopen", lambda *_args, **_kwargs: response)
    return response


def _payloads(cache: Path) -> list[Path]:
    return [
        path
        for path in cache.iterdir()
        if (entry := recognized_cache_entry(path.name)) is not None
        and entry.kind in {"partial", "installer"}
    ]


def _downloaded(cache: Path, asset: InstallerAsset | None = None) -> DownloadedInstaller:
    asset = asset or _asset()
    path = cache / asset.name
    path.write_bytes(b"installer")
    assert asset.sha256 is not None and asset.size_bytes is not None
    return DownloadedInstaller(path, asset.size_bytes, asset.sha256, asset)


def test_download_writes_digest_receipt_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = _serve(monkeypatch)
    progress: list[tuple[int, int | None]] = []
    result = download_installer(
        _asset(),
        destination_dir=tmp_path,
        progress_callback=lambda done, total: progress.append((done, total)),
    )
    assert result.path == tmp_path / _asset().name
    assert result.path.read_bytes() == b"installer"
    assert result.size_bytes == 9
    assert result.sha256 == _asset().sha256
    assert result.asset == _asset()
    assert progress[-1] == (9, 9)
    assert response.closed
    data = json.loads((tmp_path / receipt_name(result.path.name)).read_text(encoding="utf-8"))
    assert data["sha256"] == result.sha256
    assert data["version"] == "2.0.0"
    assert _payloads(tmp_path) == [result.path]


def test_reuse_hashes_file_against_trusted_metadata_even_without_receipt(tmp_path: Path) -> None:
    existing = _downloaded(tmp_path)
    progress: list[tuple[int, int | None]] = []
    result = download_installer(
        existing.asset,
        destination_dir=tmp_path,
        progress_callback=lambda done, total: progress.append((done, total)),
    )
    assert result == existing
    assert progress == [(9, 9)]
    assert (tmp_path / receipt_name(result.path.name)).is_file()


def test_same_size_corrupted_cache_is_replaced_not_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    existing = _downloaded(tmp_path)
    existing.path.write_bytes(b"corrupted")
    response = _serve(monkeypatch)
    assert (
        download_installer(existing.asset, destination_dir=tmp_path).path.read_bytes()
        == b"installer"
    )
    assert response.closed


@pytest.mark.parametrize("digest", [None, "", "x" * 64, "sha512:" + "a" * 64, "sha256:abc"])
def test_missing_or_invalid_trusted_digest_never_downloads(
    tmp_path: Path, digest: str | None
) -> None:
    with pytest.raises(UpdateError, match="SHA-256"):
        download_installer(replace(_asset(), sha256=digest), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v2.0.0/FPVSToolbox-2.0.0-setup.exe",
        "https://example.com/FPVSToolbox-2.0.0-setup.exe",
        "https://github.com/another/repo/releases/download/v2.0.0/FPVSToolbox-2.0.0-setup.exe",
        "https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v20.0.0/FPVSToolbox-2.0.0-setup.exe",
        "https://user:password@github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v2.0.0/x.exe",
    ],
)
def test_asset_source_and_version_are_exact(tmp_path: Path, url: str) -> None:
    with pytest.raises(UpdateError):
        download_installer(replace(_asset(), download_url=url), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "../FPVSToolbox-2.0.0-setup.exe",
        r"..\FPVSToolbox-2.0.0-setup.exe",
        "FPVSToolbox-2.0.0-setup.exe:stream",
        "custom.exe",
        "FPVSToolbox-2.0.0-setup.exe ",
    ],
)
def test_invalid_installer_names_do_not_create_files(tmp_path: Path, name: str) -> None:
    with pytest.raises(UpdateError):
        download_installer(replace(_asset(), name=name), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("size", [None, 0, -1, True, 4 * 1024**3 + 1])
def test_unbounded_or_invalid_asset_size_is_refused(tmp_path: Path, size: int | None) -> None:
    with pytest.raises(UpdateError, match="bounded installer size"):
        download_installer(replace(_asset(), size_bytes=size), destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "final_url",
    [
        "http://release-assets.githubusercontent.com/payload.exe",
        "https://untrusted.example/payload.exe",
        "https://release-assets.githubusercontent.com.evil.example/payload.exe",
    ],
)
def test_untrusted_or_insecure_redirect_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, final_url: str
) -> None:
    _serve(monkeypatch, _FakeResponse(url=final_url))
    with pytest.raises(UpdateError, match="redirected"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


def test_signed_https_github_cdn_redirect_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve(
        monkeypatch, _FakeResponse(url="https://release-assets.githubusercontent.com/file?sig=test")
    )
    assert download_installer(_asset(), destination_dir=tmp_path).path.is_file()


def test_missing_final_response_url_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = _FakeResponse()
    monkeypatch.setattr(response, "geturl", None)
    _serve(monkeypatch, response)
    with pytest.raises(UpdateError, match="verifiable HTTPS URL"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


def test_stream_overrun_is_rejected_before_writing_excess_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = _FakeResponse(b"too many installer bytes")
    response.headers = {}
    _serve(monkeypatch, response)
    with pytest.raises(UpdateIntegrityError, match="exceeded"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


@pytest.mark.parametrize("payload", [b"short", b"corrupted"])
def test_incomplete_or_wrong_digest_download_is_discarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    response = _FakeResponse(payload)
    response.headers = {}
    _serve(monkeypatch, response)
    with pytest.raises(UpdateIntegrityError):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


@pytest.mark.parametrize("length", ["-1", "unknown", "10"])
def test_invalid_or_mismatched_content_length_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, length: str
) -> None:
    response = _FakeResponse()
    response.headers["Content-Length"] = length
    _serve(monkeypatch, response)
    with pytest.raises(UpdateIntegrityError, match="content length"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


def test_cancel_before_start_does_not_create_lock_or_partial(tmp_path: Path) -> None:
    event = Event()
    event.set()
    with pytest.raises(UpdateCancelled):
        download_installer(_asset(), destination_dir=tmp_path, cancel_event=event)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("during_read", [False, True])
def test_cancel_from_read_or_progress_discards_staging_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, during_read: bool
) -> None:
    event = Event()
    response = _FakeResponse()
    if during_read:
        read = response.read1

        def cancel_read(size: int) -> bytes:
            event.set()
            return read(size)

        monkeypatch.setattr(response, "read1", cancel_read)
    _serve(monkeypatch, response)
    with pytest.raises(UpdateCancelled):
        download_installer(
            _asset(),
            destination_dir=tmp_path,
            cancel_event=event,
            progress_callback=lambda *_args: event.set(),
        )
    assert response.closed
    assert _payloads(tmp_path) == []
    with locked_cache(tmp_path):
        pass


def test_cancel_immediately_before_promotion_discards_complete_partial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    event = Event()
    _serve(monkeypatch)
    regular_info = CacheDirectory.regular_info

    def cancel_at_final_stat(cache: CacheDirectory, name: str):
        info = regular_info(cache, name)
        if name.endswith(".part") and info is not None and info.st_size == 9:
            event.set()
        return info

    monkeypatch.setattr(CacheDirectory, "regular_info", cancel_at_final_stat)
    with pytest.raises(UpdateCancelled):
        download_installer(_asset(), destination_dir=tmp_path, cancel_event=event)
    assert _payloads(tmp_path) == []


@pytest.mark.parametrize("cancel", [False, True])
def test_error_or_cancel_after_promotion_removes_installer_and_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cancel: bool
) -> None:
    _serve(monkeypatch)
    event = Event()
    calls = 0
    original = ValueError("progress callback failed")

    def callback(_done: int, _total: int | None) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            if cancel:
                event.set()
            else:
                raise original

    with pytest.raises(UpdateCancelled if cancel else ValueError) as raised:
        download_installer(
            _asset(),
            destination_dir=tmp_path,
            progress_callback=callback,
            cancel_event=event,
        )
    if not cancel:
        assert raised.value is original
    assert _payloads(tmp_path) == []
    assert not (tmp_path / receipt_name(_asset().name)).exists()


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://github.com", 503, "unavailable", {}, None),
        URLError("network down"),
        TimeoutError("timed out"),
    ],
)
def test_network_open_errors_leave_no_partial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(downloader, "urlopen", fail)
    with pytest.raises(UpdateError) as raised:
        download_installer(_asset(), destination_dir=tmp_path)
    assert raised.value.__cause__ is failure
    assert _payloads(tmp_path) == []


@pytest.mark.parametrize(
    "stage",
    [
        "open",
        "read",
        "response_close",
        "stat",
        "fsync",
        "replace",
        "replace_after_rename",
        "receipt_open",
        "receipt_replace",
    ],
)
def test_all_transfer_and_finalization_failures_discard_owned_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    response = _serve(monkeypatch)
    original = OSError(f"injected {stage} failure")
    open_fd = cache_io._open_file_descriptor
    regular_info = CacheDirectory.regular_info
    replace_file = CacheDirectory.replace
    once = False

    def fail_open(path: Path, mode: str) -> int:
        if mode == "new" and (
            (stage == "open" and path.name.endswith(".part"))
            or (stage == "receipt_open" and ".verified." in path.name)
        ):
            raise original
        return open_fd(path, mode)

    def fail_read(_size: int) -> bytes:
        raise original

    def fail_close(_self: _FakeResponse, *_args: object) -> None:
        raise original

    def fail_stat(cache: CacheDirectory, name: str):
        nonlocal once
        info = regular_info(cache, name)
        if stage == "stat" and name.endswith(".part") and info and info.st_size == 9 and not once:
            once = True
            raise original
        return info

    def fail_replace(cache: CacheDirectory, source: str, target: str) -> None:
        if stage == "replace" and source.endswith(".part"):
            raise original
        if stage == "receipt_replace" and target.endswith(".verified.json"):
            raise original
        replace_file(cache, source, target)
        if stage == "replace_after_rename" and source.endswith(".part"):
            raise original

    def fail_fsync(_fd: int) -> None:
        raise original

    monkeypatch.setattr(cache_io, "_open_file_descriptor", fail_open)
    monkeypatch.setattr(CacheDirectory, "regular_info", fail_stat)
    monkeypatch.setattr(CacheDirectory, "replace", fail_replace)
    if stage == "read":
        monkeypatch.setattr(response, "read1", fail_read)
    if stage == "response_close":
        monkeypatch.setattr(_FakeResponse, "__exit__", fail_close)
    if stage == "fsync":
        monkeypatch.setattr(downloader.os, "fsync", fail_fsync)
    with pytest.raises(UpdateError) as raised:
        download_installer(_asset(), destination_dir=tmp_path)
    assert raised.value.__cause__ is original
    assert _payloads(tmp_path) == []
    assert not any(path.name.endswith(".verified.json") for path in tmp_path.iterdir())


def test_cleanup_failure_preserves_original_error_and_next_attempt_refuses_extra_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    response = _serve(monkeypatch)
    original = ValueError("original callback error")
    unlink = Path.unlink

    def deny_partial(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.endswith(".part"):
            raise PermissionError("cannot remove partial")
        unlink(path, *args, **kwargs)

    def failed_callback(*_args: object) -> None:
        raise original

    monkeypatch.setattr(Path, "unlink", deny_partial)
    with pytest.raises(ValueError) as raised:
        download_installer(_asset(), destination_dir=tmp_path, progress_callback=failed_callback)
    assert raised.value is original
    assert "update_cache_discard_failed" in caplog.text
    assert len(_payloads(tmp_path)) == 1
    response._offset = 0
    with pytest.raises(UpdateError, match="cannot remove partial"):
        download_installer(_asset("3.0.0"), destination_dir=tmp_path)
    assert len(_payloads(tmp_path)) == 1


def test_uuid_staging_names_differ_after_a_canceled_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    names: list[str] = []
    for _ in range(2):
        event = Event()
        _serve(monkeypatch)

        def cancel(*_args: object, current_event: Event = event) -> None:
            names.extend(path.name for path in tmp_path.glob("*.part"))
            current_event.set()

        with pytest.raises(UpdateCancelled):
            download_installer(
                _asset(), destination_dir=tmp_path, cancel_event=event, progress_callback=cancel
            )
    assert len(names) == 2
    assert names[0] != names[1]
    assert all(recognized_cache_entry(name) is not None for name in names)


def test_concurrent_download_and_cleanup_cannot_touch_active_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ready, release = Event(), Event()
    response = _FakeResponse()
    read = response.read1

    def held_read(size: int) -> bytes:
        ready.set()
        assert release.wait(5)
        return read(size)

    monkeypatch.setattr(response, "read1", held_read)
    _serve(monkeypatch, response)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(download_installer, _asset(), destination_dir=tmp_path)
        try:
            assert ready.wait(5)
            partials = _payloads(tmp_path)
            assert len(partials) == 1 and partials[0].suffix == ".part"
            assert cleanup_update_cache("1.3.0", cache_dir=tmp_path).busy
            with pytest.raises(UpdateCacheBusy):
                download_installer(_asset("3.0.0"), destination_dir=tmp_path)
            assert partials == _payloads(tmp_path)
        finally:
            release.set()
        result = future.result(timeout=5)
    assert _payloads(tmp_path) == [result.path]


def test_read1_and_finite_timeout_support_responsive_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    response = _FakeResponse()
    seen: dict[str, object] = {}
    raw_read = response.read
    monkeypatch.setattr(response, "read1", raw_read)
    monkeypatch.setattr(response, "read", lambda *_args: pytest.fail("read() may wait to fill n"))

    def open_response(_request: object, **kwargs: object) -> _FakeResponse:
        seen.update(kwargs)
        return response

    monkeypatch.setattr(downloader, "urlopen", open_response)
    assert download_installer(_asset(), destination_dir=tmp_path).path.exists()
    assert seen["timeout"] == downloader.DOWNLOAD_TIMEOUT_SECONDS == 5


def test_total_download_deadline_stops_a_trickling_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _serve(monkeypatch)
    ticks = iter([0, 0, downloader.MAX_DOWNLOAD_SECONDS + 1])
    monkeypatch.setattr(downloader.time, "monotonic", lambda: next(ticks))
    with pytest.raises(UpdateError, match="time limit"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == []


def test_download_rejects_relative_destination_without_side_effects() -> None:
    with pytest.raises(UpdateError, match="absolute"):
        download_installer(_asset(), destination_dir=Path("relative"))


def test_launch_requires_existing_verified_exe(tmp_path: Path) -> None:
    downloaded = _downloaded(tmp_path)
    downloaded.path.unlink()
    with pytest.raises(UpdateError, match="does not exist"):
        launch_installer(downloaded)
    with pytest.raises(UpdateError, match="identity"):
        launch_installer(replace(downloaded, sha256="a" * 64))


def test_launch_rehashes_after_download_and_refuses_same_size_tampering(tmp_path: Path) -> None:
    downloaded = _downloaded(tmp_path)
    downloaded.path.write_bytes(b"corrupted")
    with pytest.raises(UpdateIntegrityError, match="SHA-256"):
        launch_installer(downloaded)


@pytest.mark.parametrize("relaunch", [False, True])
def test_launch_only_after_guarded_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relaunch: bool
) -> None:
    downloaded = _downloaded(tmp_path)
    process = object()
    commands: list[tuple[list[str], dict[str, object]]] = []

    def popen(command: list[str], **kwargs: object) -> object:
        commands.append((command, kwargs))
        assert cleanup_update_cache("1.3.0", cache_dir=tmp_path).busy
        return process

    monkeypatch.setattr("Main_App.updates.installer.subprocess.Popen", popen)
    assert launch_installer(downloaded, relaunch_after_install=relaunch) is process
    assert commands == [
        ([str(downloaded.path)] + (["/RELAUNCH=1"] if relaunch else []), {"close_fds": True})
    ]


def test_cancel_prevents_launch_but_late_cancel_cannot_undo_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    event = Event()
    event.set()
    with pytest.raises(UpdateCancelled):
        launch_installer(downloaded, cancel_event=event)
    event.clear()
    process = object()

    def popen(*_args: object, **_kwargs: object) -> object:
        event.set()
        return process

    monkeypatch.setattr("Main_App.updates.installer.subprocess.Popen", popen)
    assert launch_installer(downloaded, cancel_event=event) is process


def test_launch_failure_releases_cache_lock_and_keeps_verified_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    original = OSError("OS could not start installer")

    def popen(*_args: object, **_kwargs: object) -> None:
        raise original

    monkeypatch.setattr("Main_App.updates.installer.subprocess.Popen", popen)
    with pytest.raises(UpdateError) as raised:
        launch_installer(downloaded)
    assert raised.value.__cause__ is original
    assert downloaded.path.read_bytes() == b"installer"
    with locked_cache(tmp_path):
        pass


def test_untrusted_receipt_is_not_a_launch_authority(tmp_path: Path) -> None:
    downloaded = _downloaded(tmp_path)
    forged = replace(downloaded, asset=replace(downloaded.asset, sha256=None))
    with pytest.raises(UpdateError, match="SHA-256"):
        launch_installer(forged)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows no-write/delete sharing guarantees")
def test_windows_launch_guard_blocks_file_and_cache_root_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloaded = _downloaded(tmp_path)
    process = object()

    def popen(*_args: object, **_kwargs: object) -> object:
        with pytest.raises(PermissionError):
            downloaded.path.write_bytes(b"corrupted")
        with pytest.raises(PermissionError):
            downloaded.path.unlink()
        with pytest.raises(PermissionError):
            downloaded.path.replace(tmp_path / "renamed.exe")
        with pytest.raises(PermissionError):
            tmp_path.replace(tmp_path.with_name(tmp_path.name + "-moved"))
        return process

    monkeypatch.setattr("Main_App.updates.installer.subprocess.Popen", popen)
    assert launch_installer(downloaded) is process
    assert downloaded.path.read_bytes() == b"installer"


def test_selected_asset_prunes_other_versions_and_abandoned_parts_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / _asset("1.0.0").name
    old.write_bytes(b"old")
    partial = tmp_path / (_asset("3.0.0").name + ".part")
    partial.write_bytes(b"old-part")
    unrelated = tmp_path / "user-notes.txt"
    unrelated.write_text("keep", encoding="utf-8")

    def urlopen(*_args: object, **_kwargs: object) -> _FakeResponse:
        assert not old.exists()
        assert not partial.exists()
        assert unrelated.read_text(encoding="utf-8") == "keep"
        return _FakeResponse()

    monkeypatch.setattr(downloader, "urlopen", urlopen)
    assert download_installer(_asset(), destination_dir=tmp_path).path.is_file()


def test_reparse_named_payload_cannot_be_bypassed_to_add_another_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / _asset("1.0.0").name
    old.write_bytes(b"keep")
    original = cache_io._is_reparse
    inode = old.lstat().st_ino
    monkeypatch.setattr(
        cache_io, "_is_reparse", lambda info: info.st_ino == inode or original(info)
    )
    with pytest.raises(UpdateError, match="linked"):
        download_installer(_asset(), destination_dir=tmp_path)
    assert _payloads(tmp_path) == [old]


@pytest.mark.parametrize(
    "stage", ["staging_close", "final_read", "final_read_close", "receipt_short_write"]
)
def test_disk_read_and_close_failures_are_inside_download_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    _serve(monkeypatch)
    original_open = CacheDirectory.open_file
    original = OSError(f"injected {stage}")

    def fail_read(_size: int) -> bytes:
        raise original

    @contextmanager
    def open_file(cache: CacheDirectory, name: str, *, mode: str = "read"):
        with original_open(cache, name, mode=mode) as stream:
            if stage == "final_read" and name == _asset().name:
                monkeypatch.setattr(stream, "read", fail_read)
            if stage == "receipt_short_write" and ".verified." in name:
                monkeypatch.setattr(stream, "write", lambda payload: len(payload) - 1)
            yield stream
        if stage == "staging_close" and name.endswith(".part"):
            raise original
        if stage == "final_read_close" and name == _asset().name:
            raise original

    monkeypatch.setattr(CacheDirectory, "open_file", open_file)
    with pytest.raises(UpdateError) as raised:
        download_installer(_asset(), destination_dir=tmp_path)
    if stage == "receipt_short_write":
        assert "receipt could not be written completely" in str(raised.value)
    else:
        assert raised.value.__cause__ is original
    assert _payloads(tmp_path) == []
    assert not (tmp_path / receipt_name(_asset().name)).exists()


def test_http_close_failure_does_not_mask_callback_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    response = _serve(monkeypatch)
    original = ValueError("original callback error")

    def callback(*_args: object) -> None:
        raise original

    def close() -> None:
        raise OSError("secondary HTTP close failure")

    monkeypatch.setattr(response, "close", close)
    with pytest.raises(ValueError) as raised:
        download_installer(_asset(), destination_dir=tmp_path, progress_callback=callback)
    assert raised.value is original
    assert "update_response_close_failed" in caplog.text
    assert _payloads(tmp_path) == []
