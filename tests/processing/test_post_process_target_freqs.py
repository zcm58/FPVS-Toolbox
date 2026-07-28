from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.Shared.post_process import (
    _create_output_subfolder,
    _mean_epochs_float64,
    _resolve_target_frequencies,
    post_process,
)


@pytest.mark.parametrize(
    "array_kind",
    ["float64", "float32", "noncontiguous"],
)
def test_mean_epochs_float64_matches_copying_expression_byte_exact(
    array_kind: str,
) -> None:
    epoch_data = np.random.default_rng(24).normal(size=(7, 5, 18))
    if array_kind == "float32":
        epoch_data = epoch_data.astype(np.float32)
    elif array_kind == "noncontiguous":
        epoch_data = epoch_data[:, :, ::2]
        assert not epoch_data.flags.c_contiguous

    expected = np.mean(epoch_data.astype(np.float64), axis=0)
    actual = _mean_epochs_float64(epoch_data)

    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


def test_mean_epochs_float64_preserves_broadcast_layout_result_bytes() -> None:
    base = np.array(
        [
            [-1.4238250364546312, 1.2637284581291104, -0.8706617379590857],
            [-0.2591732349343976, -0.07534330701052097, -0.740884652085609],
        ],
        dtype=np.float64,
    )
    epoch_data = np.broadcast_to(base, (9, *base.shape))
    assert epoch_data.strides[0] == 0
    assert not epoch_data.flags.c_contiguous
    assert not epoch_data.flags.f_contiguous

    expected = np.mean(epoch_data.astype(np.float64), axis=0)
    actual = _mean_epochs_float64(epoch_data)

    assert actual.tobytes() == expected.tobytes()


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


def test_create_output_subfolder_routes_condition_then_group(tmp_path) -> None:
    app = SimpleNamespace(log=lambda _message: None)

    output = _create_output_subfolder(
        app,
        tmp_path,
        "Condition A",
        "Control",
    )

    assert output == str((tmp_path / "Condition A" / "Control").resolve())
    assert (tmp_path / "Condition A" / "Control").is_dir()


def test_create_output_subfolder_raises_instead_of_falling_back(
    tmp_path,
    monkeypatch,
) -> None:
    logs: list[str] = []
    app = SimpleNamespace(log=logs.append)

    def fail_mkdir(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("Main_App.Shared.post_process.os.makedirs", fail_mkdir)

    with pytest.raises(OSError, match="disk unavailable"):
        _create_output_subfolder(app, tmp_path, "Condition A", "Control")

    assert logs and "Processing cannot continue" in logs[-1]
    assert "Saving to parent" not in logs[-1]


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

    caplog.set_level(logging.DEBUG, logger="Main_App.Shared.post_process")
    post_process(app, ["CondA"])

    assert "[EXPORT TIMING]" in caplog.text
    assert "stage=condition_skip_no_data" in caplog.text
    assert "stage=post_process_total" in caplog.text
    assert {record["stage"] for record in app.export_timing_records} >= {
        "condition_skip_no_data",
        "post_process_total",
    }
