"""GUI smoke tests for the in-app update flow."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget
from shiboken6 import isValid

from Main_App.gui import update_lifecycle as lifecycle_module
from Main_App.gui.update_dialog import UpdateDialog
from Main_App.gui.update_lifecycle import UpdateJob, UpdateLifecycle
from Main_App.gui.updater_window import ApplyUpdateDialog, UpdaterWindow
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCancelled,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)


def _available_update(_cancel_event: Event | None = None) -> UpdateCheckResult:
    asset = InstallerAsset(
        name="FPVSToolbox-0.9.0b2-setup.exe",
        download_url=(
            "https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v0.9.0b2/"
            "FPVSToolbox-0.9.0b2-setup.exe"
        ),
        size_bytes=10,
        sha256=hashlib.sha256(b"installer").hexdigest(),
        version="0.9.0b2",
        asset_id=10,
    )
    return UpdateCheckResult(
        current_version="0.9.0b1",
        latest_version="0.9.0b2",
        update_available=True,
        release_url="https://github.com/zcm58/FPVS-Toolbox-Repo/releases/tag/v0.9.0b2",
        release_notes_summary="Improved update flow",
        installer_asset=asset,
        is_prerelease=True,
    )












def test_update_dialog_initial_result_is_themed_and_remind_later_dismisses(qtbot) -> None:
    dialog = UpdateDialog(auto_check=False, initial_result=_available_update())
    qtbot.addWidget(dialog)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.close_button.text() == "Remind Me Later")
    from Main_App.gui.theme import build_fpvs_app_stylesheet
    assert dialog.styleSheet() == build_fpvs_app_stylesheet()
    assert dialog.property("fpvsSurface") is True
    assert "QPushButton" in dialog.styleSheet()

    dialog.close_button.click()

    qtbot.waitUntil(lambda: not dialog.isVisible())




def test_update_dialog_action_buttons_fit_text_at_compact_width(qtbot) -> None:
    dialog = UpdateDialog(auto_check=False, initial_result=_available_update())
    qtbot.addWidget(dialog)
    dialog.resize(dialog.minimumSizeHint())
    dialog.show()
    qtbot.waitUntil(lambda: dialog.close_button.width() > 0)

    for button in (
        dialog.check_button,
        dialog.download_button,
        dialog.install_button,
        dialog.close_button,
    ):
        required_width = button.fontMetrics().horizontalAdvance(button.text()) + 20
        assert button.width() >= required_width, button.text()




def test_update_dialog_downloads_then_launches_installer(
    qtbot,
    monkeypatch,
    tmp_path: Path,
) -> None:
    installer_path = tmp_path / "FPVSToolbox-0.9.0b2-setup.exe"
    installer_path.write_bytes(b"installer")
    launched: list[Path] = []
    quit_calls: list[str] = []
    worker_threads: list[QThread] = []
    gui_threads: list[QThread] = []

    def _download(asset, progress, cancel_event):
        worker_threads.append(QThread.currentThread())
        assert isinstance(cancel_event, Event)
        return _download_with_progress(installer_path, progress, asset)

    def _launch(downloaded, cancel_event):
        worker_threads.append(QThread.currentThread())
        assert isinstance(cancel_event, Event)
        launched.append(downloaded.path)

    def _save() -> bool:
        gui_threads.append(QThread.currentThread())
        return True

    dialog = UpdateDialog(
        auto_check=False,
        check_callback=_available_update,
        download_callback=_download,
        installer_launcher=_launch,
        on_before_install=_save,
        quit_app=lambda: quit_calls.append("quit"),
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.start_update_check()
    qtbot.waitUntil(lambda: dialog.download_button.isEnabled())
    assert "A new FPVS Toolbox version is available." in dialog.status_label.text()
    assert "projects, settings, analysis results, and logs" in dialog.status_label.text()
    assert "0.9.0b1" in dialog.current_version_label.text()
    assert "0.9.0b2" in dialog.latest_version_label.text()
    assert "Improved update flow" in dialog.notes_label.text()
    assert dialog.release_notes_button.isEnabled()
    assert dialog.close_button.text() == "Remind Me Later"

    dialog.start_download()
    qtbot.waitUntil(lambda: dialog.install_button.isEnabled())
    assert dialog.progress_bar.value() == dialog.progress_bar.maximum() == 1000

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog.install_and_restart()

    qtbot.waitUntil(lambda: quit_calls == ["quit"])
    assert launched == [installer_path]
    assert quit_calls == ["quit"]
    assert all(thread is not dialog.thread() for thread in worker_threads)
    assert gui_threads == [dialog.thread()]


def test_update_dialog_reports_no_update(qtbot) -> None:
    dialog = UpdateDialog(
        auto_check=False,
        check_callback=lambda _cancel: UpdateCheckResult(
            current_version="0.9.0b1",
            latest_version="0.9.0b1",
            update_available=False,
            release_url=None,
            release_notes_summary="",
            installer_asset=None,
            is_prerelease=True,
        ),
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.start_update_check()
    qtbot.waitUntil(lambda: dialog.status_label.text() == "FPVS Toolbox is up to date.")

    assert dialog.download_button.isEnabled() is False
    assert dialog.install_button.isEnabled() is False
    assert dialog.close_button.text() == "Close"


def test_update_dialog_reports_manual_server_error(qtbot) -> None:
    dialog = UpdateDialog(
        auto_check=False,
        check_callback=lambda _cancel: (_ for _ in ()).throw(RuntimeError("network unavailable")),
    )
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.start_update_check()
    qtbot.waitUntil(
        lambda: "try again later from File > Check for Updates" in dialog.status_label.text()
    )

    assert "network unavailable" in dialog.notes_label.text()
    assert dialog.download_button.isEnabled() is False
    assert dialog.install_button.isEnabled() is False
    assert dialog.close_button.text() == "Close"


def _download_with_progress(
    installer_path: Path,
    progress: Callable[[int, int | None], None],
    asset: InstallerAsset,
) -> DownloadedInstaller:
    size = installer_path.stat().st_size
    progress(size // 2, size)
    progress(size, size)
    return DownloadedInstaller(
        path=installer_path,
        size_bytes=size,
        sha256=hashlib.sha256(installer_path.read_bytes()).hexdigest(),
        asset=asset,
    )


_UNSET = object()


class _DeferredUpdateJob(UpdateJob):
    """A deterministic worker double: callback return and thread finish are separate."""

    def start(self) -> None:
        self._started = True
        self._running = True

    def run_callback(self) -> None:
        assert self._started
        try:
            if self.cancel_event.is_set():
                raise UpdateCancelled("Canceled before starting.")
            self._outcome.value = self.callback(self.progress_changed.emit, self.cancel_event)
        except Exception as error:
            self._outcome.error = error

    def finish(self, value: object = _UNSET, error: Exception | None = None) -> None:
        assert self._started
        if value is not _UNSET:
            self._outcome.value = value
        if error is not None:
            self._outcome.error = error
        self._finish()


@pytest.fixture
def deferred_updates(qapp, qtbot, monkeypatch):
    jobs: list[_DeferredUpdateJob] = []
    quit_calls: list[str] = []
    original_auto_quit = qapp.quitOnLastWindowClosed()
    qapp.setQuitOnLastWindowClosed(False)

    def _create_job(*args, **kwargs):
        job = _DeferredUpdateJob(*args, **kwargs)
        jobs.append(job)
        return job

    monkeypatch.setattr(lifecycle_module, "UpdateJob", _create_job)
    lifecycle = UpdateLifecycle(qapp, quit_callback=lambda: quit_calls.append("quit"))
    yield lifecycle, jobs, quit_calls

    qtbot.waitUntil(lambda: all(job._started for job in lifecycle._jobs))
    for job in tuple(lifecycle._jobs):
        job.cancel()
        job.finish(error=UpdateCancelled("Test teardown cancellation."))
    qtbot.waitUntil(lambda: not lifecycle.has_active_jobs)
    qapp.processEvents()
    qapp.removeEventFilter(lifecycle)
    qapp.lastWindowClosed.disconnect(lifecycle._last_window_closed)
    qapp.aboutToQuit.disconnect(lifecycle._about_to_quit)
    lifecycle.deleteLater()
    qapp.setQuitOnLastWindowClosed(original_auto_quit)


def _downloaded_fixture(tmp_path: Path) -> DownloadedInstaller:
    asset = _available_update().installer_asset
    assert asset is not None and asset.sha256 is not None
    return DownloadedInstaller(
        path=tmp_path / asset.name,
        size_bytes=9,
        sha256=asset.sha256,
        asset=asset,
    )


def test_quit_filter_ignores_unrelated_item_wrapper_from_reported_trace(qapp, deferred_updates):
    lifecycle, _, _ = deferred_updates
    # Replay the exact dispatcher/item pair reported during exclusions scrolling.
    # A Quit-only filter must pass unrelated deliveries through without delegating
    # them to QObject's typed, otherwise no-op eventFilter overload.
    assert lifecycle.eventFilter(qapp.eventDispatcher(), QStandardItem("scope")) is False
    assert not lifecycle.is_shutting_down


def test_shutdown_flushes_bounded_local_persistence(qtbot, deferred_updates) -> None:
    lifecycle, jobs, quit_calls = deferred_updates
    writes = []
    lifecycle.shutdown_started.connect(lambda: lifecycle.start_task(
        lambda _progress, _cancel: writes.append("saved"), finish_on_shutdown=True,
    ))
    lifecycle._about_to_quit()  # Includes direct exit with no earlier jobs.
    assert lifecycle.has_active_jobs
    assert not jobs[0].cancel_event.is_set()
    qtbot.waitUntil(lambda: jobs[0].is_running)
    jobs[0].run_callback()
    assert writes == ["saved"]
    assert quit_calls == []
    jobs[0].finish()
    qtbot.waitUntil(lambda: quit_calls == ["quit"])


@pytest.mark.parametrize("metadata", ["missing-asset", "missing-digest", "invalid-digest"])
def test_new_release_without_trusted_installer_metadata_is_not_reported_as_current(
    qtbot, monkeypatch, metadata,
) -> None:
    result = _available_update()
    assert result.installer_asset is not None
    asset = None if metadata == "missing-asset" else replace(
        result.installer_asset,
        sha256=None if metadata == "missing-digest" else "not-a-valid-digest",
    )
    result = replace(result, installer_asset=asset)
    dialog = UpdateDialog(auto_check=False, initial_result=result)
    qtbot.addWidget(dialog)
    dialog.show()
    opened: list[str] = []
    monkeypatch.setattr(
        "Main_App.gui.update_dialog.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    assert "new FPVS Toolbox version is available" in dialog.status_label.text()
    assert "in-app installation is unavailable" in dialog.status_label.text()
    assert "valid trusted installer metadata" in dialog.status_label.text()
    assert "SHA-256 checksum" in dialog.status_label.text()
    assert "up to date" not in dialog.status_label.text()
    assert not dialog.download_button.isEnabled()
    assert not dialog.install_button.isEnabled()
    assert dialog.release_notes_button.isEnabled()
    dialog.release_notes_button.click()
    assert opened == [result.release_url]


@pytest.mark.parametrize("action", ["button", "window", "escape"])
@pytest.mark.parametrize("operation", ["check", "download", "install"])
def test_close_cancels_but_keeps_dialog_alive_until_worker_finishes(
    qtbot, monkeypatch, tmp_path, deferred_updates, action, operation,
) -> None:
    lifecycle, jobs, quit_calls = deferred_updates
    dialog = UpdateDialog(auto_check=False, initial_result=_available_update(), lifecycle=lifecycle)
    qtbot.addWidget(dialog)
    dialog.show()
    if operation == "check":
        dialog.start_update_check()
    elif operation == "download":
        dialog.start_download()
    else:
        dialog._handle_download_result(_downloaded_fixture(tmp_path))
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
        )
        dialog.install_and_restart()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)

    if action == "button":
        dialog.close_button.click()
    elif action == "window":
        dialog.close()
    else:
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    assert job.cancel_event.is_set()
    assert dialog.isVisible()
    assert dialog.close_button.text() == "Canceling..."
    assert not dialog.close_button.isEnabled()
    assert not dialog.install_button.isEnabled()
    assert lifecycle.has_active_jobs
    assert quit_calls == []

    job.finish(error=UpdateCancelled("Canceled safely."))
    qtbot.waitUntil(lambda: not dialog.isVisible())
    assert not lifecycle.has_active_jobs
    assert dialog._job is None
    assert quit_calls == []


def test_download_result_does_not_enable_install_until_thread_finished(
    qtbot, monkeypatch, tmp_path, deferred_updates,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    confirmations: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: confirmations.append("confirm")
    )
    downloaded = _downloaded_fixture(tmp_path)
    dialog = UpdateDialog(
        auto_check=False,
        initial_result=_available_update(),
        lifecycle=lifecycle,
        download_callback=lambda _asset, _progress, _cancel: downloaded,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start_download()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    job.run_callback()

    assert not dialog.install_button.isEnabled()
    assert dialog._downloaded_installer is None
    dialog.install_and_restart()
    dialog.start_download()
    assert confirmations == []
    assert len(jobs) == 1

    job.finish()
    assert dialog.install_button.isEnabled()
    assert dialog._downloaded_installer is downloaded
    assert dialog._job is None


def test_cancel_wins_over_a_download_result_not_yet_delivered(
    qtbot, tmp_path, deferred_updates,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    dialog = UpdateDialog(
        auto_check=False,
        initial_result=_available_update(),
        lifecycle=lifecycle,
        download_callback=lambda _asset, _progress, _cancel: _downloaded_fixture(tmp_path),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start_download()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    job.run_callback()
    dialog.reject()
    job.finish()

    assert not dialog.isVisible()
    assert dialog._downloaded_installer is None
    assert not dialog.install_button.isEnabled()


def test_launch_success_survives_late_cancel_and_quits_only_after_finish(
    qtbot, monkeypatch, tmp_path, deferred_updates,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    events: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
    )
    dialog = UpdateDialog(
        auto_check=False,
        initial_result=_available_update(),
        lifecycle=lifecycle,
        installer_launcher=lambda _downloaded, _cancel: events.append("launch"),
        on_before_install=lambda: events.append("save") or True,
        quit_app=lambda: events.append("quit"),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._handle_download_result(_downloaded_fixture(tmp_path))
    dialog.install_and_restart()
    assert events == ["save"]
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    job.run_callback()
    assert events == ["save", "launch"]
    dialog.close()
    assert job.cancel_event.is_set()
    assert events == ["save", "launch"]

    job.finish()
    qtbot.waitUntil(lambda: events == ["save", "launch", "quit"])
    assert not dialog.isVisible()
    assert not lifecycle.has_active_jobs


@pytest.mark.parametrize("operation", ["check", "download", "install"])
def test_parent_destruction_cancels_without_destroying_or_orphaning_worker(
    qtbot, monkeypatch, tmp_path, deferred_updates, operation,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    dialog = UpdateDialog(
        parent=parent, auto_check=False, initial_result=_available_update(), lifecycle=lifecycle
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    if operation == "check":
        dialog.start_update_check()
    elif operation == "download":
        dialog.start_download()
    else:
        dialog._handle_download_result(_downloaded_fixture(tmp_path))
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
        )
        dialog.install_and_restart()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert not isValid(dialog)
    assert job.cancel_event.is_set()
    assert lifecycle.has_active_jobs
    job.finish(error=UpdateCancelled("Canceled after parent destruction."))
    assert not lifecycle.has_active_jobs


def test_committed_launch_still_quits_when_its_dialog_was_destroyed(
    qtbot, monkeypatch, tmp_path, deferred_updates,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    events: list[str] = []
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = UpdateDialog(
        parent=parent,
        auto_check=False,
        initial_result=_available_update(),
        lifecycle=lifecycle,
        installer_launcher=lambda _downloaded, _cancel: events.append("launch"),
        quit_app=lambda: events.append("quit"),
    )
    dialog._handle_download_result(_downloaded_fixture(tmp_path))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
    )
    dialog.install_and_restart()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    job.run_callback()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(dialog)
    job.finish()
    qtbot.waitUntil(lambda: events == ["launch", "quit"])
    assert not lifecycle.has_active_jobs


@pytest.mark.parametrize("stage", ["confirmation", "save"])
@pytest.mark.parametrize("interruption", ["close", "destroy", "shutdown"])
def test_install_prompt_interruption_cannot_start_a_hidden_launch(
    qtbot, monkeypatch, tmp_path, deferred_updates, stage, interruption,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    parent = QWidget()
    if interruption != "destroy":
        qtbot.addWidget(parent)
    dialog = UpdateDialog(
        parent=parent, auto_check=False, initial_result=_available_update(), lifecycle=lifecycle
    )
    dialog._handle_download_result(_downloaded_fixture(tmp_path))

    def _interrupt() -> None:
        if interruption == "close":
            dialog.reject()
        elif interruption == "destroy":
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        else:
            lifecycle.request_shutdown()

    def _confirm(*_args):
        if stage == "confirmation":
            _interrupt()
        return QMessageBox.StandardButton.Yes

    def _save() -> bool:
        assert stage == "save", "Do not save after confirmation was interrupted."
        _interrupt()
        return True

    dialog._on_before_install = _save
    monkeypatch.setattr(QMessageBox, "question", _confirm)
    dialog.install_and_restart()
    assert not jobs
    assert not lifecycle.has_active_jobs


def test_large_download_byte_counts_are_scaled_without_qt_integer_overflow(
    qtbot, tmp_path, deferred_updates,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    dialog = UpdateDialog(auto_check=False, initial_result=_available_update(), lifecycle=lifecycle)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start_download()
    job = jobs[-1]
    qtbot.waitUntil(lambda: job.is_running)
    total = 4 * 1024**3
    job.progress_changed.emit(3 * 1024**3, total)
    assert dialog.progress_bar.maximum() == 1000
    assert dialog.progress_bar.value() == 750
    job.progress_changed.emit(total + 1, total)
    assert dialog.progress_bar.value() == 1000
    job.progress_changed.emit(total, None)
    assert dialog.progress_bar.maximum() == 0
    job.finish(replace(_downloaded_fixture(tmp_path), size_bytes=total))
    assert dialog.progress_bar.maximum() == dialog.progress_bar.value() == 1000
    assert dialog.install_button.isEnabled()




@pytest.mark.parametrize("shutdown", ["quit_event", "last_window", "about_to_quit"])
def test_application_shutdown_cancels_all_jobs_and_defers_quit(
    qapp, qtbot, deferred_updates, shutdown,
) -> None:
    lifecycle, jobs, quit_calls = deferred_updates
    qapp.setQuitOnLastWindowClosed(True)
    lifecycle.start_task(lambda _progress, _cancel: None)
    lifecycle.start_task(lambda _progress, _cancel: None)
    qtbot.waitUntil(lambda: all(job.is_running for job in jobs))
    assert not qapp.quitOnLastWindowClosed()

    if shutdown == "quit_event":
        QCoreApplication.sendEvent(qapp, QEvent(QEvent.Type.Quit))
    elif shutdown == "last_window":
        qapp.lastWindowClosed.emit()
    else:
        lifecycle._about_to_quit()
    assert lifecycle.is_shutting_down
    assert all(job.cancel_event.is_set() for job in jobs)
    assert quit_calls == []
    with pytest.raises(RuntimeError, match="closing"):
        lifecycle.start_task(lambda _progress, _cancel: None)

    jobs[0].finish()
    qapp.processEvents()
    assert lifecycle.has_active_jobs
    assert quit_calls == []
    jobs[1].finish()
    qtbot.waitUntil(lambda: quit_calls == ["quit"])
    assert not lifecycle.has_active_jobs
    assert qapp.quitOnLastWindowClosed()


def test_root_onboarding_window_transitions_do_not_cancel_startup_work(
    qapp, qtbot, deferred_updates,
) -> None:
    lifecycle, jobs, quit_calls = deferred_updates
    qapp.setQuitOnLastWindowClosed(True)
    lifecycle.begin_startup()
    lifecycle.start_task(lambda _progress, _cancel: None)
    qtbot.waitUntil(lambda: jobs[-1].is_running)
    qapp.lastWindowClosed.emit()
    assert not lifecycle.is_shutting_down
    assert not jobs[-1].cancel_event.is_set()
    jobs[-1].finish()
    assert not qapp.quitOnLastWindowClosed()
    lifecycle.finish_startup()
    assert qapp.quitOnLastWindowClosed()
    assert quit_calls == []










@pytest.mark.parametrize("operation", ["download", "install"])
def test_failed_update_stays_recoverable_and_does_not_quit(
    qtbot, monkeypatch, tmp_path, deferred_updates, operation,
) -> None:
    lifecycle, jobs, quit_calls = deferred_updates
    dialog = UpdateDialog(auto_check=False, initial_result=_available_update(), lifecycle=lifecycle)
    qtbot.addWidget(dialog)
    dialog.show()
    if operation == "download":
        dialog.start_download()
    else:
        dialog._handle_download_result(_downloaded_fixture(tmp_path))
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes
        )
        dialog.install_and_restart()
    qtbot.waitUntil(lambda: jobs[-1].is_running)
    jobs[-1].finish(error=RuntimeError("The cached installer could not be verified."))
    assert dialog.isVisible()
    assert dialog.download_button.isEnabled()
    assert dialog.check_button.isEnabled()
    assert not dialog.install_button.isEnabled()
    assert dialog._downloaded_installer is None
    assert "could not" in dialog.status_label.text()
    assert quit_calls == []


@pytest.mark.parametrize("size", [(680, 600), (760, 620)])
@pytest.mark.parametrize(
    "state",
    [
        "available",
        "patch",
        "full-required",
        "unverifiable",
        "busy",
        "canceling",
        "error",
        "checking-files",
        "download-files",
    ],
)
def test_update_dialog_long_content_fits_minimum_and_default_sizes(
    qtbot,
    tmp_path,
    deferred_updates,
    size,
    state,
) -> None:
    lifecycle, jobs, _quit_calls = deferred_updates
    full_notes = (
        "Improved update integrity, recoverable interrupted transfers, and compatible upgrade "
        "history. " * 12
    ) + str(tmp_path / ("very-long-installer-folder-" * 12))
    result = replace(
        _available_update(),
        current_version="2026.123.456rc987654321",
        latest_version="2027.123.456rc987654321",
        release_notes_summary=full_notes,
    )
    if state == "unverifiable":
        assert result.installer_asset is not None
        result = replace(result, installer_asset=replace(result.installer_asset, sha256=None))
    elif state == "patch":
        assert result.installer_asset is not None
        result = replace(
            result,
            installer_asset=replace(result.installer_asset, kind="patch", size_bytes=12_500_000),
        )
    elif state == "full-required":
        result = replace(
            result,
            selection_reason=(
                "The installed files do not match the patch. A full update is required."
            ),
        )
    dialog = UpdateDialog(auto_check=False, initial_result=result, lifecycle=lifecycle)
    qtbot.addWidget(dialog)
    dialog.resize(*size)
    dialog.show()
    if state in {"checking-files", "download-files"}:
        if state == "checking-files":
            dialog.start_update_check()
        else:
            dialog.start_download()
        qtbot.waitUntil(lambda: jobs[-1].is_running)
        status = "Verifying installed files before downloading the patch..."
        jobs[-1].progress_changed.emit(UpdatePhase(status, result), None)
        assert dialog.status_label.text() == status
        assert not dialog.download_button.isEnabled()
        assert not dialog.install_button.isEnabled()
        assert dialog.progress_bar.isVisible()
        if state == "checking-files":
            assert dialog.latest_version_label.text() == f"Latest version: {result.latest_version}"
    elif state in {"busy", "canceling"}:
        dialog.start_download()
        qtbot.waitUntil(lambda: jobs[-1].is_running)
        if state == "canceling":
            dialog.reject()
    elif state == "error":
        dialog._handle_task_error(RuntimeError(full_notes), "install")
    qtbot.waitUntil(lambda: dialog.close_button.width() > 0)
    # A close request changes wrapped status text after the previous layout.
    # Drain its queued layout request before measuring the new content.
    qtbot.wait(1)

    assert dialog.width() == size[0]
    assert dialog.height() == size[1]
    if state == "patch":
        assert "Patch (12.5 MB)" in dialog.status_label.text()
        assert dialog.download_button.isEnabled()
    elif state == "full-required":
        assert "Full installer" in dialog.status_label.text()
        assert result.selection_reason in dialog.status_label.text()
        assert dialog.download_button.isEnabled()
    assert_visible_children_within_parent(dialog)
    for button in (
        dialog.check_button,
        dialog.download_button,
        dialog.install_button,
        dialog.close_button,
        dialog.release_notes_button,
    ):
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 20
    for label in dialog.findChildren(QLabel):
        if not label.isVisible():
            continue
        if label.wordWrap():
            assert label.height() + 1 >= label.heightForWidth(label.width()), label.objectName()
        else:
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
    assert dialog.notes_label.toolTip() == full_notes
    assert len(dialog.notes_label.text()) <= 240
    assert dialog.notes_label.text() != full_notes




@pytest.mark.parametrize("size", [(680, 660), (760, 680)])
def test_standalone_repair_uses_registered_version_and_full_installer(
    qtbot, deferred_updates, monkeypatch, size
):
    lifecycle, jobs, _ = deferred_updates
    result = replace(_available_update(), current_version="0.9.0b2")
    checks = []

    def check(**kwargs):
        checks.append(kwargs)
        return result

    monkeypatch.setattr("Main_App.gui.updater_window.check_update", check)
    window = UpdaterWindow(auto_check=False, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    window.start_repair_check()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    assert not window.repair_button.isEnabled()
    jobs[-1].run_callback()
    jobs[-1].finish()
    assert checks[-1]["repair"] is True
    assert checks[-1]["force_full"] is True
    assert window.current_version_label.text() == "Current version: 0.9.0b2"
    assert "repair" in window.status_label.text()
    assert window.download_button.text() == "Download Full Installer"
    assert window.download_button.isEnabled()
    assert window.repair_button.isEnabled()
    assert not window.progress_bar.isVisible()
    qtbot.wait(1)
    assert_visible_children_within_parent(window)
    window.start_update_check()
    qtbot.waitUntil(lambda: jobs[-1]._started)
    jobs[-1].run_callback()
    jobs[-1].finish()
    assert checks[-1]["repair"] is False
    assert window.download_button.text() == "Download Update"


def test_standalone_handoff_does_not_claim_to_be_toolbox(qtbot, deferred_updates, monkeypatch):
    lifecycle, _, _ = deferred_updates
    calls = []
    monkeypatch.setattr(
        "Main_App.gui.updater_window.HelperClient.launch_install",
        lambda _self, downloaded, **kwargs: calls.append(kwargs),
    )
    window = UpdaterWindow(auto_check=False, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window._installer_launcher(object(), Event())
    assert calls[0]["parent_pid"] is None


@pytest.mark.parametrize("size", [(480, 140), (560, 160)])
def test_apply_progress_is_minimal_and_preserves_target_version(qtbot, deferred_updates, size):
    lifecycle, jobs, _ = deferred_updates
    window = ApplyUpdateDialog(lambda _progress, _cancel: None, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    assert window.status_label.text() == "Updating FPVS Toolbox... Please wait..."
    assert window.status_label.textFormat() == Qt.TextFormat.PlainText
    version = "2026.12.123rc10"
    jobs[-1].progress_changed.emit(UpdatePhase("Preparing", target_version=version), None)
    jobs[-1].progress_changed.emit(
        UpdatePhase("Installing; keep this window open", install_committed=True), None
    )
    assert window.status_label.text() == (
        f"Updating FPVS Toolbox to version {version}... Please wait..."
    )
    assert not window.details_label.isVisible()
    assert not window.repair_button.isVisible()
    assert not window.close_button.isVisible()
    assert window.progress_bar.isVisible()
    assert window.progress_bar.minimum() == window.progress_bar.maximum() == 0
    assert not window.progress_bar.isTextVisible()
    qtbot.wait(1)
    assert window.width() == size[0]
    assert window.height() == size[1]
    assert window.status_label.height() >= window.status_label.heightForWidth(
        window.status_label.width()
    )
    assert_visible_children_within_parent(window)
    jobs[-1].finish()
    assert window.status_label.text() == "FPVS Toolbox was updated and restarted successfully."
    assert window.progress_bar.value() == window.progress_bar.maximum() == 100
    assert window.progress_bar.isVisible()
    assert not window.details_label.isVisible()
    assert not window.close_button.isVisible()


@pytest.mark.parametrize("size", [(480, 140), (560, 160)])
def test_apply_progress_failure_keeps_repair_and_complete_error_accessible(
    qtbot, deferred_updates, size
):
    lifecycle, jobs, _ = deferred_updates
    window = ApplyUpdateDialog(lambda _progress, _cancel: None, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    error = "Target verification failed. " + "FPVSToolbox-long-file-name.dll " * 60
    jobs[-1].finish(error=UpdateError(error))
    assert window.details_label.toPlainText() == error
    assert window.details_label.isVisible()
    assert window.repair_button.isVisible()
    assert window.close_button.isVisible()
    assert window.close_button.isEnabled()
    assert not window.progress_bar.isVisible()
    assert window.width() >= 560
    assert window.height() >= 340
    qtbot.wait(1)
    assert_visible_children_within_parent(window)


def test_apply_failure_without_error_text_explains_repair(qtbot, deferred_updates):
    lifecycle, jobs, _ = deferred_updates
    window = ApplyUpdateDialog(lambda _progress, _cancel: None, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    jobs[-1].finish(error=UpdateError(""))
    assert window.details_label.toPlainText() == "Open Update & Repair to retry the full installer."
    assert window.details_label.isVisible()
    assert window.repair_button.isVisible()
    assert window.close_button.isVisible()


def test_apply_late_cancel_cannot_hide_installer_failure(qtbot, deferred_updates):
    lifecycle, jobs, _ = deferred_updates

    def apply(progress, cancel):
        # Model setup committing before the GUI sees its queued status signal.
        progress(UpdatePhase("Installing FPVS Toolbox...", install_committed=True), None)
        cancel.set()
        raise UpdateError("The installer did not complete (exit code 12).")

    window = ApplyUpdateDialog(apply, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    jobs[-1].run_callback()
    jobs[-1].finish()
    assert "could not be completed" in window.status_label.text()
    assert "exit code 12" in window.details_label.toPlainText()
    assert window.repair_button.isVisible()


def test_apply_close_before_deferred_start_does_not_launch(qtbot, deferred_updates):
    lifecycle, jobs, _ = deferred_updates
    window = ApplyUpdateDialog(
        lambda _progress, _cancel: pytest.fail("A dismissed helper must not install"),
        lifecycle=lifecycle,
    )
    qtbot.addWidget(window)
    window.show()
    window.reject()
    qtbot.wait(10)
    assert not jobs


def test_apply_cancel_waits_for_worker_before_close(qtbot, deferred_updates):
    lifecycle, jobs, _ = deferred_updates
    window = ApplyUpdateDialog(lambda _progress, _cancel: None, lifecycle=lifecycle)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(jobs) and jobs[-1]._started)
    window.close()
    assert window.isVisible()
    assert jobs[-1].cancel_event.is_set()
    jobs[-1].finish(error=UpdateCancelled("Canceled before launch"))
    assert "canceled before installation" in window.status_label.text()
    assert window.close_button.isVisible()
    assert window.close_button.isEnabled()
    assert not window.details_label.isVisible()
    assert not window.repair_button.isVisible()
    window.close()
    assert not window.isVisible()


@pytest.mark.parametrize("accept_drafts", [True, False])
def test_default_handoff_resolves_drafts_before_launch_and_closes_once(
    qtbot, monkeypatch, tmp_path, accept_drafts,
):
    from Main_App.gui import update_install_guard as guard

    events = []

    class Host(QWidget):
        def closeEvent(self, event):  # noqa: N802
            events.append(("close", getattr(self, "_update_exit_confirmed", False)))
            event.accept()

    host = Host()
    qtbot.addWidget(host)
    host.show()
    lifecycle = UpdateLifecycle(QCoreApplication.instance(), quit_callback=lambda: None)
    monkeypatch.setattr(guard, "_has_active_tool_operations", lambda: False)
    monkeypatch.setattr(
        guard, "_confirm_project_draft_exit",
        lambda _host: events.append("drafts") or accept_drafts,
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.Yes)
    dialog = UpdateDialog(
        parent=host, auto_check=False, lifecycle=lifecycle,
        installer_launcher=lambda _downloaded, _cancel: events.append("launch"),
    )
    qtbot.addWidget(dialog)
    asset = _available_update().installer_asset
    dialog._handle_download_result(DownloadedInstaller(tmp_path / asset.name, 10, asset.sha256, asset))
    dialog.open()
    dialog.install_and_restart()
    if accept_drafts:
        qtbot.waitUntil(lambda: ("close", True) in events)
        assert events == ["drafts", "launch", ("close", True)]
        assert host._update_exit_confirmed is False
    else:
        assert events == ["drafts"]
        assert dialog._job is None
        assert host.isVisible()
        assert not getattr(host, "_update_exit_confirmed", False)
        dialog.close()
    QCoreApplication.instance().removeEventFilter(lifecycle)
    lifecycle.deleteLater()


def assert_visible_children_within_parent(root: QWidget) -> None:
    for child in root.findChildren(QWidget):
        parent = child.parentWidget()
        if parent is None or not child.isVisible():
            continue
        top_left = child.mapTo(parent, child.rect().topLeft())
        bottom_right = child.mapTo(parent, child.rect().bottomRight())
        assert top_left.x() >= -1, child.objectName()
        assert top_left.y() >= -1, child.objectName()
        assert bottom_right.x() <= parent.width() + 1, child.objectName()
        assert bottom_right.y() <= parent.height() + 1, child.objectName()
