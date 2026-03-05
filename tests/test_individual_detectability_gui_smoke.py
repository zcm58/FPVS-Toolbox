from __future__ import annotations

from pathlib import Path

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
if not hasattr(QtCore, "QThread"):
    pytest.skip("PySide6 QtCore missing QThread", allow_module_level=True)

from Tools.Individual_Detectability.main_window import (  # noqa: E402
    IndividualDetectabilityWindow,
)


def test_individual_detectability_window_smoke(qtbot, tmp_path: Path) -> None:
    window = IndividualDetectabilityWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)


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
