import logging
import sys
import types

import numpy as np
from PySide6 import QtWidgets


def test_launch_viewer_single_hemi(monkeypatch, qtbot, caplog):
    # Stub external modules before importing viewer
    dummy_pyvista = types.SimpleNamespace(Plotter=lambda *a, **k: types.SimpleNamespace(close=lambda: None))
    dummy_pyvistaqt = types.SimpleNamespace(QtInteractor=lambda parent=None: QtWidgets.QWidget(parent))
    dummy_mne = types.SimpleNamespace()
    dummy_mne.read_source_estimate = lambda path: types.SimpleNamespace(
        vertices=[[], []], data=np.zeros((0, 1)), tstep=0.01, tmin=0.0, subject="fsaverage"
    )
    sys.modules.setdefault("pyvista", dummy_pyvista)
    sys.modules.setdefault("pyvistaqt", dummy_pyvistaqt)
    sys.modules.setdefault("mne", dummy_mne)
    sys.modules.setdefault(
        "Main_App",
        types.SimpleNamespace(SettingsManager=lambda: types.SimpleNamespace(debug_enabled=lambda: False, get=lambda *a, **k: "")),
    )
    sys.modules.setdefault(
        "Tools.SourceLocalization.logging_utils", types.SimpleNamespace(get_pkg_logger=lambda: logging.getLogger("Tools.SourceLocalization"))
    )
    sys.modules.setdefault(
        "Tools.SourceLocalization.data_utils", types.SimpleNamespace(_resolve_subjects_dir=lambda *a, **k: "")
    )
    sys.modules.setdefault("Tools.SourceLocalization.backend_utils", types.SimpleNamespace(_ensure_pyvista_backend=lambda: None))

    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "pyqt_viewer", pathlib.Path(__file__).resolve().parent.parent / "src/Tools/SourceLocalization/pyqt_viewer.py"
    )
    pv_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pv_mod)

    class DummyViewer(QtWidgets.QMainWindow):
        def __init__(self, stc_path, time_ms=None):
            super().__init__()

    monkeypatch.setattr(pv_mod, "STCViewer", DummyViewer)
    monkeypatch.setattr(pv_mod, "_ensure_pyvista_backend", lambda: None)

    with caplog.at_level(logging.DEBUG, logger="Tools.SourceLocalization"):
        pv_mod.launch_viewer("fake-lh.stc")
        qtbot.waitUntil(lambda: pv_mod._OPEN_VIEWERS and pv_mod._OPEN_VIEWERS[-1].isVisible())

    assert pv_mod._OPEN_VIEWERS[-1].isVisible()
    assert any("ENTER launch_viewer" in r.message for r in caplog.records)
