from __future__ import annotations

import logging
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.Shared.post_process import (
    _can_batch_target_noise,
    _create_output_subfolder,
    _eeg_pick_indices,
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


@pytest.mark.parametrize("object_kind", ["epochs", "evoked"])
def test_direct_mne_eeg_pick_matches_copy_pick_byte_exact(object_kind: str) -> None:
    rng = np.random.default_rng(1729)
    info = mne.create_info(
        ["Fp1", "EOG", "Cz", "Pz", "STI"],
        sfreq=256.0,
        ch_types=["eeg", "eog", "eeg", "eeg", "stim"],
    )
    info["bads"] = ["Cz"]
    if object_kind == "epochs":
        original = mne.EpochsArray(
            rng.normal(size=(4, 5, 96)),
            info,
            tmin=0.0,
            baseline=None,
            verbose=False,
        )
        is_evoked = False
    else:
        original = mne.EvokedArray(
            rng.normal(size=(5, 96)),
            info,
            tmin=0.0,
            verbose=False,
        )
        is_evoked = True

    original_bytes = (
        original.data.tobytes()
        if is_evoked
        else original.get_data(copy=True).tobytes()
    )
    expected = original.copy().pick(
        "eeg",
        exclude=[] if is_evoked else "bads",
    )
    picks = _eeg_pick_indices(original, is_evoked=is_evoked)
    actual_names = [original.ch_names[int(index)] for index in picks]
    if is_evoked:
        expected_data = expected.data
        actual_data = original.data[picks, :]
    else:
        expected_data = expected.get_data()
        actual_data = original.get_data(picks=picks, copy=True)

    assert actual_names == expected.ch_names
    assert actual_data.dtype == expected_data.dtype
    assert actual_data.shape == expected_data.shape
    assert actual_data.tobytes() == expected_data.tobytes()
    assert (
        original.data.tobytes()
        if is_evoked
        else original.get_data(copy=True).tobytes()
    ) == original_bytes
    assert original.info["bads"] == ["Cz"]


def test_direct_mne_eeg_pick_defers_empty_selection_to_copy_pick() -> None:
    info = mne.create_info(["EOG"], sfreq=128.0, ch_types=["eog"])
    evoked = mne.EvokedArray(np.zeros((1, 24)), info, verbose=False)

    picks = _eeg_pick_indices(evoked, is_evoked=True)

    assert picks.size == 0
    with pytest.raises(ValueError) as expected_error:
        evoked.copy().pick("eeg", exclude=[])
    assert "could not be interpreted" in str(expected_error.value)


def test_target_noise_batch_guard_is_conservative() -> None:
    amplitudes = np.abs(np.random.default_rng(11).normal(size=(4, 96)))
    target_indices = np.array([20, 40, -1], dtype=np.intp)

    assert _can_batch_target_noise(amplitudes, target_indices)

    with_zero = amplitudes.copy()
    with_zero[:, 30] = 0.0
    assert not _can_batch_target_noise(with_zero, target_indices)

    tied = amplitudes.copy()
    tied[:, 30:51] = 1.0
    assert not _can_batch_target_noise(tied, np.array([40], dtype=np.intp))


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
