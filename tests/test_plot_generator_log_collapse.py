import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_log_panel_collapses_and_expands(app, qtbot):
    from Tools.Plot_Generator.gui import PlotGeneratorWindow

    w = PlotGeneratorWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)

    assert w.log_body.isVisible() is True

    w.log_toggle_btn.setChecked(False)
    qtbot.waitUntil(lambda: not w.log_body.isVisible(), timeout=1000)

    w.log_toggle_btn.setChecked(True)
    qtbot.waitUntil(lambda: w.log_body.isVisible(), timeout=1000)
