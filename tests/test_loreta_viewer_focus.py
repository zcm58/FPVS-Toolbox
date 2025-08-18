import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets


def test_loreta_viewer_focus(qtbot, monkeypatch):
    # Stub external dependencies
    class DummySettings:
        def __init__(self):
            pass
        def get(self, section, key, default="", fallback=None):
            return default or (fallback or "")
        def set(self, *args, **kwargs):
            pass
        def save(self):
            pass
        def debug_enabled(self):
            return False

    main_app_stub = types.ModuleType("Main_App")
    main_app_stub.SettingsManager = DummySettings
    sys.modules["Main_App"] = main_app_stub

    mne_stub = types.ModuleType("mne")
    mne_stub.read_source_estimate = lambda *a, **k: types.SimpleNamespace(
        data=[], vertices=[[], []], tstep=0.001, tmin=0.0, subject="fsaverage"
    )
    mne_stub.viz = types.SimpleNamespace(set_3d_backend=lambda *a, **k: None, get_3d_backend=lambda: "pyvistaqt")
    mne_stub.datasets = types.SimpleNamespace(fetch_fsaverage=lambda verbose=False: types.SimpleNamespace(parent=""))
    mne_stub.surface = types.SimpleNamespace(read_surface=lambda *a, **k: ([], []))
    sys.modules["mne"] = mne_stub

    numpy_stub = types.ModuleType("numpy")
    sys.modules["numpy"] = numpy_stub

    tools_pkg = types.ModuleType("Tools")
    sys.modules["Tools"] = tools_pkg
    sl_pkg = types.ModuleType("Tools.SourceLocalization")
    sl_pkg.__path__ = [
        str(Path(__file__).resolve().parent.parent / "src" / "Tools" / "SourceLocalization")
    ]
    sys.modules["Tools.SourceLocalization"] = sl_pkg

    pv_stub = types.ModuleType("pyvista")
    class DummyPlotter:
        def __init__(self, *a, **k):
            pass
        def close(self):
            pass
    pv_stub.Plotter = DummyPlotter
    pv_stub.PolyData = lambda *a, **k: object()
    sys.modules["pyvista"] = pv_stub

    pvqt_stub = types.ModuleType("pyvistaqt")
    pvqt_stub.QtInteractor = QtWidgets.QWidget
    sys.modules["pyvistaqt"] = pvqt_stub

    import importlib
    backend_utils = importlib.import_module("Tools.SourceLocalization.backend_utils")
    pyqt_viewer = importlib.import_module("Tools.SourceLocalization.pyqt_viewer")
    qt_dialog = importlib.import_module("Tools.SourceLocalization.qt_dialog")

    monkeypatch.setattr(backend_utils, "_ensure_pyvista_backend", lambda: None)

    class DummyViewer(QtWidgets.QMainWindow):
        def __init__(self, *a, **k):
            super().__init__()
    monkeypatch.setattr(pyqt_viewer, "STCViewer", DummyViewer)
    pyqt_viewer._OPEN_VIEWERS.clear()

    dlg = qt_dialog.SourceLocalizationDialog()
    qtbot.addWidget(dlg)

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: ("dummy-lh.stc", "")
    )

    dlg._open_viewer()

    viewer = pyqt_viewer._OPEN_VIEWERS[-1]
    assert viewer.isVisible()
    assert viewer.isEnabled()

    def _active():
        assert QtWidgets.QApplication.activeWindow() is viewer

    qtbot.waitUntil(_active, timeout=500)

    for w in QtWidgets.QApplication.topLevelWidgets():
        assert not w.isModal()

    viewer.close()
