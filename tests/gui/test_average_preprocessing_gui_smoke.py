import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from Main_App.gui.components import ActionRow, SectionCard
from Tools.Average_Preprocessing.New_PySide6.main_window import AdvancedAveragingWindow


def test_advanced_averaging_window_uses_shared_components(qtbot, tmp_path):
    window = AdvancedAveragingWindow(input_dir=str(tmp_path), output_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert len(window.findChildren(SectionCard)) >= 3
    assert window.btn_start.property("primary") is True
    assert window.btn_stop.property("danger") is True
    assert window.btn_del.property("danger") is True
    assert window.btn_close.property("tertiary") is True
    assert window.log_edit.property("logSurface") is True
    assert window.btn_stop.isEnabled() is False

    action_rows = {row.objectName(): row for row in window.findChildren(ActionRow)}
    expected_rows = {
        "advanced_averaging_source_actions",
        "advanced_averaging_group_actions",
        "advanced_averaging_processing_actions",
    }
    assert expected_rows <= set(action_rows)
    assert action_rows["advanced_averaging_source_actions"].row_layout.indexOf(window.btn_add) >= 0
    assert action_rows["advanced_averaging_group_actions"].row_layout.indexOf(window.btn_del) >= 0
    assert action_rows["advanced_averaging_processing_actions"].row_layout.indexOf(window.btn_start) >= 0
