import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PySide6")
mne = pytest.importorskip("mne")

from Main_App.PySide6_App.Backend.preprocess import (  # noqa: E402
    begin_preproc_audit,
    finalize_preproc_audit,
    perform_preprocessing,
)


def _build_raw():
    sfreq = 256.0
    samples = int(sfreq)
    ch_names = ["EXG1", "EXG2", "Pz", "Status"]
    ch_types = ["eeg", "eeg", "eeg", "stim"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
    data = np.random.RandomState(7).randn(len(ch_names), samples)
    stim = np.zeros(samples)
    stim[10] = 3
    data[-1] = stim
    return mne.io.RawArray(data, info)


def test_fif_flag_audit_reports_zero(tmp_path):
    raw = _build_raw()
    params = {
        "downsample": 256,
        "downsample_rate": 256,
        "low_pass": 50.0,
        "high_pass": 0.1,
        "reject_thresh": 0.0,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 3,
        "stim_channel": "Status",
        "save_preprocessed_fif": False,
    }

    before = begin_preproc_audit(raw, params, "flag.bdf")
    processed, rejected = perform_preprocessing(raw, params, lambda msg: None, "flag.bdf")
    assert processed is not None
    events = mne.find_events(processed, stim_channel="Status", shortest_event=1)
    audit, problems = finalize_preproc_audit(
        before,
        processed,
        params,
        "flag.bdf",
        events_info={"stim_channel": "Status", "n_events": int(len(events)), "source": "stim"},
        fif_written=0,
        n_rejected=rejected,
    )

    assert audit["save_preprocessed_fif"] is False
    assert audit["fif_written"] == 0
    assert problems == []
