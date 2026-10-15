"""A watchdog's forced exit must leave inspectable failure evidence."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_watchdog_report_survives_forced_process_exit(tmp_path):
    diagnostics = tmp_path / "diagnostics"
    environment = dict(os.environ, FPVS_TEST_WATCHDOG_DIR=str(diagnostics))
    result = subprocess.run(
        [sys.executable, "-c", (
            "import os; from tests.conftest import _write_watchdog_diagnostic; "
            "_write_watchdog_diagnostic('tests/gui/test_example.py::test_hang', 20); "
            "os._exit(124)"
        )],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 124, result.stderr
    reports = list(diagnostics.glob("*.txt"))
    assert len(reports) == 1
    contents = reports[0].read_text(encoding="utf-8")
    assert "20s: tests/gui/test_example.py::test_hang" in contents
    assert "_write_watchdog_diagnostic" in contents
