import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.utils.audit import format_audit_summary


def test_format_audit_summary_includes_req_act():
    audit = {
        "sfreq": 256.0,
        "req_downsample": 256.0,
        "act_sfreq": 256.0,
        "req_highpass": 0.1,
        "act_highpass": 0.1,
        "req_lowpass": 50.0,
        "act_lowpass": 50.0,
        "req_ref_chans": ["EXG1", "EXG2"],
        "ref_chans": ["EXG1", "EXG2"],
        "act_ref_applied": True,
        "req_stim": "Status",
        "stim_channel": "Status",
        "req_max_channels": 8,
        "n_channels": 8,
        "req_reject_thresh": 3.0,
        "n_rejected": 2,
        "act_events": 240,
        "req_save_fif": True,
        "act_fif_written": 1,
    }

    line, is_warning = format_audit_summary(audit)
    assert not is_warning
    assert "DS req=256.0Hz act=256.0Hz" in line
    assert "HP req=0.1Hz act=0.1Hz" in line
    assert "LP req=50.0Hz act=50.0Hz" in line
    assert "ref req=('EXG1', 'EXG2')" in line
    assert "ch req=≤8 act=8" in line
    assert "events req_stim='Status' act=240" in line
    assert "reject req=3 act=2" in line
    assert "FIF req=True act_written=1" in line
