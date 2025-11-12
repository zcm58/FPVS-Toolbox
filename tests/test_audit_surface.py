import logging
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.GUI.main_window import MainWindow  # noqa: E402


@pytest.fixture
def main_window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _audit_payload(tmp_path: Path) -> dict:
    audit = {
        "file": str(tmp_path / "demo.bdf"),
        "sfreq": 256.0,
        "highpass": 0.1,
        "lowpass": 50.0,
        "req_downsample": 256.0,
        "act_sfreq": 256.0,
        "req_highpass": 0.1,
        "act_highpass": 0.1,
        "req_lowpass": 50.0,
        "act_lowpass": 50.0,
        "ref_chans": ["EXG1", "EXG2"],
        "req_ref_chans": ["EXG1", "EXG2"],
        "act_ref_applied": False,
        "req_stim": "Status",
        "n_channels": 8,
        "req_max_channels": 8,
        "n_events": 1,
        "act_events": 1,
        "req_reject_thresh": 3.0,
        "n_rejected": 0,
        "stim_channel": "Status",
        "save_preprocessed_fif": False,
        "req_save_fif": False,
        "fif_written": 2,
        "act_fif_written": 2,
        "sha256_head": "cafebabe",
    }
    problems = [
        "reference requested but custom_ref_applied=False",
        "save_preprocessed_fif=False but FIF outputs were written",
    ]
    return {
        "results": [
            {
                "file": str(tmp_path / "demo.bdf"),
                "audit": audit,
                "problems": problems,
            }
        ]
    }


def test_audit_problems_surface(tmp_path, main_window, monkeypatch):
    logs: list[tuple[str, int]] = []
    main_window.log = lambda message, level=logging.INFO: logs.append((message, level))
    monkeypatch.setattr(main_window.settings, "debug_enabled", lambda: False)

    main_window._on_processing_finished(_audit_payload(tmp_path))

    warning_lines = [msg for msg, level in logs if level == logging.WARNING]
    # Both problem strings must be surfaced in WARNING-level logs, even if combined.
    assert any(
        "reference requested but custom_ref_applied=False" in msg
        for msg in warning_lines
    )
    assert any(
        "save_preprocessed_fif=False but FIF outputs were written" in msg
        for msg in warning_lines
    )

    # There should also be at least one audit summary line.
    all_lines = [msg for msg, _ in logs]
    assert any(msg.startswith("[AUDIT]") for msg in all_lines)
