"""Schedule and present application updates via GitHub Releases."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from time import perf_counter
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtWidgets import QWidget

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.gui.update_dialog import UpdateDialog
from Main_App.gui.update_lifecycle import (
    UpdateJob,
    UpdateLifecycle,
    UpdateTaskResult,
    update_lifecycle,
)
from Main_App.updates.application import APP_VERSION
from Main_App.updates.cache import cleanup_update_cache
from Main_App.updates.helper_client import HelperClient
from Main_App.updates.models import UpdateCheckResult


def check_for_updates(cancel_event: Event | None = None) -> UpdateCheckResult:
    return HelperClient().check(APP_VERSION, cancel_event=cancel_event)


_LOG = logging.getLogger(__name__)

_DEBOUNCE_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True)
class _UpdateInfo:
    """Compatibility payload for older update-check tests and signal consumers."""

    latest: str
    url: str


@dataclass
class _StartupUpdateState:
    """Give an explicit check priority over this host's deferred startup scan."""

    lifecycle: UpdateLifecycle
    started: bool = False
    superseded: bool = False
    disposed: bool = False
    job: UpdateJob | None = None
    cache_started: bool = False
    cache_job: UpdateJob | None = None

    def supersede(self) -> None:
        self.superseded = True
        if self.job is not None:
            self.job.cancel()

    def dispose(self, _object: object = None) -> None:
        self.disposed = True
        self.supersede()
        if self.cache_job is not None:
            self.cache_job.cancel()
        try:
            self.lifecycle.manual_check_requested.disconnect(self.supersede)
        except RuntimeError:
            _LOG.debug("Startup update host was already disconnected.")


def prepare_startup_update_check(app: QWidget) -> _StartupUpdateState:
    """Register manual-check cancellation before the launch timer can fire."""

    state = getattr(app, "_startup_update_check", None)
    if not isinstance(state, _StartupUpdateState):
        state = _StartupUpdateState(update_lifecycle())
        setattr(app, "_startup_update_check", state)
        state.lifecycle.manual_check_requested.connect(state.supersede)
        app.destroyed.connect(state.dispose)
    return state


def _start_update_cache_housekeeping(app: QWidget, state: _StartupUpdateState) -> None:
    """Run bounded local maintenance independently of network-check preferences."""

    if state.cache_started or state.disposed or state.lifecycle.is_shutting_down:
        return
    state.cache_started = True
    job = state.lifecycle.start_task(
        lambda _progress, cancel: cleanup_update_cache(APP_VERSION, cancel_event=cancel)
    )
    state.cache_job = job
    app.destroyed.connect(job.cancel)

    def completed(outcome: UpdateTaskResult) -> None:
        if state.cache_job is job:
            state.cache_job = None
        if outcome.error is not None and not outcome.cancelled:
            _LOG.warning(
                "Startup update-cache housekeeping could not complete",
                extra={"error": str(outcome.error)},
            )

    job.finished.connect(completed)


def cleanup_old_executable() -> None:
    """Remove leftover backup EXE after an Inno update, if one exists."""

    backup = sys.executable + ".old"
    try:
        if os.path.exists(backup):
            os.remove(backup)
    except OSError:
        _LOG.warning("Could not remove old executable backup: %s", backup, exc_info=True)


def check_for_updates_async(
    app: QWidget,
    silent: bool = True,
    notify_if_no_update: bool = True,
    force: bool = False,
) -> None:
    """Check for updates without blocking the UI thread."""

    if not force and _should_skip_update_check():
        _log(app, "Skipping update check (checked recently).")
        return

    if not silent:
        prepare_startup_update_check(app).supersede()
        _show_update_dialog(app, auto_check=True)
        return

    _background_check(app, lambda result: _on_silent_result(app, result, notify_if_no_update))


def check_for_updates_on_launch(app: QWidget) -> None:
    """Startup check: stay silent unless an installable update is available."""

    if _running_under_pytest():
        _log(app, "Skipping update check during pytest.")
        return
    state = prepare_startup_update_check(app)
    if state.disposed or state.lifecycle.is_shutting_down:
        return
    _start_update_cache_housekeeping(app, state)
    if state.started or state.superseded:
        return
    state.started = True
    if _should_skip_update_check():
        _log(app, "Skipping update check (checked recently).")
        return

    def present_result(result: UpdateCheckResult) -> None:
        if not state.superseded and not state.disposed and not state.lifecycle.is_shutting_down:
            _on_launch_result(app, result)

    job = _background_check(app, present_result)
    state.job = job

    def clear_job(_outcome: UpdateTaskResult) -> None:
        if state.job is job:
            state.job = None

    job.finished.connect(clear_job)


class _UpdateSignals(QObject):
    result = Signal(object)  # UpdateCheckResult
    available = Signal(object)  # _UpdateInfo, retained for compatibility
    none = Signal(str)  # current version, retained for compatibility
    error = Signal(str)


class _CheckJob(QRunnable):
    """QRunnable that queries GitHub Releases and compares versions."""

    def __init__(self) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.sigs = _UpdateSignals()

    def run(self) -> None:
        start = perf_counter()
        try:
            _LOG.debug("Checking for updates...")
            result = _check_for_updates_and_record()
            _safe_emit(self.sigs.result, result)
            if result.update_available:
                _safe_emit(
                    self.sigs.available,
                    _UpdateInfo(latest=result.latest_version, url=result.release_url or ""),
                )
            else:
                _safe_emit(self.sigs.none, result.current_version)
        except Exception as exc:
            elapsed = int((perf_counter() - start) * 1000)
            _LOG.warning(
                "Update check failed",
                extra={
                    "op": "update_check",
                    "elapsed_ms": elapsed,
                    "exc": repr(exc),
                },
            )
            _safe_emit(self.sigs.error, str(exc))


def _safe_emit(signal: Any, *args: object) -> bool:
    """Emit a Qt signal unless its QObject has already been deleted."""

    try:
        signal.emit(*args)
        return True
    except RuntimeError as exc:
        if "deleted" in str(exc).lower():
            _LOG.debug("Skipped update-check signal emit after QObject deletion.")
            return False
        raise


def _check_for_updates_and_record(cancel_event: Event | None = None) -> UpdateCheckResult:
    result = check_for_updates(cancel_event=cancel_event)
    _record_successful_check()
    return result


def _show_update_dialog(
    parent: QWidget,
    *,
    auto_check: bool,
    initial_result: UpdateCheckResult | None = None,
) -> UpdateDialog:
    existing = getattr(parent, "_update_dialog", None)
    if isinstance(existing, UpdateDialog) and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing

    dialog = UpdateDialog(
        parent=parent,
        auto_check=auto_check,
        check_callback=_check_for_updates_and_record,
        initial_result=initial_result,
    )
    setattr(parent, "_update_dialog", dialog)
    dialog.finished.connect(lambda _code: _clear_update_dialog(parent, dialog))
    dialog.open()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def _clear_update_dialog(parent: QWidget, dialog: UpdateDialog) -> None:
    if getattr(parent, "_update_dialog", None) is dialog:
        setattr(parent, "_update_dialog", None)


def _on_launch_result(parent: QWidget, result: UpdateCheckResult) -> None:
    if result.update_available and result.installer_asset is not None:
        _log(parent, f"Update {result.latest_version} available.")
        _show_update_dialog(parent, auto_check=False, initial_result=result)
    elif result.update_available:
        _log(parent, f"Update {result.latest_version} metadata is incomplete; installer asset missing.")
    else:
        _log(parent, "No update available.")


def _on_silent_result(
    parent: QWidget,
    result: UpdateCheckResult,
    notify_if_no_update: bool,
) -> None:
    if result.update_available:
        suffix = "" if result.installer_asset is not None else " but installer metadata is incomplete"
        _log(parent, f"Update {result.latest_version} available{suffix}.")
        return
    if notify_if_no_update:
        _log(parent, "No update available.")


def _on_silent_error(parent: QWidget, msg: str) -> None:
    _log(parent, f"Update check failed: {msg}")


def _log(app: object, msg: str) -> None:
    if hasattr(app, "log"):
        try:
            app.log(msg)  # type: ignore[attr-defined]
            return
        except (AttributeError, RuntimeError, TypeError):
            _LOG.debug("Could not write update message to app log.", exc_info=True)
    _LOG.info(msg)


def _last_checked_utc() -> datetime | None:
    settings = SettingsManager()
    raw_value = settings.get("updates", "last_checked_utc", "")
    if not raw_value:
        return None
    try:
        stamp = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _should_skip_update_check() -> bool:
    last = _last_checked_utc()
    if last is None:
        return False
    return datetime.now(timezone.utc) - last < _DEBOUNCE_INTERVAL


def _record_successful_check() -> None:
    settings = SettingsManager()
    settings.set("updates", "last_checked_utc", datetime.now(timezone.utc).isoformat())
    settings.save()


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _background_check(app: QWidget, on_result) -> UpdateJob:
    """Keep startup workers alive and cancellable across application shutdown."""
    job = update_lifecycle().start_task(lambda _progress, cancel: _check_for_updates_and_record(cancel))
    app.destroyed.connect(job.cancel)

    def completed(outcome: UpdateTaskResult) -> None:
        if outcome.cancelled:
            return
        if outcome.error is not None:
            _on_silent_error(app, str(outcome.error))
        else:
            try:
                on_result(outcome.value)
            except RuntimeError:
                _LOG.debug("Update host closed before result presentation.")

    job.finished.connect(completed)
    return job
