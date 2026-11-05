"""Explicit signed metric intent survives every display-only projection."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from matplotlib.colors import to_rgb

from Tools.LORETA_Visualizer.cortical_paint import (
    payload_cluster_mask,
    payload_cluster_mask_is_empty,
    payload_cluster_mask_is_underpowered,
    project_cortical_surface_payload,
    source_payload_uses_zscores,
)
from Tools.LORETA_Visualizer.renderer import (
    _cortical_paint_display_values,
    _publication_surface_rgb,
    _visible_volume_source_arrays,
)
from Tools.LORETA_Visualizer.scalar_fields import resolve_scalar_limits, scalar_colors
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_VOLUME_POINTS,
    SourcePayload,
    source_payload_is_signed,
)
from Tools.LORETA_Visualizer.volume_overlay import (
    DEFAULT_VOLUME_CONTOUR_MAX_COUNT,
    build_smoothed_volume_overlay,
)
from Tools.LORETA_Visualizer.volume_slices import (
    MriAnatomyVolume,
    MriSlicePreviewCache,
    _panel_overlay_display,
    build_mri_slice_figure,
    build_mri_slice_panels,
)


@pytest.mark.parametrize("values,bound", [([-2.0, 1.0], 2.0), ([1.0, 3.0], 3.0),
                                          ([-4.0, -2.0], 4.0), ([0.0], 1.0), ([np.nan], 1.0)])
def test_signed_color_scale_is_symmetric_for_any_finite_support(values, bound):
    assert resolve_scalar_limits(np.array(values), auto_scale=True, signed=True) == (-bound, bound)


def test_signed_fixed_scale_uses_larger_absolute_bound_and_diverging_colors():
    assert resolve_scalar_limits(np.array([99.0]), auto_scale=False,
                                 manual_min=-2.0, manual_max=1.0, signed=True) == (-2.0, 2.0)
    colors = np.array([to_rgb(color) for color in scalar_colors(signed=True, smooth=False)])
    assert colors[0, 2] > colors[0, 0]  # Negative is blue.
    assert colors[-1, 0] > colors[-1, 2]  # Positive is red.
    assert np.ptp(colors[len(colors) // 2]) < 0.02  # Zero is neutral.


def _payload(values, *, signed=True, kind=SOURCE_KIND_SURFACE_MESH):
    values = np.asarray(values, dtype=float)
    points = np.column_stack((np.arange(len(values)), np.zeros((len(values), 2))))
    valid = np.isfinite(values)
    metadata = {
        "source_value_unit": "z-score", "cluster_mask": "source_space_cluster_permutation",
        "cluster_mask_source_indices": [], "cluster_mask_status": "insufficient_participants",
        "source_validity": {
            "policy": "complete_valid_source_support_v1", "version": 1,
            "source_count": len(values), "valid_source_count": int(valid.sum()),
            "invalid_source_indices": np.flatnonzero(~valid).tolist(),
            "scope": "group_complete_case", "participant_count": 4,
        },
    }
    if signed:
        metadata["source_value_polarity"] = "signed"
    return SourcePayload(points, values, "Synthetic source difference", kind=kind,
                         source_model="l2_mne_fsaverage_participant_zscore_mean",
                         faces=np.array([[0, 1, 2]]) if kind == SOURCE_KIND_SURFACE_MESH else None,
                         metadata=metadata)


def test_signed_projection_ignores_z_masks_and_cutoffs_but_keeps_missing_sources():
    payload = _payload([-3.0, np.nan, 0.0, 2.0])
    original = payload.values.copy()
    assert source_payload_is_signed(payload)
    assert not source_payload_uses_zscores(payload)
    assert payload_cluster_mask(payload) is None
    assert not payload_cluster_mask_is_empty(payload)
    assert not payload_cluster_mask_is_underpowered(payload)
    projected = project_cortical_surface_payload(payload.points, payload, z_threshold=100.0)
    np.testing.assert_equal(projected.values, original)
    np.testing.assert_equal(payload.values, original)
    assert (projected.source_value_min, projected.source_value_max) == (-3.0, 2.0)
    historical = replace(payload, metadata={"source_value_unit": "z-score"})
    assert not source_payload_is_signed(historical)
    assert source_payload_uses_zscores(historical)


def test_signed_cortical_preview_and_export_saturate_negatives_without_hiding_them():
    values = np.array([-3.0, 0.0, 3.0, np.nan])
    displayed = _cortical_paint_display_values(values, scalar_range=(-2.0, 2.0), signed_values=True)
    np.testing.assert_equal(displayed, values)
    colored = _publication_surface_rgb(values, None, scalar_range=(-2.0, 2.0),
                                       activation_visible=True, signed_values=True)
    hidden = _publication_surface_rgb(values, None, scalar_range=(-2.0, 2.0),
                                      activation_visible=False, signed_values=True)
    assert colored[0, 2] > colored[0, 0]
    assert colored[2, 0] > colored[2, 2]
    assert np.ptp(colored[1].astype(int)) < 5
    np.testing.assert_equal(colored[3], hidden[3])


@pytest.mark.parametrize("values", [[-4.0, np.nan, -4.0], [-4.0, np.nan, 4.0]])
def test_signed_volume_smoothing_preserves_signs_and_missing_holes_with_bounded_contours(values):
    points = np.array([[-1.0, 0, 0], [0, 0, 0], [1.0, 0, 0]])
    source_values = np.array(values)
    original = source_values.copy()
    overlay = build_smoothed_volume_overlay(
        points, source_values, source_spacing=1.0, max_dimension=15, min_dimension=15,
        edge_zero_margin=0, signed_values=True, min_visible_value=99.0,
    )
    assert overlay is not None
    assert np.isnan(overlay.values[7, 7, 7])
    assert min(overlay.contour_values) < 0.0
    assert (max(overlay.contour_values) > 0.0) == (values[-1] > 0.0)
    assert len(overlay.contour_values) <= DEFAULT_VOLUME_CONTOUR_MAX_COUNT
    assert overlay.rendered_point_count == 2
    np.testing.assert_equal(source_values, original)


def test_signed_volume_fallback_keeps_both_signs_but_avoids_zero_only_glyphs():
    payload = _payload([-2.0, 0.0, 2.0, np.nan], kind=SOURCE_KIND_VOLUME_POINTS)
    _points, values = _visible_volume_source_arrays(payload, 99.0)
    np.testing.assert_equal(values, [-2.0, 2.0])
    zero = replace(payload, values=np.zeros(4))
    assert _visible_volume_source_arrays(zero, 0.0)[1].size == 0
    assert build_smoothed_volume_overlay(zero.points, zero.values, signed_values=True) is None


def _anatomy():
    return MriAnatomyVolume(np.ones((9, 9, 9)), np.eye(4), np.eye(4), Path("unused"))


def test_signed_mri_chooses_absolute_peak_and_retains_negative_only_fields():
    values = np.array([-4.0, -2.0])
    panels, peak = build_mri_slice_panels(
        _anatomy(), np.array([[3.0, 4.0, 4.0], [5.0, 4.0, 4.0]]), values,
        scalar_range=(-4.0, 4.0), signed_values=True,
    )
    assert peak == (3, 4, 4)
    assert all(panel.signed_values for panel in panels)
    assert any(np.nanmin(panel.overlay) < 0.0 for panel in panels)
    np.testing.assert_equal(values, [-4.0, -2.0])


def test_signed_mri_opacity_is_balanced_and_missing_values_are_transparent():
    panels, _ = build_mri_slice_panels(
        _anatomy(), np.array([[4.0, 4.0, 4.0]]), np.array([2.0]),
        scalar_range=(-2.0, 2.0), signed_values=True,
    )
    panel = replace(panels[0], overlay=np.array([[-2.0, 0.0, 2.0, np.nan]]))
    masked, alpha = _panel_overlay_display(panel, -2.0, 2.0, True)
    assert alpha[0, 0] == alpha[0, 2] > 0.0
    assert alpha[0, 1] == alpha[0, 3] == 0.0
    assert masked.mask.tolist() == [[False, False, False, True]]
    figure = build_mri_slice_figure(panels, scalar_range=(-2.0, 2.0), dpi=40)
    try:
        cmap = figure.axes[0].images[1].cmap
        assert cmap(0.0)[2] > cmap(0.0)[0]
        assert cmap(1.0)[0] > cmap(1.0)[2]
    finally:
        figure.clear()


def test_mri_preview_cache_invalidates_when_signed_display_intent_changes():
    anatomy = _anatomy()
    cache = MriSlicePreviewCache()
    kwargs = dict(scalar_range=(-2.0, 2.0), preview_cache=cache)
    voxels = np.array([[4.0, 4.0, 4.0]])
    unsigned, _ = build_mri_slice_panels(anatomy, voxels, np.array([2.0]), **kwargs)
    signed, _ = build_mri_slice_panels(anatomy, voxels, np.array([2.0]), signed_values=True, **kwargs)
    assert not unsigned[0].signed_values
    assert signed[0].signed_values
    assert signed[0] is not unsigned[0]
