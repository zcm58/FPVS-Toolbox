"""Small standalone updater windows, independent of Toolbox's main GUI and models."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from Main_App.gui.updater_presentation import (
    action_button,
    apply_toolbox_theme,
    mark_primary_action,
    mark_secondary_action,
)
from Main_App.gui.update_dialog import UpdateDialog
from Main_App.gui.update_lifecycle import (
    ProgressReporter,
    UpdateCallback,
    UpdateJob,
    UpdateLifecycle,
    UpdateTaskResult,
    update_lifecycle,
)
from Main_App.updates.helper_client import HelperClient
from Main_App.updates.helper_service import (
    binary_stdio,
    check_update,
    download_update,
    run_apply,
)
from Main_App.updates.models import (
    DownloadedInstaller,
    InstallerAsset,
    UpdateCheckResult,
    UpdateError,
    UpdatePhase,
)


def _download(
    asset: InstallerAsset, progress: ProgressReporter, cancel: Event
) -> DownloadedInstaller:
    return download_update(
        asset,
        cancel_event=cancel,
        progress_callback=progress,
        phase_callback=lambda phase: progress(phase, None),
    )


class UpdaterWindow(UpdateDialog):
    """Update or explicitly repair the registered installation without opening Toolbox."""

    def __init__(
        self, *, auto_check: bool = True, lifecycle: UpdateLifecycle | None = None
    ) -> None:
        self._repair = False
        super().__init__(
            auto_check=False,
            check_task=self._check_installed,
            download_callback=_download,
            installer_launcher=lambda downloaded, cancel: HelperClient().launch_install(
                downloaded, parent_pid=None, cancel_event=cancel
            ),
            lifecycle=lifecycle,
        )
        self.setObjectName("standalone_updater")
        self.setWindowTitle("FPVS Toolbox Update & Repair")
        self.title_label.setText("FPVS Toolbox Update & Repair")
        self.current_version_label.setText("Current version: checking installed application...")
        self.setMinimumHeight(660)
        self.resize(760, 680)
        self.repair_button = action_button("Repair / Reinstall", self.button_box)
        self.repair_button.setObjectName("updater_repair_button")
        mark_secondary_action(self.repair_button)
        self.repair_button.clicked.connect(self.start_repair_check)
        actions = self.button_box.layout()
        assert isinstance(actions, QGridLayout)
        actions.addWidget(self.repair_button, 2, 0, 1, 2)
        if auto_check:
            QTimer.singleShot(0, self.start_update_check)

    def _check_installed(self, progress: ProgressReporter, cancel: Event) -> UpdateCheckResult:
        return check_update(
            repair=self._repair,
            force_full=self._repair,
            cancel_event=cancel,
            phase_callback=lambda phase: progress(phase, None),
        )

    @Slot()
    def start_update_check(self) -> None:
        if self._job is not None:
            return
        self._repair = False
        self.download_button.setText("Download Update")
        super().start_update_check()

    @Slot()
    def start_repair_check(self) -> None:
        if self._job is not None:
            return
        self._repair = True
        self.download_button.setText("Download Full Installer")
        super().start_update_check()

    def _set_busy_state(self, status_text: str) -> None:
        super()._set_busy_state(status_text)
        if hasattr(self, "repair_button"):
            self.repair_button.setEnabled(False)

    def _handle_task_finished(self, outcome: object) -> None:
        super()._handle_task_finished(outcome)
        self.repair_button.setEnabled(not self._close_pending and self._job is None)

    def _handle_check_result(self, result: object) -> None:
        super()._handle_check_result(result)
        if self._repair and isinstance(result, UpdateCheckResult) and result.update_available:
            self.download_button.setText("Download Full Installer")
            asset = result.installer_asset
            if asset is not None and asset.sha256 is not None:
                size = f" ({asset.size_bytes / 1_000_000:.1f} MB)" if asset.size_bytes else ""
                self.status_label.setText(
                    f"Full installer{size} available to update or repair FPVS Toolbox.\n\n"
                    "Close all Toolbox windows before installing. Projects, settings, "
                    "analysis results, and logs are preserved."
                )
                self._set_close_button_text("Close")


class ApplyUpdateDialog(QDialog):
    """Keep installation progress visible after the main Toolbox process exits."""

    def __init__(
        self, callback: UpdateCallback, *, lifecycle: UpdateLifecycle | None = None
    ) -> None:
        super().__init__()
        self.setObjectName("updater_install_progress")
        self.setWindowTitle("FPVS Toolbox Updater")
        self.setMinimumSize(620, 340)
        self.resize(700, 380)
        self._callback = callback
        self._lifecycle = lifecycle or update_lifecycle()
        self._job: UpdateJob | None = None
        self._committed = Event()
        self._dismissed = False
        self._repair_window: UpdaterWindow | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self.title_label = QLabel("Updating FPVS Toolbox", self)
        layout.addWidget(self.title_label)
        self.status_label = QLabel("Preparing the verified update...", self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.details_label = QPlainTextEdit(self)
        self.details_label.setReadOnly(True)
        self.details_label.setPlainText(
            "Your projects, settings, analysis results, and logs "
            "stay in their existing folders."
        )
        self.details_label.setMaximumHeight(140)
        layout.addWidget(self.details_label)
        layout.addStretch(1)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        self.repair_button = action_button("Open Update && Repair", self)
        mark_primary_action(self.repair_button)
        self.repair_button.setVisible(False)
        self.repair_button.clicked.connect(self._open_repair)
        layout.addWidget(self.repair_button)
        self.close_button = action_button("Cancel", self)
        mark_secondary_action(self.close_button)
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        apply_toolbox_theme(self)
        QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        if self._dismissed:
            return
        callback = self._callback
        committed = self._committed

        def run(progress: ProgressReporter, cancel: Event) -> object:
            def report(phase: int | UpdatePhase, total: int | None) -> None:
                # Set this before queueing the GUI signal. Cancellation cannot turn
                # an installer failure into a false "canceled before installation".
                if isinstance(phase, UpdatePhase) and phase.install_committed:
                    committed.set()
                progress(phase, total)

            return callback(report, cancel)

        self._job = self._lifecycle.start_task(run, keep_success_on_cancel=True)
        self._job.progress_changed.connect(self._progress)
        self._job.finished.connect(self._finished)

    @Slot(object, object)
    def _progress(self, phase: object, _total: object) -> None:
        if isinstance(phase, UpdatePhase):
            self.status_label.setText(phase.text)
            if phase.install_committed:
                self.close_button.setEnabled(False)
                self.close_button.setText("Installation in progress")

    @Slot(object)
    def _finished(self, outcome: object) -> None:
        self._job = None
        self.progress_bar.setVisible(False)
        self.close_button.setText("Close")
        self.close_button.setEnabled(True)
        if (
            isinstance(outcome, UpdateTaskResult)
            and outcome.error is None
            and not outcome.cancelled
        ):
            self.status_label.setText("FPVS Toolbox was updated and restarted successfully.")
            QTimer.singleShot(1500, self.accept)
        elif (
            isinstance(outcome, UpdateTaskResult)
            and outcome.cancelled
            and not self._committed.is_set()
        ):
            self.status_label.setText("The update was canceled before installation.")
        else:
            self.status_label.setText("The update could not be completed.")
            error = outcome.error if isinstance(outcome, UpdateTaskResult) else None
            self.details_label.setPlainText(
                str(error) or "Open Update & Repair to retry the full installer."
            )
            self.repair_button.setVisible(True)

    @Slot()
    def _open_repair(self) -> None:
        self._repair_window = UpdaterWindow(auto_check=False, lifecycle=self._lifecycle)
        self._repair_window.show()
        self._repair_window.start_repair_check()
        self.accept()

    def reject(self) -> None:
        if self._job is None:
            self._dismissed = True
            super().reject()
        elif not self._committed.is_set():
            self._job.cancel()
            self.close_button.setEnabled(False)
            self.status_label.setText("Canceling before installation. Please wait...")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._job is not None:
            self.reject()
            event.ignore()
        else:
            self._dismissed = True
            super().closeEvent(event)


def run_updater_gui(
    *,
    apply_mode: bool = False,
    smoke_report: Path | None = None,
    startup_error: Exception | None = None,
) -> int:
    """Create the independent Qt application only after backend mode dispatch."""
    app = QApplication([sys.argv[0]])
    app.setApplicationName("FPVS Toolbox Updater")
    app.setOrganizationName("FPVS Toolbox")
    if smoke_report is not None:
        return run_visible_smoke(app, smoke_report)
    if startup_error is not None:
        QMessageBox.critical(
            None,
            "FPVS Toolbox Updater",
            f"The updater could not start. Close other updater windows and retry.\n\n"
            f"{startup_error}\n\n"
            "You can also download the full installer from FPVS Toolbox's GitHub Releases page.",
        )
        return 1
    window: QDialog
    if apply_mode:
        try:
            incoming, outgoing = binary_stdio()
        except Exception as error:
            QMessageBox.critical(None, "FPVS Toolbox Updater", str(error))
            return 1
        window = ApplyUpdateDialog(
            lambda progress, cancel: run_apply(
                incoming,
                outgoing,
                cancel_event=cancel,
                phase_callback=lambda phase: progress(phase, None),
            )
        )
    else:
        window = UpdaterWindow()
    window.show()
    return app.exec()


def run_visible_smoke(app: QApplication, report: Path) -> int:
    """Bounded developer check: visible synthetic windows, no network or installer."""
    app.setQuitOnLastWindowClosed(False)
    window = UpdaterWindow(auto_check=False)
    window.setWindowTitle("FPVS Toolbox Updater — visible smoke check")
    window.title_label.setText("Updater smoke check (synthetic data)")
    asset = InstallerAsset(
        name="FPVSToolbox-99.0.0-setup.exe",
        download_url=(
            "https://github.com/zcm58/FPVS-Toolbox-Repo/releases/download/v99.0.0/"
            "FPVSToolbox-99.0.0-setup.exe"
        ),
        version="99.0.0",
        size_bytes=250_000_000,
        sha256="a" * 64,
        asset_id=1,
    )
    result = UpdateCheckResult(
        current_version="99.0.0",
        latest_version="99.0.0",
        update_available=True,
        release_url=None,
        release_notes_summary="Synthetic packaged GUI check. " * 30,
        installer_asset=asset,
        is_prerelease=False,
    )
    window._repair = True
    window.show_update_result(result)
    window.resize(680, 660)
    window.show()
    evidence: dict[str, object] = {"network": False, "installer": False, "passed": False}
    apply_window: ApplyUpdateDialog | None = None

    def inspect(dialog: QDialog) -> None:
        layout = dialog.layout()
        assert layout is not None
        layout.activate()
        for label in dialog.findChildren(QLabel):
            if label.isVisible() and label.wordWrap():
                if label.height() + 1 < label.heightForWidth(label.width()):
                    raise RuntimeError(f"Wrapped updater text clipped: {label.text()}")
        for button in dialog.findChildren(QPushButton):
            if button.isVisible():
                if button.width() < button.fontMetrics().horizontalAdvance(button.text()) + 20:
                    raise RuntimeError(f"Updater button clipped: {button.text()}")

    def finish(error: Exception | None = None) -> None:
        evidence["passed"] = error is None
        if error is not None:
            evidence["error"] = str(error)
        try:
            report.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        finally:
            app.exit(0 if error is None else 1)

    def inspect_apply() -> None:
        try:
            assert apply_window is not None
            if apply_window._job is not None:
                raise RuntimeError("Synthetic updater worker did not finish.")
            inspect(apply_window)
            if not apply_window.repair_button.isVisible():
                raise RuntimeError("Failed update does not expose repair.")
            if "synthetic" not in apply_window.details_label.toPlainText():
                raise RuntimeError("Failed update lost its error detail.")
            apply_window.grab().save(str(report.with_suffix(".apply.png")))
            evidence["repair_after_failure"] = True
            finish()
        except Exception as error:
            finish(error)

    def inspect_standalone() -> None:
        nonlocal apply_window
        try:
            inspect(window)
            if not window.download_button.isEnabled() or not window.repair_button.isEnabled():
                raise RuntimeError("Standalone repair actions are unavailable.")
            window.grab().save(str(report.with_suffix(".repair.png")))
            evidence["standalone_repair"] = True

            def fail(_progress: ProgressReporter, _cancel: Event) -> None:
                raise UpdateError("This synthetic installation failure tests the repair surface.")

            apply_window = ApplyUpdateDialog(fail)
            apply_window.setWindowTitle("FPVS Toolbox Updater — synthetic failure check")
            apply_window.resize(620, 340)
            apply_window.show()
            window.close()
            QTimer.singleShot(500, inspect_apply)
        except Exception as error:
            finish(error)

    QTimer.singleShot(500, inspect_standalone)
    QTimer.singleShot(10_000, lambda: finish(RuntimeError("Visible updater smoke timed out.")))
    return app.exec()
