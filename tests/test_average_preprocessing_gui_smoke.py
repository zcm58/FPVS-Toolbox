import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from Main_App.PySide6_App.widgets import SectionCard
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
