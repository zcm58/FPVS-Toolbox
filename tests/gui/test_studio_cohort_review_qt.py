from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from Main_App.gui.studio_cohort_review import StudioCohortReview
from Main_App.projects.studio_cohort import ReviewRow, StudyReview


def test_exception_first_and_full_roster_with_one_explicit_bulk_confirmation(qtbot, tmp_path):
    rows = []
    files = {}
    for number in range(1, 31):
        name = f"P{number:03}.bdf"
        files[name] = (128, number)
        visit = {"visit_id": str(number), "participant_number": str(number),
                 "participant_session_number": 1, "protocol_version_id": "version-one"}
        rows.append(ReviewRow(visit, {}, (name,), "ambiguous" if number == 30 else "clear", "new", ""))
    review = StudyReview(tuple(rows), files, {}, tmp_path, None, {})
    window = StudioCohortReview(SimpleNamespace(project_title="Example study"), review)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    assert "29 clear" in window.summary.text() and "1 ambiguous" in window.summary.text()
    assert window.table.currentRow() == 29
    assert window.table.isRowHidden(0) and not window.table.isRowHidden(29)
    qtbot.mouseClick(window.full, Qt.LeftButton)
    assert not window.table.isRowHidden(0)
    assert all(combo.currentData() is None for combo in window.decisions.values())
    qtbot.mouseClick(window.bulk, Qt.LeftButton)
    assert tuple(window.decisions["1"].currentData()) == ("matched", "P001.bdf")
    assert window.decisions["30"].currentData() is None
    window._apply()
    assert window.isVisible()
    choice = window.decisions["30"]
    choice.setCurrentIndex(choice.findText("Awaiting EEG"))
    window._apply()
    assert window.result() == QDialog.Accepted


def test_mixing_versions_names_affected_visits_and_risk_at_each_confirmation(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    versions = ["alpha-version", "beta-version"]
    rows = []
    files = {}
    for num, version in enumerate(versions, 1):
        name = f"P{num}.bdf"
        visit = {"visit_id": str(num), "participant_number": f"P{num}", "participant_session_number": 1,
                 "protocol_version_id": version, "setup_id": "setup"}
        rows.append(ReviewRow(visit, {}, (name,), "clear", "new", ""))
        files[name] = (128, num)
    study = SimpleNamespace(project_title="Mixed experiment", provenance={
        "setups": {"setup": {"protocol": {"base_hz": 6, "oddball_every_n": 5}}}})
    dialog = StudioCohortReview(study, StudyReview(tuple(rows), files, {}, tmp_path, None, {}))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.selected_versions() == [versions[0]]
    qtbot.mouseClick(dialog.bulk, Qt.LeftButton)
    dialog.versions.item(1).setCheckState(Qt.Checked)
    prompts = []
    def answer(_dialog, title, message, *_):
        prompts.append((title, message))
        return QMessageBox.No if len(prompts) == 2 else QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, "question", answer)
    monkeypatch.setattr(QMessageBox, "warning", answer)
    dialog._apply()
    assert dialog.isVisible() and not dialog.warnings
    assert len(prompts) == 2 and prompts[0][0] != prompts[1][0]
    for _, message in prompts:
        assert "noncomparable" in message and "P1 visit 1" in message and "P2 visit 1" in message
    dialog._apply()
    assert dialog.result() == QDialog.Accepted and dialog.warnings == (True, True)


def test_share_dialog_only_transfers_after_click_and_holds_close(qtbot, tmp_path, monkeypatch):
    from threading import Event
    from Main_App.gui import reporting_dialog

    started, finish = Event(), Event()
    def deliver(_root):
        started.set()
        finish.wait(timeout=5)
        return "delivered"

    monkeypatch.setattr(reporting_dialog, "publish_current", deliver)
    dialog = reporting_dialog.ResultsSharingDialog(
        SimpleNamespace(project_root=tmp_path), {"study_id":"synthetic", "experiment_id":"faces", "experiment_version":"1.0"}, None
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert not started.is_set()
    qtbot.mouseClick(dialog.publish_button, Qt.LeftButton)
    try:
        qtbot.waitUntil(started.is_set)
        dialog.reject()
        assert dialog.isVisible() and not dialog.retry_button.isEnabled()
    finally:
        finish.set()
    qtbot.waitUntil(lambda: dialog.thread is None)
    assert dialog.retry_button.isEnabled() and "accepted" in dialog.status.text()
    dialog.reject()
    assert not dialog.isVisible()
