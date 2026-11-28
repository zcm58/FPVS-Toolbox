"""Sensor-to-surface projection and scientific display invariants."""

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from Tools.Publication_Maps.scalp_io import align_render_values, biosemi64_info
from Tools.Publication_Maps.scalp_surface import (
    _cap_coordinates, _geometry, _interpolate, _render_head, build_scalp_surface_scene, draw_scalp_surface,
)


def test_electrodes_follow_canonical_montage_directions_on_template():
    geometry = _geometry()
    info = biosemi64_info()
    sensor_directions = geometry.sensor_locations - geometry.origin
    np.testing.assert_allclose(_cap_coordinates(sensor_directions), geometry.cap_coordinates, atol=1e-12)
    values = np.linspace(-1.0, 1.0, len(info.ch_names))
    np.testing.assert_allclose(_interpolate(geometry.cap_coordinates, values, geometry.cap_coordinates), values)
    # The known frontal-left maximum must be on opposite horizontal sides
    # looking into the face and looking at the back of the participant.
    fp1, fp2, oz = map(info.ch_names.index, ("Fp1", "Fp2", "Oz"))
    front, back = (_render_head(view, 256) for view in ("front", "back"))
    assert front.sensor_xy[fp1, 0] > front.sensor_xy[fp2, 0]
    assert back.sensor_xy[fp1, 0] < back.sensor_xy[fp2, 0]
    assert front.visible[fp1] and not front.visible[oz]
    assert back.visible[oz] and not back.visible[fp1]
    assert front.extent == back.extent


def test_finite_triangulation_preserves_signed_values_without_extrapolation():
    tetra = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.]])
    values = np.array([-3., -1., 1., 3.])
    at = np.array([[0., 0.], [0.5, 0.5], [1., 1.], [2., 2.]])
    result = _interpolate(tetra, values, at)
    np.testing.assert_allclose(result[:3], [-3., 0., 3.], atol=1e-14)
    assert np.isnan(result[-1])


def test_interactive_texture_uses_export_values_and_never_wraps_under_chin():
    info = biosemi64_info()
    geom = _geometry()
    # A linear signed gradient is reproduced exactly by cap interpolation.
    data = geom.cap_coordinates[:, 0]
    cmap = matplotlib.colormaps["coolwarm"]
    norm = Normalize(-2, 2)
    scene = build_scalp_surface_scene(data, info, cmap=cmap, norm=norm)
    np.testing.assert_allclose(scene.sensor_locations, geom.sensor_locations)
    assert np.all((scene.texture_coordinates >= 0) & (scene.texture_coordinates <= 1))
    assert len(scene.scalp_faces) < len(scene.faces)
    lowest = np.linalg.norm(geom.cap_coordinates, axis=1).max()
    vertex_angle = np.linalg.norm(_cap_coordinates(scene.vertices - scene.origin), axis=1)
    np.testing.assert_array_equal(scene.scalp_faces, scene.faces[(vertex_angle[scene.faces] <= lowest).any(axis=1)])
    height, width = scene.texture_rgba.shape[:2]
    opaque = scene.texture_rgba[:, :, 3] == 255
    assert opaque[height // 2, width // 2]
    assert not opaque[0].any() and not opaque[-1].any()
    # Texture column increases toward participant right, row toward anterior.
    y, x = np.nonzero(opaque)
    x, y = x[::271], y[::271]
    np.testing.assert_array_equal(scene.texture_rgba[y, x], cmap(norm((x + 0.5) * 2 * np.pi / width - np.pi), bytes=True))
    # A sparse anterior-only panel cannot color posterior scalp in the live view.
    sparse = pd.DataFrame({"electrode": ["Fp1", "Fp2", "AF3", "AF4", "Fz"], "render_value": 2.})
    values, anterior, _, _ = align_render_values(sparse)
    partial = build_scalp_surface_scene(values, anterior, cmap=cmap, norm=norm)
    assert not partial.texture_rgba[:height // 2, :, 3].any()
    assert partial.texture_rgba[height // 2:, :, 3].any()


@pytest.mark.parametrize("view", ["front", "back"])
def test_only_visible_finite_sensors_are_marked_and_unsupported_head_stays_neutral(view):
    # All finite values lie below the map's declared z threshold. Gray
    # template skin must remain distinguishable from white subthreshold data.
    info = biosemi64_info()
    missing = "Fp1" if view == "front" else "O1"
    frame = pd.DataFrame({"electrode": info.ch_names, "render_value": 1.0})
    frame.loc[frame.electrode == missing, "render_value"] = np.nan
    data, selected_info, missing_count, _ = align_render_values(frame)
    cmap = matplotlib.colormaps["viridis"].with_extremes(under="white")
    fig = Figure(figsize=(2, 3), dpi=96)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    draw_scalp_surface(ax, data, selected_info, view=view, cmap=cmap, norm=Normalize(1.64, 3))
    assert missing_count == 1
    image = np.asarray(ax.images[0].get_array())
    neutral_head = (image[:, :, 3] == 255) & (image[:, :, 0] < 250)
    assert np.any(neutral_head) and np.any(np.all(image == 255, axis=2))
    assert np.all(image[:, :, 0][neutral_head] == image[:, :, 2][neutral_head])
    head = _render_head(view, image.shape[1])
    expected = head.visible.copy()
    expected[info.ch_names.index(missing)] = False
    np.testing.assert_allclose(ax.collections[0].get_offsets(), head.sensor_xy[expected])
