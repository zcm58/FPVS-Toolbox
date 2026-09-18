"""Synchronous subprocess client, intended for Toolbox's existing Qt workers."""

from __future__ import annotations

import logging
import queue
import subprocess
import time
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

from Main_App.updates.cache_io import check_cancel
from Main_App.updates.helper_protocol import (
    asset_to_dict,
    download_from_dict,
    download_to_dict,
    phase_from_message,
    read_message,
    result_from_dict,
    write_message,
)
from Main_App.updates.helper_runtime import helper_command, spawn_helper_command
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)

_MAX_OPERATION_SECONDS = 35 * 60
_MAX_HANDOFF_SECONDS = 120
_CANCEL_GRACE_SECONDS = 15
_LOG = logging.getLogger(__name__)


def _spawn(command: list[str]) -> subprocess.Popen[bytes]:
    """Pin the staged executable through launch; never invoke a command shell."""
    return spawn_helper_command(command, stdio=True)


def _stop_uncommitted(process: subprocess.Popen[bytes]) -> None:
    """Stop only our check/download or unaccepted handoff, never running setup."""
    # EOF reaches the real worker, including a onefile child hidden behind the
    # Popen bootloader. Give its cancellation/watchdog and bootloader extraction
    # cleanup time to finish before resorting to forceful parent termination.
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            _LOG.warning("updater_cancel_pipe_close_failed", exc_info=True)
    if process.poll() is None:
        try:
            process.wait(timeout=_CANCEL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class HelperClient:
    """Private child process per operation; Toolbox owns no network/hash work."""

    def __init__(self, command_factory: Callable[..., list[str]] = helper_command) -> None:
        self._command_factory = command_factory

    def _exchange(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        cancel_event: Event | None,
        phase_callback: Callable[[UpdatePhase], None] | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> tuple[dict[str, Any], subprocess.Popen[bytes]]:
        check_cancel(cancel_event)
        process = _spawn(self._command_factory("--apply" if command == "apply" else "--stdio"))
        accepted = False
        messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=128)
        assert process.stdin is not None and process.stdout is not None
        output_stream = process.stdout

        def receive() -> None:
            try:
                while True:
                    message = read_message(output_stream)
                    messages.put(message)
                    if message["kind"] in {"result", "error", "ready"}:
                        return
            except (EOFError, OSError, UpdateError) as error:
                messages.put(error)

        try:
            write_message(process.stdin, "request", command=command, **payload)
            Thread(target=receive, name="updater-messages", daemon=True).start()
            started = time.monotonic()
            cancelled_at: float | None = None
            timeout = _MAX_HANDOFF_SECONDS if command == "apply" else _MAX_OPERATION_SECONDS
            while True:
                now = time.monotonic()
                if cancel_event is not None and cancel_event.is_set() and cancelled_at is None:
                    write_message(process.stdin, "cancel")
                    cancelled_at = now
                if cancelled_at is not None and now - cancelled_at > _CANCEL_GRACE_SECONDS:
                    raise UpdateCancelled("The updater operation was canceled.")
                if now - started > timeout:
                    raise UpdateError("The updater operation exceeded its time limit. Retry.")
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if isinstance(message, BaseException):
                    check_cancel(cancel_event)
                    raise UpdateError("The updater closed before completing the operation.") from message
                kind = message["kind"]
                if kind == "phase":
                    phase = phase_from_message(message)
                    if phase_callback is not None:
                        phase_callback(phase)
                elif kind == "progress":
                    downloaded, total = message.get("downloaded"), message.get("total")
                    if (
                        type(downloaded) is not int
                        or downloaded < 0
                        or (total is not None and (type(total) is not int or total < downloaded))
                    ):
                        raise UpdateError("The updater returned invalid download progress.")
                    if progress_callback is not None:
                        progress_callback(downloaded, total)
                elif kind == "error":
                    error_text = message.get("message")
                    if not isinstance(error_text, str):
                        raise UpdateError("The updater returned an invalid error message.")
                    if message.get("cancelled") is True:
                        raise UpdateCancelled(error_text)
                    raise UpdateError(error_text)
                elif kind == "ready" and command == "apply":
                    nonce = message.get("nonce")
                    if not isinstance(nonce, str) or len(nonce) != 32:
                        raise UpdateError("The updater returned an invalid handoff challenge.")
                    check_cancel(cancel_event)
                    # A failed pipe write may still have delivered its bytes.
                    # From this point the helper may own installation; never
                    # kill it because the acknowledgment outcome is uncertain.
                    accepted = True
                    write_message(process.stdin, "accept", nonce=nonce)
                    return message, process
                elif kind == "result" and command != "apply":
                    check_cancel(cancel_event)
                    if process.wait(timeout=10) != 0:
                        raise UpdateError("The updater could not finish the operation.")
                    return message, process
                else:
                    raise UpdateError("The updater returned an unexpected operation state.")
        finally:
            if not accepted:
                try:
                    _stop_uncommitted(process)
                except (OSError, subprocess.SubprocessError):
                    _LOG.warning("updater_child_cleanup_failed", exc_info=True)
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except OSError:
                    _LOG.warning("updater_pipe_close_failed", exc_info=True)

    def check(
        self,
        current_version: str | None = None,
        *,
        force_full: bool = False,
        repair: bool = False,
        cancel_event: Event | None = None,
        phase_callback: Callable[[UpdatePhase], None] | None = None,
    ) -> UpdateCheckResult:
        message, _ = self._exchange(
            "check",
            {"current_version": current_version, "force_full": force_full, "repair": repair},
            cancel_event=cancel_event,
            phase_callback=phase_callback,
        )
        return result_from_dict(message.get("result"))

    def download(
        self,
        asset: InstallerAsset,
        *,
        cancel_event: Event | None = None,
        phase_callback: Callable[[UpdatePhase], None] | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> DownloadedInstaller:
        message, _ = self._exchange(
            "download",
            {"asset": asset_to_dict(asset)},
            cancel_event=cancel_event,
            phase_callback=phase_callback,
            progress_callback=progress_callback,
        )
        return download_from_dict(message.get("downloaded"))

    def launch_install(
        self,
        downloaded: DownloadedInstaller,
        *,
        parent_pid: int | None = None,
        cancel_event: Event | None = None,
        phase_callback: Callable[[UpdatePhase], None] | None = None,
        relaunch_after_install: bool = True,
    ) -> subprocess.Popen[bytes]:
        """Return after the staged helper accepts responsibility, before Toolbox exits."""
        if not relaunch_after_install:
            raise UpdateError("The independent updater completes updates by restarting Toolbox.")
        _, process = self._exchange(
            "apply",
            {"downloaded": download_to_dict(downloaded), "parent_pid": parent_pid},
            cancel_event=cancel_event,
            phase_callback=phase_callback,
        )
        return process
