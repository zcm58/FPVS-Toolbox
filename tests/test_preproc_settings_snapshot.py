import pytest

pytest.importorskip("PySide6")

from Main_App.Performance import process_runner
from Main_App.PySide6_App.workers import mp_runner_bridge


def test_process_mode_modules_import() -> None:
    assert process_runner is not None
    assert mp_runner_bridge is not None
