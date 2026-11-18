"""Review an OpenFPVS destination, connect with a lab code and share released results."""

from functools import partial
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QLineEdit

from Main_App.gui.components import AppDialog, make_action_button, show_warning
from Main_App.reporting.client import ReportingError, deliver_pending, enroll
from Main_App.reporting.provenance import reporting_scope
from Main_App.reporting.publish import publish_current


_STATUS = {
    "delivered": "OpenFPVS accepted the dataset revision.",
    "pending": "An earlier revision was accepted. Another revision is pending.",
    "no_pending": "No result upload is pending.",
    "invalid_snapshot": "OpenFPVS rejected the result format. Review the current processed dataset.",
    "roster_revision_conflict": "OpenFPVS has a different roster. Share the current roster from Studio, then retry. If the roster changed, review the revised cohort and share its results.",
    "approval_required": "Ask the administrator to approve this lab computer, then connect again.",
    "connection_required": "Connect with the lab code for this study first.",
    "snapshot_parent_conflict": "Another revision or connection conflicts with this upload. Review the dataset on OpenFPVS.",
    "delivery_unavailable": "OpenFPVS is unavailable. Your local files are preserved.",
    "capacity_or_rate_limit": "OpenFPVS reached a capacity or request limit. Retry later.",
    "authorization_required": "OpenFPVS access was rejected. Review the lab connection.",
}


class _Transfer(QThread):
    message = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            status = self.operation()
            self.message.emit(_STATUS.get(status, status))
        except ReportingError as error:
            self.message.emit(_STATUS.get(error.code, "OpenFPVS could not verify this request."))
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.message.emit(str(error))
        finally:
            self.operation = None


class ResultsSharingDialog(AppDialog):
    def __init__(self, project, scope, parent):
        super().__init__("Share study results", parent)
        self.setMinimumWidth(460)
        self.project_root, self.scope = Path(project.project_root), scope
        self.thread = None
        for text in (
            f"OpenFPVS study {scope['study_id']}",
            f"{scope['experiment_id']} · {scope['experiment_version']}",
            "Sharing sends the released ROI results, processing details, electrode decisions and reviewed visit coverage to the study’s authorized readers. Each lab keeps its own dataset.",
        ):
            label = QLabel(text, self)
            label.setWordWrap(True)
            self.root_layout.addWidget(label)
        self.code = QLineEdit(self)
        self.code.setEchoMode(QLineEdit.Password)
        self.code.setPlaceholderText("Lab code")
        self.code.setAccessibleName("Lab code")
        self.root_layout.addWidget(self.code)
        self.connect_button = make_action_button("Connect to study", parent=self)
        self.publish_button = make_action_button("Share current results", parent=self)
        self.retry_button = make_action_button("Retry pending upload", parent=self)
        for button in (self.connect_button, self.publish_button, self.retry_button):
            self.root_layout.addWidget(button)
        self.connect_button.clicked.connect(self._connect)
        self.publish_button.clicked.connect(lambda: self._start(partial(publish_current, self.project_root)))
        self.retry_button.clicked.connect(lambda: self._start(partial(deliver_pending, self.project_root, retry=True)))
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        self.buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(self.buttons)

    def _connect(self):
        code = self.code.text().strip()
        self.code.clear()
        if not code:
            self.status.setText("Enter the lab code to connect to this study.")
            return

        root, scope = self.project_root, dict(self.scope)

        def connect():
            result = enroll(root, scope, code)
            return "Connected to the study." if result["upload_enabled"] else "approval_required"

        self._start(connect)

    def _start(self, operation):
        if self.thread is not None:
            return
        self.thread = _Transfer(operation, self)
        self.thread.message.connect(self.status.setText)
        self.thread.finished.connect(self._released)
        self._enable(False)
        self.status.setText("Contacting OpenFPVS…")
        self.thread.start()

    def _enable(self, enabled):
        for control in (self.code, self.connect_button, self.publish_button, self.retry_button, self.buttons):
            control.setEnabled(enabled)

    def _released(self):
        self.thread.deleteLater()
        self.thread = None
        self._enable(True)

    def reject(self):
        if self.thread is None:
            super().reject()

    def closeEvent(self, event):
        if self.thread is not None:
            event.ignore()
            return
        super().closeEvent(event)


def open_results_sharing(host):
    project = getattr(host, "currentProject", None)
    if project is None:
        return
    try:
        scope = reporting_scope(project)
    except (KeyError, ValueError) as error:
        show_warning(host, "OpenFPVS results", str(error))
        return
    dialog = ResultsSharingDialog(project, scope, host)
    host._results_sharing_dialog = dialog
    try:
        dialog.exec()
    finally:
        host._results_sharing_dialog = None
        dialog.deleteLater()
