from __future__ import annotations

import logging

from Main_App import _StructuredExtraFormatter


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
