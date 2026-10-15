"""CI-only interaction checks for the prepared MRI slice inspector."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from Tools.LORETA_Visualizer.slice_viewer import MriSliceImageLabel
from Tools.LORETA_Visualizer.volume_slices import MriSliceHitRegion, MriSliceRenderResult


def _render_result() -> MriSliceRenderResult:
    return MriSliceRenderResult(
        image_rgb=np.zeros((100, 300, 3), dtype=np.uint8),
        peak_voxel=(5, 5, 5), scalar_range=(0.0, 3.0),
        source_point_count=2, rendered_point_count=1,
        hit_regions=(MriSliceHitRegion(
            plane="axial", image_bounds=(0.0, 0.0, 100.0, 100.0), panel_shape=(11, 11),
            pixel_to_voxel=np.asarray([[1.0, 0.0, 0.0], [0.0, -1.0, 10.0], [0.0, 0.0, 5.0]]),
            fixed_voxel_axis=2,
        ),),
        anatomy_shape=(11, 11, 11), cursor_ras_mm=(5.0, 5.0, 5.0),
        nearest_source_value=-2.0, nearest_source_distance_mm=0.5,
        value_label="z-score", inspection_uses_unfiltered_payload=True,
    )


def test_slice_inspector_click_keyboard_and_reset_request_only_prepared_coordinates(qtbot) -> None:
    widget = MriSliceImageLabel()
    qtbot.addWidget(widget)
    widget.resize(600, 300)
    result = _render_result()
    widget.set_render_result(result)
    assert "fsaverage MRI RAS" in widget.toolTip()
    assert "Nearest original grid value (before display masking): -2 z-score" in widget.toolTip()
    widget.show()
    rectangle = widget._image_rect()
    assert rectangle is not None
    click = QPoint(
        int(rectangle.left() + rectangle.width() * 75.0 / 300.0),
        int(rectangle.top() + rectangle.height() * 25.0 / 100.0),
    )

    with qtbot.waitSignal(widget.slice_indices_requested) as request:
        qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=click)
    assert request.args == [(8, 8, 5)]
    with qtbot.waitSignal(widget.slice_indices_requested) as request:
        qtbot.keyClick(widget, Qt.Key.Key_Right)
    assert request.args == [(9, 8, 5)]
    with qtbot.waitSignal(widget.slice_indices_requested) as request:
        qtbot.keyClick(widget, Qt.Key.Key_PageUp)
    assert request.args == [(9, 8, 6)]
    with qtbot.waitSignal(widget.reset_requested):
        qtbot.keyClick(widget, Qt.Key.Key_Home)

    assert widget.toolTip() == ""  # An outstanding request must not retain the old readout.
    assert np.all(result.image_rgb == 0)


def test_slice_inspector_wheel_navigates_hovered_plane_and_clear_removes_readout(qtbot) -> None:
    widget = MriSliceImageLabel()
    qtbot.addWidget(widget)
    widget.resize(600, 300)
    widget.set_render_result(_render_result())
    widget.show()
    rectangle = widget._image_rect()
    assert rectangle is not None
    position = QPointF(rectangle.left() + rectangle.width() / 6.0, rectangle.center().y())
    wheel = QWheelEvent(
        position, QPointF(widget.mapToGlobal(position.toPoint())), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    with qtbot.waitSignal(widget.slice_indices_requested) as request:
        QApplication.sendEvent(widget, wheel)
    assert request.args == [(5, 5, 4)]

    widget.clear_slice_image("No source map loaded.")
    assert widget.text() == "No source map loaded."
    assert widget.toolTip() == ""
    assert widget._result is None
