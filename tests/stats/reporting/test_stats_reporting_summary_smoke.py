from __future__ import annotations

from datetime import datetime
import sys
import types

import pytest

if "pandas" not in sys.modules:
    try:
        import pandas  # noqa: F401
    except Exception:  # pragma: no cover - fallback for lightweight test env
        pandas_stub = types.ModuleType("pandas")

        class _DataFrame:  # pragma: no cover - compatibility shim
            pass

        pandas_stub.DataFrame = _DataFrame
        sys.modules["pandas"] = pandas_stub

from Tools.Stats.reporting.reporting_summary import build_default_report_path, safe_project_path_join


@pytest.mark.qt
def test_reporting_summary_ui_copy_and_slot(tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    pytest.importorskip("PySide6")
    pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("PySide6.QtGui")

    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from Tools.Stats.ui.stats_window import StatsWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    monkeypatch.setattr(StatsWindow, "refresh_rois", lambda self: setattr(self, "rois", {"ROI": ["Cz"]}), raising=False)
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
