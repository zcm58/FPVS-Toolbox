from __future__ import annotations

import numpy as np
from PIL import Image

from Tools.LORETA_Visualizer.conditions import condition_by_id
from Tools.LORETA_Visualizer.dummy_activation import make_demo_condition_activation
from Tools.LORETA_Visualizer.gui import (
    LoretaVisualizerWindow,
    _activation_display_payload,
    _activation_value_readout,
    _underpowered_cluster_mask_status_text,
)
from Tools.LORETA_Visualizer.renderer import (
    BrainRendererWidget,
    DEFAULT_SPLIT_FIGURE_SINGLE_HEIGHT_IN,
    DEFAULT_SPLIT_FIGURE_STACK_HEIGHT_IN,
    DEFAULT_SPLIT_FIGURE_WIDTH_IN,
    DISPLAY_MODE_CORTICAL_SURFACE,
    ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM,
    DISPLAY_MODE_SPLIT_HEMISPHERE,
    DISPLAY_MODE_TRANSPARENT_MESH,
    PublicationSplitFigurePanel,
    SPLIT_FIGURE_CONDITION_LABEL_SIZE_PT,
    SPLIT_FIGURE_CONDITION_TOP_MARGIN,
    SPLIT_FIGURE_EXPORT_DPI,
    SPLIT_FIGURE_HEMISPHERE_LABEL_SIZE_PT,
    SPLIT_FIGURE_SINGLE_TOP_MARGIN,
    TRANSPARENT_SPIN_DEGREES_PER_TICK,
    TRANSPARENT_SPIN_RESUME_DELAY_MS,
    _PUBLICATION_CAMERA_DISTANCE,
    _PUBLICATION_CAMERA_PARALLEL_SCALE,
    _SplitHemisphereState,
    _configure_transparency_backend,
    _cortical_paint_display_values,
    _publication_hemisphere_points,
    _publication_surface_rgb,
    write_publication_split_hemisphere_figures,
    write_publication_split_hemisphere_stack_figures,
)
from Tools.LORETA_Visualizer.scalar_fields import LORETA_SCALAR_COLORS, format_scalar_value, resolve_scalar_limits
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_VOLUME_MESH,
    filter_source_payload_values_above,
    make_source_payload,
)
from Tools.LORETA_Visualizer.synthetic_brain import BrainHemisphereMesh
from Tools.LORETA_Visualizer.synthetic_brain import make_synthetic_brain_mesh
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    MeshDisplayTransform,
)


def test_demo_conditions_place_volume_activation_in_distinct_regions() -> None:
    mesh = make_synthetic_brain_mesh()
    occipital = make_demo_condition_activation(mesh.points, mesh_faces=mesh.faces, condition=condition_by_id("occipital"))
    frontal = make_demo_condition_activation(mesh.points, mesh_faces=mesh.faces, condition=condition_by_id("frontal"))

    assert len(occipital.points) > 0
    assert len(frontal.points) > 0
    assert occipital.kind == SOURCE_KIND_VOLUME_MESH
    assert frontal.kind == SOURCE_KIND_VOLUME_MESH
    assert occipital.source_model == "volume_grid"
    assert frontal.source_model == "volume_grid"
    assert occipital.faces is not None
    assert frontal.faces is not None
    assert len(occipital.faces) > 0
    assert len(frontal.faces) > 0
    assert float(np.min(occipital.values)) > 0.0
    assert float(np.max(occipital.values)) <= 1.0
    assert float(np.mean(occipital.points[:, 1])) < 0.0
    assert float(np.mean(frontal.points[:, 1])) > 0.0
    assert float(np.mean(frontal.points[:, 1])) > float(np.mean(occipital.points[:, 1]))


def test_synthetic_brain_exposes_split_hemisphere_meshes() -> None:
    mesh = make_synthetic_brain_mesh()

    assert mesh.left_hemisphere is not None
    assert mesh.right_hemisphere is not None
    assert mesh.left_hemisphere.points.shape[1] == 3
    assert mesh.right_hemisphere.points.shape[1] == 3
    assert len(mesh.left_hemisphere.faces) > 0
    assert len(mesh.right_hemisphere.faces) > 0
    assert mesh.left_hemisphere.shade_values is not None
    assert mesh.right_hemisphere.shade_values is not None
    assert len(mesh.left_hemisphere.shade_values) == len(mesh.left_hemisphere.points)
    assert len(mesh.right_hemisphere.shade_values) == len(mesh.right_hemisphere.points)


def test_deep_demo_condition_uses_internal_volume_mesh() -> None:
    mesh = make_synthetic_brain_mesh()
    deep = make_demo_condition_activation(mesh.points, condition=condition_by_id("deep_medial_temporal"))

    shell_radius = np.linalg.norm(mesh.points, axis=1)
    deep_radius = np.linalg.norm(deep.points, axis=1)

    assert deep.kind == SOURCE_KIND_VOLUME_MESH
    assert deep.source_model == "volume_grid"
    assert len(deep.points) > 0
    assert deep.faces is not None
    assert len(deep.faces) > 0
    assert float(np.min(deep.values)) < 0.25
    assert float(np.max(deep.values)) > 0.9
    assert float(np.mean(deep_radius)) < float(np.percentile(shell_radius, 50))


def test_source_payload_normalizes_and_filters_values() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [float("nan"), 0.0, 0.0],
            ]
        ),
        values=np.asarray([2.0, 4.0, 9.0]),
        label="demo",
        source_model="volume_grid",
    )

    assert payload.points.shape == (2, 3)
    assert payload.values.tolist() == [0.0, 1.0]


def test_scalar_gradient_limits_follow_scalp_map_style_bounds() -> None:
    assert LORETA_SCALAR_COLORS[-1] == "#b2182b"
    assert resolve_scalar_limits(np.asarray([0.2, 0.8]), auto_scale=True) == (0.0, 0.8)
    assert resolve_scalar_limits(np.asarray([-0.4, 0.8]), auto_scale=True) == (-0.4, 0.8)
    assert resolve_scalar_limits(np.asarray([0.2]), auto_scale=False, manual_min=1.0, manual_max=1.0) == (1.0, 2.0)


def test_scalar_scale_readout_formats_tiny_source_values_and_units() -> None:
    assert format_scalar_value(0.0) == "0"
    assert format_scalar_value(0.000087632) == "8.763e-05"
    assert format_scalar_value(0.125) == "0.125"

    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.000087632], dtype=float),
        label="Beta source",
        value_label="beta L2-MNE cortical source amplitude",
        metadata={"source_value_unit": "arbitrary units", "sensor_value_unit": "summed BCA uV"},
        normalize_values=False,
    )

    assert _activation_value_readout(payload) == (
        "Value: beta L2-MNE cortical source amplitude; unit: arbitrary units; input: summed BCA uV"
    )


def test_filter_source_payload_values_above_remaps_mesh_faces() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.5, 1.5, 0.0],
            ],
            dtype=float,
        ),
        values=np.asarray([-1.0, 0.0, 0.5, 2.0, 3.0], dtype=float),
        label="signed z",
        kind=SOURCE_KIND_SURFACE_MESH,
        value_label="source-space z-score",
        faces=np.asarray([[0, 2, 3], [2, 3, 4], [1, 2, 4]], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )

    filtered = filter_source_payload_values_above(payload, threshold=0.0)

    assert filtered.values.tolist() == [0.5, 2.0, 3.0]
    assert np.array_equal(filtered.faces, np.asarray([[0, 1, 2]], dtype=np.int64))
    assert filtered.metadata["display_value_filter_original_point_count"] == 5
    assert filtered.metadata["display_value_filter_rendered_point_count"] == 3


def test_filter_source_payload_values_above_remaps_flat_vtk_mesh_faces() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
            ],
            dtype=float,
        ),
        values=np.asarray([-1.0, 0.5, 1.5, 2.5], dtype=float),
        label="signed z",
        kind=SOURCE_KIND_SURFACE_MESH,
        value_label="source-space z-score",
        faces=np.asarray([3, 0, 1, 2, 3, 1, 2, 3], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )

    filtered = filter_source_payload_values_above(payload, threshold=0.0)

    assert filtered.values.tolist() == [0.5, 1.5, 2.5]
    assert np.array_equal(filtered.faces, np.asarray([3, 0, 1, 2], dtype=np.int64))


def test_zscore_activation_display_defaults_to_positive_values_only() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=float,
        ),
        values=np.asarray([-6.0, 0.0, 4.2], dtype=float),
        label="Semantic Response",
        value_label="source-space z-score",
        metadata={"source_value_unit": "z-score", "sensor_value_unit": "raw FFT amplitude uV"},
        normalize_values=False,
    )

    display_payload = _activation_display_payload(payload)

    assert display_payload.values.tolist() == [4.2]
    assert _activation_value_readout(display_payload) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; display: > 0"
    )


def test_l2_mne_surface_zscore_display_uses_cortical_paint_without_filtering_points() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=float,
        ),
        values=np.asarray([-6.0, 0.0, 4.2], dtype=float),
        label="Semantic Response",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata={"source_value_unit": "z-score", "sensor_value_unit": "raw FFT amplitude uV"},
        normalize_values=False,
    )

    display_payload = _activation_display_payload(payload)

    assert display_payload.values.tolist() == [-6.0, 0.0, 4.2]
    assert _activation_value_readout(display_payload) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; "
        "display: z >= 1.64"
    )

    assert _activation_value_readout(display_payload, cortical_threshold_display=False) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV"
    )


def test_transparent_surface_zscore_display_filters_nonpositive_values_before_auto_scale() -> None:
    payload = make_source_payload(
        points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.5, 1.5, 0.0],
            ],
            dtype=float,
        ),
        values=np.asarray([-6.0, 0.0, 0.5, 2.0, 4.2], dtype=float),
        label="Semantic Response",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 2, 3], [2, 3, 4], [1, 2, 4]], dtype=np.int64),
        metadata={"source_value_unit": "z-score", "sensor_value_unit": "raw FFT amplitude uV"},
        normalize_values=False,
    )

    display_payload = _activation_display_payload(payload, transparent_mesh_display=True)

    assert display_payload.values.tolist() == [0.5, 2.0, 4.2]
    assert np.array_equal(display_payload.faces, np.asarray([[0, 1, 2]], dtype=np.int64))
    assert resolve_scalar_limits(display_payload.values, auto_scale=True) == (0.0, 4.2)
    assert _activation_value_readout(display_payload, cortical_threshold_display=False) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; display: > 0"
    )


def test_underpowered_cluster_mask_readout_marks_exploratory_threshold_display() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Erotic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "sensor_value_unit": "raw FFT amplitude uV",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [],
            "cluster_mask_vertex_count": 0,
            "participant_count": 4,
            "cluster_permutation_count": 16,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )

    assert _activation_value_readout(payload) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; "
        "display: exploratory z >= 1.64"
    )
    warning = _underpowered_cluster_mask_status_text(payload)
    assert warning is not None
    assert "small sample size (4 participants)" in warning
    assert "minimum possible cluster p = 0.0588" in warning
    assert "not group-masked" in warning


def test_hauk_cluster_mask_readout_names_publication_mask() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Semantic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "sensor_value_unit": "raw FFT amplitude uV",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [0],
            "cluster_mask_vertex_count": 1,
            "cluster_permutation_count": 10000,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )

    assert _activation_value_readout(payload) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; "
        "display: Hauk et al. (2025) cluster mask"
    )


def test_hauk_cluster_mask_readout_marks_disabled_mask_as_exploratory() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Semantic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "sensor_value_unit": "raw FFT amplitude uV",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [0],
            "cluster_mask_vertex_count": 1,
        },
        normalize_values=False,
    )

    assert _activation_value_readout(payload, use_cluster_mask=False) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; "
        "display: exploratory z >= 1.64"
    )


def test_empty_hauk_cluster_mask_readout_marks_exploratory_fallback() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Semantic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "sensor_value_unit": "raw FFT amplitude uV",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [],
            "cluster_mask_vertex_count": 0,
            "participant_count": 24,
            "cluster_permutation_count": 10000,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )

    assert _activation_value_readout(payload) == (
        "Value: source-space z-score; unit: z-score; input: raw FFT amplitude uV; "
        "display: exploratory z >= 1.64"
    )


def test_hauk_cluster_mask_load_status_messages() -> None:
    valid_payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Semantic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [1],
            "cluster_mask_vertex_count": 1,
        },
        normalize_values=False,
    )
    empty_payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.2], dtype=float),
        label="Semantic",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_fsaverage_participant_zscore_mean",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_vertex_indices": [],
            "cluster_mask_vertex_count": 0,
            "cluster_permutation_count": 10000,
            "cluster_alpha": 0.05,
        },
        normalize_values=False,
    )
    status = _StatusProbe()
    window = LoretaVisualizerWindow.__new__(LoretaVisualizerWindow)
    window.mesh_status = status

    window._set_payload_display_status(valid_payload)
    assert status.variant == "info"
    assert status.text == "Loaded Hauk et al. (2025) source-estimation cluster mask."

    window._set_payload_display_status(empty_payload)
    assert status.variant == "warning"
    assert status.text == "No vertices survived the Hauk et al. (2025) cluster-permutation mask."

    window._use_cluster_mask = False
    window._zscore_display_threshold = 2.32
    window._set_payload_display_status(valid_payload)
    assert status.variant == "info"
    assert status.text == "Cluster mask display is disabled. Showing exploratory z >= 2.32 instead."


class _StatusProbe:
    def __init__(self) -> None:
        self.variant = ""
        self.text = ""

    def set_variant(self, variant: str) -> None:
        self.variant = variant

    def set_text(self, text: str) -> None:
        self.text = text


def test_split_hemisphere_projection_uses_projection_points_for_values() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([2.0, 5.0], dtype=float),
        label="surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 1]], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )
    draw_points = np.asarray([[20.0, 0.0, 0.0], [22.0, 0.0, 0.0]], dtype=float)
    projection_points = np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float)
    hemisphere = BrainHemisphereMesh(
        points=draw_points,
        faces=np.asarray([3, 0, 1, 1], dtype=np.int64),
        projection_points=projection_points,
        surface="inflated",
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._cortical_paint_z_threshold = 1.64
    renderer._cortical_paint_use_cluster_mask = True

    state = BrainRendererWidget._project_split_hemisphere(renderer, hemisphere, payload)

    assert np.array_equal(state.points, draw_points)
    assert state.values.tolist() == [2.0, 5.0]


def test_publication_surface_rgb_preserves_shaded_cortex_underlay() -> None:
    values = np.asarray([np.nan, 2.0, 5.0], dtype=float)
    shade_values = np.asarray([0.0, 0.5, 1.0], dtype=float)

    visible_colors = _publication_surface_rgb(
        values,
        shade_values,
        scalar_range=(2.0, 5.0),
        activation_visible=True,
    )
    hidden_colors = _publication_surface_rgb(
        values,
        shade_values,
        scalar_range=(2.0, 5.0),
        activation_visible=False,
    )

    assert visible_colors.dtype == np.uint8
    assert visible_colors.shape == (3, 3)
    assert hidden_colors[0, 0] < hidden_colors[2, 0]
    assert np.array_equal(visible_colors[0], hidden_colors[0])
    assert not np.array_equal(visible_colors[1], hidden_colors[1])
    assert not np.array_equal(visible_colors[2], hidden_colors[2])


def test_publication_surface_rgb_uses_shaded_cortex_below_color_minimum() -> None:
    values = np.asarray([1.0, 2.0, 5.0], dtype=float)
    shade_values = np.asarray([0.0, 0.5, 1.0], dtype=float)

    visible_colors = _publication_surface_rgb(
        values,
        shade_values,
        scalar_range=(2.0, 5.0),
        activation_visible=True,
    )
    hidden_colors = _publication_surface_rgb(
        values,
        shade_values,
        scalar_range=(2.0, 5.0),
        activation_visible=False,
    )

    assert np.array_equal(visible_colors[0], hidden_colors[0])
    assert not np.array_equal(visible_colors[1], hidden_colors[1])
    assert not np.array_equal(visible_colors[2], hidden_colors[2])


def test_cortical_paint_display_values_hide_values_below_color_minimum() -> None:
    values = np.asarray([np.nan, 1.0, 2.0, 5.0], dtype=float)

    display_values = _cortical_paint_display_values(values, scalar_range=(2.0, 5.0))

    assert np.isnan(display_values[0])
    assert np.isnan(display_values[1])
    assert display_values[2:].tolist() == [2.0, 5.0]


def test_publication_split_figure_export_writes_pdf_and_png(tmp_path) -> None:
    state = _SplitHemisphereState(
        points=np.asarray(
            [
                [-1.0, -0.5, 0.0],
                [-1.0, 0.5, 0.0],
                [-0.5, 0.0, 1.0],
            ],
            dtype=float,
        ),
        faces=np.asarray([3, 0, 1, 2], dtype=np.int64),
        values=np.asarray([np.nan, 2.0, 5.0], dtype=float),
        shade_values=np.asarray([0.0, 0.5, 1.0], dtype=float),
    )

    pdf_path, png_path = write_publication_split_hemisphere_figures(
        tmp_path / "split.pdf",
        left_state=state,
        right_state=state,
        scalar_range=(1.64, 5.0),
        activation_visible=True,
    )

    assert pdf_path.suffix == ".pdf"
    assert png_path.suffix == ".png"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    with Image.open(png_path) as image:
        assert image.size == (
            int(round(DEFAULT_SPLIT_FIGURE_WIDTH_IN * SPLIT_FIGURE_EXPORT_DPI)),
            int(round(DEFAULT_SPLIT_FIGURE_SINGLE_HEIGHT_IN * SPLIT_FIGURE_EXPORT_DPI)),
        )
        assert image.getbbox() is not None


def test_publication_split_figure_export_renders_full_surface_png(tmp_path) -> None:
    points = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 2.0, 0.0],
            [1.0, 2.0, 0.0],
            [0.0, 3.0, 0.0],
            [1.0, 3.0, 0.0],
        ],
        dtype=float,
    )
    faces = np.asarray(
        [
            3,
            0,
            1,
            2,
            3,
            1,
            3,
            2,
            3,
            2,
            3,
            4,
            3,
            3,
            5,
            4,
            3,
            4,
            5,
            6,
            3,
            5,
            7,
            6,
        ],
        dtype=np.int64,
    )
    state = _SplitHemisphereState(
        points=points,
        faces=faces,
        values=np.asarray(
            [np.nan, 2.0, np.nan, 3.0, np.nan, 4.0, np.nan, 5.0],
            dtype=float,
        ),
    )

    _pdf_path, png_path = write_publication_split_hemisphere_figures(
        tmp_path / "small.pdf",
        left_state=state,
        right_state=state,
        scalar_range=(1.64, 5.0),
        activation_visible=True,
    )

    with Image.open(png_path) as image:
        assert image.getbbox() is not None


def test_publication_split_stack_figure_export_writes_pdf_and_png(tmp_path) -> None:
    state = _SplitHemisphereState(
        points=np.asarray(
            [
                [-1.0, -0.5, 0.0],
                [-1.0, 0.5, 0.0],
                [-0.5, 0.0, 1.0],
            ],
            dtype=float,
        ),
        faces=np.asarray([3, 0, 1, 2], dtype=np.int64),
        values=np.asarray([np.nan, 2.0, 5.0], dtype=float),
        shade_values=np.asarray([0.0, 0.5, 1.0], dtype=float),
    )
    panels = (
        PublicationSplitFigurePanel(
            label="CR",
            left_state=state,
            right_state=state,
            scalar_range=(1.64, 5.0),
            activation_visible=True,
        ),
        PublicationSplitFigurePanel(
            label="SR",
            left_state=state,
            right_state=state,
            scalar_range=(1.64, 5.0),
            activation_visible=True,
        ),
    )

    pdf_path, png_path = write_publication_split_hemisphere_stack_figures(
        tmp_path / "stack.pdf",
        panels=panels,
    )

    assert pdf_path.read_bytes().startswith(b"%PDF")
    with Image.open(png_path) as image:
        assert image.size == (
            int(round(DEFAULT_SPLIT_FIGURE_WIDTH_IN * SPLIT_FIGURE_EXPORT_DPI)),
            int(round(DEFAULT_SPLIT_FIGURE_STACK_HEIGHT_IN * SPLIT_FIGURE_EXPORT_DPI)),
        )
        assert image.getbbox() is not None


def test_publication_split_stack_figure_uses_elsevier_one_and_half_column_dimensions_and_labels() -> None:
    assert DEFAULT_SPLIT_FIGURE_WIDTH_IN * 25.4 == ELSEVIER_ONE_AND_HALF_COLUMN_WIDTH_MM
    assert DEFAULT_SPLIT_FIGURE_STACK_HEIGHT_IN * 25.4 < 240.0
    assert SPLIT_FIGURE_CONDITION_LABEL_SIZE_PT >= 14
    assert SPLIT_FIGURE_HEMISPHERE_LABEL_SIZE_PT >= 14
    assert SPLIT_FIGURE_CONDITION_TOP_MARGIN >= 150.0
    assert SPLIT_FIGURE_SINGLE_TOP_MARGIN >= 130.0


def test_split_payload_refresh_preserves_existing_camera_and_orientation(monkeypatch) -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=float),
        values=np.asarray([2.0, 3.0, 4.0], dtype=float),
        label="surface z",
        kind=SOURCE_KIND_SURFACE_MESH,
        source_model="l2_mne_cortical_surface_hauk_zscore_beta",
        value_label="source-space z-score",
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata={"source_value_unit": "z-score"},
        normalize_values=False,
    )
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakePlotter()
    renderer._display_mode = DISPLAY_MODE_SPLIT_HEMISPHERE
    renderer._split_hemisphere_active = True
    renderer._activation_actor = None
    renderer._split_left_actor = None
    renderer._split_right_actor = None
    reset_camera_values: list[bool] = []

    def fake_set_split_payload(
        _self: BrainRendererWidget,
        _payload,
        *,
        reset_camera: bool = True,
    ) -> bool:
        reset_camera_values.append(reset_camera)
        return True

    monkeypatch.setattr(BrainRendererWidget, "_set_split_hemisphere_payload", fake_set_split_payload)

    renderer.set_activation_payload(payload)

    assert reset_camera_values == [False]


class _FakePlotter:
    def render(self) -> None:
        return None


class _FakePublicationCamera:
    def __init__(self) -> None:
        self.position: tuple[float, float, float] | None = None
        self.focal_point: tuple[float, float, float] | None = None
        self.view_up: tuple[float, float, float] | None = None
        self.parallel_projection_enabled = False
        self.parallel_scale: float | None = None

    def SetPosition(self, x: float, y: float, z: float) -> None:
        self.position = (x, y, z)

    def SetFocalPoint(self, x: float, y: float, z: float) -> None:
        self.focal_point = (x, y, z)

    def SetViewUp(self, x: float, y: float, z: float) -> None:
        self.view_up = (x, y, z)

    def ParallelProjectionOn(self) -> None:
        self.parallel_projection_enabled = True

    def SetParallelScale(self, scale: float) -> None:
        self.parallel_scale = scale


class _FakePublicationCameraPlotter:
    def __init__(self) -> None:
        self.camera = _FakePublicationCamera()
        self.reset_camera_calls = 0
        self.reset_camera_clipping_range_calls = 0
        self.camera_position: str | None = None

    def reset_camera(self) -> None:
        self.reset_camera_calls += 1

    def reset_camera_clipping_range(self) -> None:
        self.reset_camera_clipping_range_calls += 1


def test_publication_camera_opens_split_view_zoomed_out() -> None:
    plotter = _FakePublicationCameraPlotter()
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = plotter

    BrainRendererWidget._set_publication_camera(renderer)

    assert plotter.reset_camera_calls == 1
    assert plotter.reset_camera_clipping_range_calls == 1
    assert plotter.camera.position == (0.0, -_PUBLICATION_CAMERA_DISTANCE, 0.25)
    assert plotter.camera.focal_point == (0.0, 0.0, 0.0)
    assert plotter.camera.view_up == (0.0, 0.0, 1.0)
    assert plotter.camera.parallel_projection_enabled is True
    assert plotter.camera.parallel_scale == _PUBLICATION_CAMERA_PARALLEL_SCALE
    assert _PUBLICATION_CAMERA_DISTANCE > 5.0
    assert _PUBLICATION_CAMERA_PARALLEL_SCALE > 2.0


class _FakeTransparentSpinTimer:
    def __init__(self) -> None:
        self.active = False
        self.started_intervals: list[int | None] = []
        self.stop_calls = 0

    def isActive(self) -> bool:
        return self.active

    def start(self, interval: int | None = None) -> None:
        self.active = True
        self.started_intervals.append(interval)

    def stop(self) -> None:
        self.active = False
        self.stop_calls += 1


class _FakeTransparentSpinCamera(_FakePublicationCamera):
    def __init__(self) -> None:
        super().__init__()
        self.orthogonalize_calls = 0

    def OrthogonalizeViewUp(self) -> None:
        self.orthogonalize_calls += 1


class _FakeTransparentSpinPlotter:
    def __init__(self) -> None:
        self.camera = _FakeTransparentSpinCamera()
        self.reset_camera_calls = 0
        self.reset_camera_clipping_range_calls = 0
        self.render_calls = 0

    def reset_camera(self) -> None:
        self.reset_camera_calls += 1

    def reset_camera_clipping_range(self) -> None:
        self.reset_camera_clipping_range_calls += 1

    def render(self) -> None:
        self.render_calls += 1


def _make_transparent_spin_renderer(display_mode: str = DISPLAY_MODE_TRANSPARENT_MESH) -> BrainRendererWidget:
    renderer = BrainRendererWidget.__new__(BrainRendererWidget)
    renderer._plotter = _FakeTransparentSpinPlotter()
    renderer._current_mesh = make_synthetic_brain_mesh()
    renderer._display_mode = display_mode
    renderer._transparent_spin_enabled = False
    renderer._transparent_spin_angle_degrees = 0.0
    renderer._transparent_spin_timer = _FakeTransparentSpinTimer()
    renderer._transparent_spin_resume_timer = _FakeTransparentSpinTimer()
    return renderer


def test_transparent_spin_starts_from_x_axis_with_z_vertical() -> None:
    renderer = _make_transparent_spin_renderer()
    plotter = renderer._plotter

    renderer.set_transparent_spin_enabled(True)

    assert renderer._transparent_spin_timer.isActive()
    assert not renderer._transparent_spin_resume_timer.isActive()
    assert plotter.camera.focal_point is not None
    assert plotter.camera.position is not None
    assert plotter.camera.view_up == (0.0, 0.0, 1.0)
    assert plotter.camera.position[0] > plotter.camera.focal_point[0]
    assert np.isclose(plotter.camera.position[1], plotter.camera.focal_point[1])
    assert np.isclose(plotter.camera.position[2], plotter.camera.focal_point[2])
    assert plotter.reset_camera_calls == 1
    assert plotter.reset_camera_clipping_range_calls == 1
    assert plotter.render_calls == 1


def test_transparent_spin_waits_for_transparent_mesh_mode() -> None:
    renderer = _make_transparent_spin_renderer(display_mode=DISPLAY_MODE_CORTICAL_SURFACE)

    renderer.set_transparent_spin_enabled(True)

    assert renderer.transparent_spin_enabled()
    assert not renderer._transparent_spin_timer.isActive()
    assert not renderer._transparent_spin_resume_timer.isActive()


def test_transparent_spin_pauses_then_resets_orientation_after_interaction() -> None:
    renderer = _make_transparent_spin_renderer()

    renderer.set_transparent_spin_enabled(True)
    renderer._advance_transparent_spin()
    assert np.isclose(renderer._transparent_spin_angle_degrees, TRANSPARENT_SPIN_DEGREES_PER_TICK)

    renderer._pause_transparent_spin_for_interaction()

    assert not renderer._transparent_spin_timer.isActive()
    assert renderer._transparent_spin_resume_timer.isActive()
    assert renderer._transparent_spin_resume_timer.started_intervals[-1] == TRANSPARENT_SPIN_RESUME_DELAY_MS

    renderer._resume_transparent_spin_after_interaction()

    assert renderer._transparent_spin_timer.isActive()
    assert renderer._transparent_spin_angle_degrees == 0.0
    assert renderer._plotter.camera.view_up == (0.0, 0.0, 1.0)


class _FakeTransparencyPlotter:
    def __init__(self) -> None:
        self.disable_depth_peeling_calls = 0
        self.enable_depth_peeling_calls = 0

    def disable_depth_peeling(self) -> None:
        self.disable_depth_peeling_calls += 1

    def enable_depth_peeling(self, *_args, **_kwargs) -> None:
        self.enable_depth_peeling_calls += 1


class _FakeVtkRenderer:
    def __init__(self) -> None:
        self.use_depth_peeling: bool | None = None

    def SetUseDepthPeeling(self, value: bool) -> None:
        self.use_depth_peeling = bool(value)


class _FakeLegacyTransparencyPlotter:
    def __init__(self) -> None:
        self.renderer = _FakeVtkRenderer()


def test_renderer_transparency_prefers_plain_alpha_blending() -> None:
    plotter = _FakeTransparencyPlotter()

    _configure_transparency_backend(plotter)

    assert plotter.disable_depth_peeling_calls == 1
    assert plotter.enable_depth_peeling_calls == 0


def test_renderer_transparency_disables_depth_peeling_on_legacy_renderer() -> None:
    plotter = _FakeLegacyTransparencyPlotter()

    _configure_transparency_backend(plotter)

    assert plotter.renderer.use_depth_peeling is False


def test_publication_hemisphere_points_separate_left_and_right_layouts() -> None:
    source_points = np.asarray(
        [
            [-1.0, -0.5, 0.0],
            [-1.0, 0.5, 0.0],
            [-0.5, 0.0, 1.0],
        ],
        dtype=float,
    )

    left = _publication_hemisphere_points(source_points, side="left")
    right = _publication_hemisphere_points(-source_points, side="right")
    rotated_left = _publication_hemisphere_points(source_points, side="left", extra_yaw_degrees=12.0)

    assert float(np.mean(left[:, 0])) < 0.0
    assert float(np.mean(right[:, 0])) > 0.0
    assert not np.allclose(left, rotated_left)
    assert float(np.max(np.linalg.norm(left - np.mean(left, axis=0), axis=1))) <= 0.83


def test_demo_condition_can_exercise_native_to_display_bridge() -> None:
    native_mesh_points = np.asarray(
        [
            [-35.0, -70.0, -20.0],
            [-35.0, 40.0, 40.0],
            [35.0, -70.0, -18.0],
            [35.0, 42.0, 38.0],
            [0.0, -20.0, 72.0],
            [0.0, -15.0, -45.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    display_mesh_points = transform.to_display_points(native_mesh_points)

    direct_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("occipital"),
    )
    bridged_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("occipital"),
        display_transform=transform,
    )

    assert bridged_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert bridged_payload.metadata["transform_simulation"] is True
    assert bridged_payload.metadata["native_coordinate_space"] == COORDINATE_SPACE_FSAVERAGE
    assert np.allclose(bridged_payload.points, direct_payload.points)
    assert np.allclose(bridged_payload.values, direct_payload.values)
    assert np.array_equal(bridged_payload.faces, direct_payload.faces)


def test_prepared_source_fixture_condition_has_real_data_handoff_shape() -> None:
    mesh = make_synthetic_brain_mesh()
    payload = make_demo_condition_activation(
        mesh.points,
        condition=condition_by_id("prepared_source_fixture"),
        display_transform=mesh.display_transform,
    )

    assert payload.kind == SOURCE_KIND_VOLUME_MESH
    assert payload.source_model == "prepared_fsaverage_volume_fixture"
    assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert payload.faces is not None
    assert len(payload.faces) > 0
    assert len(payload.points) == len(payload.values)
    assert payload.metadata["fixture_kind"] == "prepared_source_map"
    assert payload.metadata["source_file_format"] == "in_memory_fixture"
    assert payload.metadata["source_lobes"] == 4
    assert float(np.min(payload.values)) < 0.1
    assert float(np.max(payload.values)) > 0.9
    assert len(np.unique(np.round(payload.values, decimals=3))) > 30


def test_prepared_source_fixture_uses_fsaverage_like_transform_bridge() -> None:
    native_mesh_points = np.asarray(
        [
            [-65.0, -85.0, -40.0],
            [-62.0, 48.0, 52.0],
            [62.0, -82.0, -38.0],
            [65.0, 50.0, 50.0],
            [0.0, -18.0, 76.0],
            [0.0, -22.0, -52.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    display_mesh_points = transform.to_display_points(native_mesh_points)

    direct_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("prepared_source_fixture"),
    )
    bridged_payload = make_demo_condition_activation(
        display_mesh_points,
        condition=condition_by_id("prepared_source_fixture"),
        display_transform=transform,
    )

    assert bridged_payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert bridged_payload.metadata["source_space"] == COORDINATE_SPACE_FSAVERAGE
    assert bridged_payload.metadata["adapted_through"] == "source_payload_to_display"
    assert np.allclose(bridged_payload.points, direct_payload.points)
    assert np.allclose(bridged_payload.values, direct_payload.values)
    assert np.array_equal(bridged_payload.faces, direct_payload.faces)
