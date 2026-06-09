"""PyVista/VTK rendering adapter for the embedded LORETA visualizer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtWidgets import QVBoxLayout, QWidget

from Tools.LORETA_Visualizer.cortical_paint import (
    DEFAULT_CORTICAL_PAINT_Z_THRESHOLD,
    project_cortical_surface_payload,
    uses_cortical_surface_paint,
)
from Tools.LORETA_Visualizer.scalar_fields import (
    CORTICAL_PAINT_BASE_COLOR,
    DEFAULT_SCALAR_MAX,
    DEFAULT_SCALAR_MIN,
    LORETA_SCALAR_COLORS,
)
from Tools.LORETA_Visualizer.source_payloads import (
    SOURCE_KIND_ROI_MESH,
    SOURCE_KIND_SURFACE_MESH,
    SOURCE_KIND_SURFACE_POINTS,
    SOURCE_KIND_VOLUME_MESH,
    SOURCE_KIND_VOLUME_POINTS,
    SourcePayload,
)
from Tools.LORETA_Visualizer.synthetic_brain import BrainHemisphereMesh, BrainMesh, make_synthetic_brain_mesh
from Tools.LORETA_Visualizer.transforms import MeshDisplayTransform

logger = logging.getLogger(__name__)

DISPLAY_MODE_SPLIT_HEMISPHERE = "split_hemisphere"
DISPLAY_MODE_CORTICAL_SURFACE = "cortical_surface"
DISPLAY_MODE_TRANSPARENT_MESH = "transparent_mesh"
DISPLAY_MODES = (
    DISPLAY_MODE_SPLIT_HEMISPHERE,
    DISPLAY_MODE_CORTICAL_SURFACE,
    DISPLAY_MODE_TRANSPARENT_MESH,
)
SPLIT_HEMISPHERE_ROTATION_STEP_DEGREES = 12.0
_LEFT_HEMISPHERE_DEFAULT_YAW = 90.0
_RIGHT_HEMISPHERE_DEFAULT_YAW = -90.0
_LEFT_HEMISPHERE_OFFSET = (-1.08, 0.0, 0.0)
_RIGHT_HEMISPHERE_OFFSET = (1.08, 0.0, 0.0)
_PUBLICATION_HEMISPHERE_RADIUS = 0.82
_PUBLICATION_SHADE_DARK = "#636b6d"
_PUBLICATION_SHADE_LIGHT = "#d8dcda"


class RenderBackendError(RuntimeError):
    """Raised when the optional 3D rendering stack cannot initialize."""


@dataclass(frozen=True)
class _SplitHemisphereState:
    """Projected display values for one publication-layout hemisphere."""

    points: np.ndarray
    faces: np.ndarray
    values: np.ndarray
    shade_values: np.ndarray | None = None


class BrainRendererWidget(QWidget):
    """Widget wrapping a PyVista Qt interactor for real-time brain rendering."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_opacity: float = 0.48,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("loreta_brain_renderer")
        self._plotter: Any | None = None
        self._brain_actor: Any | None = None
        self._activation_actor: Any | None = None
        self._split_left_actor: Any | None = None
        self._split_right_actor: Any | None = None
        self._split_left_state: _SplitHemisphereState | None = None
        self._split_right_state: _SplitHemisphereState | None = None
        self._surface: Any | None = None
        self._current_mesh: BrainMesh | None = None
        self._brain_opacity = initial_opacity
        self._activation_opacity = 0.72
        self._activation_visible = True
        self._activation_scalar_range = (DEFAULT_SCALAR_MIN, DEFAULT_SCALAR_MAX)
        self._display_mode = DISPLAY_MODE_SPLIT_HEMISPHERE
        self._cortical_paint_active = False
        self._split_hemisphere_active = False
        self._split_left_rotation_degrees = 0.0
        self._split_right_rotation_degrees = 0.0
        self._cortical_paint_z_threshold = DEFAULT_CORTICAL_PAINT_Z_THRESHOLD
        self._last_activation_payload: SourcePayload | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            self._initialize_backend(layout, initial_opacity=initial_opacity)
        except Exception as exc:
            logger.warning("loreta_renderer_initialization_failed", extra={"error": str(exc)})
            raise RenderBackendError(str(exc)) from exc

    def _initialize_backend(self, layout: QVBoxLayout, *, initial_opacity: float) -> None:
        import pyvista as pv
        from pyvistaqt import QtInteractor

        plotter = QtInteractor(self)
        plotter.setObjectName("loreta_pyvista_interactor")
        plotter.set_background("#f7f9fc")
        plotter.enable_trackball_style()
        _configure_transparency_backend(plotter)
        layout.addWidget(plotter)
        self._plotter = plotter

        mesh = make_synthetic_brain_mesh()
        self._current_mesh = mesh
        self._surface = self._to_polydata(pv, mesh)
        self._brain_actor = self._add_brain_actor(self._surface)
        plotter.add_axes(interactive=False)
        plotter.camera_position = "xy"
        plotter.reset_camera()
        plotter.render()

    @staticmethod
    def _to_polydata(pv: Any, mesh: BrainMesh) -> Any:
        surface = pv.PolyData(mesh.points, mesh.faces)
        try:
            return surface.compute_normals(
                point_normals=True,
                cell_normals=False,
                split_vertices=False,
                consistent_normals=True,
                auto_orient_normals=True,
                feature_angle=90.0,
                inplace=False,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_mesh_normals_failed", exc_info=True)
            return surface

    @staticmethod
    def _apply_brain_material(actor: Any) -> None:
        try:
            prop = actor.GetProperty()
            prop.SetInterpolationToPhong()
            prop.SetEdgeVisibility(False)
            prop.SetAmbient(0.42)
            prop.SetDiffuse(0.72)
            prop.SetSpecular(0.20)
            prop.SetSpecularPower(16)
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("loreta_brain_material_failed", exc_info=True)

    @staticmethod
    def _to_surface_polydata(pv: Any, points: np.ndarray, faces: np.ndarray) -> Any:
        surface = pv.PolyData(points, faces)
        try:
            return surface.compute_normals(
                point_normals=True,
                cell_normals=False,
                split_vertices=False,
                consistent_normals=True,
                auto_orient_normals=True,
                feature_angle=90.0,
                inplace=False,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_surface_normals_failed", exc_info=True)
            return surface

    def _add_brain_actor(self, surface: Any) -> Any:
        plotter = self._plotter
        if plotter is None:
            return None
        actor = plotter.add_mesh(
            surface,
            color=CORTICAL_PAINT_BASE_COLOR,
            opacity=self._brain_opacity,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.22,
            specular_power=12,
            ambient=0.42,
            diffuse=0.72,
        )
        self._apply_brain_material(actor)
        return actor

    def _active_scalar_actors(self) -> tuple[Any, ...]:
        if self._split_hemisphere_active:
            return tuple(
                actor
                for actor in (self._split_left_actor, self._split_right_actor)
                if actor is not None
            )
        if self._cortical_paint_active and self._brain_actor is not None:
            return (self._brain_actor,)
        if self._activation_actor is not None:
            return (self._activation_actor,)
        return ()

    def _active_cortical_actors(self) -> tuple[Any, ...]:
        if self._split_hemisphere_active:
            return tuple(
                actor
                for actor in (self._split_left_actor, self._split_right_actor)
                if actor is not None
            )
        if self._brain_actor is not None:
            return (self._brain_actor,)
        return ()

    def _add_cortical_paint_actor(self, surface: Any) -> Any:
        plotter = self._plotter
        if plotter is None:
            return None
        actor = plotter.add_mesh(
            surface,
            scalars="activation",
            cmap=list(LORETA_SCALAR_COLORS),
            clim=self._activation_scalar_range,
            color=CORTICAL_PAINT_BASE_COLOR,
            nan_color=CORTICAL_PAINT_BASE_COLOR,
            nan_opacity=1.0,
            opacity=1.0,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.18,
            specular_power=12,
            ambient=0.48,
            diffuse=0.70,
            show_scalar_bar=False,
        )
        self._apply_brain_material(actor)
        return actor

    def _add_publication_split_actor(self, surface: Any) -> Any:
        plotter = self._plotter
        if plotter is None:
            return None
        actor = plotter.add_mesh(
            surface,
            scalars="publication_rgb",
            rgb=True,
            opacity=1.0,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.16,
            specular_power=10,
            ambient=0.58,
            diffuse=0.56,
            show_scalar_bar=False,
        )
        self._apply_publication_material(actor)
        return actor

    @staticmethod
    def _apply_publication_material(actor: Any) -> None:
        try:
            prop = actor.GetProperty()
            prop.SetInterpolationToPhong()
            prop.SetEdgeVisibility(False)
            prop.SetAmbient(0.58)
            prop.SetDiffuse(0.56)
            prop.SetSpecular(0.16)
            prop.SetSpecularPower(10)
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("loreta_publication_material_failed", exc_info=True)

    def set_brain_opacity(self, opacity: float) -> None:
        opacity = max(0.05, min(1.0, float(opacity)))
        self._brain_opacity = opacity
        plotter = self._plotter
        if plotter is None:
            return
        if self._cortical_paint_active:
            for actor in self._active_cortical_actors():
                actor.GetProperty().SetOpacity(1.0)
            plotter.render()
            return
        actor = self._brain_actor
        if actor is None:
            return
        actor.GetProperty().SetOpacity(opacity)
        plotter.render()

    def mesh_points(self) -> Any | None:
        mesh = self._current_mesh
        if mesh is None:
            return None
        return mesh.points

    def mesh_faces(self) -> Any | None:
        mesh = self._current_mesh
        if mesh is None:
            return None
        return mesh.faces

    def mesh_display_transform(self) -> MeshDisplayTransform | None:
        mesh = self._current_mesh
        if mesh is None:
            return None
        return mesh.display_transform

    def to_display_points(self, points: Any, *, coordinate_space: str | None = None) -> Any | None:
        transform = self.mesh_display_transform()
        if transform is None:
            return None
        return transform.to_display_points(points, coordinate_space=coordinate_space)

    def replace_brain_mesh(self, mesh: BrainMesh, *, reset_camera: bool = True) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        import pyvista as pv

        self._remove_brain_actor(render=False)
        self._remove_activation_actor(render=False)
        self._remove_split_hemisphere_actors(render=False)
        self._cortical_paint_active = False
        self._split_hemisphere_active = False
        self._split_left_state = None
        self._split_right_state = None
        self._last_activation_payload = None
        self._current_mesh = mesh
        self._surface = self._to_polydata(pv, mesh)
        self._brain_actor = self._add_brain_actor(self._surface)
        if reset_camera:
            plotter.reset_camera()
        plotter.render()

    def set_activation_payload(self, payload: SourcePayload) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        import pyvista as pv

        self._last_activation_payload = payload
        preserve_split_view = (
            self._display_mode == DISPLAY_MODE_SPLIT_HEMISPHERE
            and self._split_hemisphere_active
        )
        self._remove_activation_actor(render=False)
        self._remove_split_hemisphere_actors(render=False)
        self._split_hemisphere_active = False
        if len(payload.points) == 0:
            self._restore_base_brain_actor(render=False)
            plotter.render()
            return
        if uses_cortical_surface_paint(payload):
            if (
                self._display_mode == DISPLAY_MODE_SPLIT_HEMISPHERE
                and self._set_split_hemisphere_payload(payload, reset_camera=not preserve_split_view)
            ):
                plotter.render()
                return
            if self._display_mode == DISPLAY_MODE_CORTICAL_SURFACE and self._set_cortical_paint_payload(payload):
                plotter.render()
                return
        self._restore_base_brain_actor(render=False)
        self._add_activation_overlay(pv, payload)
        plotter.render()

    def _add_activation_overlay(self, pv: Any, payload: SourcePayload) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        mesh_kinds = {SOURCE_KIND_ROI_MESH, SOURCE_KIND_SURFACE_MESH, SOURCE_KIND_VOLUME_MESH}
        has_faces = payload.faces is not None and len(payload.faces) > 0
        if payload.kind in mesh_kinds and has_faces:
            cloud = pv.PolyData(payload.points, payload.faces)
            render_points_as_spheres = False
            point_size = 12
            style = "surface"
        else:
            cloud = pv.PolyData(payload.points)
            is_volume_points = payload.kind == SOURCE_KIND_VOLUME_POINTS
            is_surface_points = payload.kind == SOURCE_KIND_SURFACE_POINTS
            render_points_as_spheres = is_volume_points
            point_size = 14 if is_volume_points else 22
            style = "points_gaussian" if is_surface_points else "points"
        cloud["activation"] = payload.values
        self._activation_actor = plotter.add_mesh(
            cloud,
            scalars="activation",
            cmap=list(LORETA_SCALAR_COLORS),
            clim=self._activation_scalar_range,
            opacity=self._activation_opacity,
            render_points_as_spheres=render_points_as_spheres,
            point_size=point_size,
            style=style,
            lighting=False,
            ambient=1.0,
            diffuse=0.0,
            specular=0.0,
            smooth_shading=payload.kind in mesh_kinds and has_faces,
            show_scalar_bar=False,
        )
        self._activation_actor.SetVisibility(self._activation_visible)

    def _set_cortical_paint_payload(self, payload: SourcePayload) -> bool:
        mesh = self._current_mesh
        surface = self._surface
        if mesh is None or surface is None:
            return False
        try:
            projection = project_cortical_surface_payload(
                mesh.points,
                payload,
                z_threshold=self._cortical_paint_z_threshold,
            )
            paint_surface = surface.copy(deep=True)
            paint_surface["activation"] = projection.values
        except (ImportError, ModuleNotFoundError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_cortical_paint_projection_failed", extra={"error": str(exc)})
            return False

        self._remove_brain_actor(render=False)
        self._remove_split_hemisphere_actors(render=False)
        self._brain_actor = self._add_cortical_paint_actor(paint_surface)
        self._cortical_paint_active = True
        self._split_hemisphere_active = False
        self._set_cortical_paint_scalar_visibility(self._activation_visible)
        return True

    def _set_split_hemisphere_payload(self, payload: SourcePayload, *, reset_camera: bool = True) -> bool:
        mesh = self._current_mesh
        if mesh is None or mesh.left_hemisphere is None or mesh.right_hemisphere is None:
            return False
        try:
            left_state = self._project_split_hemisphere(mesh.left_hemisphere, payload)
            right_state = self._project_split_hemisphere(mesh.right_hemisphere, payload)
        except (ImportError, ModuleNotFoundError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("loreta_split_hemisphere_projection_failed", extra={"error": str(exc)})
            return False

        self._remove_brain_actor(render=False)
        self._remove_activation_actor(render=False)
        self._split_left_state = left_state
        self._split_right_state = right_state
        self._cortical_paint_active = True
        self._split_hemisphere_active = True
        self._render_split_hemispheres(render=False)
        if reset_camera:
            self._set_publication_camera()
        return True

    def _project_split_hemisphere(
        self,
        hemisphere: BrainHemisphereMesh,
        payload: SourcePayload,
    ) -> _SplitHemisphereState:
        projection_points = (
            np.asarray(hemisphere.projection_points, dtype=float)
            if hemisphere.projection_points is not None
            else np.asarray(hemisphere.points, dtype=float)
        )
        display_points = np.asarray(hemisphere.points, dtype=float)
        if len(projection_points) != len(display_points):
            raise ValueError("Split hemisphere display and projection points must align one-to-one.")
        projection = project_cortical_surface_payload(
            projection_points,
            payload,
            z_threshold=self._cortical_paint_z_threshold,
        )
        return _SplitHemisphereState(
            points=display_points.copy(),
            faces=np.asarray(hemisphere.faces, dtype=np.int64).copy(),
            values=np.asarray(projection.values, dtype=float),
            shade_values=(
                np.asarray(hemisphere.shade_values, dtype=float).copy()
                if hemisphere.shade_values is not None and len(hemisphere.shade_values) == len(display_points)
                else None
            ),
        )

    def _render_split_hemispheres(self, *, render: bool) -> None:
        plotter = self._plotter
        left_state = self._split_left_state
        right_state = self._split_right_state
        if plotter is None or left_state is None or right_state is None:
            return
        import pyvista as pv

        self._remove_split_hemisphere_actors(render=False)
        left_surface = self._split_state_to_surface(pv, left_state, side="left")
        right_surface = self._split_state_to_surface(pv, right_state, side="right")
        self._split_left_actor = self._add_publication_split_actor(left_surface)
        self._split_right_actor = self._add_publication_split_actor(right_surface)
        if render:
            plotter.render()

    def _split_state_to_surface(self, pv: Any, state: _SplitHemisphereState, *, side: str) -> Any:
        points = _publication_hemisphere_points(
            state.points,
            side=side,
            extra_yaw_degrees=(
                self._split_left_rotation_degrees
                if side == "left"
                else self._split_right_rotation_degrees
            ),
        )
        surface = self._to_surface_polydata(pv, points, state.faces)
        surface["publication_rgb"] = _publication_surface_rgb(
            state.values,
            state.shade_values,
            scalar_range=self._activation_scalar_range,
            activation_visible=self._activation_visible,
        )
        return surface

    def set_display_mode(self, display_mode: str) -> None:
        mode = display_mode if display_mode in DISPLAY_MODES else DISPLAY_MODE_SPLIT_HEMISPHERE
        if mode == self._display_mode:
            return
        self._display_mode = mode
        if mode == DISPLAY_MODE_SPLIT_HEMISPHERE:
            self._reset_split_rotations()
        payload = self._last_activation_payload
        if payload is not None:
            self.set_activation_payload(payload)
            return
        self._restore_base_brain_actor(render=True)

    def display_mode(self) -> str:
        return self._display_mode

    def rotate_split_hemisphere(self, side: str, degrees: float) -> None:
        if side == "left":
            self._split_left_rotation_degrees += float(degrees)
        elif side == "right":
            self._split_right_rotation_degrees += float(degrees)
        else:
            return
        if self._split_hemisphere_active:
            self._render_split_hemispheres(render=True)

    def _reset_split_rotations(self) -> None:
        self._split_left_rotation_degrees = 0.0
        self._split_right_rotation_degrees = 0.0

    def _set_publication_camera(self) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        try:
            plotter.reset_camera()
            plotter.camera.SetPosition(0.0, -5.0, 0.25)
            plotter.camera.SetFocalPoint(0.0, 0.0, 0.0)
            plotter.camera.SetViewUp(0.0, 0.0, 1.0)
            plotter.reset_camera_clipping_range()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_publication_camera_failed", exc_info=True)
            plotter.camera_position = "xy"

    def set_cortical_paint_z_threshold(self, threshold: float) -> None:
        numeric_threshold = max(0.0, float(threshold))
        self._cortical_paint_z_threshold = numeric_threshold
        payload = self._last_activation_payload
        if self._cortical_paint_active and payload is not None:
            self.set_activation_payload(payload)

    def _restore_base_brain_actor(self, *, render: bool) -> None:
        if not self._cortical_paint_active:
            return
        plotter = self._plotter
        surface = self._surface
        if plotter is None or surface is None:
            return
        self._remove_brain_actor(render=False)
        self._remove_split_hemisphere_actors(render=False)
        self._brain_actor = self._add_brain_actor(surface)
        self._cortical_paint_active = False
        self._split_hemisphere_active = False
        if render:
            plotter.render()

    def set_activation_scalar_range(self, vmin: float, vmax: float) -> None:
        if vmax <= vmin:
            vmax = vmin + 1.0
        self._activation_scalar_range = (float(vmin), float(vmax))
        if self._split_hemisphere_active:
            self._render_split_hemispheres(render=True)
            return
        actors = self._active_scalar_actors()
        plotter = self._plotter
        if not actors or plotter is None:
            return
        for actor in actors:
            mapper = self._actor_mapper(actor)
            if mapper is not None:
                try:
                    mapper.SetScalarRange(*self._activation_scalar_range)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    logger.debug("loreta_activation_scalar_range_failed", exc_info=True)
        plotter.render()

    def set_activation_opacity(self, opacity: float) -> None:
        opacity = max(0.0, min(1.0, float(opacity)))
        self._activation_opacity = opacity
        actor = self._activation_actor
        plotter = self._plotter
        if actor is None or plotter is None:
            return
        actor.GetProperty().SetOpacity(opacity)
        plotter.render()

    def set_activation_visible(self, visible: bool) -> None:
        self._activation_visible = bool(visible)
        plotter = self._plotter
        if plotter is None:
            return
        if self._cortical_paint_active:
            if self._split_hemisphere_active:
                self._render_split_hemispheres(render=False)
            else:
                self._set_cortical_paint_scalar_visibility(self._activation_visible)
            plotter.render()
            return
        actor = self._activation_actor
        if actor is None:
            return
        actor.SetVisibility(self._activation_visible)
        plotter.render()

    @staticmethod
    def _actor_mapper(actor: Any) -> Any | None:
        mapper = getattr(actor, "mapper", None)
        if mapper is not None:
            return mapper
        try:
            return actor.GetMapper()
        except (AttributeError, RuntimeError, TypeError):
            return None

    def _set_cortical_paint_scalar_visibility(self, visible: bool) -> None:
        actor = self._brain_actor
        if actor is None:
            return
        self._set_actor_scalar_visibility(actor, visible)

    def _set_split_scalar_visibility(self, visible: bool) -> None:
        for actor in self._active_cortical_actors():
            self._set_actor_scalar_visibility(actor, visible)

    def _set_actor_scalar_visibility(self, actor: Any, visible: bool) -> None:
        mapper = self._actor_mapper(actor)
        if mapper is not None:
            try:
                mapper.SetScalarVisibility(bool(visible))
            except (AttributeError, RuntimeError, TypeError):
                logger.debug("loreta_cortical_paint_visibility_failed", exc_info=True)
        try:
            prop = actor.GetProperty()
            prop.SetColor(*_hex_to_rgb(CORTICAL_PAINT_BASE_COLOR))
            prop.SetOpacity(1.0)
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("loreta_cortical_paint_base_material_failed", exc_info=True)

    def _remove_brain_actor(self, *, render: bool) -> None:
        plotter = self._plotter
        actor = self._brain_actor
        self._brain_actor = None
        if plotter is None or actor is None:
            return
        try:
            plotter.remove_actor(actor, render=render)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_remove_previous_actor_failed", exc_info=True)

    def _remove_activation_actor(self, *, render: bool) -> None:
        plotter = self._plotter
        actor = self._activation_actor
        self._activation_actor = None
        if plotter is None or actor is None:
            return
        try:
            plotter.remove_actor(actor, render=render)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_remove_activation_actor_failed", exc_info=True)

    def _remove_split_hemisphere_actors(self, *, render: bool) -> None:
        plotter = self._plotter
        actors = (self._split_left_actor, self._split_right_actor)
        self._split_left_actor = None
        self._split_right_actor = None
        if plotter is None:
            return
        for actor in actors:
            if actor is None:
                continue
            try:
                plotter.remove_actor(actor, render=render)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("loreta_remove_split_hemisphere_actor_failed", exc_info=True)

    def zoom_in(self) -> None:
        self.zoom(1.18)

    def zoom_out(self) -> None:
        self.zoom(0.84)

    def zoom(self, factor: float) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        plotter.camera.Zoom(float(factor))
        plotter.render()

    def reset_camera(self) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        if self._split_hemisphere_active:
            self._reset_split_rotations()
            self._render_split_hemispheres(render=False)
            self._set_publication_camera()
            plotter.render()
            return
        plotter.camera_position = "xy"
        plotter.reset_camera()
        plotter.render()

    def shutdown(self) -> None:
        plotter = self._plotter
        self._plotter = None
        self._brain_actor = None
        self._activation_actor = None
        self._split_left_actor = None
        self._split_right_actor = None
        self._split_left_state = None
        self._split_right_state = None
        self._surface = None
        self._current_mesh = None
        self._cortical_paint_active = False
        self._split_hemisphere_active = False
        self._last_activation_payload = None
        if plotter is None:
            return
        try:
            plotter.close()
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("loreta_renderer_close_failed", exc_info=True)


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    if len(value) != 6:
        return (0.79, 0.80, 0.82)
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _configure_transparency_backend(plotter: Any) -> None:
    """Prefer driver-tolerant alpha blending for translucent brain meshes."""
    try:
        plotter.disable_depth_peeling()
    except AttributeError:
        try:
            plotter.renderer.SetUseDepthPeeling(False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_depth_peeling_disable_unavailable", exc_info=True)
    except (RuntimeError, TypeError, ValueError):
        logger.debug("loreta_depth_peeling_disable_failed", exc_info=True)


def _publication_surface_rgb(
    values: np.ndarray,
    shade_values: np.ndarray | None,
    *,
    scalar_range: tuple[float, float],
    activation_visible: bool,
) -> np.ndarray:
    scalar_values = np.asarray(values, dtype=float).reshape(-1)
    colors = _publication_base_rgb(len(scalar_values), shade_values)
    if not activation_visible:
        return colors
    finite = np.isfinite(scalar_values)
    if not np.any(finite):
        return colors
    colors[finite] = _scalar_values_to_rgb(scalar_values[finite], scalar_range=scalar_range)
    return colors


def _publication_base_rgb(count: int, shade_values: np.ndarray | None) -> np.ndarray:
    if count <= 0:
        return np.empty((0, 3), dtype=np.uint8)
    if shade_values is None:
        shade = np.full(count, 0.58, dtype=float)
    else:
        shade = np.asarray(shade_values, dtype=float).reshape(-1)
        if len(shade) != count:
            shade = np.full(count, 0.58, dtype=float)
        else:
            shade = np.where(np.isfinite(shade), shade, 0.58)
    shade = np.clip(shade, 0.0, 1.0)
    dark = np.asarray(_hex_to_rgb(_PUBLICATION_SHADE_DARK), dtype=float)
    light = np.asarray(_hex_to_rgb(_PUBLICATION_SHADE_LIGHT), dtype=float)
    rgb = dark + shade[:, np.newaxis] * (light - dark)
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)


def _scalar_values_to_rgb(values: np.ndarray, *, scalar_range: tuple[float, float]) -> np.ndarray:
    scalar_values = np.asarray(values, dtype=float).reshape(-1)
    vmin, vmax = float(scalar_range[0]), float(scalar_range[1])
    if vmax <= vmin:
        vmax = vmin + 1.0
    t = np.clip((scalar_values - vmin) / (vmax - vmin), 0.0, 1.0)
    ramp = np.asarray([_hex_to_rgb(color) for color in LORETA_SCALAR_COLORS], dtype=float)
    position = t * (len(ramp) - 1)
    lower_index = np.floor(position).astype(np.int64)
    upper_index = np.clip(lower_index + 1, 0, len(ramp) - 1)
    mix = (position - lower_index)[:, np.newaxis]
    rgb = ramp[lower_index] * (1.0 - mix) + ramp[upper_index] * mix
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)


def _publication_hemisphere_points(
    points: np.ndarray,
    *,
    side: str,
    extra_yaw_degrees: float = 0.0,
) -> np.ndarray:
    hemisphere_points = np.asarray(points, dtype=float)
    if hemisphere_points.ndim != 2 or hemisphere_points.shape[1] != 3 or len(hemisphere_points) == 0:
        return hemisphere_points.copy()
    if side == "right":
        default_yaw = _RIGHT_HEMISPHERE_DEFAULT_YAW
        offset = np.asarray(_RIGHT_HEMISPHERE_OFFSET, dtype=float)
    else:
        default_yaw = _LEFT_HEMISPHERE_DEFAULT_YAW
        offset = np.asarray(_LEFT_HEMISPHERE_OFFSET, dtype=float)
    centered = hemisphere_points - np.mean(hemisphere_points, axis=0)
    radius = float(np.max(np.linalg.norm(centered, axis=1)))
    if np.isfinite(radius) and radius > 1e-9:
        centered = centered * (_PUBLICATION_HEMISPHERE_RADIUS / radius)
    rotated = centered @ _rotation_z(default_yaw + float(extra_yaw_degrees)).T
    return rotated + offset


def _rotation_z(degrees: float) -> np.ndarray:
    radians = np.deg2rad(float(degrees))
    cos_value = float(np.cos(radians))
    sin_value = float(np.sin(radians))
    return np.asarray(
        [
            [cos_value, -sin_value, 0.0],
            [sin_value, cos_value, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
