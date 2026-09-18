"""Authenticated direct-patch discovery and read-only installed-baseline checks."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from threading import Event
from urllib.error import URLError
from urllib.request import Request, urlopen

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.updates.application import UNINSTALL_KEY, APPLICATION_FILENAME
from Main_App.updates.cache_io import (
    CacheDirectory,
    check_cancel,
    guarded_read_directory,
    guarded_read_path,
)
from Main_App.updates.models import (
    InstallerAsset,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
    UpdateIntegrityError,
    UpdatePhase,
    normalize_sha256,
)
from Main_App.updates.validation import (
    managed_response,
    parse_release_version,
    validate_asset_identity,
    validate_release_asset_url,
    validate_response_url,
)

MAX_PATCH_METADATA_BYTES = 1024 * 1024
MAX_PATCH_METADATA_SECONDS = 30
MAX_INVENTORY_BYTES = 64 * 1024 * 1024
MAX_INVENTORY_FILES = 250_000
MAX_BASE_BYTES = 16 * 1024**3
MAX_BASE_SECONDS = 5 * 60
INVENTORY_NAME = "fpvs-owned-files-v1.txt"
_UNINSTALL_KEY = UNINSTALL_KEY
_HASH_CHUNK = 1024 * 1024
_LOG = logging.getLogger(__name__)
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|clock\$|com[1-9¹²³]|lpt[1-9¹²³])\Z", re.I)
_PROTECTED = {
    ".fpvs-toolbox",
    "cache",
    "logs",
    "project.json",
    "runs",
    "stimuli",
    INVENTORY_NAME,
    "fpvs-pending-owned-files-v1.txt",
    "fpvs-patch-transaction-v1.txt",
}


def _windows_process_executable() -> Path | None:
    """Read the executable and effective architecture from Windows, not Python hints."""
    if sys.platform != "win32":
        _LOG.info("Patch unavailable: process is not running on Windows")
        return None
    import ctypes
    from ctypes import wintypes

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.IsWow64Process2.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.USHORT),
            ctypes.POINTER(wintypes.USHORT),
        ]
        kernel.IsWow64Process2.restype = wintypes.BOOL
        kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        kernel.GetModuleFileNameW.restype = wintypes.DWORD
        process_machine, native_machine = wintypes.USHORT(), wintypes.USHORT()
        if not kernel.IsWow64Process2(
            kernel.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)
        ):
            _LOG.warning("Patch process architecture lookup failed: %s", ctypes.get_last_error())
            return None
        # UNKNOWN means native execution. x64 emulation on ARM64 is also an
        # x64-compatible process; native ARM64 and 32-bit Python are not.
        if (process_machine.value or native_machine.value) != 0x8664:
            _LOG.info("Patch unavailable: process architecture is not x64")
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(None, buffer, len(buffer))
        if not 0 < length < len(buffer):
            _LOG.warning("Patch process executable lookup failed or returned a truncated path")
            return None
        return Path(buffer.value)
    except (AttributeError, OSError):
        _LOG.warning("Patch process identity API unavailable", exc_info=True)
        return None


def installed_patch_root() -> Path | None:
    """Require the actual x64 executable to match the registered installation."""
    executable = _windows_process_executable()
    if executable is None:
        return None
    if executable.name.casefold() != APPLICATION_FILENAME.casefold():
        _LOG.info("Patch unavailable: process is not the installed FPVS Toolbox executable")
        return None
    # A portable copy can contain valid inventory bytes, but Inno must update the
    # same per-user registered installation. Match its explicit 64-bit view.
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _UNINSTALL_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as registration:
            location, location_type = winreg.QueryValueEx(registration, "InstallLocation")
            version, version_type = winreg.QueryValueEx(registration, "DisplayVersion")
    except OSError:
        _LOG.info("Patch unavailable: per-user installation registration could not be read")
        return None
    if (
        location_type != winreg.REG_SZ
        or version_type != winreg.REG_SZ
        or not isinstance(location, str)
        or not isinstance(version, str)
    ):
        _LOG.info("Patch unavailable: installation registration has invalid value types")
        return None
    if Path(location) != executable.parent:
        _LOG.info("Patch unavailable: executable directory differs from installation registration")
        return None
    if version != __version__:
        _LOG.info(
            "Patch unavailable: registered version %r differs from running version %r",
            version,
            __version__,
        )
        return None
    return executable.parent


def select_patch_update(
    result: UpdateCheckResult,
    assets: Sequence[dict[str, object]],
    *,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> UpdateCheckResult:
    """Choose the smallest authenticated compatible patch, with an explicit full reason."""

    check_cancel(cancel_event)
    root = installed_patch_root()
    if root is None:
        return replace(
            result,
            selection_reason=("Full installer for this unregistered or unsupported application build."),
        )
    name = f"FPVSToolbox-Update-{result.latest_version}.json"
    matching = [item for item in assets if item.get("name") == name]
    if not matching:
        return replace(result, selection_reason="This release provides a full installer.")
    if len(matching) != 1:
        raise UpdateIntegrityError("The release has ambiguous patch metadata assets.")
    document = _fetch_manifest(matching[0], result.latest_version, cancel_event)
    patches = _parse_manifest(document, assets, result.latest_version)
    full = result.installer_asset
    if full is None or full.sha256 is None:
        return replace(result, selection_reason="The release has no verified full installer.")
    compatible = [asset for asset in patches if asset.from_version == result.current_version]
    if not compatible:
        return replace(result, selection_reason="No direct patch is available for your version.")
    for asset in sorted(compatible, key=lambda candidate: candidate.size_bytes or 0):
        if (asset.size_bytes or 0) >= (full.size_bytes or 0):
            continue
        try:
            if phase_callback is not None:
                phase_callback(UpdatePhase("Verifying installed files for the smaller patch...", result))
            verify_patch_baseline(asset, root, result.current_version, cancel_event=cancel_event)
        except UpdateCancelled:
            raise
        except (UpdateError, OSError) as error:
            _LOG.info("update_patch_baseline_incompatible", extra={"reason": str(error)})
            return replace(
                result,
                selection_reason=("The installed files do not match this patch. A full update is required."),
            )
        return replace(
            result,
            installer_asset=asset,
            selection_reason="Smaller patch verified for your installed version.",
        )
    return replace(result, selection_reason="The full installer is the smaller download.")


def require_running_patch_baseline(asset: InstallerAsset, *, cancel_event: Event | None = None) -> Path:
    """Recheck the actual running install before transfer or installer handoff."""

    root = installed_patch_root()
    if root is None:
        raise UpdateError("Patch updates require an installed Windows x64 application.")
    try:
        verify_patch_baseline(asset, root, __version__, cancel_event=cancel_event)
    except UpdateCancelled:
        raise
    except (UpdateError, OSError) as error:
        raise UpdateIntegrityError(
            "The installed application no longer matches this patch. "
            "Check for updates again to select the full installer."
        ) from error
    return root


def select_patch_candidate(
    result: UpdateCheckResult,
    assets: Sequence[dict[str, object]],
    *,
    install_root: Path | None,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> UpdateCheckResult:
    """Choose a download candidate; Inno performs full compatibility checks at install."""
    check_cancel(cancel_event)
    if install_root is None:
        return replace(result, selection_reason="A full installer is available for this build.")
    name = f"FPVSToolbox-Update-{result.latest_version}.json"
    matching = [item for item in assets if item.get("name") == name]
    if not matching:
        return replace(result, selection_reason="This release provides a full installer.")
    if len(matching) != 1:
        raise UpdateIntegrityError("The release has ambiguous patch metadata assets.")
    if phase_callback is not None:
        phase_callback(UpdatePhase("Checking available patch metadata...", result))
    document = _fetch_manifest(matching[0], result.latest_version, cancel_event)
    candidates = _parse_manifest(document, assets, result.latest_version)
    full = result.installer_asset
    if full is None or full.sha256 is None:
        return result
    candidates = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.from_version == result.current_version and (candidate.size_bytes or 0) < (full.size_bytes or 0)
        ),
        key=lambda candidate: candidate.size_bytes or 0,
    )
    for candidate in candidates:
        try:
            _read_baseline_inventory(candidate, install_root, result.current_version, cancel_event)
        except UpdateCancelled:
            raise
        except (UpdateError, OSError) as error:
            _LOG.info("update_patch_inventory_incompatible", extra={"reason": str(error)})
            continue
        return replace(
            result,
            installer_asset=candidate,
            selection_reason=("Smaller patch available. Compatibility is checked during installation."),
        )
    return replace(result, selection_reason="A full installer is required for this installation.")


def _read_baseline_inventory(asset: InstallerAsset, root: Path, version: str, cancel_event: Event | None) -> list[str]:
    started = time.monotonic()
    with guarded_read_path(root / INVENTORY_NAME, cancel_event=cancel_event) as source:
        raw = bytearray()
        while True:
            _checkpoint(cancel_event, started, MAX_PATCH_METADATA_SECONDS)
            chunk = source.read(_HASH_CHUNK)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_INVENTORY_BYTES:
                raise UpdateIntegrityError("the installed inventory is too large.")
    if hashlib.sha256(raw).hexdigest() != asset.source_inventory_sha256:
        raise UpdateIntegrityError("the installed inventory does not match the patch baseline.")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeError as error:
        raise UpdateIntegrityError("the installed inventory is unreadable.") from error
    if lines[:3] != ["FPVS-TOOLBOX-OWNED-FILES-1", "kind=current", f"version={version}"]:
        raise UpdateIntegrityError("the installed inventory has a different version.")
    return lines


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UpdateIntegrityError("Patch metadata contains duplicate JSON fields.")
        result[key] = value
    return result


def _fetch_manifest(metadata: dict[str, object], target: str, cancel_event: Event | None) -> object:
    name, url, size = (
        metadata.get("name"),
        metadata.get("browser_download_url"),
        metadata.get("size"),
    )
    digest = metadata.get("digest")
    asset_id = metadata.get("id")
    if (
        not isinstance(name, str)
        or not isinstance(url, str)
        or type(size) is not int
        or not 0 < size <= MAX_PATCH_METADATA_BYTES
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or normalize_sha256(digest) is None
        or type(asset_id) is not int
        or asset_id <= 0
    ):
        raise UpdateIntegrityError("The release has no trusted, bounded patch metadata asset.")
    validate_release_asset_url(name, url, target)
    started = time.monotonic()
    request = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "FPVSToolbox-Updater"})
    try:
        with managed_response(urlopen(request, timeout=5)) as response:
            validate_response_url(response)
            headers = getattr(response, "headers", None)
            length = headers.get("Content-Length") if headers is not None else None
            if length is not None and length != str(size):
                raise UpdateIntegrityError("Patch metadata content length does not match GitHub.")
            payload = bytearray()
            read = getattr(response, "read1", response.read)
            while True:
                _checkpoint(cancel_event, started, MAX_PATCH_METADATA_SECONDS)
                chunk = read(64 * 1024)
                _checkpoint(cancel_event, started, MAX_PATCH_METADATA_SECONDS)
                if not chunk:
                    break
                if len(payload) + len(chunk) > size:
                    raise UpdateIntegrityError("Patch metadata exceeded its GitHub asset size.")
                payload.extend(chunk)
    except (OSError, URLError) as error:
        raise UpdateError(f"Could not read patch update metadata: {error}") from error
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != normalize_sha256(digest):
        raise UpdateIntegrityError("Patch metadata SHA-256 or size did not match GitHub.")
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as error:
        raise UpdateIntegrityError("The release has unreadable patch update metadata.") from error


def _parse_manifest(document: object, assets: Sequence[dict[str, object]], target: str) -> list[InstallerAsset]:
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "target_version", "platform", "patches"}
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or document["target_version"] != target
        or document["platform"] != "windows-x64"
        or not isinstance(document["patches"], list)
        or len(document["patches"]) > 100
    ):
        raise UpdateIntegrityError("The release has an invalid patch manifest identity or schema.")
    patches = []
    seen: set[str] = set()
    for item in document["patches"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"from_version", "source_inventory_sha256", "asset_name", "size_bytes", "sha256"}
            or not isinstance(item["from_version"], str)
            or not isinstance(item["asset_name"], str)
        ):
            raise UpdateIntegrityError("The release has an invalid direct patch entry.")
        source = item["from_version"]
        if (
            str(parse_release_version(source)) != source
            or parse_release_version(source) >= parse_release_version(target)
            or item["asset_name"] != f"FPVSToolbox-Patch-{source}-to-{target}.exe"
            or source in seen
        ):
            raise UpdateIntegrityError("The patch source, target, or filename is invalid or duplicated.")
        seen.add(source)
        matches = [candidate for candidate in assets if candidate.get("name") == item["asset_name"]]
        if len(matches) != 1:
            raise UpdateIntegrityError("The patch manifest does not identify one GitHub asset.")
        github = matches[0]
        digest = github.get("digest")
        url = github.get("browser_download_url")
        asset_id = github.get("id")
        if (
            not isinstance(url, str)
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or normalize_sha256(digest) != item["sha256"]
            or normalize_sha256(item["sha256"]) != item["sha256"]
            or item["sha256"] is None
            or type(item["size_bytes"]) is not int
            or github.get("size") != item["size_bytes"]
            or type(github.get("size")) is not int
            or type(asset_id) is not int
            or asset_id <= 0
        ):
            raise UpdateIntegrityError("The patch size, SHA-256, or identity does not match GitHub.")
        asset = InstallerAsset(
            name=item["asset_name"],
            download_url=url,
            size_bytes=item["size_bytes"],
            sha256=item["sha256"],
            version=target,
            asset_id=asset_id,
            kind="patch",
            from_version=source,
            source_inventory_sha256=item["source_inventory_sha256"],
        )
        validate_asset_identity(asset)
        patches.append(asset)
    return patches


def verify_patch_baseline(
    asset: InstallerAsset, root: Path, current_version: str, *, cancel_event: Event | None = None
) -> None:
    """Authenticate the official installed inventory, then verify every baseline file.

    The inventory's trusted digest comes from the GitHub-authenticated manifest.
    A local ownership receipt alone cannot qualify a modified installation.
    Inno repeats verification immediately before applying any changes.
    """

    validate_asset_identity(asset)
    if asset.kind != "patch" or asset.from_version != current_version:
        raise UpdateIntegrityError("the installed version does not match the patch baseline.")
    started = time.monotonic()
    with guarded_read_path(root / INVENTORY_NAME, cancel_event=cancel_event) as source:
        raw = bytearray()
        while True:
            _checkpoint(cancel_event, started, MAX_BASE_SECONDS)
            chunk = source.read(_HASH_CHUNK)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_INVENTORY_BYTES:
                raise UpdateIntegrityError("the installed inventory is too large.")
    if hashlib.sha256(raw).hexdigest() != asset.source_inventory_sha256:
        raise UpdateIntegrityError("the installed file inventory does not match the patch baseline.")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeError as error:
        raise UpdateIntegrityError("the installed file inventory is unreadable.") from error
    if (
        lines[:3] != ["FPVS-TOOLBOX-OWNED-FILES-1", "kind=current", f"version={current_version}"]
        or not 0 < len(lines) - 3 <= MAX_INVENTORY_FILES
    ):
        raise UpdateIntegrityError("the installed inventory has an invalid version or format.")
    with ExitStack() as parent_guards:
        seen: set[str] = set()
        total = 0
        directory: CacheDirectory | None = None
        for line in lines[3:]:
            _checkpoint(cancel_event, started, MAX_BASE_SECONDS)
            pieces = line.split("|")
            if len(pieces) != 2 or normalize_sha256(pieces[1]) != pieces[1]:
                raise UpdateIntegrityError("the installed inventory contains an invalid file record.")
            relative, expected = pieces
            _validate_relative_path(relative)
            if relative.casefold() in seen:
                raise UpdateIntegrityError("the installed inventory contains a duplicate path.")
            seen.add(relative.casefold())
            path = root / relative
            if directory is None or directory.path != path.parent:
                parent_guards.close()
                directory = parent_guards.enter_context(guarded_read_directory(path.parent, cancel_event=cancel_event))
            with directory.open_file(path.name) as source:
                before = os.fstat(source.fileno())
                if total + before.st_size > MAX_BASE_BYTES:
                    raise UpdateIntegrityError("the installed patch baseline exceeds its size limit.")
                digest = hashlib.sha256()
                count = 0
                while True:
                    _checkpoint(cancel_event, started, MAX_BASE_SECONDS)
                    chunk = source.read(_HASH_CHUNK)
                    _checkpoint(cancel_event, started, MAX_BASE_SECONDS)
                    if not chunk:
                        break
                    count += len(chunk)
                    total += len(chunk)
                    if count > before.st_size or total > MAX_BASE_BYTES:
                        raise UpdateIntegrityError("an installed file changed during patch verification.")
                    digest.update(chunk)
                after = os.fstat(source.fileno())
                if (
                    count != before.st_size
                    or digest.hexdigest() != expected
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise UpdateIntegrityError("an installed application file differs from the patch baseline.")
        if APPLICATION_FILENAME.casefold() not in seen:
            raise UpdateIntegrityError("the patch baseline has no application executable.")
        _checkpoint(cancel_event, started, MAX_BASE_SECONDS)


def _validate_relative_path(value: str) -> None:
    parts = value.split("/")
    if (
        not value
        or len(value) > 1024
        or PureWindowsPath(value).drive
        or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"\\|?*' for char in value)
        or any(
            part in {"", ".", ".."} or part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part.split(".", 1)[0])
            for part in parts
        )
        or parts[0].casefold() in _PROTECTED
        or (len(parts) == 1 and value.casefold().startswith("unins"))
    ):
        raise UpdateIntegrityError("the installed inventory contains an unsafe file path.")


def _checkpoint(event: Event | None, started: float, limit: int) -> None:
    check_cancel(event)
    if time.monotonic() - started > limit:
        raise UpdateError("Patch verification exceeded its time limit.")
