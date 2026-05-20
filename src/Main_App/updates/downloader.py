"""Installer download helpers for the FPVS Toolbox updater."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import FPVS_TOOLBOX_VERSION
from Main_App.Shared.settings_paths import APP_CONFIG_DIR_NAME
from Main_App.updates.models import DownloadedInstaller, InstallerAsset, UpdateError

ProgressCallback = Callable[[int, int | None], None]

_CHUNK_SIZE = 1024 * 1024


def default_update_cache_dir() -> Path:
    """Return the user-writable cache folder for downloaded update installers."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_CONFIG_DIR_NAME / "updates"
    return Path(tempfile.gettempdir()) / APP_CONFIG_DIR_NAME / "updates"


def download_installer(
    asset: InstallerAsset,
    *,
    destination_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DownloadedInstaller:
    """Download one validated installer asset to a user-writable cache path."""

    _validate_asset(asset)
    target_dir = destination_dir or default_update_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / asset.name

    if target_path.is_file() and asset.size_bytes is not None:
        existing_size = target_path.stat().st_size
        if existing_size == asset.size_bytes:
            _emit_progress(progress_callback, existing_size, asset.size_bytes)
            return DownloadedInstaller(path=target_path, size_bytes=existing_size)

    temp_path = target_path.with_suffix(f"{target_path.suffix}.part")
    request = Request(
        asset.download_url,
        headers={"User-Agent": f"FPVS-Toolbox/{FPVS_TOOLBOX_VERSION}"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            total = _response_total(response, fallback=asset.size_bytes)
            downloaded = 0
            with temp_path.open("wb") as output:
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    _emit_progress(progress_callback, downloaded, total)
    except HTTPError as error:
        _unlink_partial(temp_path)
        raise UpdateError(f"Installer download failed with HTTP {error.code}.") from error
    except URLError as error:
        _unlink_partial(temp_path)
        raise UpdateError(f"Could not download the installer: {error.reason}") from error
    except TimeoutError as error:
        _unlink_partial(temp_path)
        raise UpdateError("Installer download timed out.") from error
    except OSError as error:
        _unlink_partial(temp_path)
        raise UpdateError(f"Could not write the installer download: {error}") from error

    final_size = temp_path.stat().st_size
    if asset.size_bytes is not None and final_size != asset.size_bytes:
        _unlink_partial(temp_path)
        raise UpdateError("Downloaded installer size did not match the release asset.")

    try:
        temp_path.replace(target_path)
    except OSError as error:
        _unlink_partial(temp_path)
        raise UpdateError(f"Could not finalize the installer download: {error}") from error
    _emit_progress(progress_callback, final_size, asset.size_bytes)
    return DownloadedInstaller(path=target_path, size_bytes=final_size)


def _validate_asset(asset: InstallerAsset) -> None:
    parsed_url = urlparse(asset.download_url)
    if parsed_url.scheme != "https":
        raise UpdateError("Installer downloads require an HTTPS URL.")
    if not asset.name.lower().endswith(".exe"):
        raise UpdateError("The selected update asset is not a Windows installer.")
    if "/" in asset.name or "\\" in asset.name:
        raise UpdateError("The selected update asset has an invalid filename.")


def _response_total(response: object, *, fallback: int | None) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw_length = headers.get("Content-Length")
        if raw_length is not None:
            try:
                parsed = int(raw_length)
            except ValueError:
                return fallback
            if parsed >= 0:
                return parsed
    return fallback


def _emit_progress(
    progress_callback: ProgressCallback | None,
    downloaded: int,
    total: int | None,
) -> None:
    if progress_callback is not None:
        progress_callback(downloaded, total)


def _unlink_partial(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
