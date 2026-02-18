from fractions import Fraction

import numpy as np
import pytest

from Main_App.Legacy_App.fft_crop_utils import compute_onbin_N, compute_onbin_step
from Main_App.Legacy_App.post_process import _attempt_legacy_55_onbin_crop
from Main_App.Legacy_App.post_process_excel import build_fft_neighbors_rows


def test_compute_onbin_step_fs_256_and_divisible_n():
    fs_i, n_step, err = compute_onbin_step(256.0, Fraction(6, 5))
    assert err is None
    assert fs_i == 256
    assert n_step == 640

    available_samples = 32257
    n = compute_onbin_N(available_samples, n_step)
    assert n % 640 == 0


def test_compute_onbin_step_fs_512_and_divisible_n():
    fs_i, n_step, err = compute_onbin_step(512.0, Fraction(6, 5))
    assert err is None
    assert fs_i == 512
    assert n_step == 1280

    n = compute_onbin_N(9999, n_step)
    assert n % n_step == 0


def test_compute_onbin_n_smaller_than_step_returns_zero():
    _, n_step, err = compute_onbin_step(256.0, Fraction(6, 5))
    assert err is None
    n = compute_onbin_N(available_samples=n_step - 1, N_step=n_step)
    assert n == 0


def test_compute_onbin_n_stop_exclusive_no_plus_one():
    _, n_step, err = compute_onbin_step(256.0, Fraction(6, 5))
    assert err is None
    n = compute_onbin_N(available_samples=n_step, N_step=n_step)
    assert n == n_step


def test_fft_neighbors_sheet_metadata_uses_enforced_n_and_df():
    fs = 256.0
    n_samples = 640
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    fft_amplitudes = np.ones((1, len(freqs)))

    rows = build_fft_neighbors_rows(
        file_name="demo.fif",
        condition_label="cond",
        condition_id="1",
        repetition_index="1",
        electrode_names=["Oz"],
        fft_amplitudes=fft_amplitudes,
        freqs=freqs,
        fs=fs,
        n_samples=n_samples,
        target_freq=1.2,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["N"] == n_samples
    assert row["df_hz"] == fs / n_samples
    assert row["crop_mode"] == "fixed_epoch_fallback"


def test_fft_neighbors_sheet_includes_crop_diagnostics_for_onbin():
    fs = 256.0
    n_samples = 6400
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    fft_amplitudes = np.ones((1, len(freqs)))

    rows = build_fft_neighbors_rows(
        file_name="demo.fif",
        condition_label="cond",
        condition_id="1",
        repetition_index="1",
        electrode_names=["Oz"],
        fft_amplitudes=fft_amplitudes,
        freqs=freqs,
        fs=fs,
        n_samples=n_samples,
        target_freq=1.2,
        crop_mode="55_onbin",
        n55=16,
        first55_samp=100,
        last55_samp=6500,
        n_step=640,
        fallback_reason="",
    )

    row = rows[0]
    assert row["crop_mode"] == "55_onbin"
    assert row["N_step"] == 640
    assert row["N_mod_step"] == 0
    assert row["fallback_reason"] == ""


def test_fft_neighbors_sheet_rejects_non_divisible_55_onbin_n():
    fs = 256.0
    n_samples = 6500
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    fft_amplitudes = np.ones((1, len(freqs)))

    with pytest.raises(ValueError):
        build_fft_neighbors_rows(
            file_name="demo.fif",
            condition_label="cond",
            condition_id="1",
            repetition_index="1",
            electrode_names=["Oz"],
            fft_amplitudes=fft_amplitudes,
            freqs=freqs,
            fs=fs,
            n_samples=n_samples,
            target_freq=1.2,
            crop_mode="55_onbin",
            n_step=640,
        )


def test_legacy_55_onbin_crop_prefers_55_branch_and_enforces_step():
    sfreq = 256.0
    n_samples = 6400
    avg_data = np.ones((2, n_samples))
    events = np.array(
        [
            [1000, 0, 1],
            [1256, 0, 55],
            [1512, 0, 55],
            [1768, 0, 55],
            [2024, 0, 55],
            [2280, 0, 55],
            [2536, 0, 55],
            [2792, 0, 55],
            [3048, 0, 55],
            [3304, 0, 55],
            [3560, 0, 55],
            [3816, 0, 55],
            [4072, 0, 55],
            [4328, 0, 55],
            [4584, 0, 55],
            [5000, 0, 2],
        ],
        dtype=int,
    )

    cropped, crop_mode, n55, first55, last55, n_step, fallback_reason = _attempt_legacy_55_onbin_crop(
        avg_data=avg_data,
        sfreq=sfreq,
        data_idx=0,
        condition_id=1,
        onset_ids=[1, 2, 3, 4, 5],
        global_events=events,
        stream_end_sample=6000,
        epoch_start_sec=0.0,
    )

    assert crop_mode == "55_onbin"
    assert fallback_reason == ""
    assert n55 == 14
    assert first55 == 1256
    assert last55 == 4584
    assert n_step == 640
    assert cropped.shape[1] % 640 == 0


def test_legacy_55_onbin_crop_reports_specific_fallback_reason_when_no_55():
    sfreq = 256.0
    avg_data = np.ones((2, 2000))
    events = np.array(
        [
            [1000, 0, 1],
            [1600, 0, 2],
        ],
        dtype=int,
    )

    _, crop_mode, n55, first55, last55, n_step, fallback_reason = _attempt_legacy_55_onbin_crop(
        avg_data=avg_data,
        sfreq=sfreq,
        data_idx=0,
        condition_id=1,
        onset_ids=[1, 2, 3, 4, 5],
        global_events=events,
        stream_end_sample=2000,
        epoch_start_sec=0.0,
    )

    assert crop_mode == "fixed_epoch_fallback"
    assert fallback_reason == "no_55_in_block"
    assert n55 == 0
    assert first55 is None
    assert last55 is None
    assert n_step == 640
