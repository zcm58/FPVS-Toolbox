from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from Tools.LORETA_Visualizer.gui import (
    DISPLAY_MODE_CORTICAL_SURFACE,
    DISPLAY_MODE_MRI_SLICES,
    DISPLAY_MODE_SPLIT_HEMISPHERE,
    DISPLAY_MODE_TRANSPARENT_MESH,
    LoretaVisualizerWindow,
    SourceMapOptionsDialog,
)
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
    SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
)
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_VOLUME_POINTS,
    make_source_payload,
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


def test_loreta_display_selector_separates_cortical_and_volume_views(qtbot) -> None:
    combo = QComboBox()
    qtbot.addWidget(combo)
    host = SimpleNamespace(
        display_mode_combo=combo,
        _display_mode=DISPLAY_MODE_TRANSPARENT_MESH,
    )
    volume_payload = make_source_payload(
        points=np.asarray([[0.0, -0.7, -0.4]], dtype=float),
        values=np.asarray([1.7], dtype=float),
        label="eLORETA volume",
        kind=SOURCE_KIND_VOLUME_POINTS,
        source_model="eloreta_volume_hauk_source_psd_vector_norm_v1_mean",
        normalize_values=False,
    )

    LoretaVisualizerWindow._sync_display_mode_combo_options(host, volume_payload)

    assert [combo.itemData(index) for index in range(combo.count())] == [
        DISPLAY_MODE_TRANSPARENT_MESH,
        DISPLAY_MODE_MRI_SLICES,
    ]
    assert combo.itemText(0) == "3D volume overlay"
    assert combo.itemText(1) == "MRI slices (recommended for anatomy)"
    assert "display-only interpolation" in combo.toolTip()
    assert "not the source boundary" in combo.toolTip()

    host._display_mode = DISPLAY_MODE_SPLIT_HEMISPHERE
    surface_payload = make_source_payload(
        points=np.asarray(
            [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.0, 0.1, 0.0]],
            dtype=float,
        ),
        values=np.asarray([1.0, 2.0, 3.0], dtype=float),
        label="Hauk L2-MNE",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_hauk_source_psd_cortical_normal_v1_mean",
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        normalize_values=False,
    )

    LoretaVisualizerWindow._sync_display_mode_combo_options(host, surface_payload)

    assert [combo.itemData(index) for index in range(combo.count())] == [
        DISPLAY_MODE_SPLIT_HEMISPHERE,
        DISPLAY_MODE_CORTICAL_SURFACE,
    ]
    assert combo.itemText(0) == "Cortical surface — split hemispheres"
    assert combo.itemText(1) == "Cortical surface — combined"
    assert "Hauk-style L2-MNE values" in combo.toolTip()
