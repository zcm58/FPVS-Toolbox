from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

from Main_App import _StructuredExtraFormatter
from Main_App.diagnostics import log_router


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.__dict__.update(extra)
    return record


def test_structured_formatter_leaves_plain_logs_unchanged() -> None:
    formatter = _StructuredExtraFormatter("%(levelname)s:%(name)s:%(message)s")

    assert formatter.format(_record("plain_message")) == "INFO:test.logger:plain_message"


def test_structured_formatter_appends_extra_fields() -> None:
    formatter = _StructuredExtraFormatter("%(levelname)s:%(name)s:%(message)s")

    formatted = formatter.format(
        _record(
            "stats_multigroup_issues_summary",
            issue_count=36,
            warning_count=36,
            blocking_count=0,
            preview="Subject listed in manifest has no Excel outputs. (pid=P2)",
        )
    )

    assert formatted.startswith("INFO:test.logger:stats_multigroup_issues_summary ")
    assert "blocking_count=0" in formatted
    assert "issue_count=36" in formatted
    assert 'preview="Subject listed in manifest has no Excel outputs. (pid=P2)"' in formatted
    assert "warning_count=36" in formatted


def test_gui_log_route_appends_visible_line_and_warning_reaches_backend(caplog) -> None:
    host = SimpleNamespace(
        text_log=[],
        settings=SimpleNamespace(debug_enabled=lambda: False),
    )
    logger = logging.getLogger("tests.gui_log_route")

    with caplog.at_level(logging.INFO, logger="tests.gui_log_route"):
        log_router.emit_gui_log(
            host,
            logger,
            message="visible warning",
            level=logging.WARNING,
        )

    assert len(host.text_log) == 1
    assert "[GUI]: visible warning" in host.text_log[0]
    assert "visible warning" in caplog.text


def test_gui_log_line_uses_shared_format() -> None:
    line = log_router.gui_log_line(
        "hello",
        when=datetime(2026, 5, 21, 9, 1, 2, 345000),
    )

    assert line == "09:01:02.345 [GUI]: hello"


def test_noisy_dependency_loggers_are_quieted() -> None:
    fonttools_subset = logging.getLogger("fontTools.subset")
    previous_level = fonttools_subset.level
    try:
        fonttools_subset.setLevel(logging.NOTSET)

        log_router._quiet_noisy_dependency_loggers()

        assert fonttools_subset.level == logging.WARNING
    finally:
        fonttools_subset.setLevel(previous_level)


def test_replay_worker_timing_records_routes_export_and_skips_excel(caplog) -> None:
    logger = logging.getLogger("tests.worker_timing_route")
    result = {
        "file": r"C:\data\demo.bdf",
        "export_timing_records": [
            {"source": "post_process", "stage": "workbook_write", "elapsed_ms": 10},
            {
                "source": "excel",
                "stage": "sheet_to_excel",
                "elapsed_ms": 20,
                "sheet": "FullSNR",
                "rows": 64,
                "cols": 2501,
            },
        ],
    }

    with caplog.at_level(logging.INFO, logger="tests.worker_timing_route"):
        log_router.replay_worker_timing_records(logger, result=result)

    assert "[EXPORT TIMING] file=demo.bdf stage=workbook_write" in caplog.text
    assert "[EXCEL TIMING]" not in caplog.text
    assert "sheet='FullSNR'" not in caplog.text
