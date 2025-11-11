import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.GUI.main_window import MainWindow  # noqa: E402


@pytest.fixture
def main_window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _payload(tmp_path: Path) -> dict:
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
        "act_ref_applied": True,
        "req_stim": "Status",
        "n_channels": 8,
        "req_max_channels": 8,
        "n_events": 2,
        "act_events": 2,
        "req_reject_thresh": 3.0,
        "n_rejected": 0,
        "stim_channel": "Status",
        "save_preprocessed_fif": False,
        "req_save_fif": False,
        "fif_written": 0,
        "act_fif_written": 0,
        "sha256_head": "deadbeef",
    }
    return {"results": [{"file": str(tmp_path / "demo.bdf"), "audit": audit, "problems": []}]}


def test_audit_json_toggle(tmp_path, main_window, monkeypatch):
    logs: list[tuple[str, int]] = []
    main_window.log = lambda message, level=logging.INFO: logs.append((message, level))
    results_dir = tmp_path / "Results" / "Excel"
    results_dir.mkdir(parents=True)
    main_window.save_folder_path = SimpleNamespace(get=lambda: str(results_dir))
    main_window.validated_params = {"downsample": 256}

    monkeypatch.setattr(main_window.settings, "debug_enabled", lambda: False)
    main_window._on_processing_finished(_payload(tmp_path))
    assert any("DS req=" in msg for msg, _ in logs if msg.startswith("[AUDIT]"))
    audit_dir = results_dir.parent / "audit"
    assert (not audit_dir.exists()) or (not any(audit_dir.iterdir()))

    logs.clear()
    monkeypatch.setattr(main_window.settings, "debug_enabled", lambda: True)
    main_window._on_processing_finished(_payload(tmp_path))
    created = list((results_dir.parent / "audit").glob("*.json"))
    assert created
    assert any("FIF req=" in msg for msg, _ in logs if msg.startswith("[AUDIT]"))
