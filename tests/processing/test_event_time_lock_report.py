# ruff: noqa: E402
import pytest

np = pytest.importorskip("numpy")
mne = pytest.importorskip("mne")

from Main_App.diagnostics.event_time_lock_report import (
    _compare_pre_post_events,
    _epoch_stats,
    _extract_events,
)
from Main_App.diagnostics import event_time_lock_report


def _make_raw_with_stim_pulses(
    sfreq: float,
    duration_s: float,
    pulse_onsets_s: list[float],
    pulse_width_samples: int,
    event_code: int = 7,
) -> mne.io.RawArray:
    n_samples = int(duration_s * sfreq)
    eeg = np.zeros((1, n_samples), dtype=float)
    stim = np.zeros((1, n_samples), dtype=float)
    for onset_s in pulse_onsets_s:
        start = int(round(onset_s * sfreq))
        stop = min(start + pulse_width_samples, n_samples)
        stim[0, start:stop] = float(event_code)

    data = np.vstack([eeg, stim])
    info = mne.create_info(["EEG 001", "Status"], sfreq=sfreq, ch_types=["eeg", "stim"])
    return mne.io.RawArray(data, info, verbose=False)


def test_find_events_and_epoch_lengths_consistent():
    raw = _make_raw_with_stim_pulses(
        sfreq=1024.0,
        duration_s=12.0,
        pulse_onsets_s=[1.0, 3.0, 5.0, 7.0, 9.0],
        pulse_width_samples=8,
        event_code=11,
    )

    events, summary = _extract_events(raw, stim_channel="Status", shortest_event=1)

    assert summary.source == "stim"
    assert summary.counts_by_code == {"11": 5}

    epoch_stats = _epoch_stats(raw, events, tmin=-0.1, tmax=0.4)
    code_stats = epoch_stats["per_code"]["11"]

    assert code_stats["n_epochs"] == 5
    assert code_stats["all_epochs_same_n_times"] is True
    assert len(set(code_stats["per_epoch_n_times"])) == 1


def test_resample_integrity_stable_for_wide_pulses():
    raw_pre = _make_raw_with_stim_pulses(
        sfreq=1024.0,
        duration_s=10.0,
        pulse_onsets_s=[1.0, 2.5, 4.0, 5.5, 7.0],
        pulse_width_samples=32,
        event_code=9,
    )
    pre_events, _ = _extract_events(raw_pre, stim_channel="Status", shortest_event=1)

    raw_post = raw_pre.copy().resample(256.0, npad="auto", verbose=False)
    post_events, _ = _extract_events(raw_post, stim_channel="Status", shortest_event=1)

    comparison = _compare_pre_post_events(
        pre_events,
        pre_sfreq=float(raw_pre.info["sfreq"]),
        post_events=post_events,
        post_sfreq=float(raw_post.info["sfreq"]),
    )

    assert comparison["counts_by_code_pre_vs_post"]["9"]["pre"] == 5
    assert comparison["counts_by_code_pre_vs_post"]["9"]["post"] == 5
    assert comparison["event_loss_flags"]["9"] is False


def test_resample_integrity_flags_loss_for_too_narrow_pulses():
    raw_pre = _make_raw_with_stim_pulses(
        sfreq=2048.0,
        duration_s=10.0,
        pulse_onsets_s=[1.0, 2.0, 3.0, 4.0, 5.0],
        pulse_width_samples=1,
        event_code=5,
    )
    pre_events, _ = _extract_events(raw_pre, stim_channel="Status", shortest_event=1)
    post_events = pre_events[:3].copy()

    comparison = _compare_pre_post_events(
        pre_events,
        pre_sfreq=float(raw_pre.info["sfreq"]),
        post_events=post_events,
        post_sfreq=256.0,
    )

    assert comparison["counts_by_code_pre_vs_post"]["5"]["pre"] == 5
    assert comparison["counts_by_code_pre_vs_post"]["5"]["post"] < 5
    assert comparison["event_loss_flags"]["5"] is True


def test_gui_entrypoint_applies_shared_theme(qapp, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QDialog
    from Main_App.gui import theme

    themed_apps = []
    monkeypatch.setattr(theme, "apply_fpvs_theme", lambda app: themed_apps.append(app))
    monkeypatch.setattr(QDialog, "show", lambda self: None)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    assert event_time_lock_report._run_gui() == 0
    assert themed_apps == [qapp]
