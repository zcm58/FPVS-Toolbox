"""CI-only Qt coverage of display navigation, never permutation inference."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from Tools.Free_Harmonic_Clustering import render_cluster_maps  # noqa: E402
from Tools.Free_Harmonic_Clustering.gui.cluster_map_view import ClusterMapView  # noqa: E402
from Tools.Free_Harmonic_Clustering.models import ClusterRecord  # noqa: E402
from Tools.Free_Harmonic_Clustering.visualization import ClusterMapData  # noqa: E402


def _cluster(cluster_id: int, coordinates: tuple[tuple[int, int], ...], p_value: float) -> ClusterRecord:
    return ClusterRecord(
        cluster_id=cluster_id,
        sign="positive" if cluster_id > 0 else "negative",
        mass=12.0 if cluster_id > 0 else -10.0,
        p_value=p_value,
        conservative_p_value=p_value,
        adjusted_two_sided_p_value=2 * p_value,
        tie_count=0,
        p_ci_low=p_value / 2,
        p_ci_high=p_value * 1.5,
        confidence_interval_straddles_alpha=False,
        significant=True,
        node_indices=tuple(sensor * 4 + harmonic for sensor, harmonic in coordinates),
        sensor_indices=tuple(sensor for sensor, _harmonic in coordinates),
        harmonic_indices=tuple(harmonic for _sensor, harmonic in coordinates),
    )


def _maps(*, empty: bool = False, repeated: bool = False) -> ClusterMapData:
    clusters = () if empty else (
        _cluster(3, ((0, 0), (1, 1), (2, 1)), 0.003),
        _cluster(-2, ((3, 0), (3, 2)), 0.009),
    )
    labels = np.zeros((4, 4), dtype=np.int64)
    for cluster in clusters:
        labels.reshape(-1)[list(cluster.node_indices)] = cluster.cluster_id
    return ClusterMapData(
        sensor_names=("C1", "Cz", "CPz", "Pz"),
        harmonic_orders=(1, 2, 4, 6),
        harmonics_hz=(1.2, 2.4, 4.8, 7.2),
        mean_difference=np.array(
            [[0.5, 0.1, 0.0, -0.2], [0.0, 0.4, 0.1, 0.0],
             [0.0, 0.3, 0.0, 0.1], [-0.6, 0.2, -0.3, 0.1]]
        ),
        cluster_labels=labels,
        clusters=clusters,
        arm_a_label="Visit 2" if repeated else "Erotic",
        arm_b_label="Visit 1" if repeated else "Neg Val",
        run_label="Paired sessions | Neutral" if repeated else "Erotic − Neg Val",
        value_label="Mean normalized SNR session difference" if repeated else "Mean normalized SNR difference",
        multiplicity_note=(
            "Run-global p = 0.006; Holm within family p = 0.018; Holm across batch p = 0.072. "
            "Holm values apply to the run, not individual clusters."
            if repeated else ""
        ),
    )


@pytest.fixture
def view(qtbot, monkeypatch):
    # Renderer geometry/export behavior has GUI-neutral coverage. Keep this
    # widget test independent of a full montage and expensive interpolation.
    calls = []

    def draw(axis, data, harmonic_index, *, cluster_id=None, show_sensor_names=False):
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize

        calls.append((data, harmonic_index, cluster_id, show_sensor_names))
        axis.set_axis_off()
        return ScalarMappable(norm=Normalize(-data.color_limit, data.color_limit), cmap="RdBu_r")

    monkeypatch.setattr(render_cluster_maps, "draw_harmonic_map", draw)
    widget = ClusterMapView()
    widget.resize(1000, 650)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget, calls


def _harmonic_indices(widget: ClusterMapView) -> list[int]:
    return [widget.harmonic_combo.itemData(index) for index in range(widget.harmonic_combo.count())]


def test_filters_exact_membership_without_reusing_cluster_electrode_union(view):
    widget, calls = view
    data = _maps()
    widget.set_maps((data,))

    assert widget.members_only_checkbox.isChecked()
    assert _harmonic_indices(widget) == [0, 1, 2]
    assert widget.select_cluster(3)
    assert _harmonic_indices(widget) == [0, 1]
    assert "C1" in widget.members.toPlainText()
    assert "CPz" not in widget.members.toPlainText()
    assert "Cz" not in widget.members.toPlainText()
    assert "0.003" in widget.p_values.toPlainText()

    widget.next_button.click()
    assert widget.harmonic_combo.currentData() == 1
    assert "Cz, CPz" in widget.members.toPlainText()
    assert "C1" not in widget.members.toPlainText()
    assert "0.003" in widget.p_values.toPlainText()
    assert not widget.next_button.isEnabled()
    assert widget.previous_button.isEnabled()
    assert calls[-1][1:3] == (1, 3)
    assert all(call[0].color_limit == 0.6 for call in calls)


def test_all_harmonics_exposes_missing_cluster_slice_without_new_significance(view):
    widget, calls = view
    widget.set_maps((_maps(),))
    widget.select_cluster(3)
    widget.members_only_checkbox.setChecked(False)
    assert _harmonic_indices(widget) == [0, 1, 2, 3]
    assert widget.harmonic_combo.itemText(2) == "H4 (4.8 Hz)"
    widget.harmonic_combo.setCurrentIndex(2)

    assert "0 member electrodes" in widget.member_count_label.text()
    assert "No selected-cluster members" in widget.members.toPlainText()
    assert "no members" in widget.status.text()
    assert "0.003" in widget.p_values.toPlainText()
    assert calls[-1][1:3] == (2, 3)

    widget.members_only_checkbox.setChecked(True)
    assert _harmonic_indices(widget) == [0, 1]
    assert widget.harmonic_combo.currentData() == 0


def test_negative_cluster_retains_original_id_and_actual_contrast_direction(view):
    widget, calls = view
    widget.set_maps((_maps(),))
    assert widget.select_cluster(-2)
    assert widget.cluster_combo.currentText() == "Cluster -2"
    assert _harmonic_indices(widget) == [0, 2]
    assert "Black markers: Erotic > Neg Val" in widget.legend_label.text()
    assert "White markers: Neg Val > Erotic" in widget.legend_label.text()
    assert "Pz" in widget.members.toPlainText()
    assert "Cluster -2: raw p = 0.009" in widget.p_values.toPlainText()

    widget.sensor_names_checkbox.setChecked(True)
    assert calls[-1][2:] == (-2, True)


def test_empty_result_allows_descriptive_harmonics_only_on_filter_change(view):
    widget, calls = view
    widget.set_maps((_maps(empty=True),))

    assert widget.harmonic_combo.count() == 0
    assert not widget.harmonic_combo.isEnabled()
    assert not widget.cluster_combo.isEnabled()
    assert "No significant clusters" in widget.status.text()
    assert "Uncheck" in widget.status.text()
    assert not calls

    widget.members_only_checkbox.setChecked(False)
    assert _harmonic_indices(widget) == [0, 1, 2, 3]
    assert "descriptive difference map only" in widget.status.text()
    assert "0 member electrodes" in widget.member_count_label.text()
    assert calls[-1][1:3] == (0, None)


def test_repeated_run_navigation_preserves_run_holm_context_and_clears_stale_state(view):
    widget, calls = view
    first, repeated = _maps(), _maps(repeated=True)
    widget.set_maps((first, repeated))
    assert widget.run_row.isVisible()
    assert widget.select_cluster(-2, run_index=1)
    assert widget.run_combo.currentIndex() == 1
    assert calls[-1][0] is repeated
    assert "Visit 2 − Visit 1" in widget.contrast_label.text()
    assert "Holm across batch p = 0.072" in widget.multiplicity.toPlainText()
    assert "not individual clusters" in widget.multiplicity.toPlainText()
    assert "raw p = 0.009" in widget.p_values.toPlainText()
    assert "0.072" not in widget.p_values.toPlainText()
    assert not widget.select_cluster(999, run_index=0)
    assert not widget.select_run(99)
    assert widget.run_combo.currentIndex() == 1

    assert widget.select_run(0)
    assert widget.cluster_combo.currentData() is None
    assert widget.multiplicity.isHidden()
    assert calls[-1][0] is first

    widget.clear()
    assert widget._maps == ()
    assert widget.run_combo.count() == 0
    assert widget.cluster_combo.count() == 0
    assert widget.harmonic_combo.count() == 0
    assert widget.p_values.toPlainText() == ""
    assert widget.members.toPlainText() == ""
    assert widget.multiplicity.toPlainText() == ""
    assert not widget.next_button.isEnabled()
    assert widget._canvas.isHidden()
    assert "Run an analysis" in widget.status.text()
