import os
import sys
import types
from pathlib import Path
import pytest


def test_phase1_perf_hygiene(qtbot):
    main_path = Path(__file__).resolve().parents[1] / "src" / "main.py"
    lines = main_path.read_text().splitlines()
    set_line = next(i for i, l in enumerate(lines) if "set_blas_threads_single_process()" in l)
    main_app_import = next(i for i, l in enumerate(lines) if "from Main_App" in l and "mp_env" not in l)
    assert set_line < main_app_import

    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.pop(var, None)
    mp_env_path = Path(__file__).resolve().parents[1] / "src" / "Main_App" / "Performance" / "mp_env.py"
    spec = types.ModuleType("mp_env")
    exec(mp_env_path.read_text(), spec.__dict__)
    spec.set_blas_threads_single_process()
    assert os.environ.get("OMP_NUM_THREADS")

    sys.modules.pop("Main_App", None)
    stub = types.ModuleType("Main_App")
    stub.__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "Main_App")]
    class _SettingsManager:
        def __init__(self, *a, **k):
            pass
    stub.SettingsManager = _SettingsManager
    sys.modules["Main_App"] = stub
    legacy_stub = types.ModuleType("Main_App.Legacy_App")
    legacy_stub.__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "Main_App" / "Legacy_App")]
    sys.modules["Main_App.Legacy_App"] = legacy_stub
    pp_stub = types.ModuleType("Main_App.Legacy_App.post_process")
    def _pp(*a, **k):
        return None
    pp_stub.post_process = _pp
    sys.modules["Main_App.Legacy_App.post_process"] = pp_stub

    try:
        from Main_App.PySide6_App.GUI.main_window import MainWindow
    except Exception as e:  # pragma: no cover - env missing deps
        pytest.skip(f"MainWindow import skipped: {e}")

    window = MainWindow()
    qtbot.addWidget(window)

    timer = window._processing_timer
    timer.start(100)
    assert timer.interval() >= 100

    assert callable(window._periodic_queue_check)
    assert timer.receivers(timer.timeout) > 0
