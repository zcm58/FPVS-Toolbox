from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from matplotlib.figure import Figure
import numpy as np
from PIL import Image
import pytest

from Main_App.gui.roi_electrode_selector_state import BIOSEMI64_LABELS
from Tools.Free_Harmonic_Clustering import render_cluster_maps as rendering
from Tools.Free_Harmonic_Clustering.models import ClusterRecord, FreeHarmonicCancelledError
from Tools.Free_Harmonic_Clustering.visualization import ClusterMapData


def _cluster(cluster_id: int, members: tuple[tuple[int, int], ...], harmonics: int) -> ClusterRecord:
    return ClusterRecord(
        cluster_id=cluster_id, sign="positive" if cluster_id > 0 else "negative",
        mass=10.0 if cluster_id > 0 else -10.0, p_value=0.01,
        conservative_p_value=0.01, adjusted_two_sided_p_value=0.02,
        tie_count=0, p_ci_low=0.005, p_ci_high=0.02,
        confidence_interval_straddles_alpha=False, significant=True,
        node_indices=tuple(sensor * harmonics + harmonic for sensor, harmonic in members),
        sensor_indices=tuple(sensor for sensor, _harmonic in members),
        harmonic_indices=tuple(harmonic for _sensor, harmonic in members),
    )


def synthetic_map_data(harmonics: int = 3) -> ClusterMapData:
    """Full-cap fixture with changing memberships and an unsorted sensor axis."""

    names = tuple(reversed(BIOSEMI64_LABELS))
    positions = rendering.sensor_positions(names)
    orders = tuple(index for index in range(1, harmonics + 4) if index % 5 != 0)[:harmonics]
    values = np.column_stack([
        0.12 * positions[:, 1] + 0.03 * positions[:, 0] + 0.01 * harmonic
        for harmonic in range(harmonics)
    ])
    positive_members = ((names.index("Fp1"), 0), (names.index("Cz"), min(1, harmonics - 1)))
    negative_members = ((names.index("O1"), 0), (names.index("Oz"), min(1, harmonics - 1)))
    clusters = (_cluster(3, positive_members, harmonics), _cluster(-2, negative_members, harmonics))
    labels = np.zeros(values.shape, dtype=np.int64)
    for cluster in clusters:
        for sensor, harmonic in zip(cluster.sensor_indices, cluster.harmonic_indices, strict=True):
            labels[sensor, harmonic] = cluster.cluster_id
            values[sensor, harmonic] = 0.15 if cluster.cluster_id > 0 else -0.15
    return ClusterMapData(
        sensor_names=names, harmonic_orders=orders,
        harmonics_hz=tuple(order * 1.2 for order in orders),
        mean_difference=values, cluster_labels=labels, clusters=clusters,
        arm_a_label="Condition A", arm_b_label="Condition B", run_label="Synthetic paired contrast",
        value_label="Mean normalized SNR difference", multiplicity_note="Within-run cluster inference only.",
    )


def _markers(ax, sign: str):
    return next(item for item in ax.collections if item.get_gid() == f"fhc-cluster-{sign}")


def test_positions_are_nose_up_participant_left_and_follow_sensor_order() -> None:
    positions = rendering.sensor_positions(("Oz", "Fp1", "Cz", "Fp2"))
    assert positions[0, 1] < 0 < positions[1, 1]
    assert positions[1, 0] < 0 < positions[3, 0]
    np.testing.assert_allclose(positions[2], (0.0, 0.0), atol=1e-15)
    np.testing.assert_allclose(positions[1], rendering.sensor_positions(("fp1",))[0])
    with pytest.raises(ValueError, match="No BioSemi64"):
        rendering.sensor_positions(("EXG1",))


def test_exact_harmonic_markers_do_not_repeat_union_or_restrict_surface() -> None:
    data = synthetic_map_data()
    positions = rendering.sensor_positions(data.sensor_names)
    figure = Figure()
    ax = figure.subplots()
    first = rendering.draw_harmonic_map(ax, data, 0)
    np.testing.assert_allclose(_markers(ax, "positive").get_offsets(), positions[[data.sensor_names.index("Fp1")]])
    np.testing.assert_allclose(_markers(ax, "negative").get_offsets(), positions[[data.sensor_names.index("O1")]])
    np.testing.assert_allclose(_markers(ax, "positive").get_facecolors()[0], (0, 0, 0, 1))
    np.testing.assert_allclose(_markers(ax, "negative").get_facecolors()[0], (1, 1, 1, 1))
    original = first.get_array().copy()
    filtered = rendering.draw_harmonic_map(ax, data, 0, cluster_id=3)
    np.testing.assert_allclose(filtered.get_array(), original)
    assert len(_markers(ax, "negative").get_offsets()) == 0
    rendering.draw_harmonic_map(ax, data, 1)
    np.testing.assert_allclose(_markers(ax, "positive").get_offsets(), positions[[data.sensor_names.index("Cz")]])
    rendering.draw_harmonic_map(ax, data, 2)
    assert len(_markers(ax, "positive").get_offsets()) == 0
    assert len(_markers(ax, "negative").get_offsets()) == 0


def test_surface_is_bounded_and_scale_is_fixed_over_every_harmonic() -> None:
    data = synthetic_map_data()
    values = data.mean_difference.copy()
    values[0, 2] = 0.75
    data = replace(data, mean_difference=values)
    figure = rendering.create_harmonic_figure(data, harmonic_indices=(2, 0), columns=2)
    assert [ax.get_title() for ax in figure.axes[:2]] == ["H3 · 3.6 Hz", "H1 · 1.2 Hz"]
    for index, ax in zip((2, 0), figure.axes[:2], strict=True):
        image = ax.images[0]
        assert image.get_clim() == (-0.75, 0.75)
        surface = image.get_array()
        assert surface.min() >= data.mean_difference[:, index].min()
        assert surface.max() <= data.mean_difference[:, index].max()
        assert np.ma.getmaskarray(surface)[0, 0]
    assert "mean(A) − mean(B)" in rendering.cluster_map_caption(data)
    assert rendering.PAPER_DOI in rendering.cluster_map_caption(data)


def test_zero_contrast_has_neutral_field_only_zero_colorbar_tick_and_no_dots() -> None:
    data = synthetic_map_data()
    data = replace(data, mean_difference=np.zeros_like(data.mean_difference),
                   cluster_labels=np.zeros_like(data.cluster_labels), clusters=())
    figure = rendering.create_harmonic_figure(data, harmonic_indices=(0,))
    image = figure.axes[0].images[0]
    assert image.get_clim() == (-1.0, 1.0)
    assert np.all(image.get_array().compressed() == 0)
    np.testing.assert_allclose(figure.axes[-1].get_xticks(), [0.0])
    assert len(_markers(figure.axes[0], "positive").get_offsets()) == 0
    assert "display fallback" in rendering.cluster_map_caption(data)


def test_export_pairs_paginate_all_retained_harmonics_and_keep_metadata(tmp_path, monkeypatch) -> None:
    data = synthetic_map_data(13)
    calls = []

    def capture_save(figure, path, **kwargs):
        calls.append((Path(path), kwargs, tuple(ax.get_title() for ax in figure.axes[:-1]),
                      tuple(ax.images[0].get_clim() for ax in figure.axes[:-1])))
        Path(path).write_bytes(b"figure-placeholder")

    monkeypatch.setattr(Figure, "savefig", capture_save)
    paths = rendering.export_cluster_map_figures(data, tmp_path / "maps")
    assert [path.suffix for path in paths] == [".pdf", ".png", ".pdf", ".png"]
    assert [len(item[2]) for item in calls] == [12, 12, 1, 1]
    assert calls[2][2] == (f"H{data.harmonic_orders[-1]} · {data.harmonics_hz[-1]:g} Hz",)
    assert all(item[1]["dpi"] == 600 for item in calls)
    assert all(clim == (-data.color_limit, data.color_limit) for call in calls for clim in call[3])
    assert rendering.PAPER_DOI in calls[0][1]["metadata"]["Subject"]
    assert "not independently significant" in calls[1][1]["metadata"]["Description"]


def test_real_agg_export_has_600dpi_png_and_one_page_pdf(tmp_path) -> None:
    data = synthetic_map_data(1)
    paths = rendering.export_cluster_map_figures(data, tmp_path)
    with Image.open(next(path for path in paths if path.suffix == ".png")) as image:
        assert image.size[0] == 2040
        assert image.size[1] > 2040
        assert image.info["dpi"] == pytest.approx((600, 600), abs=0.01)
        assert "piecewise-linear" in image.info["Description"]
    pdf = next(path for path in paths if path.suffix == ".pdf").read_bytes()
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == 1
    assert b"/Subject" in pdf


def test_long_repeated_labels_fit_a_single_harmonic_figure() -> None:
    data = replace(
        synthetic_map_data(1),
        run_label="Neutral expressions: Group × session interaction",
        arm_a_label="Higher anxiety participants (Follow-up session minus Baseline session)",
        arm_b_label="Lower anxiety participants (Follow-up session minus Baseline session)",
        value_label="Mean session-averaged normalized SNR change difference",
    )
    figure = rendering.create_harmonic_figure(data)
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    for text in [*figure.texts, figure.axes[0].title, figure.axes[-1].xaxis.label]:
        bounds = text.get_window_extent(renderer)
        assert bounds.x0 >= 0 and bounds.y0 >= 0
        assert bounds.x1 <= figure.bbox.width and bounds.y1 <= figure.bbox.height
    assert "dimensionless" in figure.axes[-1].xaxis.label.get_text()
    assert "Higher anxiety" in figure.texts[0].get_text()


def test_cancel_before_export_does_not_create_output(tmp_path) -> None:
    destination = tmp_path / "maps"
    with pytest.raises(FreeHarmonicCancelledError, match="cancelled"):
        rendering.export_cluster_map_figures(synthetic_map_data(), destination, cancel_check=lambda: True)
    assert not destination.exists()
