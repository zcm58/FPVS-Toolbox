from __future__ import annotations

import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from Main_App.gui.components import SectionCard
from Tools.Sensitivity_Analysis.gui import SensitivityAnalysisWindow


def _build_page(qtbot) -> SensitivityAnalysisWindow:
    page = SensitivityAnalysisWindow()
    qtbot.addWidget(page)
    page.resize(900, 700)
    page.show()
    qtbot.wait(30)
    return page


def test_defaults_and_paired_result_are_visible(qtbot) -> None:
    page = _build_page(qtbot)

    assert page.sample_size_spin.value() == 24
    assert page.power_spin.value() == pytest.approx(0.80)
    assert page.alpha_spin.value() == pytest.approx(0.05)
    assert page.design_stack.currentIndex() == page.PAIRED_TEST

    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.result_banner.text() == "Cohen's dz = 0.60"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert page.reporting_label.isVisibleTo(page)
    assert not page.equivalent_label.isVisibleTo(page)


def test_rm_anova_result_and_reset(qtbot) -> None:
    page = _build_page(qtbot)

    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.design_stack.currentIndex() == page.RM_ANOVA
    assert page.result_banner.text() == "Cohen's f = 0.30"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert page.equivalent_label.text() == "Equivalent eta-squared: 0.082"
    assert page.equivalent_label.isVisibleTo(page)

    qtbot.mouseClick(page.reset_button, Qt.LeftButton)

    assert page.analysis_combo.currentIndex() == page.PAIRED_TEST
    assert page.sample_size_spin.value() == 24
    assert page.result_banner.text() == "Set the assumptions and select Calculate."


def test_embedded_surface_has_no_horizontal_clipping(qtbot) -> None:
    page = _build_page(qtbot)
    scroll = page.findChild(QScrollArea, "sensitivity_scroll_area")
    inputs = page.findChild(SectionCard, "sensitivity_inputs_card")
    results = page.findChild(SectionCard, "sensitivity_results_card")

    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert scroll.widget().width() <= scroll.viewport().width()
    assert inputs is not None and inputs.width() >= 350
    assert results is not None and results.width() >= 350
    assert inputs.geometry().right() < scroll.widget().width()
    assert results.geometry().right() < scroll.widget().width()
    assert page.calculate_button.isVisibleTo(page)
    assert page.reset_button.isVisibleTo(page)
    assert page.disclaimer.isVisibleTo(page)
