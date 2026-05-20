"""Installer download backend tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from Main_App.updates.downloader import download_installer
from Main_App.updates.installer import launch_installer
from Main_App.updates.models import InstallerAsset, UpdateError


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FailingResponse(_FakeResponse):
    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        if chunk:
            return chunk
        raise OSError("stream failed")


def _asset(name: str = "FPVSToolbox-1.0.1-setup.exe", *, size_bytes: int | None = 9) -> InstallerAsset:
    return InstallerAsset(
        name=name,
        download_url=f"https://github.com/downloads/{name}",
        size_bytes=size_bytes,
    )


def test_download_installer_writes_to_destination_and_reports_progress(
    monkeypatch,
    tmp_path: Path,
) -> None:
    payload = b"installer"
    progress: list[tuple[int, int | None]] = []

    monkeypatch.setattr(
        "Main_App.updates.downloader.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    result = download_installer(
        _asset(size_bytes=len(payload)),
        destination_dir=tmp_path,
        progress_callback=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert result.path == tmp_path / "FPVSToolbox-1.0.1-setup.exe"
    assert result.path.read_bytes() == payload
    assert result.size_bytes == len(payload)
    assert progress[-1] == (len(payload), len(payload))


def test_download_installer_reuses_complete_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "FPVSToolbox-1.0.1-setup.exe"
    target.write_bytes(b"installer")
    progress: list[tuple[int, int | None]] = []

    result = download_installer(
        _asset(size_bytes=target.stat().st_size),
        destination_dir=tmp_path,
        progress_callback=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert result.path == target
    assert progress == [(len(b"installer"), len(b"installer"))]


def test_download_installer_rejects_non_https_urls(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="HTTPS"):
        download_installer(
            InstallerAsset(
                name="FPVSToolbox-1.0.1-setup.exe",
                download_url="http://example.com/FPVSToolbox-1.0.1-setup.exe",
                size_bytes=1,
            ),
            destination_dir=tmp_path,
        )


def test_download_installer_rejects_path_like_asset_names(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="invalid filename"):
        download_installer(
            _asset(name="nested/FPVSToolbox-1.0.1-setup.exe"),
            destination_dir=tmp_path,
        )


def test_download_installer_removes_partial_file_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "Main_App.updates.downloader.urlopen",
        lambda *_args, **_kwargs: _FailingResponse(b"installer"),
    )

    with pytest.raises(UpdateError, match="write"):
        download_installer(_asset(size_bytes=None), destination_dir=tmp_path)

    assert not (tmp_path / "FPVSToolbox-1.0.1-setup.exe.part").exists()


def test_launch_installer_requires_existing_exe(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="does not exist"):
        launch_installer(tmp_path / "missing.exe")

    not_exe = tmp_path / "installer.txt"
    not_exe.write_text("not an exe", encoding="utf-8")
    with pytest.raises(UpdateError, match="Windows .exe"):
        launch_installer(not_exe)


def test_launch_installer_requests_relaunch(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "FPVSToolbox-1.0.1-setup.exe"
    installer.write_bytes(b"installer")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        "Main_App.updates.installer.subprocess.Popen",
        lambda command, **_kwargs: commands.append(command),
    )

    launch_installer(installer)

    assert commands == [[str(installer), "/RELAUNCH=1"]]
