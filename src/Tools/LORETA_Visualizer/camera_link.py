"""Event-driven camera synchronization for two prepared-map renderers."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class LinkedBrainCameras:
    """Copy camera changes in either direction and coalesce peer redraws.

    Each renderer keeps its own camera and actors. There is no polling timer;
    the single-shot timer only renders after a camera has actually changed.
    The owners must detach this link before either render window is closed.
    """

    def __init__(self, first: Any, second: Any) -> None:
        self._owners = (first, second)
        self._cameras = (first._plotter.camera, second._plotter.camera)
        self._observers: list[tuple[Any, int]] = []
        self._pending: set[int] = set()
        self._syncing = False
        self._closed = False
        self._timer = QTimer(first)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_pending)
        initialized = False
        try:
            for index, camera in enumerate(self._cameras):
                callback = self._camera_callback(index)
                self._observers.append((camera, camera.AddObserver("ModifiedEvent", callback)))
            self._copy_camera(0)
            initialized = True
        finally:
            if not initialized:
                self.close()

    def connects(self, first: Any, second: Any) -> bool:
        return not self._closed and (
            (self._owners[0] is first and self._owners[1] is second)
            or (self._owners[0] is second and self._owners[1] is first)
        )

    def is_primary(self, owner: Any) -> bool:
        """Only one peer adjusts the shared framing when both panes resize."""
        return not self._closed and self._owners[0] is owner

    def _camera_callback(self, index: int):
        def changed(_camera: Any, _event: str) -> None:
            self._copy_camera(index)

        return changed

    def _copy_camera(self, source_index: int) -> None:
        if self._closed or self._syncing:
            return
        target_index = 1 - source_index
        target = self._owners[target_index]
        plotter = getattr(target, "_plotter", None)
        if plotter is None:
            self.close()
            return
        self._syncing = True
        try:
            self._cameras[target_index].DeepCopy(self._cameras[source_index])
            # vtkCamera.DeepCopy copies fields without advancing its MTime;
            # otherwise VTK can reuse the peer's old projection transform.
            self._cameras[target_index].Modified()
            # A prepared peer must never re-fit the copied view on add_mesh.
            plotter.camera_set = True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_linked_camera_copy_failed", exc_info=True)
            return
        finally:
            self._syncing = False
        self._pending.add(target_index)
        if not self._timer.isActive():
            self._timer.start(0)

    def _render_pending(self) -> None:
        if self._closed:
            return
        pending = tuple(self._pending)
        self._pending.clear()
        self._syncing = True
        try:
            for index in pending:
                plotter = getattr(self._owners[index], "_plotter", None)
                if plotter is not None:
                    plotter.render()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("loreta_linked_camera_render_failed", exc_info=True)
        finally:
            # Rendering can update clipping state. Do not recursively redraw
            # the other window in response to those internal camera changes.
            self._syncing = False

    def pause_spin_for_interaction(self) -> None:
        if self._closed:
            return
        for owner in self._owners:
            owner._pause_transparent_spin_for_interaction()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._pending.clear()
        for camera, observer_id in self._observers:
            try:
                camera.RemoveObserver(observer_id)
            except (AttributeError, RuntimeError, TypeError):
                logger.debug("loreta_linked_camera_observer_removal_failed", exc_info=True)
        self._observers.clear()
        for owner in self._owners:
            if getattr(owner, "_camera_link", None) is self:
                owner._camera_link = None
        self._timer.timeout.disconnect(self._render_pending)
        self._timer.deleteLater()
        self._owners = ()
        self._cameras = ()
