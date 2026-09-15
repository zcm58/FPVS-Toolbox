"""Cancelable, bounded, SHA-256 verified downloads for the explicit updater flow."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.updates.cache import (
    cleanup_update_cache as cleanup_update_cache,
)
from Main_App.updates.cache import (
    default_update_cache_dir as default_update_cache_dir,
)
from Main_App.updates.cache import (
    discard_file,
    prune_for_download,
    receipt_name,
    verified_installer,
    write_receipt,
)
from Main_App.updates.cache_io import CacheDirectory, check_cancel, locked_cache
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateError,
    UpdateIntegrityError,
    UpdatePhase,
)
from Main_App.updates.patches import require_running_patch_baseline
from Main_App.updates.validation import (
    managed_response,
    validate_asset_identity,
    validate_response_url,
)

ProgressCallback = Callable[[int, int | None], None]
_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 5
MAX_DOWNLOAD_SECONDS = 30 * 60


def download_installer(
    asset: InstallerAsset,
    *,
    destination_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
    verify_patch_files: bool = True,
) -> DownloadedInstaller:
    """Prune, reuse or transfer, verify and promote under one exclusive cache lock.

    A failed or canceled attempt never resumes its partial file. Failed pruning
    refuses the attempt before any additional installer bytes are written.
    """

    check_cancel(cancel_event)
    validate_asset_identity(asset)
    if asset.kind == "patch" and verify_patch_files:
        if phase_callback is not None:
            phase_callback(UpdatePhase("Verifying installed files before downloading the patch..."))
        require_running_patch_baseline(asset, cancel_event=cancel_event)
    if phase_callback is not None:
        phase_callback(UpdatePhase("Preparing the update download..."))
    target_dir = destination_dir if destination_dir is not None else default_update_cache_dir()
    with locked_cache(target_dir, cancel_event=cancel_event) as cache:
        prune_for_download(cache, asset, cancel_event)
        check_cancel(cancel_event)
        if cache.regular_info(asset.name) is not None:
            if phase_callback is not None:
                phase_callback(UpdatePhase("Verifying the previously downloaded update..."))
            try:
                with verified_installer(cache, asset, cancel_event=cancel_event) as existing:
                    _emit_progress(progress_callback, existing.size_bytes, asset.size_bytes)
                    check_cancel(cancel_event)
                    write_receipt(cache, asset, cancel_event)
                    check_cancel(cancel_event)
                    return existing
            except UpdateIntegrityError:
                # Metadata from this request, not a receipt or size alone, governs reuse.
                cache.remove(asset.name)
                cache.remove(receipt_name(asset.name))
        if phase_callback is not None:
            phase_callback(UpdatePhase("Downloading and verifying the update..."))
        return _download_locked(cache, asset, progress_callback, cancel_event)


def _download_locked(
    cache: CacheDirectory,
    asset: InstallerAsset,
    progress_callback: ProgressCallback | None,
    cancel_event: Event | None,
) -> DownloadedInstaller:
    temporary = f"{asset.name}.{uuid.uuid4().hex}.part"
    promoted = False
    completed = False
    try:
        check_cancel(cancel_event)
        request = Request(
            asset.download_url,
            headers={"User-Agent": f"FPVS-Toolbox/{__version__}", "Accept-Encoding": "identity"},
        )
        started = time.monotonic()
        with managed_response(urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)) as response:
            validate_response_url(response)
            _validate_response_length(response, asset.size_bytes)
            check_cancel(cancel_event)
            with cache.open_file(temporary, mode="new") as output:
                downloaded = 0
                digest = hashlib.sha256()
                # HTTPResponse.read(n) can wait indefinitely on a trickling peer.
                # read1 consumes at most one buffered/socket read before we check again.
                read = getattr(response, "read1", response.read)
                while True:
                    check_cancel(cancel_event)
                    if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                        raise UpdateError("Installer download exceeded its time limit.")
                    chunk = read(_CHUNK_SIZE)
                    check_cancel(cancel_event)
                    if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                        raise UpdateError("Installer download exceeded its time limit.")
                    if not chunk:
                        break
                    if asset.size_bytes is None or downloaded + len(chunk) > asset.size_bytes:
                        raise UpdateIntegrityError("Installer exceeded the release asset size.")
                    if output.write(chunk) != len(chunk):
                        raise OSError("The installer download could not be written completely.")
                    downloaded += len(chunk)
                    digest.update(chunk)
                    _emit_progress(progress_callback, downloaded, asset.size_bytes)
                output.flush()
                os.fsync(output.fileno())
        check_cancel(cancel_event)
        info = cache.regular_info(temporary)
        if info is None or info.st_size != asset.size_bytes or downloaded != asset.size_bytes:
            raise UpdateIntegrityError("Downloaded installer size did not match the release asset.")
        if digest.hexdigest() != asset.sha256:
            raise UpdateIntegrityError("Installer SHA-256 did not match the selected GitHub asset.")
        check_cancel(cancel_event)
        promoted = True
        cache.replace(temporary, asset.name)
        # Re-read disk bytes, and deny writes/deletion through receipt finalization.
        with verified_installer(cache, asset, cancel_event=cancel_event) as installer:
            write_receipt(cache, asset, cancel_event)
            _emit_progress(progress_callback, installer.size_bytes, asset.size_bytes)
            check_cancel(cancel_event)
        completed = True
        return installer
    except HTTPError as error:
        raise UpdateError(f"Installer download failed with HTTP {error.code}.") from error
    except URLError as error:
        raise UpdateError(f"Could not download the installer: {error.reason}") from error
    except TimeoutError as error:
        raise UpdateError("Installer download timed out.") from error
    except OSError as error:
        raise UpdateError(f"Could not write the installer download: {error}") from error
    finally:
        # Includes callback, open/read/close, stat, validation, fsync and replace errors.
        discard_file(cache, temporary)
        if promoted and not completed:
            discard_file(cache, asset.name)
            discard_file(cache, receipt_name(asset.name))


def _validate_response_length(response: object, expected: int | None) -> None:
    headers = getattr(response, "headers", None)
    raw = headers.get("Content-Length") if headers is not None else None
    if raw is None:
        return
    try:
        actual = int(raw)
    except (TypeError, ValueError) as error:
        raise UpdateIntegrityError("GitHub returned an invalid installer content length.") from error
    if actual != expected:
        raise UpdateIntegrityError("Installer content length did not match the release asset.")


def _emit_progress(progress_callback: ProgressCallback | None, downloaded: int, total: int | None) -> None:
    if progress_callback is not None:
        progress_callback(downloaded, total)
