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

    top_container_height_before = w._main_splitter.widget(0).height()
    window_height_before = w.height()

    assert w.log_body.isVisible() is True

    w.log_toggle_btn.setChecked(False)
    qtbot.waitUntil(lambda: not w.log_body.isVisible(), timeout=1000)

    assert w.height() < window_height_before

    top_container_height_after = w._main_splitter.widget(0).height()
    tolerance = 4
    assert top_container_height_after <= top_container_height_before + tolerance

    w.log_toggle_btn.setChecked(True)
    qtbot.waitUntil(lambda: w.log_body.isVisible(), timeout=1000)

    assert w.height() >= window_height_before
