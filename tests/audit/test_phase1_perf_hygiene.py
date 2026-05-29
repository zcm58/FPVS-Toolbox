import os
import sys
import types
import pytest

from tests import repo_root


def test_phase1_perf_hygiene(qtbot):
    root = repo_root()
    main_path = root / "src" / "main.py"
    lines = main_path.read_text().splitlines()
    set_line = next(i for i, line in enumerate(lines) if "set_blas_threads_single_process()" in line)
    main_app_import = next(i for i, line in enumerate(lines) if "from Main_App" in line and "mp_env" not in line)
    assert set_line < main_app_import

    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.pop(var, None)
    mp_env_path = root / "src" / "Main_App" / "Performance" / "mp_env.py"
    spec = types.ModuleType("mp_env")
    exec(mp_env_path.read_text(), spec.__dict__)
    spec.set_blas_threads_single_process()

    cores = os.cpu_count() or 1
    expected_threads = str(cores)
    expected_numexpr_threads = str(max(1, cores // 2))

    assert os.environ.get("MKL_NUM_THREADS") == expected_threads
    assert os.environ.get("OPENBLAS_NUM_THREADS") == expected_threads
    assert os.environ.get("OMP_NUM_THREADS") == expected_threads
    assert os.environ.get("NUMEXPR_NUM_THREADS") == expected_numexpr_threads

    sys.modules.pop("Main_App", None)
    stub = types.ModuleType("Main_App")
    stub.__path__ = [str(root / "src" / "Main_App")]
    class _SettingsManager:
        def __init__(self, *a, **k):
            pass

        def debug_enabled(self):
            return False
    stub.SettingsManager = _SettingsManager
    sys.modules["Main_App"] = stub
    shared_stub = types.ModuleType("Main_App.Shared")
    shared_stub.__path__ = [str(root / "src" / "Main_App" / "Shared")]
    sys.modules["Main_App.Shared"] = shared_stub
    pp_stub = types.ModuleType("Main_App.Shared.post_process")
    def _pp(*a, **k):
        return None
    stub.post_process = _pp
    pp_stub.post_process = _pp
    sys.modules["Main_App.Shared.post_process"] = pp_stub

    try:
        from Main_App.gui.main_window import MainWindow
    except Exception as e:  # pragma: no cover - env missing deps
        pytest.skip(f"MainWindow import skipped: {e}")

    window = MainWindow()
    qtbot.addWidget(window)

    timer = window._processing_timer
    timer.start(100)
    assert timer.interval() >= 100

    assert callable(window._periodic_queue_check)
    assert timer.receivers("2timeout()") > 0
