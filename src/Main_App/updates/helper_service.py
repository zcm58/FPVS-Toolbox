"""Backend operations used by the helper GUI and its private stdio worker mode."""

from __future__ import annotations

import logging
import os
import queue
import sys
import time
import uuid
from collections.abc import Callable
from threading import Event, Lock, Thread
from typing import Any, BinaryIO

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.updates.cache_io import check_cancel
from Main_App.updates.downloader import download_installer
from Main_App.updates.github_releases import check_update_candidate
from Main_App.updates.helper_protocol import (
    asset_from_dict,
    download_from_dict,
    download_to_dict,
    read_message,
    result_to_dict,
    write_message,
)
from Main_App.updates.helper_runtime import prepare_install, registered_installation
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)

_LOG = logging.getLogger(__name__)
HANDOFF_ACCEPT_TIMEOUT_SECONDS = 30
CANCELLED_WORKER_EXIT_SECONDS = 8


class _CancellationWatchdog:
    """End a stalled, uncommitted worker while its onefile bootloader stays alive.

    DNS resolution cannot be interrupted by Python's cancellation Event. A hard
    exit here releases this worker's handles; the surviving PyInstaller parent
    performs ordinary child reaping and extraction cleanup. Acceptance disarms
    this watchdog before any native installer can be launched.
    """

    def __init__(
        self,
        cancel_event: Event,
        *,
        exit_process: Callable[[int], None] | None = None,
        grace_seconds: float = CANCELLED_WORKER_EXIT_SECONDS,
    ) -> None:
        self._cancel = cancel_event
        self._done = Event()
        self._transition = Lock()
        self._exit_process = exit_process if exit_process is not None else os._exit
        self._grace = grace_seconds
        self._thread = Thread(target=self._watch, name="updater-cancel-watchdog", daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._cancel.is_set():
            if self._done.wait(0.1):
                return
        if self._done.wait(self._grace):
            return
        with self._transition:
            if not self._done.is_set():
                self._exit_process(1)

    def disarm(self) -> None:
        # Serialize acceptance with the final hard-exit decision, so a late
        # canceled flag can never race installer commitment.
        with self._transition:
            self._done.set()


def check_update(
    current_version: str | None = None,
    *,
    force_full: bool = False,
    repair: bool = False,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> UpdateCheckResult:
    """Discover candidates quickly; native setup owns final baseline verification."""
    installation = registered_installation()
    current = current_version or (installation.version if installation is not None else __version__)
    root = installation.root if installation is not None and installation.version == current else None
    return check_update_candidate(
        current_version=current,
        install_root=root,
        force_full=force_full,
        repair=repair,
        cancel_event=cancel_event,
        phase_callback=phase_callback,
    )


def download_update(
    asset: InstallerAsset,
    *,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> DownloadedInstaller:
    return download_installer(
        asset,
        cancel_event=cancel_event,
        phase_callback=phase_callback,
        progress_callback=progress_callback,
        verify_patch_files=False,
    )


def binary_stdio() -> tuple[BinaryIO, BinaryIO]:
    """Recover inherited pipe handles in PyInstaller's windowed Windows build.

    Duplicate the handles before wrapping them, so closing a Python stream cannot
    invalidate a handle owned by the bootloader or Qt.
    """
    streams: list[Any] = []
    for stream, standard, mode in ((sys.stdin, -10, "rb"), (sys.stdout, -11, "wb")):
        if stream is not None:
            # The cancellation listener can still be in a read when this short-
            # lived process exits. A raw duplicate avoids finalization waiting
            # for a daemon thread's BufferedReader lock on sys.stdin.
            streams.append(os.fdopen(os.dup(stream.fileno()), mode, buffering=0))
            continue
        if sys.platform != "win32":
            raise UpdateError("The updater was started without a private connection.")
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.DuplicateHandle.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel.DuplicateHandle.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        original = kernel.GetStdHandle(standard)
        duplicate = wintypes.HANDLE()
        process = kernel.GetCurrentProcess()
        if not original or not kernel.DuplicateHandle(process, original, process, ctypes.byref(duplicate), 0, False, 2):
            raise UpdateError("The updater could not open its private connection.")
        if duplicate.value is None:
            raise UpdateError("The updater private connection has no Windows handle.")
        try:
            descriptor = msvcrt.open_osfhandle(
                duplicate.value, os.O_BINARY | (os.O_RDONLY if mode == "rb" else os.O_WRONLY)
            )
        except OSError:
            kernel.CloseHandle(duplicate)
            raise
        streams.append(os.fdopen(descriptor, mode, buffering=0))
    return streams[0], streams[1]


def _validate_request(request: dict[str, Any]) -> str:
    if request.get("kind") != "request":
        raise UpdateError("The updater expected an operation request.")
    command = request.get("command")
    if not isinstance(command, str):
        raise UpdateError("The updater request has no operation name.")
    if command == "check":
        if set(request) != {
            "protocol",
            "kind",
            "command",
            "current_version",
            "force_full",
            "repair",
        }:
            raise UpdateError("The updater check request has an invalid schema.")
        if (
            (request["current_version"] is not None and not isinstance(request["current_version"], str))
            or type(request["force_full"]) is not bool
            or type(request["repair"]) is not bool
        ):
            raise UpdateError("The updater check request has invalid values.")
    elif command == "download":
        if set(request) != {"protocol", "kind", "command", "asset"}:
            raise UpdateError("The updater download request has an invalid schema.")
    else:
        raise UpdateError("The updater does not support this operation.")
    return command


def serve_stdio(input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> int:
    """Run one cancelable check/download; this mode can never execute an installer."""
    if input_stream is None or output_stream is None:
        input_stream, output_stream = binary_stdio()
    cancel_event = Event()
    watchdog: _CancellationWatchdog | None = None
    output = output_stream

    def phase(value: UpdatePhase) -> None:
        write_message(
            output,
            "phase",
            text=value.text,
            result=result_to_dict(value.result) if value.result is not None else None,
            install_committed=value.install_committed,
        )

    def progress(downloaded: int, total: int | None) -> None:
        write_message(output, "progress", downloaded=downloaded, total=total)

    def read_cancellation() -> None:
        try:
            message = read_message(input_stream)
            if set(message) != {"protocol", "kind"} or message["kind"] != "cancel":
                _LOG.warning("updater_invalid_cancel_message")
        except (EOFError, OSError, UpdateError):
            pass
        cancel_event.set()

    try:
        request = read_message(input_stream)
        command = _validate_request(request)
        watchdog = _CancellationWatchdog(cancel_event, grace_seconds=CANCELLED_WORKER_EXIT_SECONDS)
        Thread(target=read_cancellation, name="updater-cancellation", daemon=True).start()
        if command == "check":
            result = check_update(
                request["current_version"],
                force_full=request["force_full"],
                repair=request["repair"],
                cancel_event=cancel_event,
                phase_callback=phase,
            )
            write_message(output, "result", result=result_to_dict(result))
        else:
            downloaded = download_update(
                asset_from_dict(request["asset"]),
                cancel_event=cancel_event,
                phase_callback=phase,
                progress_callback=progress,
            )
            write_message(output, "result", downloaded=download_to_dict(downloaded))
        return 0
    except (EOFError, OSError, UpdateError, ValueError, TypeError) as error:
        _LOG.info("updater_worker_failed", exc_info=True)
        try:
            write_message(
                output,
                "error",
                message=str(error),
                cancelled=isinstance(error, UpdateCancelled),
            )
        except (OSError, UpdateError):
            pass
        return 1
    finally:
        if watchdog is not None:
            watchdog.disarm()


def run_apply(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    cancel_event: Event | None = None,
    phase_callback: Callable[[UpdatePhase], None] | None = None,
) -> None:
    """Prepare, acknowledge, explicitly accept, then install in a GUI worker.

    Toolbox remains open until acceptance. An early EOF, cancel, failed preparation,
    or unanswered ready message can never launch setup, including standalone repair.
    """
    cancel = cancel_event if cancel_event is not None else Event()
    controls: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
    prepared = None
    accepted = False
    watchdog: _CancellationWatchdog | None = None

    def read_control() -> None:
        try:
            control = read_message(input_stream)
            if control["kind"] == "cancel":
                cancel.set()
            controls.put(control)
        except (EOFError, OSError, UpdateError) as error:
            cancel.set()
            controls.put(error)

    try:
        request = read_message(input_stream)
        if (
            set(request) != {"protocol", "kind", "command", "downloaded", "parent_pid"}
            or request["kind"] != "request"
            or request["command"] != "apply"
            or (
                request["parent_pid"] is not None
                and (type(request["parent_pid"]) is not int or request["parent_pid"] <= 0)
            )
        ):
            raise UpdateError("The updater received an invalid installation handoff.")
        downloaded = download_from_dict(request["downloaded"])
        watchdog = _CancellationWatchdog(cancel, grace_seconds=CANCELLED_WORKER_EXIT_SECONDS)
        Thread(target=read_control, name="updater-handoff", daemon=True).start()
        if phase_callback is not None:
            phase_callback(UpdatePhase("Preparing the verified update handoff..."))
        prepared = prepare_install(downloaded, request["parent_pid"], cancel_event=cancel)
        check_cancel(cancel)
        nonce = uuid.uuid4().hex
        write_message(output_stream, "ready", nonce=nonce)
        deadline = time.monotonic() + HANDOFF_ACCEPT_TIMEOUT_SECONDS
        while True:
            check_cancel(cancel)
            if time.monotonic() >= deadline:
                raise UpdateError("Toolbox did not accept the update handoff. Retry the update.")
            try:
                control = controls.get(timeout=0.1)
                break
            except queue.Empty:
                continue
        if (
            isinstance(control, BaseException)
            or set(control) != {"protocol", "kind", "nonce"}
            or control["kind"] != "accept"
            or control["nonce"] != nonce
        ):
            raise UpdateError("Toolbox did not accept the prepared update handoff.")
        check_cancel(cancel)
        watchdog.disarm()
        accepted = True
        prepared.run(cancel_event=cancel, phase_callback=phase_callback)
    except (EOFError, OSError, UpdateError, ValueError, TypeError) as error:
        if not accepted:
            try:
                write_message(
                    output_stream,
                    "error",
                    message=str(error),
                    cancelled=isinstance(error, UpdateCancelled),
                )
            except (OSError, UpdateError):
                pass
        raise
    finally:
        if watchdog is not None:
            watchdog.disarm()
        if prepared is not None:
            prepared.close()
