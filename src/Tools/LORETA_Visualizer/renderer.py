"""PyVista/VTK rendering adapter for the embedded LORETA visualizer."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QWidget

from Tools.LORETA_Visualizer.dummy_activation import ActivationPayload
from Tools.LORETA_Visualizer.synthetic_brain import BrainMesh, make_synthetic_brain_mesh

logger = logging.getLogger(__name__)


class RenderBackendError(RuntimeError):
    """Raised when the optional 3D rendering stack cannot initialize."""


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
        self._surface: Any | None = None
        self._current_mesh: BrainMesh | None = None
        self._brain_opacity = initial_opacity
        self._activation_opacity = 0.72
        self._activation_visible = True

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
        try:
            plotter.enable_depth_peeling(number_of_peels=8, occlusion_ratio=0.0)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_depth_peeling_unavailable", exc_info=True)
        layout.addWidget(plotter)
        self._plotter = plotter

        mesh = make_synthetic_brain_mesh()
        self._current_mesh = mesh
        self._surface = self._to_polydata(pv, mesh)
        self._brain_actor = plotter.add_mesh(
            self._surface,
            color="#efc7b7",
            opacity=initial_opacity,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.22,
            specular_power=12,
            ambient=0.42,
            diffuse=0.72,
        )
        self._apply_brain_material(self._brain_actor)
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

    def set_brain_opacity(self, opacity: float) -> None:
        opacity = max(0.05, min(1.0, float(opacity)))
        self._brain_opacity = opacity
        actor = self._brain_actor
        plotter = self._plotter
        if actor is None or plotter is None:
            return
        actor.GetProperty().SetOpacity(opacity)
        plotter.render()

    def mesh_points(self) -> Any | None:
        mesh = self._current_mesh
        if mesh is None:
            return None
        return mesh.points

    def replace_brain_mesh(self, mesh: BrainMesh, *, reset_camera: bool = True) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        import pyvista as pv

        previous_actor = self._brain_actor
        if previous_actor is not None:
            try:
                plotter.remove_actor(previous_actor, render=False)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("loreta_remove_previous_actor_failed", exc_info=True)
        self._current_mesh = mesh
        self._surface = self._to_polydata(pv, mesh)
        self._brain_actor = plotter.add_mesh(
            self._surface,
            color="#efc7b7",
            opacity=self._brain_opacity,
            smooth_shading=True,
            show_edges=False,
            lighting=True,
            specular=0.22,
            specular_power=12,
            ambient=0.42,
            diffuse=0.72,
        )
        self._apply_brain_material(self._brain_actor)
        if reset_camera:
            plotter.reset_camera()
        plotter.render()

    def set_activation_payload(self, payload: ActivationPayload) -> None:
        plotter = self._plotter
        if plotter is None:
            return
        import pyvista as pv

        self._remove_activation_actor(render=False)
        if len(payload.points) == 0:
            plotter.render()
            return
        cloud = pv.PolyData(payload.points)
        cloud["activation"] = payload.values
        self._activation_actor = plotter.add_mesh(
            cloud,
            scalars="activation",
            cmap="Reds",
            clim=(0.0, 1.0),
            opacity=self._activation_opacity,
            render_points_as_spheres=True,
            point_size=18,
            show_scalar_bar=False,
        )
        self._activation_actor.SetVisibility(self._activation_visible)
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
        actor = self._activation_actor
        plotter = self._plotter
        if actor is None or plotter is None:
            return
        actor.SetVisibility(self._activation_visible)
        plotter.render()

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
        plotter.camera_position = "xy"
        plotter.reset_camera()
        plotter.render()

    def shutdown(self) -> None:
        plotter = self._plotter
        self._plotter = None
        self._brain_actor = None
        self._activation_actor = None
        self._surface = None
        self._current_mesh = None
        if plotter is None:
            return
        try:
            plotter.close()
        except (AttributeError, RuntimeError, TypeError):
            logger.debug("loreta_renderer_close_failed", exc_info=True)
