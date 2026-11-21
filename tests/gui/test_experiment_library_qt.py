"""Registered native-library coverage. Execute only in an approved Qt environment."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from Main_App.gui.experiment_library_page import ExperimentLibraryPage
from Main_App.gui.components import SectionCard
from Main_App.gui.theme import set_appearance_mode
from Main_App.projects.experiment_library import PublicDataset


@pytest.fixture
def dataset():
    return PublicDataset(
        item_id="simulated-fpvs-oddball-demo", version="1.0.0",
        title="Simulated FPVS-Oddball Demo",
        description="Simulated FPVS-oddball experiment. Download this to test FPVS Toolbox on your PC.",
        filename="simulated-fpvs-oddball-demo-1.0.0.zip",
        size_bytes=251090004, uncompressed_size_bytes=436267828,
        file_count=44, sha256="a" * 64, min_toolbox_version="3.0.0",
        project_format="fpvs-toolbox-project-v1", participant_count=32,
        condition_count=2, sample_rate_hz=256,
    )


@pytest.mark.parametrize("appearance", ["Light", "Dark"])
def test_library_states_preserve_content_and_actions_fit(qtbot, qapp, dataset, appearance):
    set_appearance_mode(qapp, appearance)
    page = ExperimentLibraryPage()
    qtbot.addWidget(page)
    page.resize(900, 470)
    page.set_datasets((dataset,))
    page.show_status("Download from OpenFPVS", "251.1 MB download")
    page.primary_button.setText("Download and open")
    page.show()
    qtbot.waitExposed(page)
    assert not page.findChildren(SectionCard)
    assert page.dataset_title.text() == dataset.title
    assert page.dataset_description.text() == dataset.description
    assert not page.preview.pixmap().isNull()
    body_geometry = page.dataset_body.geometry()
    for title in ("Downloading dataset…", "Verifying experiment files…", "Setting up project…"):
        page.show_status(title, "Preparing experiment files.", busy=True, cancelable=True)
        qtbot.wait(20)
        assert page.dataset_body.geometry() == body_geometry
        assert page.cancel_button.isVisible()
        assert not page.primary_button.isVisible()
        assert page.rect().contains(page.cancel_button.geometry())
    page.show_canceling()
    assert not page.cancel_button.isEnabled()
    page.show_status("Installed", "Ready to open on this computer.")
    page.primary_button.setText("Open project")
    assert page.primary_button.isVisible()
    assert not page.cancel_button.isVisible()


def test_cancel_emits_without_replacing_the_visible_dataset(qtbot, dataset):
    page = ExperimentLibraryPage()
    qtbot.addWidget(page)
    page.set_datasets((dataset,))
    page.show_status("Downloading dataset…", busy=True, cancelable=True)
    page.show()
    with qtbot.waitSignal(page.cancel_requested):
        qtbot.mouseClick(page.cancel_button, Qt.LeftButton)
    assert page.selected_dataset is dataset
