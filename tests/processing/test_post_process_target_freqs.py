from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from Main_App.Shared.post_process import _resolve_target_frequencies, post_process


def test_resolve_target_frequencies_from_nested_analysis_dict() -> None:
    app = SimpleNamespace(
        settings={"analysis": {"oddball_freq": 1.2, "bca_upper_limit": 24.0}}
    )

    freqs, upper = _resolve_target_frequencies(app)

    assert upper == pytest.approx(24.0)
    assert float(freqs[0]) == pytest.approx(1.2)
    assert float(freqs[-1]) == pytest.approx(24.0)
    assert len(freqs) == 20


def test_resolve_target_frequencies_from_settings_getter() -> None:
    class _FakeSettings:
        def get(self, section, option, fallback=None):
            if section == "analysis" and option == "oddball_freq":
                return "1.2"
            if section == "analysis" and option == "bca_upper_limit":
                return "19.2"
            return fallback

    app = SimpleNamespace(settings=_FakeSettings())

    freqs, upper = _resolve_target_frequencies(app)

    assert upper == pytest.approx(19.2)
    assert float(freqs[-1]) == pytest.approx(19.2)
    assert len(freqs) == 16


def test_resolve_target_frequencies_rejects_non_locked_oddball() -> None:
    app = SimpleNamespace(
        settings={"analysis": {"oddball_freq": 6.0, "bca_upper_limit": 30.0}}
    )

    with pytest.raises(ValueError, match="locked at 1.2 Hz"):
        _resolve_target_frequencies(app)


def test_post_process_logs_export_timing_when_no_data(tmp_path, caplog) -> None:
    class _PathBox:
        def get(self):
            return str(tmp_path)

    logs: list[str] = []
    app = SimpleNamespace(
        save_folder_path=_PathBox(),
        settings={},
        preprocessed_data={},
        data_paths=[],
        log=logs.append,
        export_timing_records=[],
    )

    caplog.set_level(logging.INFO, logger="Main_App.Shared.post_process")
    post_process(app, ["CondA"])

    assert "[EXPORT TIMING]" in caplog.text
    assert "stage=condition_skip_no_data" in caplog.text
    assert "stage=post_process_total" in caplog.text
    assert {record["stage"] for record in app.export_timing_records} >= {
        "condition_skip_no_data",
        "post_process_total",
    }
