from fractions import Fraction

import numpy as np

from Main_App.Legacy_App.fft_crop_utils import compute_onbin_N, compute_onbin_step
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
