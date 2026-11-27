from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
if not hasattr(QtCore, "QThread"):
    pytest.skip("PySide6 QtCore missing QThread", allow_module_level=True)

from Tools.Individual_Detectability.main_window import (  # noqa: E402
    IndividualDetectabilityWindow,
)
from Main_App.gui.style_tokens import (  # noqa: E402
    COMPACT_SECTION_MAX_HEIGHT,
    SECTION_HEADER_CONTENT_GAP,
)
from Main_App.gui.components import PathPickerRow, SectionCard, StatusBanner  # noqa: E402
from Main_App.gui.theme import apply_fpvs_theme  # noqa: E402


def test_individual_detectability_window_smoke(qtbot, tmp_path: Path, monkeypatch) -> None:
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    cards = {card.objectName(): card for card in window.findChildren(SectionCard)}
    expected_cards = {
        "individual_detectability_input",
        "individual_detectability_conditions",
        "individual_detectability_output",
        "individual_detectability_participants",
        "individual_detectability_run",
        "individual_detectability_harmonics",
        "individual_detectability_snr",
        "individual_detectability_layout",
        "individual_detectability_summary",
    }
    assert expected_cards <= set(cards)
    assert isinstance(window.input_root_row, PathPickerRow)
    assert window.basic_tab.layout() is window.basic_grid
    assert window.basic_grid.getItemPosition(
        window.basic_grid.indexOf(cards["individual_detectability_input"])
    ) == (0, 0, 1, 2)
    assert window.basic_grid.getItemPosition(
        window.basic_grid.indexOf(cards["individual_detectability_conditions"])
    ) == (1, 0, 1, 1)
    assert window.basic_grid.getItemPosition(
        window.basic_grid.indexOf(cards["individual_detectability_participants"])
    ) == (1, 1, 1, 1)
    assert window.basic_grid.getItemPosition(
        window.basic_grid.indexOf(cards["individual_detectability_output"])
    ) == (2, 0, 1, 1)
    assert window.basic_grid.getItemPosition(
        window.basic_grid.indexOf(cards["individual_detectability_run"])
    ) == (2, 1, 1, 1)
    assert window.basic_grid.rowStretch(1) > window.basic_grid.rowStretch(2)
    assert window.basic_grid.columnStretch(0) == window.basic_grid.columnStretch(1)
    assert window.input_root_row.objectName() == "individual_detectability_input_root_row"
    assert window.input_root_edit.placeholderText() == "Select Excel root folder"
    assert isinstance(window.output_root_row, PathPickerRow)
    assert window.output_root_row.objectName() == "individual_detectability_output_root_row"
    assert window.output_root_edit.placeholderText() == "Select output folder"
    assert isinstance(window.status_label, StatusBanner)
    assert window.status_label.objectName() == "individual_detectability_status"
    assert window.status_label.text() == "Choose the folder containing your processed Excel workbooks."
    assert not window.run_btn.isEnabled()
    assert window.status_label.property("statusVariant") == "info"
    assert window.use_custom_harmonics_check.isChecked() is False
    assert window.harmonics_edit.isEnabled() is False
    assert window.custom_harmonics_warning.isHidden() is True
    assert "FPVS Toolbox significant harmonics" in window.summary_box.toPlainText()
    assert window.run_btn.property("variant") == "primary"
    assert window.view_generation_log_btn.property("variant") == "tertiary"
    assert window.log_box.property("logSurface") is True
    assert not hasattr(window, "output_table")
    for card in cards.values():
        assert card.shell_layout.spacing() == SECTION_HEADER_CONTENT_GAP
        assert card.content_layout.spacing() == SECTION_HEADER_CONTENT_GAP
        header_item = card.shell_layout.itemAt(card.shell_layout.indexOf(card.header))
        assert header_item.alignment() & QtCore.Qt.AlignmentFlag.AlignTop
    assert cards["individual_detectability_output"].maximumHeight() == (
        COMPACT_SECTION_MAX_HEIGHT
    )
    assert cards["individual_detectability_conditions"].sizePolicy().verticalPolicy() == (
        cards["individual_detectability_participants"].sizePolicy().verticalPolicy()
    )
    assert window.summary_box.minimumHeight() >= 150

    monkeypatch.setattr(
        "Tools.Individual_Detectability.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )
    window._browse_input_root()
    assert window.input_root_edit.text() == ""
    assert window._last_dir is None

    window._browse_output_root()
    assert window.output_root_edit.text() == ""
    assert window._last_dir is None

    window._append_log("Checking retained recordings")
    window.view_generation_log_btn.click()
    assert window.log_dialog.isVisible()
    assert window.log_dialog.isAncestorOf(window.log_box)
    window.log_dialog.reject()
    window._append_log("Figure generation complete")
    window.view_generation_log_btn.click()
    assert window.log_box.toPlainText().splitlines() == [
        "Checking retained recordings",
        "Figure generation complete",
    ]
    window.log_dialog.reject()


def test_individual_detectability_advanced_fits_embedded_workspace(
    qtbot,
    qapp,
    tmp_path: Path,
) -> None:
    apply_fpvs_theme(qapp)
    window = IndividualDetectabilityWindow(project_root=str(tmp_path), embedded=True)
    qtbot.addWidget(window)
    available_size = QtCore.QSize(1156, 725)
    window.resize(available_size)
    window.show()
    qtbot.waitExposed(window)

    window.tabs.setCurrentWidget(window.advanced_tab)
    window.use_custom_harmonics_check.setChecked(True)
    qapp.processEvents()

    assert window.size() == available_size
    for control in (
        window.harmonics_edit,
        window.fdr_alpha_spin,
        window.custom_harmonics_warning,
        window.show_mid_xtick_check,
        window.letter_portrait_check,
        window.summary_box,
    ):
        assert control.isVisibleTo(window)
        assert window.rect().contains(control.mapTo(window, control.rect().bottomRight()))


def test_individual_detectability_scan_populates_participants_with_missingness(
    qtbot,
    tmp_path: Path,
) -> None:
    excel_root = tmp_path / "1 - Excel Data Files"
    angry = excel_root / "AngryNeutral"
    happy = excel_root / "HappyNeutral"
    angry.mkdir(parents=True)
    happy.mkdir(parents=True)
    (angry / "P1_Angry Neutral_Results.xlsx").write_text("data")
    (angry / "P11_Angry Neutral_Results.xlsx").write_text("data")
    (happy / "P11_Happy Neutral_Results.xlsx").write_text("data")

    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)

    window._refresh_conditions()

    assert window.conditions_list.count() == 2
    assert window.participant_table.rowCount() == 2
    assert window.status_label.text() == "Choose an output folder."
    assert not window.run_btn.isEnabled()
    participants = {
        window.participant_table.item(row, 1).text()
        for row in range(window.participant_table.rowCount())
    }
    assert participants == {"P1", "P11"}
    assert window._collect_output_stems() == {
        "AngryNeutral": "AngryNeutral_individual_detectability_grid",
        "HappyNeutral": "HappyNeutral_individual_detectability_grid",
    }
    window.use_custom_harmonics_check.setChecked(True)
    assert window.harmonics_edit.isEnabled() is True
    assert window.custom_harmonics_warning.isHidden() is False
    assert window._collect_output_stems() == {
        "AngryNeutral": "AngryNeutral_individual_detectability_grid_custom_harmonics",
        "HappyNeutral": "HappyNeutral_individual_detectability_grid_custom_harmonics",
    }


@pytest.mark.parametrize("second_group", [False, True])
def test_indexed_native_group_results_populate_page_and_preserve_selection(qtbot, tmp_path, second_group):
    participants = [f"P{i}" for i in range(1, 32)] + ["E2P2final"]
    groups = ["Simulated", "Comparison"] if second_group else ["Simulated"]
    memberships = {pid: groups[i % len(groups)] for i, pid in enumerate(participants)}
    excel = tmp_path / "Results" / "Processed"
    for condition in ("Green", "Red"):
        for pid, group in memberships.items():
            folder = excel / condition / group
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{pid}_{condition}_Results.fpvs").touch()
            (folder / f"{pid}_{condition}_Results.xlsx").touch()
    manifest = {
        "results_folder": "Results",
        "subfolders": {"excel": "Processed"},
        "groups": {
            group.lower(): {"label": group, "folder_name": group, "raw_input_folder": f"Input/{group}"}
            for group in groups
        },
        "participants": {pid: {"group_id": group.lower()} for pid, group in memberships.items()},
    }
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    window = IndividualDetectabilityWindow(project_root=str(tmp_path), embedded=True)
    qtbot.addWidget(window)
    assert Path(window.input_root_edit.text()) == excel
    assert Path(window.output_root_edit.text()) == tmp_path / "Individual Detectability"
    assert not window.output_root_open_btn.isEnabled()
    qtbot.waitUntil(lambda: window._scan_job is None)
    assert window.run_btn.isEnabled()
    assert window.conditions_list.count() == 2 * len(groups)
    assert sum(len(c.files) for c in window._conditions) == 64
    assert {window.participant_table.item(row, 1).text() for row in range(32)} == set(participants)
    for cond in window._conditions:
        assert set(cond.participant_ids) == {pid for pid, group in memberships.items() if group == cond.group.label}
        assert all(path.suffix == ".fpvs" and path.parent.name == cond.group.folder_name for path in cond.files)
    window.conditions_list.item(0).setCheckState(QtCore.Qt.Unchecked)
    window.refresh_btn.click()
    qtbot.waitUntil(lambda: window._scan_job is None)
    assert window._selected_conditions() == window._conditions[1:]


def test_exclusions_and_condition_choices_survive_refresh_within_one_folder(qtbot, tmp_path):
    roots = [tmp_path / "First", tmp_path / "Second"]
    for root in roots:
        for condition, pid in (("A", "P1"), ("B", "P2")):
            folder = root / condition
            folder.mkdir(parents=True)
            (folder / f"{pid}_{condition}_Results.xlsx").touch()
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    window.input_root_edit.setText(str(roots[0]))
    window.refresh_btn.click()

    window.participant_table.item(0, 0).setCheckState(QtCore.Qt.Checked)
    window.conditions_list.item(0).setCheckState(QtCore.Qt.Unchecked)
    window.refresh_btn.click()
    assert [condition.name for condition in window._selected_conditions()] == ["B"]
    assert window._excluded_participants() == set()
    window.select_all_btn.click()
    assert window._excluded_participants() == {"P1"}
    window.refresh_btn.click()
    assert window._excluded_participants() == {"P1"}
    window.conditions_list.item(0).setCheckState(QtCore.Qt.Unchecked)

    window.input_root_edit.setText(str(roots[1]))
    window.refresh_btn.click()
    assert [condition.name for condition in window._selected_conditions()] == ["A", "B"]
    assert window._excluded_participants() == set()


def test_custom_harmonics_rejects_invalid_entries_without_using_a_partial_list(qtbot, tmp_path):
    excel = tmp_path / "1 - Excel Data Files" / "A"
    excel.mkdir(parents=True)
    (excel / "P1_A_Results.xlsx").touch()
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    window.output_root_edit.setText(str(tmp_path))
    window.use_custom_harmonics_check.setChecked(True)
    for text in ("", "1.2, typo", "1.2, nan", "1.2, inf", "0", "-1", "1.2, 1.20"):
        window.harmonics_edit.setText(text)
        assert not window.run_btn.isEnabled()
        assert "Check Advanced settings" in window.status_label.text()
    window.harmonics_edit.setText("1.2, 2.4")
    assert window.run_btn.isEnabled()
    assert window._collect_settings().oddball_harmonics_hz == [1.2, 2.4]
    window.harmonics_edit.setText("typo")
    window.use_custom_harmonics_check.setChecked(False)
    assert window.run_btn.isEnabled()


def test_switch_project_keeps_running_export_until_finished(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QStackedWidget

    excel = tmp_path / "1 - Excel Data Files" / "A"
    excel.mkdir(parents=True)
    (excel / "P1_A_Results.xlsx").touch()
    started, finish = Event(), Event()
    opened = []

    def export(request, **_callbacks):
        started.set()
        if not finish.wait(5):
            raise AssertionError("test export did not receive its completion signal")
        return request.output_root

    monkeypatch.setattr("Tools.Individual_Detectability.worker.run_detectability_export", export)
    monkeypatch.setattr(
        "Tools.Individual_Detectability.main_window.QDesktopServices.openUrl", opened.append
    )
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    window = IndividualDetectabilityWindow(stack, str(tmp_path), embedded=True)
    stack.addWidget(window)
    window.output_root_edit.setText(str(tmp_path))
    window._update_run_state()
    window.run_btn.click()
    try:
        qtbot.waitUntil(started.is_set)
        stack.removeWidget(window)
        window.retire_from_workspace()
        assert window._thread in stack.findChildren(QtCore.QThread)
        assert window._thread.isRunning()
    finally:
        finish.set()
    with qtbot.waitSignal(window.destroyed):
        pass
    assert not opened


def test_excluded_selection_and_qc_empty_export_do_not_open_previous_results(qtbot, tmp_path, monkeypatch):
    from dataclasses import replace

    condition = tmp_path / "1 - Excel Data Files" / "Faces"
    condition.mkdir(parents=True)
    (condition / "P1_Faces_Results.xlsx").touch()
    output = tmp_path / "previous"
    output.mkdir()
    (output / "figure.pdf").write_bytes(b"previous run")
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    window.output_root_edit.setText(str(output))
    window.participant_table.item(0, 0).setCheckState(QtCore.Qt.Checked)
    assert not window.run_btn.isEnabled()
    assert "Include at least one participant" in window.status_label.text()
    window.participant_table.item(0, 0).setCheckState(QtCore.Qt.Unchecked)
    assert window.run_btn.isEnabled()
    monkeypatch.setattr(
        "Tools.Individual_Detectability.export_run._require_current_project_inputs",
        lambda request: (replace(request, conditions=[]), {}),
    )
    opened = []
    monkeypatch.setattr("Tools.Individual_Detectability.main_window.QDesktopServices.openUrl", opened.append)
    window.run_btn.click()
    qtbot.waitUntil(lambda: window._thread is None)
    assert "No figures were generated" in window.status_label.text()
    assert window.status_label.property("statusVariant") == "warning"
    assert not opened
    assert (output / "figure.pdf").read_bytes() == b"previous run"


def test_malformed_managed_results_path_shows_recoverable_error(qtbot, tmp_path):
    manifest = tmp_path / "project.json"
    manifest.write_text(json.dumps({"results_folder": "bad\x00folder"}), encoding="utf-8")
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    assert "Check project.json and refresh" in window.status_label.text()
    assert not window.run_btn.isEnabled()

    manifest.write_text("{}", encoding="utf-8")
    (tmp_path / "1 - Excel Data Files").mkdir()
    window.refresh_btn.click()
    qtbot.waitUntil(lambda: window._scan_job is None)
    assert Path(window.input_root_edit.text()) == tmp_path / "1 - Excel Data Files"
    assert "Check project.json" not in window.status_label.text()
