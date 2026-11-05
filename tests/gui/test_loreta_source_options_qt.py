from __future__ import annotations

from types import SimpleNamespace
import sys

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


def test_scientific_color_range_keeps_small_values_through_edit_and_step(qtbot):
    from PySide6.QtCore import Qt
    from Tools.LORETA_Visualizer.scalar_range_control import ScientificDoubleSpinBox

    spin = ScientificDoubleSpinBox()
    qtbot.addWidget(spin)
    spin.show()
    spin.setValue(2e-9)
    assert spin.value() == 2e-9
    assert spin.text() == "2e-09"
    spin.lineEdit().selectAll()
    qtbot.keyClicks(spin.lineEdit(), "-3.5e-9")
    qtbot.keyClick(spin.lineEdit(), Qt.Key_Return)
    assert spin.value() == -3.5e-9
    assert spin.text() == "-3.5e-09"
    before = spin.value()
    spin.stepUp()
    assert 0.0 < spin.value() - before < 1e-9
    spin.setValue(1.64)
    assert spin.text() == "1.64"
    assert spin.close()


def test_scientific_color_range_rejects_invalid_input_without_erasing_value(qtbot):
    from PySide6.QtGui import QValidator
    from Tools.LORETA_Visualizer.scalar_range_control import ScientificDoubleSpinBox

    spin = ScientificDoubleSpinBox()
    qtbot.addWidget(spin)
    spin.setValue(-2e-9)
    for text in ("nan", "inf", "1e999", "1e-999", "2e7"):
        assert spin.validate(text, len(text))[0] == QValidator.State.Invalid
        assert spin.fixup(text) == "-2e-09"
    assert spin.validate("1e-", 3)[0] == QValidator.State.Intermediate
    assert spin.value() == -2e-9
    spin.setValue(spin.maximum())
    spin.stepUp()
    assert spin.value() == spin.maximum()
    assert spin.close()


def test_group_comparison_toggle_preserves_single_view_controls(qtbot, monkeypatch) -> None:
    from pathlib import Path
    from Tools.LORETA_Visualizer import gui
    from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry

    class DisplayDouble(QWidget):
        def __init__(self, parent=None, **_kwargs):
            super().__init__(parent)

        def set_display_mode(self, *_args, **_kwargs):
            pass

        def set_cortical_paint_cluster_mask_enabled(self, *_args, **_kwargs):
            pass

        def set_transparent_spin_enabled(self, *_args, **_kwargs):
            pass

        def set_activation_payload(self, *_args, **_kwargs):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(gui, "BrainRendererWidget", DisplayDouble)
    monkeypatch.setattr(LoretaVisualizerWindow, "_start_fsaverage_load", lambda *_a, **_k: None)
    monkeypatch.setattr(LoretaVisualizerWindow, "_refresh_current_activation", lambda _self: None)
    window = LoretaVisualizerWindow()
    qtbot.addWidget(window)
    entries = tuple(
        PreparedSourceManifestEntry(
            f"{group}_words_mean", f"{group} words raw mean z-score", Path(f"{group}.json"),
            {"producer_method": "l2_mne_hauk_source_psd_cortical_normal_v1_mean", "participant_zscore_aggregation": "mean"},
        ) for group in ("a", "b")
    )
    window._replace_manifest_conditions(entries)
    window._select_first_condition_if_needed()
    window.show()
    assert window.compare_groups_check.isEnabled()

    window.compare_groups_check.click()
    assert window._group_comparison_enabled
    assert window.activation_scale_combo.itemText(0) == "Scale: both groups"
    assert not window.export_figures_btn.isEnabled()
    assert "not a between-group statistical test" in window.compare_groups_check.toolTip()

    window.compare_groups_check.click()
    assert not window._group_comparison_enabled
    assert window.activation_scale_combo.itemText(0) == "Scale: current map"
    assert window.export_figures_btn.isEnabled()
    assert window.condition_combo.count() == 2

    window._display_mode = DISPLAY_MODE_MRI_SLICES
    window._sync_source_map_selectors_enabled()
    assert not window.compare_groups_check.isEnabled()
    assert "3D volume overlay" in window.compare_groups_check.toolTip()
    assert window.close()


def test_metric_and_canonical_comparison_controls_preserve_source_selection(qtbot, monkeypatch, tmp_path):
    from Tools.LORETA_Visualizer import gui
    from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry

    class DisplayDouble(QWidget):
        def __init__(self, parent=None, **_kwargs):
            super().__init__(parent)

        def set_display_mode(self, *_args, **_kwargs):
            pass

        def set_cortical_paint_cluster_mask_enabled(self, *_args, **_kwargs):
            pass

        def set_transparent_spin_enabled(self, *_args, **_kwargs):
            pass

        def set_activation_payload(self, *_args, **_kwargs):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(gui, "BrainRendererWidget", DisplayDouble)
    monkeypatch.setattr(LoretaVisualizerWindow, "_start_fsaverage_load", lambda *_a, **_k: None)
    monkeypatch.setattr(LoretaVisualizerWindow, "_refresh_current_activation", lambda _self: None)
    window = LoretaVisualizerWindow()
    qtbot.addWidget(window)
    entries = []
    for metric in (gui.METRIC_Z_SCORE, gui.METRIC_AMPLITUDE):
        for group, condition in (("a", "words"), ("b", "words"), ("a", "faces")):
            cell = f"{group}_{condition}"
            entries.append(PreparedSourceManifestEntry(
                f"{cell}_mean_{metric}", cell, tmp_path / f"{cell}.json", {
                    "producer_method": "l2_mne_hauk_source_psd_cortical_normal_v1_mean",
                    "source_metric": metric, "source_cell_id": cell, "source_cell_label": cell,
                    "participant_zscore_aggregation": "mean", "group_id": group,
                    "canonical_condition_id": condition, "descriptive_comparison_available": True,
                },
            ))
    window._replace_manifest_conditions(tuple(entries))
    window._select_first_condition_if_needed()
    window.show()
    window.metric_combo.setCurrentIndex(window.metric_combo.findData(gui.METRIC_AMPLITUDE))
    assert window._selected_condition_id == "a_words"
    assert window.summary_combo.currentText() == "Raw mean"
    window.compare_groups_check.click()
    assert window.comparison_target_combo.isVisible()
    assert window.comparison_target_combo.currentData() == "b_words_mean_baseline_corrected_amplitude"
    window.comparison_kind_combo.setCurrentIndex(window.comparison_kind_combo.findData("conditions"))
    assert window.comparison_target_combo.currentData() == "a_faces_mean_baseline_corrected_amplitude"
    assert "paired conditions" in window.compare_groups_check.toolTip()
    window.comparison_view_combo.setCurrentIndex(window.comparison_view_combo.findData("difference"))
    assert window._comparison_view == "difference"
    window.activation_min_spin.setValue(-3e-10)
    window.activation_max_spin.setValue(2e-10)
    assert window.activation_min_spin.value() == -3e-10
    assert window.activation_max_spin.value() == 2e-10
    assert window.close()


def test_unsupported_graphics_show_recoverable_error_before_vtk(qtbot, monkeypatch):
    from Tools.LORETA_Visualizer import graphics_support

    native_calls = []

    def unsupported(_parent):
        raise RuntimeError("LORETA 3D rendering requires desktop OpenGL 3.2 or later.")

    def unexpected_interactor(*_args, **_kwargs):
        native_calls.append(True)
        raise AssertionError("Unsupported graphics reached VTK")

    monkeypatch.setattr(graphics_support, "require_desktop_opengl", unsupported)
    monkeypatch.setitem(sys.modules, "pyvista", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pyvistaqt", SimpleNamespace(QtInteractor=unexpected_interactor))
    window = LoretaVisualizerWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.renderer is None
    assert window._mesh_thread is None
    assert window.status_banner.isVisible()
    assert any("desktop OpenGL 3.2" in label.text() for label in window.status_banner.findChildren(QLabel))
    assert native_calls == []
    assert window.close()


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
    assert combo.itemText(0) == "Cortical normal (Toolbox default)"
    assert combo.itemData(0) == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    assert combo.itemText(1) == "Legacy MNE pooled orientation (reproduce older maps)"
    assert combo.itemData(1) == SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM
    assert combo.isEnabled()
    assert "next L2-MNE source-map rebuild" in combo.toolTip()

    note = dialog.findChild(QLabel, "loreta_l2_source_orientation_note")
    assert note is not None
    assert "L2-MNE cortical maps only" in note.text()
    assert "eLORETA volume maps always use the corrected vector norm" in note.text()
    assert dialog.volume_smooth_shell_check.text() == "Use smooth shell in 3D volume view"
    assert not dialog.volume_smooth_shell_check.isChecked()
    assert dialog.volume_smooth_shell_check.isEnabled()
    assert "Source estimates, masks and colors are unchanged" in dialog.volume_smooth_shell_check.toolTip()
    dialog.volume_smooth_shell_check.click()
    assert dialog.volume_smooth_shell_check.isChecked()


def test_loreta_smooth_shell_option_retains_preference_when_anatomy_is_unavailable(qtbot) -> None:
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
        project_available=False,
        export_busy=False,
        volume_smooth_shell_enabled=True,
        volume_smooth_shell_available=False,
    )
    qtbot.addWidget(dialog)
    assert dialog.volume_smooth_shell_check.isChecked()
    assert not dialog.volume_smooth_shell_check.isEnabled()
    assert "unavailable" in dialog.volume_smooth_shell_check.toolTip()
    assert "detailed cortical backdrop is used" in dialog.volume_smooth_shell_check.toolTip()


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
    assert "L2-MNE values" in combo.toolTip()
