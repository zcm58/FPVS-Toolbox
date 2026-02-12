from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types

import pytest

REPORTING_MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "Tools" / "Stats" / "PySide6" / "reporting_summary.py"
if "pandas" not in sys.modules:
    try:
        import pandas  # noqa: F401
    except Exception:  # pragma: no cover - fallback for lightweight test env
        pandas_stub = types.ModuleType("pandas")

        class _DataFrame:  # pragma: no cover - compatibility shim
            pass

        pandas_stub.DataFrame = _DataFrame
        sys.modules["pandas"] = pandas_stub

_spec = importlib.util.spec_from_file_location("reporting_summary", REPORTING_MODULE_PATH)
assert _spec and _spec.loader
_reporting_summary = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _reporting_summary
_spec.loader.exec_module(_reporting_summary)

build_default_report_path = _reporting_summary.build_default_report_path
safe_project_path_join = _reporting_summary.safe_project_path_join


@pytest.mark.qt
def test_reporting_summary_ui_copy_and_slot(tmp_path):
    pytest.importorskip("pytestqt")
    pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    pytest.importorskip("PySide6")
    pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtGui")

    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    window = StatsWindow(project_dir=str(tmp_path))
    window.show()

    sample = "FPVS TOOLBOX — STATS REPORTING SUMMARY\nRUN METADATA"
    window._on_report_ready(sample)
    assert window.reporting_summary_text.toPlainText() == sample

    window._copy_reporting_summary_text()
    assert QGuiApplication.clipboard().text() == sample


def test_reporting_summary_path_helper_scopes_to_project(tmp_path):
    report_path = build_default_report_path(tmp_path, datetime(2025, 1, 2, 3, 4, 5))
    assert str(report_path).startswith(str(tmp_path))
    assert report_path.name == "Stats_Reporting_Summary_20250102_030405.txt"

    joined = safe_project_path_join(tmp_path, "Stats", "Reports", "a.txt")
    assert str(joined).startswith(str(tmp_path))

    with pytest.raises(ValueError):
        safe_project_path_join(tmp_path, "..", "escape.txt")
