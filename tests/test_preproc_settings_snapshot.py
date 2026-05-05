import pytest

pytest.importorskip("PySide6")

from Main_App.workers import mp_runner_bridge, process_runner


def test_process_mode_modules_import() -> None:
    assert process_runner is not None
    assert mp_runner_bridge is not None
