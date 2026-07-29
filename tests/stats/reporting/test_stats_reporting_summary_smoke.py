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

from Tools.Stats.reporting.reporting_summary import (
    build_default_report_path,
    safe_project_path_join,
)


def test_reporting_summary_path_helper_scopes_to_project(tmp_path):
    report_path = build_default_report_path(
        tmp_path,
        datetime(2025, 1, 2, 3, 4, 5),
    )
    assert str(report_path).startswith(str(tmp_path))
    assert report_path.name == "Stats_Reporting_Summary_20250102_030405.txt"

    joined = safe_project_path_join(tmp_path, "Stats", "Reports", "a.txt")
    assert str(joined).startswith(str(tmp_path))

    with pytest.raises(ValueError):
        safe_project_path_join(tmp_path, "..", "escape.txt")
