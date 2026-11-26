"""Review an OpenFPVS destination, connect with a lab code and share released results."""

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit

from Main_App.gui.components import AppDialog, SubsectionHeaderLabel, make_action_button, make_action_row, show_warning
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
    "snapshot_scope_conflict": "The pending upload and the current study destination differ. Review the project's study connection.",
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
        self.project_root, self.scope = Path(project.project_root), dict(scope)
        self.thread = None
        project_name = SubsectionHeaderLabel(project.name, self)
        project_name.setTextFormat(Qt.PlainText)
        project_name.setWordWrap(True)
        self.root_layout.addWidget(project_name)
        destination = QLabel(f"Experiment: {scope['experiment_id']} · version {scope['experiment_version']}\n"
                             f"OpenFPVS study: {scope['study_id']}", self)
        destination.setTextFormat(Qt.PlainText)
        destination.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        destination.setWordWrap(True)
        self.root_layout.addWidget(destination)
        contents = QLabel("Authorized study readers can see your lab’s ROI results, processing details, "
                          "electrode decisions and reviewed visits. Each lab’s results are listed separately.", self)
        contents.setWordWrap(True)
        self.root_layout.addWidget(contents)
        self.code = QLineEdit(self)
        self.code.setEchoMode(QLineEdit.Password)
        self.code.setAccessibleName("Lab code")
        code_label = QLabel("Lab code", self)
        code_label.setBuddy(self.code)
        self.connect_button = make_action_button("Connect to study", parent=self)
        connection = QHBoxLayout()
        connection.addWidget(code_label)
        connection.addWidget(self.code, 1)
        connection.addWidget(self.connect_button)
        self.root_layout.addLayout(connection)
        self.publish_button = make_action_button("Share current results", variant="primary", parent=self)
        self.retry_button = make_action_button("Retry pending upload", parent=self)
        self.connect_button.clicked.connect(self._connect)
        self.publish_button.clicked.connect(lambda: self._start(
            partial(publish_current, self.project_root, expected_scope=dict(self.scope))))
        self.retry_button.clicked.connect(lambda: self._start(
            partial(deliver_pending, self.project_root, expected_scope=dict(self.scope), retry=True)))
        self.status = QLabel("", self)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)
        self.close_button = make_action_button("Close", parent=self)
        self.close_button.clicked.connect(self.reject)
        self.root_layout.addWidget(make_action_row((self.retry_button, self.close_button, self.publish_button), parent=self))
        self.code.setFocus()

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
        for control in (self.code, self.connect_button, self.publish_button, self.retry_button, self.close_button):
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
