"""Bounded updater cache retention and offline verification receipts.

Receipts are small cache bookkeeping, not a replacement trust source for execution.
Reuse and launch always verify against the selected asset's GitHub metadata again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

from packaging.version import Version
from Main_App.updates.application import APP_NAME

from Main_App.updates.cache_io import (
    CacheDirectory,
    check_cancel,
    locked_cache,
    validate_cache_path,
)
from Main_App.updates.models import (
    CacheCleanupResult,
    DownloadedInstaller,
    InstallerAsset,
    UpdateCacheBusy,
    UpdateCancelled,
    UpdateError,
    UpdateIntegrityError,
)
from Main_App.updates.validation import (
    installer_filename_version,
    parse_release_version,
    validate_asset_identity,
)

_LOG = logging.getLogger(__name__)
_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_RECEIPT_BYTES = 16 * 1024
_UUID_SUFFIX = r"[0-9a-fA-F]{32}"


@dataclass(frozen=True)
class CacheEntry:
    name: str
    installer_name: str
    kind: str


def default_update_cache_dir() -> Path:
    """App-owned storage, deliberately independent of projects and settings roots."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return base / APP_NAME / "updates"


def recognized_cache_entry(name: str) -> CacheEntry | None:
    """Recognize only direct updater payload/receipt names, including old .exe.part files."""

    if installer_filename_version(name) is not None:
        return CacheEntry(name, name, "installer")
    for suffix, kind in (
        (r"\.verified\.json", "receipt"),
        (rf"\.verified\.{_UUID_SUFFIX}\.tmp", "receipt_temp"),
        (rf"\.(?:{_UUID_SUFFIX}\.)?part", "partial"),
    ):
        match = re.fullmatch(rf"(?P<installer>.+\.exe){suffix}", name, re.IGNORECASE | re.ASCII)
        if match is not None and installer_filename_version(match.group("installer")) is not None:
            return CacheEntry(name, match.group("installer"), kind)
    return None


def receipt_name(installer_name: str) -> str:
    return f"{installer_name}.verified.json"


def _entries(cache: CacheDirectory) -> list[CacheEntry]:
    return [entry for name in cache.names() if (entry := recognized_cache_entry(name)) is not None]


def prune_for_download(cache: CacheDirectory, asset: InstallerAsset, cancel_event: Event | None) -> None:
    """Explicit selection supersedes all other payloads; any pruning error stops the attempt."""

    for entry in _entries(cache):
        check_cancel(cancel_event)
        # A recognized directory/link is never deleted and must not be worked around.
        cache.regular_info(entry.name)
        if entry.kind == "installer" and entry.name == asset.name:
            continue
        if entry.kind == "receipt" and entry.installer_name == asset.name:
            continue
        cache.remove(entry.name)


def cleanup_update_cache(
    current_version: str,
    *,
    cache_dir: Path | None = None,
    cancel_event: Event | None = None,
) -> CacheCleanupResult:
    """Best-effort startup maintenance. Never fetch metadata, download, or launch here."""

    removed: list[Path] = []
    warnings: list[str] = []
    kept: Path | None = None
    try:
        check_cancel(cancel_event)
        current = parse_release_version(current_version)
        path = validate_cache_path(cache_dir if cache_dir is not None else default_update_cache_dir())
        try:
            path.lstat()
        except FileNotFoundError:
            return CacheCleanupResult()
        with locked_cache(path, create=False, cancel_event=cancel_event) as cache:
            kept = _cleanup_locked(cache, current, cancel_event, removed, warnings)
    except UpdateCancelled:
        raise
    except UpdateCacheBusy as error:
        _LOG.info("update_cache_cleanup_busy", extra={"reason": str(error)})
        return CacheCleanupResult(busy=True)
    except (UpdateError, OSError) as error:
        _record_warning(warnings, error)
    return CacheCleanupResult(kept, tuple(removed), tuple(warnings))


def _cleanup_locked(
    cache: CacheDirectory,
    current: Version,
    cancel_event: Event | None,
    removed: list[Path],
    warnings: list[str],
) -> Path | None:
    entries = _entries(cache)
    candidates: list[tuple[Version, InstallerAsset]] = []
    for entry in entries:
        check_cancel(cancel_event)
        if entry.kind in {"partial", "receipt_temp"}:
            _remove_best_effort(cache, entry.name, removed, warnings)
        elif entry.kind == "installer":
            try:
                cache.regular_info(entry.name)
                asset = _read_receipt(cache, entry.name)
                version = validate_asset_identity(asset)
                if version > current and (asset.kind != "patch" or asset.from_version == str(current)):
                    candidates.append((version, asset))
                else:
                    _remove_best_effort(cache, entry.name, removed, warnings)
            except UpdateIntegrityError:
                _remove_best_effort(cache, entry.name, removed, warnings)
            except (UpdateError, OSError) as error:
                _record_warning(warnings, error)

    kept: Path | None = None
    for _, asset in sorted(candidates, key=lambda item: (item[0], item[1].name), reverse=True):
        check_cancel(cancel_event)
        if kept is not None:
            _remove_best_effort(cache, asset.name, removed, warnings)
            continue
        try:
            with verified_installer(cache, asset, cancel_event=cancel_event) as installer:
                kept = installer.path
        except UpdateCancelled:
            raise
        except UpdateIntegrityError:
            _remove_best_effort(cache, asset.name, removed, warnings)
        except (UpdateError, OSError) as error:
            _record_warning(warnings, error)

    # Do not discard receipts for payloads whose removal was blocked by the OS.
    for entry in entries:
        check_cancel(cancel_event)
        if entry.kind != "receipt":
            continue
        try:
            if cache.regular_info(entry.installer_name) is None:
                _remove_best_effort(cache, entry.name, removed, warnings)
        except (UpdateError, OSError) as error:
            _record_warning(warnings, error)
    return kept


def _remove_best_effort(cache: CacheDirectory, name: str, removed: list[Path], warnings: list[str]) -> None:
    try:
        if cache.remove(name):
            removed.append(cache.child(name))
    except (UpdateError, OSError) as error:
        _record_warning(warnings, error)


def _record_warning(warnings: list[str], error: Exception) -> None:
    warnings.append(str(error))
    _LOG.warning("update_cache_cleanup_failed", extra={"reason": str(error)})


def discard_file(cache: CacheDirectory, name: str) -> None:
    """Failure cleanup must never replace the original transfer/verification exception."""

    try:
        cache.remove(name)
    except Exception:  # Cleanup must preserve the original transfer/verification error.
        _LOG.warning("update_cache_discard_failed", extra={"cache_file": name}, exc_info=True)


def _read_receipt(cache: CacheDirectory, name: str) -> InstallerAsset:
    try:
        with cache.open_file(receipt_name(name)) as source:
            raw = source.read(_MAX_RECEIPT_BYTES + 1)
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise UpdateIntegrityError("The update verification receipt is too large.")
        data = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or type(data.get("schema")) is not int
            or data.get("schema") != 1
            or data.get("name") != name
        ):
            raise UpdateIntegrityError("The update verification receipt has an invalid identity.")
        if not isinstance(data.get("download_url"), str) or not isinstance(data.get("version"), str):
            raise UpdateIntegrityError("The update verification receipt is incomplete.")
        asset_id = data.get("asset_id")
        if asset_id is not None and (type(asset_id) is not int or asset_id <= 0):
            raise UpdateIntegrityError("The update verification receipt has an invalid asset ID.")
        asset = InstallerAsset(
            name=name,
            download_url=data["download_url"],
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
            version=data["version"],
            asset_id=asset_id,
            kind=data.get("kind", "full"),
            from_version=data.get("from_version"),
            source_inventory_sha256=data.get("source_inventory_sha256"),
        )
        validate_asset_identity(asset)
        return asset
    except FileNotFoundError as error:
        raise UpdateIntegrityError("The cached installer has no verification receipt.") from error
    except (UnicodeError, ValueError, TypeError, UpdateError) as error:
        raise UpdateIntegrityError("The cached installer has an invalid verification receipt.") from error


def write_receipt(cache: CacheDirectory, asset: InstallerAsset, cancel_event: Event | None) -> None:
    version = validate_asset_identity(asset)
    check_cancel(cancel_event)
    payload = json.dumps({"schema": 1, **asdict(asset), "version": str(version)}, sort_keys=True)
    encoded = payload.encode("utf-8")
    if len(encoded) > _MAX_RECEIPT_BYTES:
        raise UpdateError("The update verification metadata is too large to cache safely.")
    temporary = f"{asset.name}.verified.{uuid.uuid4().hex}.tmp"
    try:
        with cache.open_file(temporary, mode="new") as output:
            if output.write(encoded) != len(encoded):
                raise OSError("The update verification receipt could not be written completely.")
            output.flush()
            os.fsync(output.fileno())
        check_cancel(cancel_event)
        cache.replace(temporary, receipt_name(asset.name))
    finally:
        discard_file(cache, temporary)


@contextmanager
def verified_installer(
    cache: CacheDirectory, asset: InstallerAsset, *, cancel_event: Event | None = None
) -> Iterator[DownloadedInstaller]:
    """Hash a pinned regular file and keep its no-write/delete guard until the caller exits."""

    validate_asset_identity(asset)
    check_cancel(cancel_event)
    with cache.open_file(asset.name) as source:
        before = os.fstat(source.fileno())
        if before.st_size != asset.size_bytes:
            raise UpdateIntegrityError("Installer size did not match the release asset.")
        digest = hashlib.sha256()
        total = 0
        while True:
            check_cancel(cancel_event)
            chunk = source.read(_HASH_CHUNK_SIZE)
            check_cancel(cancel_event)
            if not chunk:
                break
            total += len(chunk)
            if asset.size_bytes is None or total > asset.size_bytes:
                raise UpdateIntegrityError("Installer exceeded the release asset size.")
            digest.update(chunk)
        after = os.fstat(source.fileno())
        current = cache.regular_info(asset.name)
        if (
            current is None
            or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or total != asset.size_bytes
            or digest.hexdigest() != asset.sha256
        ):
            raise UpdateIntegrityError("Installer SHA-256 did not match the selected GitHub asset.")
        check_cancel(cancel_event)
        yield DownloadedInstaller(cache.child(asset.name), total, digest.hexdigest(), asset)
