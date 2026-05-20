"""User-facing update dialog for FPVS Toolbox."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from config import FPVS_TOOLBOX_VERSION
from Main_App.gui.components import make_action_button
from Main_App.gui.components.messages import confirm, show_warning
from Main_App.updates.downloader import download_installer
from Main_App.updates.github_releases import check_for_updates
from Main_App.updates.installer import launch_installer
from Main_App.updates.models import DownloadedInstaller, InstallerAsset, UpdateCheckResult

ProgressReporter = Callable[[int, int | None], None]
TaskCallback = Callable[[ProgressReporter], object]


class _UpdateTaskWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    progress_changed = Signal(int, object)
    finished = Signal()

    def __init__(self, callback: TaskCallback) -> None:
        super().__init__()
        self._callback = callback

    @Slot()
    def run(self) -> None:
        try:
            result = self._callback(self._emit_progress)
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def _emit_progress(self, downloaded: int, total: int | None) -> None:
        self.progress_changed.emit(downloaded, total)


class UpdateDialog(QDialog):
    """Check GitHub Releases and guide the user through an installer update."""

    def __init__(
        self,
        *,
        parent: QWidget | None = None,
        auto_check: bool = True,
        check_callback: Callable[[], UpdateCheckResult] = check_for_updates,
        download_callback: Callable[
            [InstallerAsset, ProgressReporter],
            DownloadedInstaller,
        ] = lambda asset, progress: download_installer(asset, progress_callback=progress),
        installer_launcher: Callable[[Path], object] = launch_installer,
        initial_result: UpdateCheckResult | None = None,
        on_before_install: Callable[[], bool] | None = None,
        quit_app: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("update_dialog")
        self.setProperty("fpvsSurface", True)
        self.setWindowTitle("Check for Updates")
        self.setMinimumWidth(680)

        self._check_callback = check_callback
        self._download_callback = download_callback
        self._installer_launcher = installer_launcher
        self._on_before_install = on_before_install or (lambda: default_install_guard(parent))
        self._quit_app = quit_app or self._quit_application
        self._thread: QThread | None = None
        self._worker: _UpdateTaskWorker | None = None
        self._result: UpdateCheckResult | None = None
        self._downloaded_installer: DownloadedInstaller | None = None

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
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.status_label = QLabel("Ready to check for updates.", self)
        self.status_label.setObjectName("update_dialog_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        versions_layout = QVBoxLayout()
        versions_layout.setSpacing(4)
        self.current_version_label = QLabel(f"Current version: {FPVS_TOOLBOX_VERSION}", self)
        self.latest_version_label = QLabel("Latest version: Not checked yet", self)
        versions_layout.addWidget(self.current_version_label)
        versions_layout.addWidget(self.latest_version_label)
        layout.addLayout(versions_layout)

        self.notes_heading_label = QLabel("What's New", self)
        self.notes_heading_label.setObjectName("update_dialog_notes_heading")
        self.notes_heading_label.setProperty("subsectionHeader", True)
        layout.addWidget(self.notes_heading_label)

        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setObjectName("update_dialog_notes")
        self.notes_edit.setReadOnly(True)
        self.notes_edit.setMinimumHeight(110)
        self.notes_edit.setPlainText("Release notes will appear when an update is available.")
        layout.addWidget(self.notes_edit)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("update_dialog_progress")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        notes_row = QHBoxLayout()
        notes_row.setSpacing(8)
        self.release_notes_button = make_action_button(
            "View Full Release Notes",
            variant="tertiary",
            parent=self,
        )
        self.release_notes_button.setObjectName("update_dialog_release_notes_button")
        self.release_notes_button.clicked.connect(self._open_release_notes)
        notes_row.addWidget(self.release_notes_button)
        notes_row.addStretch(1)
        layout.addLayout(notes_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        self.check_button = make_action_button("Check Again", parent=self)
        self.download_button = make_action_button("Download Update", variant="primary", parent=self)
        self.install_button = make_action_button("Install and Restart", variant="primary", parent=self)
        self.close_button = make_action_button("Close", variant="secondary", parent=self)
        for button in (
            self.check_button,
            self.download_button,
            self.install_button,
            self.close_button,
        ):
            button_row.addWidget(button)
        self.check_button.clicked.connect(self.start_update_check)
        self.download_button.clicked.connect(self.start_download)
        self.install_button.clicked.connect(self.install_and_restart)
        self.close_button.clicked.connect(self._dismiss_dialog)
        layout.addLayout(button_row)
        self._fit_action_buttons()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            event.ignore()
            return
        super().closeEvent(event)

    @Slot()
    def start_update_check(self) -> None:
        if self._thread is not None:
            return
        self._result = None
        self._downloaded_installer = None
        self._set_busy_state("Checking GitHub Releases...")
        self.progress_bar.setVisible(False)
        self._start_task(lambda _progress: self._check_callback(), self._handle_check_result)

    def show_update_result(self, result: UpdateCheckResult) -> None:
        """Populate the dialog from an already-completed update check."""

        self._handle_check_result(result)

    @Slot()
    def start_download(self) -> None:
        if self._thread is not None:
            return
        if self._result is None or self._result.installer_asset is None:
            return
        asset = self._result.installer_asset
        self._downloaded_installer = None
        self._set_busy_state("Downloading update...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self._start_task(
            lambda progress: self._download_callback(asset, progress),
            self._handle_download_result,
        )

    @Slot()
    def install_and_restart(self) -> None:
        if self._downloaded_installer is None:
            return
        if not confirm(
            self,
            "Install Update",
            "FPVS Toolbox needs to close to install the update.\n\n"
            "Install the update and restart FPVS Toolbox?",
        ):
            return
        if not self._on_before_install():
            return
        try:
            self._installer_launcher(self._downloaded_installer.path)
        except Exception as error:
            show_warning(self, "Install Update", str(error))
            return
        self.accept()
        self._quit_app()

    def _start_task(
        self,
        callback: TaskCallback,
        result_handler: Callable[[object], None],
    ) -> None:
        thread = QThread(self)
        worker = _UpdateTaskWorker(callback)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(result_handler)
        worker.failed.connect(self._handle_task_error)
        worker.progress_changed.connect(self._handle_download_progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._handle_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object)
    def _handle_check_result(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            self._handle_task_error(TypeError("Update check returned an unexpected result."))
            return

        self._result = result
        self.current_version_label.setText(f"Current version: {result.current_version}")
        self.latest_version_label.setText(f"Latest version: {result.latest_version}")
        self.release_notes_button.setEnabled(result.release_url is not None)
        if result.release_notes_summary:
            self.notes_edit.setPlainText(result.release_notes_summary)
        elif result.release_url is not None:
            self.notes_edit.setPlainText("No release notes were provided for this release.")
        else:
            self.notes_edit.setPlainText("Release notes will appear when an update is available.")

        if result.update_available and result.installer_asset is not None:
            self.status_label.setText(
                "A new FPVS Toolbox version is available. The installer replaces app files only; "
                "projects, settings, logs, and generated outputs stay outside the install folder."
            )
            self.download_button.setEnabled(True)
            self._set_close_button_text("Remind Me Later")
        elif result.update_available and result.installer_asset is None:
            self.status_label.setText(
                "A newer FPVS Toolbox release exists, but its GitHub release metadata is incomplete. "
                "The expected Windows installer asset was not found."
            )
            self.download_button.setEnabled(False)
            self._set_close_button_text("Close")
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
            self._handle_task_error(TypeError("Update download returned an unexpected result."))
            return
        self._downloaded_installer = result
        self.status_label.setText("The update is ready to install.")
        self.download_button.setEnabled(True)
        self.install_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, max(1, result.size_bytes))
        self.progress_bar.setValue(result.size_bytes)

    @Slot(object)
    def _handle_task_error(self, error: object) -> None:
        self.status_label.setText(
            "The update operation could not be completed. Check your internet connection "
            "or release metadata and try again later from File > Check for Updates."
        )
        self.notes_edit.setPlainText(str(error) or "GitHub Releases could not be reached.")
        self.progress_bar.setVisible(False)
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._set_close_button_text("Close")

    @Slot(int, object)
    def _handle_download_progress(self, downloaded: int, total: object) -> None:
        if isinstance(total, int) and total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(downloaded, total))
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)

    @Slot()
    def _handle_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

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
        self.close_button.setEnabled(False)

    @Slot()
    def _dismiss_dialog(self) -> None:
        self.close_button.setEnabled(False)
        QTimer.singleShot(0, self.reject)

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
        required_width = sum(button.minimumWidth() for button in buttons) + (
            12 * max(0, len(buttons) - 1)
        ) + 60
        self.setMinimumWidth(max(self.minimumWidth(), required_width))

    def _open_release_notes(self) -> None:
        if self._result is None or self._result.release_url is None:
            return
        QDesktopServices.openUrl(QUrl(self._result.release_url))

    @staticmethod
    def _quit_application() -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()


def default_install_guard(parent: QWidget | None) -> bool:
    """Block installer launch while Toolbox has active processing/export work."""

    if parent is None:
        return True
    if not _host_has_active_work(parent):
        return True

    show_warning(
        parent,
        "Update Blocked",
        "Processing or export work is still running. Finish or stop the active operation "
        "before installing an update.",
    )
    return False


def _host_has_active_work(host: QWidget) -> bool:
    if bool(getattr(host, "busy", False)):
        return True
    if bool(getattr(host, "_run_active", False)):
        return True
    if bool(getattr(host, "_pending_finalize", False)):
        return True
    if bool(getattr(host, "_post_backlog", None)):
        return True
    for attr_name in (
        "processing_thread",
        "detection_thread",
        "_post_thread",
        "_thread",
        "_worker_thread",
    ):
        if _handle_is_active(getattr(host, attr_name, None)):
            return True
    if getattr(host, "_post_worker", None) is not None:
        return True
    return False


def _handle_is_active(handle: Any) -> bool:
    if handle is None:
        return False
    for method_name in ("isRunning", "is_alive"):
        method = getattr(handle, method_name, None)
        if callable(method):
            try:
                return bool(method())
            except RuntimeError:
                return False
    return False
