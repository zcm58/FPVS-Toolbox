"""User-facing update dialog for FPVS Toolbox."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from threading import Event

from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from Main_App.updates.application import APP_VERSION as __version__
from Main_App.gui.updater_presentation import (
    action_button,
    apply_toolbox_theme,
    mark_primary_action,
    mark_secondary_action,
)
from Main_App.gui.updater_presentation import elide_middle
from Main_App.gui.update_lifecycle import (
    ProgressReporter,
    UpdateCallback,
    UpdateJob,
    UpdateLifecycle,
    UpdateTaskResult,
    update_lifecycle,
)
from Main_App.gui.update_install_guard import close_after_update, default_install_guard
from Main_App.updates.helper_client import HelperClient
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCheckResult,
    UpdatePhase,
)

_LOGGER = logging.getLogger(__name__)
_MINIMUM_SIZE = (680, 600)
_DEFAULT_SIZE = (760, 620)
_PROGRESS_MAXIMUM = 1000


def _check_update(progress: ProgressReporter, cancel_event: Event) -> UpdateCheckResult:
    return HelperClient().check(
        __version__, cancel_event=cancel_event, phase_callback=lambda phase: progress(phase, None)
    )


def _download_update(
    asset: InstallerAsset,
    progress: ProgressReporter,
    cancel_event: Event,
) -> DownloadedInstaller:
    return HelperClient().download(
        asset,
        progress_callback=progress,
        cancel_event=cancel_event,
        phase_callback=lambda phase: progress(phase, None),
    )


def _launch_update(downloaded: DownloadedInstaller, cancel_event: Event) -> object:
    return HelperClient().launch_install(
        downloaded, parent_pid=os.getpid(), cancel_event=cancel_event
    )


class UpdateDialog(QDialog):
    """Check GitHub Releases and guide the user through an installer update."""

    def __init__(
        self,
        *,
        parent: QWidget | None = None,
        auto_check: bool = True,
        check_callback: Callable[[Event], UpdateCheckResult] | None = None,
        check_task: UpdateCallback | None = None,
        download_callback: Callable[
            [InstallerAsset, ProgressReporter, Event],
            DownloadedInstaller,
        ] = _download_update,
        installer_launcher: Callable[[DownloadedInstaller, Event], object] = _launch_update,
        initial_result: UpdateCheckResult | None = None,
        on_before_install: Callable[[], bool] | None = None,
        quit_app: Callable[[], None] | None = None,
        lifecycle: UpdateLifecycle | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("update_dialog")
        self.setWindowTitle("Check for Updates")
        self.setMinimumSize(*_MINIMUM_SIZE)
        self.resize(*_DEFAULT_SIZE)

        self._check_callback = check_callback
        self._check_task = check_task
        self._download_callback = download_callback
        self._installer_launcher = installer_launcher
        self._on_before_install = on_before_install or (lambda: default_install_guard(parent))
        self._quit_app = quit_app or (
            (lambda: close_after_update(parent))
            if parent is not None else self._quit_application
        )
        self._lifecycle = lifecycle or update_lifecycle()
        self._job: UpdateJob | None = None
        self._task_kind: str | None = None
        self._close_pending = False
        self._close_result = int(QDialog.DialogCode.Rejected)
        self._result: UpdateCheckResult | None = None
        self._downloaded_installer: DownloadedInstaller | None = None
        self._disposed = Event()
        disposed = self._disposed
        self.destroyed.connect(lambda _object=None: disposed.set())
        self._lifecycle.shutdown_started.connect(self._handle_application_shutdown)

        self._build_ui()
        self._set_idle_state()
        if initial_result is not None:
            self.show_update_result(initial_result)
        elif auto_check:
            QTimer.singleShot(0, self.start_update_check)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.title_label = QLabel("FPVS Toolbox updates", self)
        self.title_label.setObjectName("update_dialog_title")
        layout.addWidget(self.title_label)

        self.status_label = QLabel("Ready to check for updates.", self)
        self.status_label.setObjectName("update_dialog_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        versions_layout = QVBoxLayout()
        versions_layout.setSpacing(4)
        self.current_version_label = QLabel(f"Current version: {__version__}", self)
        self.latest_version_label = QLabel("Latest version: Not checked yet", self)
        self.current_version_label.setWordWrap(True)
        self.latest_version_label.setWordWrap(True)
        versions_layout.addWidget(self.current_version_label)
        versions_layout.addWidget(self.latest_version_label)
        layout.addLayout(versions_layout)

        self.notes_heading_label = QLabel("What's New", self)
        self.notes_heading_label.setObjectName("update_dialog_notes_heading")
        layout.addWidget(self.notes_heading_label)
        self.notes_label = QLabel("Release notes will appear when an update is available.", self)
        self.notes_label.setObjectName("update_dialog_notes")
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notes_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.notes_label)
        layout.addStretch(1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("update_dialog_progress")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.release_notes_button = action_button("View Full Release Notes", self)
        self.release_notes_button.setObjectName("update_dialog_release_notes_button")
        mark_secondary_action(self.release_notes_button)
        self.release_notes_button.clicked.connect(self._open_release_notes)
        button_row.addWidget(self.release_notes_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.button_box = QWidget(self)
        self.button_box.setObjectName("update_dialog_button_box")
        actions_layout = QGridLayout(self.button_box)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setHorizontalSpacing(8)
        actions_layout.setVerticalSpacing(8)
        actions_layout.setColumnStretch(0, 1)
        actions_layout.setColumnStretch(1, 1)
        self.check_button = action_button("Check Again", self.button_box)
        self.check_button.setObjectName("update_dialog_check_button")
        self.download_button = action_button("Download Update", self.button_box)
        self.download_button.setObjectName("update_dialog_download_button")
        self.install_button = action_button("Install and Restart", self.button_box)
        self.install_button.setObjectName("update_dialog_install_button")
        self.close_button = action_button("Close", self.button_box)
        self.close_button.setObjectName("update_dialog_close_button")
        actions_layout.addWidget(self.check_button, 0, 0)
        actions_layout.addWidget(self.download_button, 0, 1)
        actions_layout.addWidget(self.install_button, 1, 0)
        actions_layout.addWidget(self.close_button, 1, 1)
        mark_secondary_action(self.check_button)
        mark_primary_action(self.download_button)
        mark_primary_action(self.install_button)
        mark_secondary_action(self.close_button)
        self.check_button.clicked.connect(self.start_update_check)
        self.download_button.clicked.connect(self.start_download)
        self.install_button.clicked.connect(self.install_and_restart)
        self.close_button.clicked.connect(self._dismiss_dialog)
        layout.addWidget(self.button_box)
        apply_toolbox_theme(self)
        self._fit_action_buttons()

    @Slot()
    def start_update_check(self) -> None:
        if (
            self._disposed.is_set()
            or self._job is not None
            or self._close_pending
            or self._lifecycle.is_shutting_down
        ):
            return
        self._result = None
        self._downloaded_installer = None
        self._set_busy_state("Checking GitHub Releases...")
        self.progress_bar.setVisible(False)
        check_callback = self._check_callback
        self._lifecycle.manual_check_requested.emit()
        self._start_task(
            "check",
            self._check_task
            or (
                _check_update
                if check_callback is None
                else lambda _progress, cancel: check_callback(cancel)
            ),
        )

    def show_update_result(self, result: UpdateCheckResult) -> None:
        """Populate the dialog from an already-completed update check."""

        if not self._disposed.is_set() and self._job is None and not self._close_pending:
            self._handle_check_result(result)

    @Slot()
    def start_download(self) -> None:
        if (
            self._disposed.is_set()
            or self._job is not None
            or self._close_pending
            or self._lifecycle.is_shutting_down
        ):
            return
        if self._result is None:
            return
        asset = self._result.installer_asset
        if asset is None or asset.sha256 is None:
            return
        self._downloaded_installer = None
        self._set_busy_state("Downloading and verifying the update...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        download_callback = self._download_callback
        self._start_task(
            "download",
            lambda progress, cancel: download_callback(asset, progress, cancel),
        )

    @Slot()
    def install_and_restart(self) -> None:
        if (
            self._disposed.is_set()
            or self._job is not None
            or self._downloaded_installer is None
            or self._close_pending
            or self._lifecycle.is_shutting_down
        ):
            return
        answer = QMessageBox.question(
            self,
            "Install Update",
            "FPVS Toolbox needs to close to install the update.\n\n"
            "Install the update and restart FPVS Toolbox?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # Confirmation and Save can enter nested GUI event loops. The parent or app
        # may have closed while either prompt was open; never continue into a dead
        # dialog or launch an installer after that cancellation.
        if self._disposed.is_set() or self._close_pending or self._lifecycle.is_shutting_down:
            return
        if self._on_before_install is not None and not self._on_before_install():
            return
        if self._disposed.is_set() or self._close_pending or self._lifecycle.is_shutting_down:
            return
        downloaded = self._downloaded_installer
        if downloaded is None:
            return
        installer_launcher = self._installer_launcher
        self._set_busy_state("Preparing FPVS Toolbox Updater. Toolbox will close when it is ready...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self._start_task(
            "install",
            lambda _progress, cancel: installer_launcher(downloaded, cancel),
            keep_success_on_cancel=True,
            on_committed_success=self._quit_app,
        )

    def _start_task(
        self,
        kind: str,
        callback: UpdateCallback,
        *,
        keep_success_on_cancel: bool = False,
        on_committed_success: Callable[[], None] | None = None,
    ) -> None:
        job = self._lifecycle.start_task(
            callback,
            keep_success_on_cancel=keep_success_on_cancel,
            on_committed_success=on_committed_success,
        )
        job.finished.connect(self._handle_task_finished)
        job.progress_changed.connect(self._handle_download_progress)
        self.destroyed.connect(job.cancel)
        self._job = job
        self._task_kind = kind

    @Slot(object)
    def _handle_task_finished(self, outcome: object) -> None:
        kind = self._task_kind
        self._job = None
        self._task_kind = None
        if not isinstance(outcome, UpdateTaskResult) and (
            self._close_pending or self._lifecycle.is_shutting_down
        ):
            super().done(self._close_result)
            return
        if not isinstance(outcome, UpdateTaskResult):
            self._handle_task_error(TypeError("Updater returned an unexpected outcome."), kind)
        elif kind == "install" and outcome.error is None and not outcome.cancelled:
            # Launch has committed. A late close/cancel cannot undo Popen, and the app
            # must exit, but only now that the launch/verification worker has stopped.
            self._close_pending = False
            self.accept()
            return
        elif self._close_pending or self._lifecycle.is_shutting_down:
            super().done(self._close_result)
            return
        elif outcome.cancelled:
            self._handle_task_cancelled()
        elif outcome.error is not None:
            self._handle_task_error(outcome.error, kind)
        elif kind == "check":
            self._handle_check_result(outcome.value)
        elif kind == "download":
            self._handle_download_result(outcome.value)

    @Slot(object)
    def _handle_check_result(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            self._handle_task_error(
                TypeError("Update check returned an unexpected result."), "check"
            )
            return
        self._result = result
        self._downloaded_installer = None
        self.progress_bar.setVisible(False)
        self.current_version_label.setText(f"Current version: {result.current_version}")
        self.latest_version_label.setText(f"Latest version: {result.latest_version}")
        self.release_notes_button.setEnabled(result.release_url is not None)
        if result.release_notes_summary:
            self._set_notes_text(result.release_notes_summary)
        elif result.release_url is not None:
            self._set_notes_text("No release notes were provided for this release.")
        else:
            self._set_notes_text("Release notes will appear when an update is available.")

        if result.update_available:
            asset = result.installer_asset
            verified_asset = asset is not None and asset.sha256 is not None
            if verified_asset:
                assert asset is not None
                download_kind = "Patch" if asset.kind == "patch" else "Full installer"
                download_size = (
                    f" ({asset.size_bytes / 1_000_000:.1f} MB)"
                    if asset.size_bytes is not None
                    else ""
                )
                selection = f"{download_kind}{download_size}."
                if result.selection_reason:
                    selection += f" {result.selection_reason}"
                self.status_label.setText(
                    f"A new FPVS Toolbox version is available. {selection}\n\n"
                    "Updates replace application files. Your projects, settings, "
                    "analysis results, and logs are preserved."
                )
            else:
                self.status_label.setText(
                    "A new FPVS Toolbox version is available, but in-app installation is "
                    "unavailable because this release lacks valid trusted installer metadata "
                    "(including its SHA-256 checksum). "
                    "Use View Full Release Notes to open the release page."
                )
            self.download_button.setEnabled(verified_asset)
            self._set_close_button_text("Remind Me Later")
        else:
            self.status_label.setText("FPVS Toolbox is up to date.")
            self.download_button.setEnabled(False)
            self._set_close_button_text("Close")
        self.check_button.setEnabled(True)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(True)

    @Slot(object)
    def _handle_download_result(self, result: object) -> None:
        if not isinstance(result, DownloadedInstaller):
            self._handle_task_error(
                TypeError("Update download returned an unexpected result."), "download"
            )
            return
        self._downloaded_installer = result
        self.status_label.setText("The update is verified and ready to install.")
        self.download_button.setEnabled(True)
        self.install_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Close")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, _PROGRESS_MAXIMUM)
        self.progress_bar.setValue(_PROGRESS_MAXIMUM)

    def _handle_task_error(self, error: object, kind: str | None = None) -> None:
        _LOGGER.warning("Updater operation failed", extra={"operation": kind, "error": str(error)})
        if kind == "download":
            message = "The update download could not be completed. Retry starts a new download."
        elif kind == "install":
            message = "The installer could not be verified or launched. Download the update again."
            self._downloaded_installer = None
        else:
            message = (
                "The update check could not be completed. Check your internet connection "
                "and try again later from File > Check for Updates."
            )
        self.status_label.setText(message)
        self._set_notes_text(str(error) or "The update operation could not be completed.")
        self.progress_bar.setVisible(False)
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(self._download_available())
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Close")

    @Slot(object, object)
    def _handle_download_progress(self, downloaded: object, total: object) -> None:
        if self._close_pending or self._job is None:
            return
        if isinstance(downloaded, UpdatePhase):
            self.status_label.setText(downloaded.text)
            result = downloaded.result
            if result is not None and self._task_kind == "check":
                self.current_version_label.setText(f"Current version: {result.current_version}")
                self.latest_version_label.setText(f"Latest version: {result.latest_version}")
                self._set_notes_text(result.release_notes_summary)
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setVisible(True)
            return
        if isinstance(downloaded, int) and isinstance(total, int) and total > 0:
            # Qt widgets accept signed 32-bit integers, but supported downloads can
            # exceed 2 GiB. Keep Python-sized byte math and pass only scaled units.
            scaled = max(0, min(downloaded, total)) * _PROGRESS_MAXIMUM // total
            self.progress_bar.setRange(0, _PROGRESS_MAXIMUM)
            self.progress_bar.setValue(scaled)
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)

    def _handle_task_cancelled(self) -> None:
        self._downloaded_installer = None
        self.status_label.setText("The update operation was canceled. Retry starts from zero.")
        self.progress_bar.setVisible(False)
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(self._download_available())
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Close")

    def _download_available(self) -> bool:
        asset = None if self._result is None else self._result.installer_asset
        return bool(
            self._result is not None
            and self._result.update_available
            and asset is not None
            and asset.sha256 is not None
        )

    def _set_idle_state(self) -> None:
        self.release_notes_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Close")

    def _set_busy_state(self, status_text: str) -> None:
        self.status_label.setText(status_text)
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Cancel and Close")

    @Slot()
    def _dismiss_dialog(self) -> None:
        self.reject()

    def reject(self) -> None:
        self.done(int(QDialog.DialogCode.Rejected))

    def done(self, result: int) -> None:
        if self._job is not None:
            self._request_close(result)
            return
        self._close_pending = True
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._job is not None:
            self._request_close(int(QDialog.DialogCode.Rejected))
            event.ignore()
            return
        super().closeEvent(event)

    def _request_close(self, result: int) -> None:
        self._close_pending = True
        self._close_result = result
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self._set_close_button_text("Canceling...")
        self.status_label.setText(
            "Canceling the update operation and waiting for it to finish safely. "
            "Incomplete downloads are discarded; a retry starts from zero. "
            "A network check may need to reach its timeout."
        )
        if self._job is not None:
            self._job.cancel()

    @Slot()
    def _handle_application_shutdown(self) -> None:
        if self._job is not None:
            self._request_close(int(QDialog.DialogCode.Rejected))
        else:
            self.reject()

    def _set_close_button_text(self, text: str) -> None:
        self.close_button.setText(text)
        self._fit_action_buttons()

    def _fit_action_buttons(self) -> None:
        buttons = (
            self.check_button,
            self.download_button,
            self.install_button,
            self.close_button,
        )
        for button in buttons:
            text_width = button.fontMetrics().horizontalAdvance(button.text())
            button.setMinimumWidth(max(button.minimumSizeHint().width(), text_width + 36))
        required_width = max(button.minimumWidth() for button in buttons) * 2 + 8 + 36
        self.setMinimumWidth(max(_MINIMUM_SIZE[0], required_width))

    def _set_notes_text(self, text: str) -> None:
        # A compact preview keeps every action visible at the minimum size. The full
        # release/error value remains available by tooltip and release-page action.
        words = (elide_middle(word, 64) for word in text.split())
        self.notes_label.setText(elide_middle(" ".join(words), 240))
        self.notes_label.setToolTip(text)

    def _open_release_notes(self) -> None:
        if self._result is None or self._result.release_url is None:
            return
        QDesktopServices.openUrl(QUrl(self._result.release_url))

    @staticmethod
    def _quit_application() -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
