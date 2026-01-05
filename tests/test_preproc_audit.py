import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PySide6")
mne = pytest.importorskip("mne")

from Main_App.PySide6_App.Backend.preprocess import (  # noqa: E402
    begin_preproc_audit,
    finalize_preproc_audit,
    perform_preprocessing,
)


def _synth_raw():
    sfreq = 512.0
    samples = int(sfreq * 2)
    ch_names = ["EXG1", "EXG2"] + [f"E{i}" for i in range(1, 9)] + ["Status"]
    ch_types = ["eeg", "eeg"] + ["eeg"] * 8 + ["stim"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
    data = np.random.RandomState(42).randn(len(ch_names), samples)
    stim_idx = ch_names.index("Status")
    stim = np.zeros(samples)
    stim[100] = 5
    stim[400] = 7
    data[stim_idx] = stim
    return mne.io.RawArray(data, info)


def test_preproc_audit_round_trip():
    raw = _synth_raw()
    params = {
        "downsample": 256,
        "downsample_rate": 256,
        "low_pass": 50.0,
        "high_pass": 0.1,
        "reject_thresh": 3.0,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 8,
        "stim_channel": "Status",
        "save_preprocessed_fif": False,
    }

    before = begin_preproc_audit(raw, params, "demo.bdf")
    processed, rejected = perform_preprocessing(raw, params, lambda msg: None, "demo.bdf")
    assert processed is not None

    events = mne.find_events(processed, stim_channel="Status", shortest_event=1)
    audit, problems = finalize_preproc_audit(
        before,
        processed,
        params,
        "demo.bdf",
        events_info={"stim_channel": "Status", "n_events": int(len(events)), "source": "stim"},
        fif_written=0,
        n_rejected=rejected,
    )

    assert problems == []
    assert abs(audit["sfreq"] - 256.0) < 0.05
    assert audit["stim_channel"] == "Status"
    assert audit["sha256_head"] not in {"", "NA"}
