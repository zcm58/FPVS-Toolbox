from __future__ import annotations

from pathlib import Path

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
if not hasattr(QtCore, "QThread"):
    pytest.skip("PySide6 QtCore missing QThread", allow_module_level=True)

from Tools.Individual_Detectability.main_window import (  # noqa: E402
    IndividualDetectabilityWindow,
)
from Main_App.gui.components import PathPickerRow, SectionCard, StatusBanner  # noqa: E402


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
    }
    assert expected_cards <= set(cards)
    assert isinstance(window.input_root_row, PathPickerRow)
    assert window.input_root_row.objectName() == "individual_detectability_input_root_row"
    assert window.input_root_edit.placeholderText() == "Select Excel root folder"
    assert isinstance(window.output_root_row, PathPickerRow)
    assert window.output_root_row.objectName() == "individual_detectability_output_root_row"
    assert window.output_root_edit.placeholderText() == "Select output folder"
    assert isinstance(window.status_label, StatusBanner)
    assert window.status_label.objectName() == "individual_detectability_status"
    assert window.status_label.text() == "Ready."
    assert window.status_label.property("statusVariant") == "info"
    assert window.run_btn.property("variant") == "primary"
    assert window.toggle_log_btn.property("variant") == "tertiary"
    assert window.log_box.property("logSurface") is True

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
    participants = {
        window.participant_table.item(row, 1).text()
        for row in range(window.participant_table.rowCount())
    }
    assert participants == {"P1", "P11"}
