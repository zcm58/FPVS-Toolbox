"""CI-only smoke coverage for the bounded multi-condition image editor."""

import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from Main_App.gui.components import SectionCard
from Main_App.gui.theme import apply_fpvs_theme
from Tools.Sequence_Figure import gui


@pytest.fixture
def page(tmp_path, qtbot, qapp):
    apply_fpvs_theme(qapp)
    window = gui.SequenceFigureWindow(project_root=str(tmp_path))
    qtbot.addWidget(window)
    # Approximate the embedded area inside the supported 1280x900 main shell.
    window.resize(1000, 760)
    window.show()
    qtbot.waitExposed(window)
    return window


@pytest.mark.parametrize("count", [1, 3, 4])
def test_condition_tabs_fit_embedded_workspace(page, qtbot, count) -> None:
    assert page.condition_count_spin.minimum() == 1
    assert page.condition_count_spin.maximum() == 4
    assert page.condition_count_spin.value() == 3
    page.condition_count_spin.setValue(count)
    assert page.condition_tabs.count() == count
    assert not page.findChildren(QScrollArea)
    assert page.minimumSizeHint().width() <= 1000
    assert page.minimumSizeHint().height() <= 760
    assert all(not card.findChildren(SectionCard) for card in page.findChildren(SectionCard))
    assert page.sequence_figure_info_btn.isVisibleTo(page)

    for condition in range(count):
        page.condition_tabs.setCurrentIndex(condition)
        qtbot.wait(10)
        for row in page.image_rows[condition]:
            assert row.isVisibleTo(page)
            assert page.rect().contains(row.mapTo(page, row.rect().topLeft()))
            assert page.rect().contains(row.mapTo(page, row.rect().bottomRight()))
    assert page.export_btn.isVisibleTo(page)
    assert page.rect().contains(page.export_btn.mapTo(page, page.export_btn.rect().bottomRight()))


def test_active_condition_payload_and_hidden_state_are_preserved(page, tmp_path) -> None:
    page.condition_count_spin.setValue(4)
    for condition in range(4):
        page._image_paths[condition] = [
            str(tmp_path / f"condition-{condition}-slot-{slot}.png") for slot in range(5)
        ]
    page.condition_label_edits[0].setText("Faces")
    page.condition_label_edits[3].setText("Scenes")
    page.grayscale_safe_check.setChecked(True)
    page.transparent_pdf_check.setChecked(True)
    page._set_output_folder(tmp_path)
    page.condition_count_spin.setValue(2)

    spec = page._build_spec()

    assert spec is not None
    assert len(spec.image_paths) == 2
    assert spec.condition_labels == ("Faces", "Condition 2")
    assert spec.grayscale_safe and spec.transparent_pdf
    assert spec.output_dir == tmp_path
    assert spec.png_dpi == 600
    assert spec.export_svg
    page.condition_count_spin.setValue(4)
    assert page.condition_label_edits[3].text() == "Scenes"
    assert page.condition_tabs.tabText(3) == "Scenes"
    assert len(page._build_spec().image_paths) == 4


def test_image_picker_targets_condition_and_cancel_preserves_selection(
    page, tmp_path, qtbot, monkeypatch,
) -> None:
    image_path = tmp_path / "stimulus.png"
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(image_path), ""))
    page.condition_tabs.setCurrentIndex(1)
    qtbot.mouseClick(page.image_rows[1][4].button, Qt.LeftButton)
    assert page._image_paths[1][4] == str(image_path)
    assert page.image_rows[1][4].line_edit.text() == str(image_path)
    assert page._image_paths[0][4] == ""
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    qtbot.mouseClick(page.image_rows[1][4].button, Qt.LeftButton)
    assert page._image_paths[1][4] == str(image_path)


def test_project_default_and_cancelled_output_picker_preserve_folder(
    tmp_path, qtbot, monkeypatch,
) -> None:
    figures = tmp_path / "Figures"
    figures.mkdir()
    page = gui.SequenceFigureWindow(project_root=str(tmp_path))
    qtbot.addWidget(page)
    monkeypatch.setattr(gui.QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")
    page._select_output_folder()
    assert Path(page._output_folder) == figures
    assert page.output_row.line_edit.text() == str(figures)


def test_missing_images_only_consider_active_conditions(page, tmp_path, monkeypatch) -> None:
    errors = []
    monkeypatch.setattr(gui, "show_error", lambda _parent, title, message: errors.append((title, message)))
    page.condition_count_spin.setValue(1)
    page._set_output_folder(tmp_path)
    assert page._build_spec() is None
    assert "condition 1, slot 5" in errors[-1][1]
    assert "condition 2" not in errors[-1][1]
    page._image_paths[0] = [str(tmp_path / f"slot-{slot}.png") for slot in range(5)]
    assert page._build_spec() is not None
