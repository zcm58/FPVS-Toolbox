import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_log_panel_is_always_visible(app, qtbot):
    from Tools.Plot_Generator.gui import PlotGeneratorWindow

    w = PlotGeneratorWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)

    height_before = w.height()
    assert not hasattr(w, "log_toggle_btn")
    assert w.log_body.isVisible() is True
    assert w.advanced_box.height() >= 290
    assert w.console_box.height() <= 180
    assert 95 <= w.log.height() <= 120

    w.log.append("Always visible")
    qtbot.wait(50)

    assert "Always visible" in w.log.toPlainText()
    assert w.height() <= height_before + 10
