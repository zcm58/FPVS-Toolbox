"""Schedule and present application updates via GitHub Releases."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QWidget

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.gui.update_dialog import UpdateDialog
from Main_App.updates.github_releases import check_for_updates
from Main_App.updates.models import UpdateCheckResult

_LOG = logging.getLogger(__name__)

_DEBOUNCE_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True)
class _UpdateInfo:
    """Compatibility payload for older update-check tests and signal consumers."""

    latest: str
    url: str


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
        _show_update_dialog(app, auto_check=True)
        return

    job = _CheckJob()
    job.sigs.result.connect(lambda result: _on_silent_result(app, result, notify_if_no_update))
    job.sigs.error.connect(lambda msg: _on_silent_error(app, msg))
    QThreadPool.globalInstance().start(job)


def check_for_updates_on_launch(app: QWidget) -> None:
    """Startup check: stay silent unless an installable update is available."""

    if _running_under_pytest():
        _log(app, "Skipping update check during pytest.")
        return
    if _should_skip_update_check():
        _log(app, "Skipping update check (checked recently).")
        return

    job = _CheckJob()
    job.sigs.result.connect(lambda result: _on_launch_result(app, result))
    job.sigs.error.connect(lambda msg: _log(app, f"Update check failed: {msg}"))
    QThreadPool.globalInstance().start(job)


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
            _LOG.info("Checking for updates...")
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


def _check_for_updates_and_record() -> UpdateCheckResult:
    result = check_for_updates()
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
