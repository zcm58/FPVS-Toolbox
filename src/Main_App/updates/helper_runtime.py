"""Independent helper staging and guarded Windows installation handoff.

The helper is copied outside the application before it runs, so native setup can
replace the bundled helper together with Toolbox. No project directory is involved.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from Main_App.updates.cache import default_update_cache_dir, discard_file, verified_installer
from Main_App.updates.cache_io import (
    check_cancel,
    guarded_read_directory,
    guarded_read_path,
    locked_cache,
    validate_cache_path,
)
from Main_App.updates.github_releases import DEFAULT_RELEASES_API_URL, fetch_release_metadata
from Main_App.updates.installer import launch_installer
from Main_App.updates.models import (
    DownloadedInstaller,
    UpdateError,
    UpdatePhase,
    normalize_sha256,
)
from Main_App.updates.process_launch import launch_independent_process
from Main_App.updates.validation import parse_release_version, validate_asset_identity
from Main_App.updates.application import APPLICATION_FILENAME, UPDATER_FILENAME, UNINSTALL_KEY

_UNINSTALL_KEY = UNINSTALL_KEY
_STAGED_NAME = re.compile(r"updater-[0-9a-f]{64}\.exe\Z")
_PART_NAME = re.compile(r"updater-[0-9a-f]{32}\.part\Z")
_MAX_HELPER_BYTES = 512 * 1024 * 1024
_MAX_STAGED_HELPERS = 2
_CHUNK_SIZE = 1024 * 1024
PARENT_EXIT_TIMEOUT_SECONDS = 120
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstalledApplication:
    root: Path
    version: str
    all_users: bool = False


def registered_installation() -> InstalledApplication | None:
    """Read Toolbox's registration, independently of the helper's own version."""
    if sys.platform != "win32":
        return None
    import winreg

    for hive, all_users in ((winreg.HKEY_CURRENT_USER, False), (winreg.HKEY_LOCAL_MACHINE, True)):
        try:
            with winreg.OpenKey(hive, _UNINSTALL_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                location, location_type = winreg.QueryValueEx(key, "InstallLocation")
                version, version_type = winreg.QueryValueEx(key, "DisplayVersion")
            break
        except FileNotFoundError:
            continue
        except OSError as error:
            raise UpdateError("Could not read Toolbox's installation registration.") from error
    else:
        return None
    if (
        location_type != winreg.REG_SZ
        or version_type != winreg.REG_SZ
        or not isinstance(location, str)
        or not isinstance(version, str)
    ):
        raise UpdateError("Toolbox's installation registration is invalid.")
    parse_release_version(version)
    root = validate_cache_path(Path(location))
    with guarded_read_directory(root):
        pass
    return InstalledApplication(root, version, all_users)


def helper_cache_dir() -> Path:
    return default_update_cache_dir().parent / "updater-helper"


def stage_helper(executable: Path, *, cancel_event: Event | None = None) -> Path:
    """Copy only a pinned helper into the bounded, flat helper cache.

    Old active executables may remain locked by Windows. Keep at most two known
    helper payloads, or decline staging without adding another payload.
    """
    executable = Path(executable)
    with guarded_read_path(executable, cancel_event=cancel_event) as source:
        size = os.fstat(source.fileno()).st_size
        if not 0 < size <= _MAX_HELPER_BYTES:
            raise UpdateError("The bundled updater has an invalid size.")
        digest = hashlib.sha256()
        while chunk := source.read(_CHUNK_SIZE):
            check_cancel(cancel_event)
            digest.update(chunk)
        name = f"updater-{digest.hexdigest()}.exe"
        with locked_cache(helper_cache_dir(), cancel_event=cancel_event) as cache:
            for old in cache.names():
                if _PART_NAME.fullmatch(old):
                    # A prior failed write must be removed before adding bytes.
                    # Only executable files can legitimately belong to an
                    # active helper while this exclusive staging lock is held.
                    cache.remove(old)
                elif _STAGED_NAME.fullmatch(old) and old != name:
                    try:
                        cache.remove(old)
                    except (OSError, UpdateError):
                        # A running helper is intentionally left alone. Count it
                        # below instead of allowing unbounded retained payloads.
                        _LOG.info("updater_helper_cleanup_deferred", extra={"helper": old})
            info = cache.regular_info(name)
            if info is not None:
                with cache.open_file(name) as existing:
                    actual = hashlib.sha256()
                    while chunk := existing.read(_CHUNK_SIZE):
                        check_cancel(cancel_event)
                        actual.update(chunk)
                if info.st_size != size or actual.digest() != digest.digest():
                    raise UpdateError("The staged updater differs from the bundled executable.")
                return cache.child(name)
            retained = sum(bool(_STAGED_NAME.fullmatch(old)) for old in cache.names())
            if retained >= _MAX_STAGED_HELPERS:
                raise UpdateError("Other updater windows are still open. Close them and retry.")
            temporary = f"updater-{uuid.uuid4().hex}.part"
            try:
                source.seek(0)
                with cache.open_file(temporary, mode="new") as output:
                    copied = 0
                    while chunk := source.read(_CHUNK_SIZE):
                        check_cancel(cancel_event)
                        copied += len(chunk)
                        if copied > size or output.write(chunk) != len(chunk):
                            raise UpdateError("The staged updater could not be copied completely.")
                    output.flush()
                    os.fsync(output.fileno())
                if copied != size:
                    raise UpdateError("The bundled updater changed while it was staged.")
                check_cancel(cancel_event)
                cache.replace(temporary, name)
                return cache.child(name)
            finally:
                discard_file(cache, temporary)


def helper_command(*arguments: str) -> list[str]:
    """Return a staged packaged helper command, or the source development entry."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, str(Path(__file__).resolve().parents[2] / "updater.py"), *arguments]
    executable = Path(sys.executable)
    if executable.name == APPLICATION_FILENAME:
        executable = executable.parent / "Updater" / UPDATER_FILENAME
    elif executable.name != UPDATER_FILENAME and not _STAGED_NAME.fullmatch(executable.name):
        raise UpdateError("This executable is not a supported Toolbox updater.")
    staged = stage_helper(executable)
    return [str(staged), *arguments]


def is_staged_helper() -> bool:
    executable = Path(sys.executable)
    return (
        bool(getattr(sys, "frozen", False))
        and executable.parent == helper_cache_dir()
        and _STAGED_NAME.fullmatch(executable.name) is not None
    )


def spawn_helper_command(command: list[str], *, stdio: bool = False) -> subprocess.Popen[bytes]:
    """Verify staged helper bytes under the guard held through process creation."""
    if not command:
        raise UpdateError("The updater executable command is empty.")
    executable = Path(command[0])
    options: dict[str, Any] = {
        "close_fds": True,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    if stdio:
        options.update(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with guarded_read_path(executable) as source:
            if _STAGED_NAME.fullmatch(executable.name):
                if executable.parent != helper_cache_dir():
                    raise UpdateError("The staged updater is outside its private cache.")
                expected = executable.name.removeprefix("updater-").removesuffix(".exe")
                digest = hashlib.sha256()
                total = 0
                while chunk := source.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > _MAX_HELPER_BYTES:
                        raise UpdateError("The staged updater exceeded its size limit.")
                    digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise UpdateError("The staged updater changed before it could be launched.")
            return launch_independent_process(command, **options)
    except OSError as error:
        raise UpdateError(f"Could not start FPVS Toolbox Updater: {error}") from error


def _windows_api() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return kernel


def _process_image(kernel: Any, handle: Any) -> Path:
    import ctypes
    from ctypes import wintypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(buffer))
    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
        raise UpdateError("Could not identify the Toolbox process before updating.")
    return Path(buffer.value)


class ParentProcess:
    """Hold a process handle, never a reusable PID, throughout Toolbox shutdown."""

    def __init__(self, pid: int, expected_executable: Path) -> None:
        if sys.platform != "win32" or type(pid) is not int or pid <= 0 or pid == os.getpid():
            raise UpdateError("The updater received an invalid Toolbox process identity.")
        self._kernel = _windows_api()
        self._handle = self._kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self._handle:
            raise UpdateError("Toolbox closed before the updater could accept the handoff. Retry.")
        try:
            if _process_image(self._kernel, self._handle) != expected_executable:
                raise UpdateError("The updater handoff does not identify the installed Toolbox.")
        except BaseException:
            self.close()
            raise

    def wait(self, cancel_event: Event | None = None) -> None:
        started = time.monotonic()
        while True:
            check_cancel(cancel_event)
            state = self._kernel.WaitForSingleObject(self._handle, 100)
            if state == 0:
                return
            if state != 258:
                raise UpdateError("The updater could not wait for Toolbox to close.")
            if time.monotonic() - started > PARENT_EXIT_TIMEOUT_SECONDS:
                raise UpdateError("Toolbox is still open. Close it and retry the update.")

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def application_is_running(executable: Path) -> bool:
    """Check other exact-path Toolbox processes without closing any application."""
    if sys.platform != "win32":
        raise UpdateError("Installing Toolbox updates requires Windows.")
    import ctypes
    from ctypes import wintypes

    kernel = _windows_api()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcesses.argtypes = [
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    psapi.EnumProcesses.restype = wintypes.BOOL
    ids = (wintypes.DWORD * 32768)()
    count = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(count)):
        raise UpdateError("Could not check whether Toolbox is still open.")
    if count.value >= ctypes.sizeof(ids):
        raise UpdateError("The Windows process list exceeded the updater's limit.")
    for pid in ids[: count.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            try:
                if _process_image(kernel, handle) == executable:
                    return True
            except UpdateError:
                continue
        finally:
            kernel.CloseHandle(handle)
    return False


def _phase(
    callback: Callable[[UpdatePhase], None] | None,
    text: str,
    *,
    install_committed: bool = False,
) -> None:
    if callback is not None:
        callback(UpdatePhase(text, install_committed=install_committed))


@dataclass
class PreparedInstall:
    """Accepted handoff. Only ``run`` may start setup, after the parent exits."""

    downloaded: DownloadedInstaller
    installation: InstalledApplication
    parent: ParentProcess | None

    def close(self) -> None:
        if self.parent is not None:
            self.parent.close()
            self.parent = None

    def run(
        self,
        *,
        cancel_event: Event | None = None,
        phase_callback: Callable[[UpdatePhase], None] | None = None,
    ) -> None:
        try:
            # The payload cache lock ends after guarded Popen. This independent
            # lock prevents another helper from starting setup while that first
            # installer is still modifying Toolbox or arranging its restart.
            with locked_cache(default_update_cache_dir().parent / "updater-install", cancel_event=cancel_event):
                self._run_locked(cancel_event=cancel_event, phase_callback=phase_callback)
        finally:
            self.close()

    def _run_locked(
        self,
        *,
        cancel_event: Event | None,
        phase_callback: Callable[[UpdatePhase], None] | None,
    ) -> None:
        try:
            if self.parent is not None:
                _phase(phase_callback, "Waiting for FPVS Toolbox to close...")
                self.parent.wait(cancel_event)
            check_cancel(cancel_event)
            current = registered_installation()
            if current != self.installation:
                raise UpdateError("Toolbox's installation changed. Check for updates again.")
            executable = self.installation.root / APPLICATION_FILENAME
            if application_is_running(executable):
                raise UpdateError("Another Toolbox window is open. Close it and retry the update.")
            _phase(phase_callback, "Verifying the update package before installation...")
            process = launch_installer(
                self.downloaded,
                install_root=self.installation.root,
                verify_patch_files=False,
                managed=True,
                all_users=self.installation.all_users,
                relaunch_after_install=False,
                cancel_event=cancel_event,
            )
            # Setup owns mutations from here. Never kill it or pretend that a
            # cancellation can safely interrupt its replacement/recovery steps.
            try:
                _phase(
                    phase_callback,
                    "Installing FPVS Toolbox. Please keep this window open...",
                    install_committed=True,
                )
            except Exception:  # A status callback cannot abandon a running installer.
                # Once setup owns mutations, a failed status consumer must not
                # abandon its result or cause us to terminate the installer.
                _LOG.exception("updater_committed_status_callback_failed")
            code = process.wait()
            if code != 0:
                suffix = (
                    " Use Download Full Installer to repair Toolbox."
                    if self.downloaded.asset.kind == "patch"
                    else " Retry the full installer to repair Toolbox."
                )
                raise UpdateError(f"The installer did not complete (exit code {code}).{suffix}")
            installed = registered_installation()
            if (
                installed is None
                or installed.root != self.installation.root
                or installed.version != self.downloaded.asset.version
            ):
                raise UpdateError("Setup finished, but the expected Toolbox version was not registered.")
            _phase(phase_callback, "Update installed. Restarting FPVS Toolbox...")
            with guarded_read_path(executable):
                try:
                    launch_independent_process([str(executable)], close_fds=True, cwd=str(executable.parent))
                except OSError as error:
                    raise UpdateError(
                        "Toolbox was updated successfully but could not restart. Open it from Start."
                    ) from error
        finally:
            self.close()


def prepare_install(
    downloaded: DownloadedInstaller,
    parent_pid: int | None = None,
    *,
    cancel_event: Event | None = None,
) -> PreparedInstall:
    """Authenticate a handoff and pin Toolbox's process before acknowledging ready."""
    check_cancel(cancel_event)
    validate_asset_identity(downloaded.asset)
    installation = registered_installation()
    if installation is None:
        raise UpdateError("Install Toolbox using its full installer before using Update & Repair.")
    target = downloaded.asset.version
    if target is None or parse_release_version(target) < parse_release_version(installation.version):
        raise UpdateError("The updater will not install an older Toolbox version.")
    if downloaded.asset.kind == "patch" and downloaded.asset.from_version != installation.version:
        raise UpdateError("This patch is for a different installed version. Check for updates again.")
    if (
        downloaded.path.parent != default_update_cache_dir()
        or downloaded.path.name != downloaded.asset.name
        or downloaded.sha256 != downloaded.asset.sha256
        or downloaded.size_bytes != downloaded.asset.size_bytes
    ):
        raise UpdateError("The installer handoff does not match Toolbox's verified update cache.")
    _authenticate_release_asset(downloaded, cancel_event)
    parent = ParentProcess(parent_pid, installation.root / APPLICATION_FILENAME) if parent_pid is not None else None
    try:
        with locked_cache(downloaded.path.parent, create=False, cancel_event=cancel_event) as cache:
            with verified_installer(cache, downloaded.asset, cancel_event=cancel_event):
                pass
        check_cancel(cancel_event)
        return PreparedInstall(downloaded, installation, parent)
    except BaseException:
        if parent is not None:
            parent.close()
        raise


def _authenticate_release_asset(downloaded: DownloadedInstaller, cancel_event: Event | None) -> None:
    """A pipe payload or cache receipt is never an executable trust anchor.

    Reacquire the digest from the fixed official repository before accepting the
    handoff. A patch installer contains its own digest-authenticated baseline contract;
    the incoming inventory hint cannot authorize different installer bytes.
    """
    asset = downloaded.asset
    matches: list[dict[str, Any]] = []
    for release in fetch_release_metadata(DEFAULT_RELEASES_API_URL, cancel_event=cancel_event):
        tag = release.get("tag_name")
        if release.get("draft") is True or not isinstance(tag, str):
            continue
        try:
            version = str(parse_release_version(tag))
        except UpdateError:
            continue
        if version != asset.version:
            continue
        raw_assets = release.get("assets")
        if not isinstance(raw_assets, list):
            continue
        matches.extend(item for item in raw_assets if isinstance(item, dict) and item.get("name") == asset.name)
    if len(matches) != 1:
        raise UpdateError("The downloaded installer is no longer a unique official release asset.")
    published = matches[0]
    digest = published.get("digest")
    if (
        published.get("id") != asset.asset_id
        or type(published.get("id")) is not int
        or published.get("browser_download_url") != asset.download_url
        or published.get("size") != asset.size_bytes
        or type(published.get("size")) is not int
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or normalize_sha256(digest) != asset.sha256
    ):
        raise UpdateError("The downloaded installer no longer matches its official GitHub release.")
