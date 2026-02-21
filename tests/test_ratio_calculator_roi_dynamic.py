from __future__ import annotations

import importlib.util

import pytest


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


def _table_rows(window) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row_idx in range(window.roi_table.rowCount()):
        roi_item = window.roi_table.item(row_idx, 0)
        elec_item = window.roi_table.item(row_idx, 1)
        rows.append((roi_item.text() if roi_item else "", elec_item.text() if elec_item else ""))
    return rows


def test_ratio_calculator_uses_runtime_roi_settings_and_refreshes(qtbot):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtWidgets import QApplication

    from Tools.Ratio_Calculator.gui import RatioCalculatorWindow

    QApplication.instance() or QApplication([])
    roi_state = {
        "Occipital": ["O1", "O2", "Oz"],
        "Temporal": ["P7", "P8"],
    }

    def fake_loader() -> dict[str, list[str]]:
        return {name: list(chans) for name, chans in roi_state.items()}

    window = RatioCalculatorWindow(roi_loader=fake_loader)
    qtbot.addWidget(window)
    window.show()

    assert _table_rows(window) == [
        ("Occipital", "O1, O2, Oz"),
        ("Temporal", "P7, P8"),
    ]

    roi_state.clear()
    roi_state["Parietal"] = ["P3", "P4"]
    window.refresh_btn.click()

    assert _table_rows(window) == [("Parietal", "P3, P4")]

    roi_state.clear()
    roi_state["Central"] = ["C3", "C4"]
    window._sync_rois_if_changed()
    assert _table_rows(window) == [("Central", "C3, C4")]
