"""Sensor-to-surface projection and scientific display invariants."""

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
import mne
import numpy as np
import pandas as pd
import pytest

from Tools.Publication_Maps.natural_neighbor import natural_neighbor_weights
from Tools.Publication_Maps.scalp_io import align_render_values, biosemi64_info
from Tools.Publication_Maps.scalp_surface import (
    _camera_sensors, _cap_coordinates, _display_samples, _display_values, _geometry, _head_atlas, _rasterize_skin,
    _render_head, _scalp_field,
    _sensor_projection, build_scalp_surface_scene, draw_scalp_surface,
)


def _display_at(sites, values, points):
    key = sites.tobytes()
    samples = _display_samples(key, points, np.arange(len(points)))
    result = np.full(len(points), np.nan)
    result[samples.pixels] = _display_values(_scalp_field(key), samples, values)
    return result


def test_electrodes_follow_canonical_montage_directions_on_template():
    geometry = _geometry()
    info = biosemi64_info()
    projection = _sensor_projection(info)
    sensor_directions = projection.locations - geometry.origin
    np.testing.assert_allclose(_cap_coordinates(sensor_directions), projection.cap_coordinates, atol=1e-12)
    source = np.asarray([channel["loc"][:3] for channel in info["chs"]])
    np.testing.assert_allclose(projection.cap_coordinates, _cap_coordinates(source - geometry.origin), atol=1e-12)
    values = np.linspace(-1.0, 1.0, len(info.ch_names))
    np.testing.assert_allclose(_display_at(projection.cap_coordinates, values, projection.cap_coordinates), values)
    # The known frontal-left maximum must be on opposite horizontal sides
    # looking into the face and looking at the back of the participant.
    fp1, fp2, oz = map(info.ch_names.index, ("Fp1", "Fp2", "Oz"))
    front, back = (_render_head(view, 256) for view in ("front", "back"))
    front_xy, front_mask = _camera_sensors(front, "front", projection.locations)
    back_xy, back_mask = _camera_sensors(back, "back", projection.locations)
    assert front_xy[fp1, 0] > front_xy[fp2, 0]
    assert back_xy[fp1, 0] < back_xy[fp2, 0]
    assert front_mask[fp1] and not front_mask[oz]
    assert back_mask[oz] and not back_mask[fp1]
    assert front.extent == back.extent


def test_display_preserves_signed_values_without_extrapolation():
    tetra = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.]])
    values = np.array([-3., -1., 1., 3.])
    at = np.array([[0., 0.], [0.5, 0.5], [1., 1.], [2., 2.]])
    result = _display_at(tetra, values, at)
    np.testing.assert_allclose(result[:3], [-3., 0., 3.], atol=1e-14)
    assert np.isnan(result[-1])


def test_dense_jagged_field_matches_exact_sites_hull_and_subpercent_raster_accuracy():
    montage = mne.channels.make_standard_montage("biosemi256")
    info = mne.create_info(montage.ch_names, 100, "eeg").set_montage(montage)
    sites = _sensor_projection(info).cap_coordinates
    rng = np.random.default_rng(903)
    # The last interior point is near a steep part of the lateral ring. Both
    # exact and approximate rendering must leave the exterior point unpainted.
    probes = rng.uniform(sites.min(axis=0), sites.max(axis=0), (1800, 2))
    points = np.vstack((sites, probes, [1.61922, -0.41605], [3., 3.]))
    values = rng.choice([-1., 1.], len(sites))
    weights = natural_neighbor_weights(sites, points)
    expected = weights @ values
    supported = np.diff(weights.indptr) > 0
    actual = _display_at(sites, values, points)
    np.testing.assert_array_equal(np.isfinite(actual), supported)
    np.testing.assert_array_equal(actual[:len(sites)], values)
    assert np.all(np.abs(actual[supported]) <= 1 + 1e-13)
    np.testing.assert_allclose(actual[supported], expected[supported], atol=0.01 * np.ptp(values))


def test_viewer_and_export_paint_sibson_field_for_four_corner_electrodes():
    # The Sibson weight of the top-right corner of a square is the product
    # of its two fractional coordinates. Linear Delaunay interpolation would
    # instead choose one of the two diagonals and paint a ridge there.
    square = np.array([[-1., -1.], [1., -1.], [-1., 1.], [1., 1.]])
    angle = np.linalg.norm(square, axis=1)
    directions = np.column_stack((square * np.sinc(angle[:, None] / np.pi), np.cos(angle)))
    names = ["Back-L", "Back-R", "Front-L", "Front-R"]
    xyz = _geometry().origin + 0.095 * directions
    info = mne.create_info(names, 100, "eeg").set_montage(
        mne.channels.make_dig_montage(ch_pos=dict(zip(names, xyz, strict=True)), coord_frame="head")
    )
    values = np.array([0., 0., 0., 1.])
    cmap = matplotlib.colormaps["gray"]
    norm = Normalize(0, 1)

    scene = build_scalp_surface_scene(values, info, cmap=cmap, norm=norm)
    y, x = np.nonzero(scene.texture_rgba[::13, ::13, 3])
    y, x = y * 13, x * 13
    cap_xy = (np.column_stack((x, y)) + 0.5) * (2 * np.pi / scene.texture_rgba.shape[0]) - np.pi
    expected = cmap(np.prod((cap_xy + 1) / 2, axis=1), bytes=True)
    np.testing.assert_allclose(scene.texture_rgba[y, x], expected, atol=1)

    fig = Figure(figsize=(2, 3), dpi=96)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    draw_scalp_surface(ax, values, info, view="front", cmap=cmap, norm=norm)
    image = np.asarray(ax.images[0].get_array())
    head = _render_head("front", image.shape[1])
    supported = np.flatnonzero((np.abs(head.cap_coordinates) < 1).all(axis=1))[::13]
    assert len(supported) > 20
    expected = cmap(np.prod((head.cap_coordinates[supported] + 1) / 2, axis=1), bytes=True)
    actual = image.reshape(-1, 4)[head.pixel_indices[supported]]
    np.testing.assert_allclose(actual, expected, atol=1)


def test_interactive_texture_uses_export_values_and_never_wraps_under_chin():
    info = biosemi64_info()
    projection = _sensor_projection(info)
    # A linear signed gradient is reproduced exactly by cap interpolation.
    data = projection.cap_coordinates[:, 0]
    cmap = matplotlib.colormaps["coolwarm"]
    norm = Normalize(-2, 2)
    scene = build_scalp_surface_scene(data, info, cmap=cmap, norm=norm)
    np.testing.assert_allclose(scene.sensor_locations, projection.locations)
    assert np.all((scene.texture_coordinates >= 0) & (scene.texture_coordinates <= 1))
    assert len(scene.scalp_faces) < len(scene.faces)
    lowest = np.linalg.norm(projection.cap_coordinates, axis=1).max()
    vertex_angle = np.linalg.norm(_cap_coordinates(scene.vertices - scene.origin), axis=1)
    np.testing.assert_array_equal(scene.scalp_faces, scene.faces[(vertex_angle[scene.faces] <= lowest).any(axis=1)])
    height, width = scene.texture_rgba.shape[:2]
    supported = scene.texture_rgba[:, :, 3] > 0
    assert supported[height // 2, width // 2]
    assert not supported[0].any() and not supported[-1].any()
    # Texture column increases toward participant right, row toward anterior.
    y, x = np.nonzero(supported)
    x, y = x[::271], y[::271]
    expected_pigment = cmap(norm((x + 0.5) * 2 * np.pi / width - np.pi), bytes=True)
    rgb = scene.texture_rgba[y, x, :3].astype(float)
    palette = expected_pigment[:, :3].astype(float)
    gain = rgb.max(axis=1) / palette.max(axis=1)
    assert np.all((gain >= 0.77) & (gain <= 1.001))
    assert np.ptp(gain) > 0.05
    np.testing.assert_allclose(rgb, palette * gain[:, None], atol=1.1)
    assert np.all(scene.texture_rgba[y, x, 3] == 255)
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
    xy, expected = _camera_sensors(head, view, _sensor_projection(info).locations)
    expected[info.ch_names.index(missing)] = False
    np.testing.assert_allclose(ax.collections[0].get_offsets(), xy[expected])
    assert len(ax.collections[0].get_edgecolors()) == 0


@pytest.mark.parametrize("montage_name", ["GSN-HydroCel-128", "GSN-HydroCel-256", "easycap-M43"])
def test_dense_sensor_geometry_keeps_inferior_sites_and_stays_fixed_across_subsets(montage_name):
    montage = mne.channels.make_standard_montage(montage_name)
    info = mne.create_info(montage.ch_names, 100, "eeg").set_montage(montage)
    data = np.linspace(-1, 1, len(info.ch_names))
    projection = _sensor_projection(info)
    scene = build_scalp_surface_scene(data, info, cmap=matplotlib.colormaps["RdBu_r"], norm=Normalize(-1, 1))
    assert len(scene.sensor_locations) == len(info.ch_names)
    assert np.linalg.norm(projection.cap_coordinates, axis=1).max() > np.deg2rad(135)
    selected = np.arange(0, len(info.ch_names), 7)
    subset = _sensor_projection(mne.pick_info(info, selected.tolist()))
    np.testing.assert_allclose(subset.locations, projection.locations[selected], atol=1e-12)
    np.testing.assert_allclose(subset.cap_coordinates, projection.cap_coordinates[selected], atol=1e-12)
    plane = _geometry().neck_plane
    assert np.all(scene.sensor_locations @ plane[:3] + plane[3] > 0.001)
    assert ((scene.vertices @ plane[:3] + plane[3])[scene.scalp_faces] > 1e-7).any(axis=1).all()
    # A triangle straddling the projection's south pole would interpolate
    # unrelated scalp colors across the bottom of the neck. Check every
    # textured triangle against its independently projected spatial midpoint.
    centers = scene.vertices[scene.scalp_faces].mean(axis=1)
    mapped_centers = (scene.texture_coordinates[scene.scalp_faces].mean(axis=1) - 0.5) * (2 * np.pi)
    error = np.linalg.norm(mapped_centers - _cap_coordinates(centers - scene.origin), axis=1)
    assert error.max() < 0.05


def test_sensor_geometry_uses_positions_with_any_channel_names():
    positions = np.array([[.03, .07, .065], [-.03, .07, .065], [.02, .04, .105], [-.02, .04, .105]])
    names = ["A1", "X15", "P9", "animal"]
    montage = mne.channels.make_dig_montage(ch_pos=dict(zip(names, positions, strict=True)), coord_frame="head")
    info = mne.create_info(names, 100, "eeg").set_montage(montage)
    projection = _sensor_projection(info)
    np.testing.assert_allclose(projection.cap_coordinates, _cap_coordinates(positions - _geometry().origin))
    np.testing.assert_allclose(_sensor_projection(mne.pick_info(info, [2, 3])).locations, projection.locations[2:])


def test_automatic_color_limits_cover_the_full_texture():
    info = biosemi64_info()
    # The last scanline in the convex hull contains the largest values.
    coordinates = _sensor_projection(info).cap_coordinates
    norm = Normalize()
    scene = build_scalp_surface_scene(coordinates[:, 1], info, cmap=matplotlib.colormaps["viridis"], norm=norm)
    supported_rows = np.where(scene.texture_rgba[:, :, 3].any(axis=1))[0]
    size = scene.texture_rgba.shape[0]
    expected = (supported_rows[[0, -1]] + 0.5) * (2 * np.pi / size) - np.pi
    np.testing.assert_allclose([norm.vmin, norm.vmax], expected, atol=1e-14)


def test_named_electrodes_below_the_template_cannot_color_its_artificial_base():
    origin = _geometry().origin
    positions = {"Frontal": origin + [0, .08, .05], "Top": origin + [0, 0, .1],
                 "Below-L": origin + [-.004, -.024, -.08], "Below-R": origin + [.004, -.024, -.08]}
    montage = mne.channels.make_dig_montage(ch_pos=positions, coord_frame="head")
    info = mne.create_info(list(positions), 100, "eeg").set_montage(montage)
    with pytest.raises(ValueError, match="Below-L, Below-R.*2D top view"):
        _sensor_projection(info)
    uv, faces = _head_atlas(np.pi)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        assert np.linalg.norm(uv[faces[:, a]] - uv[faces[:, b]], axis=1).max() < 0.5


def test_scanlines_choose_nearest_triangle_independent_of_order_and_interpolate_shading():
    square_triangle = np.array([[0., 0.], [3., 0.], [0., 3.]])
    vertices = np.tile(square_triangle, (2, 1))
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    heights = np.array([1., 4., 1., 2.5, 2.5, 2.5])
    shades = np.array([100., 190., 130., 90., 90., 90.])
    for order in (faces, faces[::-1]):
        depth, gray = _rasterize_skin(vertices, order, heights, shades, 4, 4)
        assert depth[0, 0] == 2.5 and gray[0, 0] == 90
        assert depth[1, 2] == 3 and gray[1, 2] == 170
        assert np.isneginf(depth[3, 3])
