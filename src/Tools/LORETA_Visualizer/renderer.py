"""PyVista/VTK rendering adapter for the embedded LORETA visualizer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    apply_matplotlib_figure_style,
    figure_text_spec,
    pil_font_candidates,
)
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
DEFAULT_SPLIT_FIGURE_WIDTH = 1950
DEFAULT_SPLIT_FIGURE_WIDTH_IN = 6.5
DEFAULT_SPLIT_FIGURE_SINGLE_HEIGHT_IN = 3.0
DEFAULT_SPLIT_FIGURE_STACK_HEIGHT_IN = 6.75
DEFAULT_SPLIT_FIGURE_MAX_FACES_PER_HEMISPHERE: int | None = None
_SPLIT_FIGURE_UNITS_PER_INCH = DEFAULT_SPLIT_FIGURE_WIDTH / DEFAULT_SPLIT_FIGURE_WIDTH_IN
SPLIT_FIGURE_EXPORT_DPI = FIGURE_EXPORT_DPI


class RenderBackendError(RuntimeError):
    """Raised when the optional 3D rendering stack cannot initialize."""


@dataclass(frozen=True)
class _SplitHemisphereState:
    """Projected display values for one publication-layout hemisphere."""

    points: np.ndarray
    faces: np.ndarray
    values: np.ndarray
    shade_values: np.ndarray | None = None


@dataclass(frozen=True)
class PublicationSplitFigurePanel:
    """One labeled split-hemisphere panel for figure export."""

    label: str
    left_state: _SplitHemisphereState
    right_state: _SplitHemisphereState
    scalar_range: tuple[float, float]
    activation_visible: bool
    left_rotation_degrees: float = 0.0
    right_rotation_degrees: float = 0.0


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
            paint_surface["activation"] = _cortical_paint_display_values(
                projection.values,
                scalar_range=self._activation_scalar_range,
            )
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
        if self._cortical_paint_active:
            payload = self._last_activation_payload
            if payload is not None:
                self.set_activation_payload(payload)
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

    def can_export_split_hemisphere_figure(self) -> bool:
        return self._split_hemisphere_active and self._split_left_state is not None and self._split_right_state is not None

    def split_hemisphere_figure_panel_for_payload(
        self,
        payload: SourcePayload,
        *,
        label: str = "",
        scalar_range: tuple[float, float] | None = None,
    ) -> PublicationSplitFigurePanel:
        """Prepare a split-hemisphere figure panel without changing the live renderer."""
        mesh = self._current_mesh
        if mesh is None or mesh.left_hemisphere is None or mesh.right_hemisphere is None:
            raise RuntimeError("Split-hemisphere figure export requires fsaverage hemisphere meshes.")
        return PublicationSplitFigurePanel(
            label=label,
            left_state=self._project_split_hemisphere(mesh.left_hemisphere, payload),
            right_state=self._project_split_hemisphere(mesh.right_hemisphere, payload),
            scalar_range=scalar_range or self._activation_scalar_range,
            activation_visible=self._activation_visible,
            left_rotation_degrees=self._split_left_rotation_degrees,
            right_rotation_degrees=self._split_right_rotation_degrees,
        )

    def write_split_hemisphere_figures(self, output_path: str | Path) -> tuple[Path, Path]:
        if not self.can_export_split_hemisphere_figure():
            raise RuntimeError("Publication split hemispheres must be visible before exporting figures.")
        return write_publication_split_hemisphere_figures(
            output_path,
            left_state=self._split_left_state,
            right_state=self._split_right_state,
            scalar_range=self._activation_scalar_range,
            activation_visible=self._activation_visible,
            left_rotation_degrees=self._split_left_rotation_degrees,
            right_rotation_degrees=self._split_right_rotation_degrees,
        )

    def write_split_hemisphere_stack_figures(
        self,
        output_path: str | Path,
        *,
        panels: Sequence[PublicationSplitFigurePanel],
    ) -> tuple[Path, Path]:
        return write_publication_split_hemisphere_stack_figures(output_path, panels=panels)

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


def write_publication_split_hemisphere_figures(
    output_path: str | Path,
    *,
    left_state: _SplitHemisphereState,
    right_state: _SplitHemisphereState,
    scalar_range: tuple[float, float],
    activation_visible: bool,
    left_rotation_degrees: float = 0.0,
    right_rotation_degrees: float = 0.0,
    width_inches: float = DEFAULT_SPLIT_FIGURE_WIDTH_IN,
    height_inches: float = DEFAULT_SPLIT_FIGURE_SINGLE_HEIGHT_IN,
    dpi: int = SPLIT_FIGURE_EXPORT_DPI,
    max_faces_per_hemisphere: int | None = DEFAULT_SPLIT_FIGURE_MAX_FACES_PER_HEMISPHERE,
) -> tuple[Path, Path]:
    """Write 600 DPI PDF and PNG files for the current split-hemisphere view."""
    panel = PublicationSplitFigurePanel(
        label="",
        left_state=left_state,
        right_state=right_state,
        scalar_range=scalar_range,
        activation_visible=activation_visible,
        left_rotation_degrees=left_rotation_degrees,
        right_rotation_degrees=right_rotation_degrees,
    )
    return _write_publication_split_figures(
        output_path,
        panels=(panel,),
        width_inches=width_inches,
        height_inches=height_inches,
        dpi=dpi,
        max_faces_per_hemisphere=max_faces_per_hemisphere,
    )


def write_publication_split_hemisphere_stack_figures(
    output_path: str | Path,
    *,
    panels: Sequence[PublicationSplitFigurePanel],
    width_inches: float = DEFAULT_SPLIT_FIGURE_WIDTH_IN,
    height_inches: float = DEFAULT_SPLIT_FIGURE_STACK_HEIGHT_IN,
    dpi: int = SPLIT_FIGURE_EXPORT_DPI,
    max_faces_per_hemisphere: int | None = DEFAULT_SPLIT_FIGURE_MAX_FACES_PER_HEMISPHERE,
) -> tuple[Path, Path]:
    """Write 600 DPI PDF and PNG files for stacked split-hemisphere panels."""
    return _write_publication_split_figures(
        output_path,
        panels=panels,
        width_inches=width_inches,
        height_inches=height_inches,
        dpi=dpi,
        max_faces_per_hemisphere=max_faces_per_hemisphere,
    )


def _write_publication_split_figures(
    output_path: str | Path,
    *,
    panels: Sequence[PublicationSplitFigurePanel],
    width_inches: float,
    height_inches: float,
    dpi: int,
    max_faces_per_hemisphere: int | None,
) -> tuple[Path, Path]:
    path = Path(output_path)
    base_path = path.with_suffix("")
    pdf_path = base_path.with_suffix(".pdf")
    png_path = base_path.with_suffix(".png")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if not panels:
        raise RuntimeError("At least one split-hemisphere panel is required for figure export.")

    width = max(1, int(round(float(width_inches) * int(dpi))))
    height = max(1, int(round(float(height_inches) * int(dpi))))
    prepared_panels = _prepare_split_figure_panels(
        panels,
        max_faces_per_hemisphere=max_faces_per_hemisphere,
    )
    image = _render_publication_split_image(
        prepared_panels,
        width=width,
        height=height,
    )
    image.save(png_path, format="PNG", dpi=(int(dpi), int(dpi)))
    _save_publication_split_pdf(
        image,
        pdf_path,
        width_inches=width_inches,
        height_inches=height_inches,
        dpi=int(dpi),
    )
    return pdf_path, png_path


def _prepare_split_figure_panels(
    panels: Sequence[PublicationSplitFigurePanel],
    *,
    max_faces_per_hemisphere: int | None,
) -> list[tuple[PublicationSplitFigurePanel, dict[str, Any], dict[str, Any]]]:
    prepared_panels = []
    for panel in panels:
        left = _figure_surface_faces(
            panel.left_state,
            side="left",
            extra_yaw_degrees=panel.left_rotation_degrees,
            scalar_range=panel.scalar_range,
            activation_visible=panel.activation_visible,
            max_faces=max_faces_per_hemisphere,
        )
        right = _figure_surface_faces(
            panel.right_state,
            side="right",
            extra_yaw_degrees=panel.right_rotation_degrees,
            scalar_range=panel.scalar_range,
            activation_visible=panel.activation_visible,
            max_faces=max_faces_per_hemisphere,
        )
        prepared_panels.append((panel, left, right))
    if not any(left["faces"] or right["faces"] for _panel, left, right in prepared_panels):
        raise RuntimeError("No split-hemisphere triangles are available for figure export.")
    return prepared_panels


def _render_publication_split_image(
    prepared_panels: Sequence[tuple[PublicationSplitFigurePanel, dict[str, Any], dict[str, Any]]],
    *,
    width: int,
    height: int,
):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (int(width), int(height)), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    panel_count = len(prepared_panels)
    scale = float(width) / float(DEFAULT_SPLIT_FIGURE_WIDTH)
    legend_reserved_height = 225.0 * scale
    panel_height = max((float(height) - legend_reserved_height) / panel_count, 1.0)
    for index, (panel, left, right) in enumerate(prepared_panels):
        _draw_split_figure_panel(
            draw,
            panel,
            left,
            right,
            width=width,
            panel_top=float(index) * panel_height,
            panel_height=panel_height,
            show_condition_label=panel_count > 1,
            show_hemisphere_labels=index == 0,
            scale_factor=scale,
        )
    _draw_split_figure_legend(
        draw,
        width=width,
        height=height,
        scalar_range=prepared_panels[-1][0].scalar_range,
        scale_factor=scale,
    )
    return image


def _draw_split_figure_panel(
    draw,
    panel: PublicationSplitFigurePanel,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    width: int,
    panel_top: float,
    panel_height: float,
    show_condition_label: bool,
    show_hemisphere_labels: bool,
    scale_factor: float,
) -> None:
    all_points = np.vstack((left["points_2d"], right["points_2d"]))
    min_xy = np.min(all_points, axis=0)
    max_xy = np.max(all_points, axis=0)
    span = np.maximum(max_xy - min_xy, 1e-9)
    side_margin = 110.0 * scale_factor
    top_margin = (120.0 if show_condition_label else 105.0) * scale_factor
    bottom_margin = 35.0 * scale_factor
    draw_width = max(float(width) - 2.0 * side_margin, 1.0)
    draw_height = max(float(panel_height) - top_margin - bottom_margin, 1.0)
    coordinate_scale = min(draw_width / float(span[0]), draw_height / float(span[1]))
    used_width = float(span[0]) * coordinate_scale
    x_offset = (float(width) - used_width) / 2.0 - float(min_xy[0]) * coordinate_scale
    y_offset = panel_top + top_margin + float(max_xy[1]) * coordinate_scale

    face_rows = []
    for surface in (left, right):
        screen = np.column_stack(
            (
                surface["points_2d"][:, 0] * coordinate_scale + x_offset,
                y_offset - surface["points_2d"][:, 1] * coordinate_scale,
            )
        )
        for face in surface["faces"]:
            triangle = screen[face["triangle"]]
            if not np.all(np.isfinite(triangle)):
                continue
            face_rows.append((float(face["depth"]), triangle, face["color"]))
    face_rows.sort(key=lambda row: row[0], reverse=True)

    for _depth, triangle, color in face_rows:
        draw.polygon(
            [(float(point[0]), float(point[1])) for point in triangle],
            fill=_hex_to_rgba(color),
        )

    left_center = _figure_label_center(left["points_2d"], scale=coordinate_scale, x_offset=x_offset)
    right_center = _figure_label_center(right["points_2d"], scale=coordinate_scale, x_offset=x_offset)
    if show_condition_label and panel.label.strip():
        _draw_centered_text(
            draw,
            float(width) / 2.0,
            panel_top + 54.0 * scale_factor,
            panel.label.strip(),
            role="condition_label",
            scale_factor=scale_factor,
        )
    if show_hemisphere_labels:
        label_y = panel_top + (88.0 if show_condition_label else 70.0) * scale_factor
        _draw_centered_text(draw, left_center, label_y, "Left", role="axis_label", scale_factor=scale_factor)
        _draw_centered_text(draw, right_center, label_y, "Right", role="axis_label", scale_factor=scale_factor)


def _draw_split_figure_legend(
    draw,
    *,
    width: int,
    height: int,
    scalar_range: tuple[float, float],
    scale_factor: float,
) -> None:
    legend_width = int(round(860 * scale_factor))
    legend_height = int(round(52 * scale_factor))
    legend_x = (int(width) - legend_width) / 2.0
    legend_y = int(height) - 150.0 * scale_factor
    ramp = np.asarray([_hex_to_rgb(color) for color in LORETA_SCALAR_COLORS], dtype=float)
    max_x = max(legend_width - 1, 1)
    for x in range(legend_width):
        t = x / max_x
        position = t * (len(ramp) - 1)
        lower = int(np.floor(position))
        upper = min(lower + 1, len(ramp) - 1)
        mix = position - lower
        rgb = ramp[lower] * (1.0 - mix) + ramp[upper] * mix
        rgba = tuple(np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8).tolist()) + (255,)
        draw.line(
            (
                (legend_x + x, legend_y),
                (legend_x + x, legend_y + legend_height),
            ),
            fill=rgba,
        )
    stroke_width = max(1, int(round(2 * scale_factor)))
    draw.rectangle(
        [
            (legend_x, legend_y),
            (legend_x + legend_width, legend_y + legend_height),
        ],
        outline="#111111",
        width=stroke_width,
    )
    label_y = legend_y + legend_height + 54.0 * scale_factor
    vmin, vmax = scalar_range
    _draw_centered_text(
        draw,
        legend_x,
        label_y,
        _format_figure_scalar(vmin),
        role="tick_label",
        scale_factor=scale_factor,
    )
    _draw_centered_text(
        draw,
        legend_x + legend_width,
        label_y,
        _format_figure_scalar(vmax),
        role="tick_label",
        scale_factor=scale_factor,
    )


def _save_publication_split_pdf(
    image,
    output_path: Path,
    *,
    width_inches: float,
    height_inches: float,
    dpi: int,
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    apply_matplotlib_figure_style()
    fig = plt.figure(figsize=(float(width_inches), float(height_inches)), dpi=dpi)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.imshow(image, interpolation="nearest")
    try:
        fig.savefig(output_path, format="pdf", dpi=dpi, transparent=True)
    finally:
        plt.close(fig)


def _draw_centered_text(
    draw,
    x: float,
    y: float,
    text: str,
    *,
    role: str,
    scale_factor: float,
) -> None:
    font = _pil_font(role, scale_factor=scale_factor)
    draw.text((float(x), float(y)), str(text), fill="#111111", font=font, anchor="mm")


def _pil_font(role: str, *, scale_factor: float):
    from PIL import ImageFont

    spec = figure_text_spec(role)
    size = max(8, int(round(spec.point_size * _SPLIT_FIGURE_UNITS_PER_INCH * scale_factor / 72.0)))
    bold = str(spec.weight).lower() == "bold"
    for candidate in pil_font_candidates(bold=bold):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _figure_surface_faces(
    state: _SplitHemisphereState,
    *,
    side: str,
    extra_yaw_degrees: float,
    scalar_range: tuple[float, float],
    activation_visible: bool,
    max_faces: int | None,
) -> dict[str, Any]:
    points_3d = _publication_hemisphere_points(
        state.points,
        side=side,
        extra_yaw_degrees=extra_yaw_degrees,
    )
    triangles = _vtk_faces_to_triangle_rows(state.faces, point_count=len(points_3d))
    colors = _publication_surface_rgb(
        state.values,
        state.shade_values,
        scalar_range=scalar_range,
        activation_visible=activation_visible,
    )
    face_rows: list[dict[str, Any]] = []
    for triangle in triangles:
        triangle_points = points_3d[triangle]
        face_color = np.mean(colors[triangle], axis=0)
        face_rows.append(
            {
                "triangle": triangle,
                "depth": float(np.mean(triangle_points[:, 1])),
                "color": _rgb_to_hex(face_color),
                "active": bool(activation_visible and np.any(np.isfinite(state.values[triangle]))),
            }
        )
    return {
        "points_2d": points_3d[:, [0, 2]],
        "faces": _limit_figure_face_rows(face_rows, max_faces),
    }


def _limit_figure_face_rows(face_rows: list[dict[str, Any]], max_faces: int | None) -> list[dict[str, Any]]:
    if max_faces is None or max_faces <= 0 or len(face_rows) <= max_faces:
        return face_rows
    active_rows = [row for row in face_rows if row.get("active")]
    base_rows = [row for row in face_rows if not row.get("active")]
    if not active_rows:
        return _sample_figure_face_rows(face_rows, max_faces)
    base_budget = min(len(base_rows), max(1, max_faces // 4))
    active_budget = max(max_faces - base_budget, 0)
    sampled_active = _sample_figure_face_rows(active_rows, active_budget)
    sampled_base = _sample_figure_face_rows(base_rows, max_faces - len(sampled_active))
    return [*sampled_active, *sampled_base]


def _sample_figure_face_rows(face_rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    if len(face_rows) <= count:
        return face_rows
    indices = np.linspace(0, len(face_rows) - 1, count, dtype=np.int64)
    return [face_rows[int(index)] for index in indices]


def _vtk_faces_to_triangle_rows(faces: np.ndarray, *, point_count: int) -> np.ndarray:
    face_array = np.asarray(faces, dtype=np.int64)
    if face_array.ndim == 1:
        if len(face_array) % 4 != 0:
            raise ValueError("Figure export requires VTK triangular face records.")
        vtk_faces = face_array.reshape(-1, 4)
        if not np.all(vtk_faces[:, 0] == 3):
            raise ValueError("Figure export requires triangular faces.")
        triangles = vtk_faces[:, 1:4]
    elif face_array.ndim == 2 and face_array.shape[1] == 3:
        triangles = face_array
    elif face_array.ndim == 2 and face_array.shape[1] == 4:
        if not np.all(face_array[:, 0] == 3):
            raise ValueError("Figure export requires triangular faces.")
        triangles = face_array[:, 1:4]
    else:
        raise ValueError("Figure export requires triangle rows or VTK triangular face records.")
    if len(triangles) == 0:
        return np.empty((0, 3), dtype=np.int64)
    if not np.all((triangles >= 0) & (triangles < int(point_count))):
        raise ValueError("Figure export faces refer to missing points.")
    return triangles.astype(np.int64)


def _figure_label_center(points_2d: np.ndarray, *, scale: float, x_offset: float) -> float:
    if len(points_2d) == 0:
        return 0.0
    return float(np.mean(points_2d[:, 0]) * scale + x_offset)


def _format_figure_scalar(value: float) -> str:
    numeric = float(value)
    if numeric == 0.0:
        return "0"
    magnitude = abs(numeric)
    if magnitude >= 1000.0 or magnitude < 0.001:
        return f"{numeric:.3e}"
    if magnitude < 10.0:
        return f"{numeric:.2f}".rstrip("0").rstrip(".")
    return f"{numeric:.1f}".rstrip("0").rstrip(".")


def _rgb_to_hex(rgb: np.ndarray) -> str:
    values = np.clip(np.rint(np.asarray(rgb, dtype=float)), 0, 255).astype(np.uint8)
    return f"#{int(values[0]):02x}{int(values[1]):02x}{int(values[2]):02x}"


def _hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        return (0, 0, 0, 255)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4)) + (255,)


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
    vmin = float(scalar_range[0])
    finite = np.isfinite(scalar_values) & (scalar_values >= vmin)
    if not np.any(finite):
        return colors
    colors[finite] = _scalar_values_to_rgb(scalar_values[finite], scalar_range=scalar_range)
    return colors


def _cortical_paint_display_values(values: np.ndarray, *, scalar_range: tuple[float, float]) -> np.ndarray:
    scalar_values = np.asarray(values, dtype=float).reshape(-1)
    vmin = float(scalar_range[0])
    return np.where(np.isfinite(scalar_values) & (scalar_values >= vmin), scalar_values, np.nan)


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
