from __future__ import annotations

import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from Main_App.gui.components import SectionCard, ToolInfoDialog
from Tools.Sensitivity_Analysis.gui import SensitivityAnalysisWindow
from Tools.Sensitivity_Analysis.tool_info import SENSITIVITY_ANALYSIS_TOOL_INFO


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
    assert page.result_banner.metric_label.text() == "COHEN'S DZ"
    assert page.result_banner.value_label.text() == "0.60"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert page.reporting_label.isVisibleTo(page)
    assert not page.equivalent_label.isVisibleTo(page)


def test_rm_anova_result_and_reset(qtbot) -> None:
    page = _build_page(qtbot)

    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    assert page.conditions_spin.value() == 2
    assert page.rois_spin.value() == 1
    assert page.effect_target_combo.currentIndex() == page.CONDITION_EFFECT
    assert page.measurements_spin.value() == 2
    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.design_stack.currentIndex() == page.RM_ANOVA
    assert page.result_banner.text() == "Cohen's f = 0.30"
    assert page.result_banner.metric_label.text() == "COHEN'S F"
    assert page.result_banner.value_label.text() == "0.30"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert page.equivalent_label.text() == "Equivalent eta-squared: 0.082"
    assert page.equivalent_label.isVisibleTo(page)

    qtbot.mouseClick(page.reset_button, Qt.LeftButton)

    assert page.analysis_combo.currentIndex() == page.PAIRED_TEST
    assert page.sample_size_spin.value() == 24
    assert page.result_banner.text() == "Set the assumptions and select Calculate."


def test_fpvs_design_inputs_derive_repeated_measurements(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    page.conditions_spin.setValue(4)
    page.rois_spin.setValue(3)

    page.effect_target_combo.setCurrentIndex(page.CONDITION_EFFECT)
    assert page.measurements_spin.value() == 4
    assert "ROIs are assumed averaged" in page.measurement_explanation.text()

    page.effect_target_combo.setCurrentIndex(page.ROI_EFFECT)
    assert page.measurements_spin.value() == 3
    assert "Conditions are assumed averaged" in page.measurement_explanation.text()

    page.effect_target_combo.setCurrentIndex(page.OMNIBUS_CELLS)
    assert page.measurements_spin.value() == 12
    assert "not interaction power" in page.measurement_explanation.text()


def test_info_dialog_explains_repeated_measurement_derivation(qtbot) -> None:
    page = _build_page(qtbot)
    dialog = ToolInfoDialog(SENSITIVITY_ANALYSIS_TOOL_INFO, page)
    qtbot.addWidget(dialog)
    text = dialog.browser.toPlainText()

    assert page.tool_info_button.toolTip() == "About Sensitivity Analysis"
    assert "Sample size (N) is the number of participants" in text
    assert "repeated measurements = conditions × ROIs" in text
    assert "does not specifically estimate power" in text


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
    assert inputs.height() < scroll.viewport().height()
    assert results.height() < scroll.viewport().height()
    assert page.calculate_button.isVisibleTo(page)
    assert page.reset_button.isVisibleTo(page)
    assert page.disclaimer.isVisibleTo(page)
