"""Lightweight MRI slice navigation over worker-rendered prepared images."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from Tools.LORETA_Visualizer.volume_slices import MriSliceHitRegion, MriSliceRenderResult


class MriSliceImageLabel(QLabel):
    """Linked crosshair and navigation requests; rendering stays worker-owned."""

    slice_indices_requested = Signal(object)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("loreta_mri_slice_view")
        self.setAccessibleName("MRI slice inspector")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)
        self.setWordWrap(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._source_pixmap: QPixmap | None = None
        self._result: MriSliceRenderResult | None = None
        self._cursor_voxel: tuple[int, int, int] | None = None
        self._active_plane = "axial"
        self.clear_slice_image()

    def set_render_result(self, result: MriSliceRenderResult) -> None:
        """Display a completed worker render and its image-coordinate mapping."""

        self.set_slice_image(result.image_rgb)
        self._result = result
        self._cursor_voxel = result.peak_voxel
        x, y, z = result.cursor_ras_mm
        details = [f"fsaverage MRI RAS: x={x:+.1f}, y={y:+.1f}, z={z:+.1f} mm"]
        if result.nearest_source_value is not None and result.nearest_source_distance_mm is not None:
            scope = " (before display masking)" if result.inspection_uses_unfiltered_payload else ""
            details.append(
                f"Nearest original grid value{scope}: {result.nearest_source_value:.4g} {result.value_label}"
                f" ({result.nearest_source_distance_mm:.1f} mm away)."
            )
        details.append("Click to position. Arrow keys move the crosshair. Wheel or Page Up/Down changes the slice. Home resets.")
        self.setToolTip("\n".join(details))
        self.update()

    def set_slice_image(self, image_rgb: np.ndarray) -> None:
        image = np.ascontiguousarray(image_rgb, dtype=np.uint8)
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("MRI slice image must be an RGB array.")
        self._result = None
        self._cursor_voxel = None
        self.setToolTip("")
        height, width, _channels = image.shape
        qimage = QImage(image.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        self._source_pixmap = QPixmap.fromImage(qimage)
        self.setText("")
        self._sync_scaled_pixmap()

    def clear_slice_image(self, message: str = "") -> None:
        self._source_pixmap = None
        self._result = None
        self._cursor_voxel = None
        self.clear()
        self.setToolTip("")
        if message:
            self.setText(message)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._sync_scaled_pixmap()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        if self._result is None or self._cursor_voxel is None:
            return
        target = self._image_rect()
        if target is None:
            return
        source_height, source_width = self._result.image_rgb.shape[:2]
        scale_x, scale_y = target.width() / source_width, target.height() / source_height
        painter = QPainter(self)
        painter.setPen(QPen(QColor(255, 255, 255, 190), 1.0))
        for region in self._result.hit_regions:
            left, top, width, height = region.image_bounds
            rectangle = QRectF(
                target.left() + left * scale_x, target.top() + top * scale_y,
                width * scale_x, height * scale_y,
            )
            x, y = region.image_position(self._cursor_voxel)
            x = target.left() + x * scale_x
            y = target.top() + y * scale_y
            painter.save()
            painter.setClipRect(rectangle)
            painter.drawLine(QPointF(x, rectangle.top()), QPointF(x, rectangle.bottom()))
            painter.drawLine(QPointF(rectangle.left(), y), QPointF(rectangle.right(), y))
            painter.restore()
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_at(event.position())
            if hit is not None:
                region, x, y = hit
                self._active_plane = region.plane
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._request_voxel(region.voxel_at(x, y))
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        hit = self._hit_at(event.position())
        if hit is not None and event.angleDelta().y():
            region, _x, _y = hit
            self._active_plane = region.plane
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            delta = event.angleDelta().y()
            steps = int(delta / 120) or (1 if delta > 0 else -1)
            self._step_slice(region, steps)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._result is None or self._cursor_voxel is None:
            super().keyPressEvent(event)
            return
        region = next((item for item in self._result.hit_regions if item.plane == self._active_plane), None)
        if region is None:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Home:
            self.reset_requested.emit()
        elif event.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self._step_slice(region, 1 if event.key() == Qt.Key.Key_PageUp else -1)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            column_step, row_step = {
                Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
            }[event.key()]
            delta = region.pixel_to_voxel[:, 0] * column_step + region.pixel_to_voxel[:, 1] * row_step
            self._request_voxel(np.asarray(self._cursor_voxel) + delta)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _step_slice(self, region: MriSliceHitRegion, steps: int) -> None:
        if self._cursor_voxel is None:
            return
        voxel = np.asarray(self._cursor_voxel, dtype=int)
        voxel[region.fixed_voxel_axis] += int(steps) * region.fixed_voxel_step
        self._request_voxel(voxel)

    def _request_voxel(self, voxel: np.ndarray) -> None:
        if self._result is None:
            return
        clipped = np.clip(np.rint(voxel).astype(int), 0, np.asarray(self._result.anatomy_shape) - 1)
        selected = tuple(int(value) for value in clipped)
        if selected == self._cursor_voxel:
            return
        self._cursor_voxel = selected
        self.setToolTip("")
        self.update()
        self.slice_indices_requested.emit(selected)

    def _hit_at(self, point: QPointF) -> tuple[MriSliceHitRegion, float, float] | None:
        target = self._image_rect()
        if target is None or self._result is None or not target.contains(point):
            return None
        height, width = self._result.image_rgb.shape[:2]
        x = (point.x() - target.left()) * width / target.width()
        y = (point.y() - target.top()) * height / target.height()
        for region in self._result.hit_regions:
            left, top, panel_width, panel_height = region.image_bounds
            if left <= x < left + panel_width and top <= y < top + panel_height:
                return region, x, y
        return None

    def _image_rect(self) -> QRectF | None:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        content = self.contentsRect()
        width, height = pixmap.width(), pixmap.height()
        return QRectF(content.x() + (content.width() - width) / 2, content.y() + (content.height() - height) / 2, width, height)

    def _sync_scaled_pixmap(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        size = self.contentsRect().size()
        if size.isValid():
            self.setPixmap(self._source_pixmap.scaled(
                size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            ))
