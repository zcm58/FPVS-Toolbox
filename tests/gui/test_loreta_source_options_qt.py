from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from Tools.LORETA_Visualizer.gui import SourceMapOptionsDialog
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
    SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
)


def test_loreta_source_options_exposes_l2_orientation_modes(qtbot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = SourceMapOptionsDialog(
        parent,
        include_flagged_subjects=False,
        zscore_display_threshold=1.64,
        use_cluster_mask=True,
        source_map_visible=True,
        transparent_spin_enabled=False,
        source_orientation_mode=SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
        project_available=True,
        export_busy=False,
    )
    qtbot.addWidget(dialog)

    combo = dialog.source_orientation_combo
    assert combo.currentData() == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    assert combo.itemText(0) == "Cortical normal (Hauk-style; recommended)"
    assert combo.itemData(0) == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    assert combo.itemText(1) == "Legacy MNE pooled orientation (reproduce older maps)"
    assert combo.itemData(1) == SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM
    assert combo.isEnabled()
    assert "next L2-MNE source-map rebuild" in combo.toolTip()

    note = dialog.findChild(QLabel, "loreta_l2_source_orientation_note")
    assert note is not None
    assert "L2-MNE cortical maps only" in note.text()
    assert "eLORETA volume maps always use the corrected vector norm" in note.text()
