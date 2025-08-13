import sys, pytest
from PySide6.QtWidgets import QApplication
from Main_App.PySide6_App.widgets.busy_spinner import BusySpinner

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)

def test_spinner_start_stop(app, qtbot):
    sp = BusySpinner()
    qtbot.addWidget(sp)
    assert not sp.isVisible()
    sp.start()
    assert sp.isVisible()
    qtbot.wait(120)
    sp.stop()
    assert not sp.isVisible()
