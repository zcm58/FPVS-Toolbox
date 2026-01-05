import importlib.util
import json
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not available", allow_module_level=True)

from Main_App.PySide6_App.Backend.project import Project
from Main_App.PySide6_App.Backend.preprocessing_settings import PREPROCESSING_CANONICAL_KEYS


def test_normalization_and_roundtrip(tmp_path):
    manifest_path = Path(tmp_path) / "project.json"
    manifest_path.write_text(
        json.dumps(
            {
                "preprocessing": {
                    "low_pass": "45",
                    "high_pass": "0.25",
                    "downsample_rate": "512",
                    "reject_thresh": "4.2",
                    "epoch_start": "-0.5",
                    "epoch_end": "110",
                    "ref_chan1": "Cz",
                    "ref_chan2": "Pz",
                    "max_idx_keep": "32",
                    "max_bad_chans": "4",
                    "save_preprocessed_fif": "true",
                    "stim_channel": "Status",
                }
            }
        )
    )

    project = Project.load(tmp_path)
    normalized = project.preprocessing

    assert normalized["high_pass"] == 0.25
    assert normalized["low_pass"] == 45.0
    assert normalized["downsample"] == 512
    assert normalized["rejection_z"] == 4.2
    assert normalized["epoch_start_s"] == -0.5
    assert normalized["epoch_end_s"] == 110.0
    assert normalized["ref_chan1"] == "Cz"
    assert normalized["ref_chan2"] == "Pz"
    assert normalized["max_chan_idx_keep"] == 32
    assert normalized["max_bad_chans"] == 4
    assert normalized["save_preprocessed_fif"] is True
    assert normalized["stim_channel"] == "Status"

    project.update_preprocessing(
        {
            "low_pass": 30,
            "high_pass": 0.5,
            "downsample": 256,
            "rejection_z": 3.0,
            "epoch_start_s": -1.0,
            "epoch_end_s": 120.0,
            "ref_chan1": "EXG1",
            "ref_chan2": "EXG2",
            "max_chan_idx_keep": 64,
            "max_bad_chans": 8,
            "save_preprocessed_fif": False,
            "stim_channel": "Status",
        }
    )
    project.save()

    saved = json.loads(manifest_path.read_text())
    stored_keys = set(saved["preprocessing"].keys())
    assert stored_keys == set(PREPROCESSING_CANONICAL_KEYS)
    assert saved["preprocessing"]["downsample"] == 256
    assert "downsample_rate" not in saved["preprocessing"]

    fresh = Project.load(tmp_path)
    assert fresh.preprocessing["high_pass"] == 0.5
    assert fresh.preprocessing["low_pass"] == 30.0
    assert fresh.preprocessing["max_chan_idx_keep"] == 64
    assert fresh.preprocessing["save_preprocessed_fif"] is False


def test_project_loads_legacy_inverted_bandpass(tmp_path):
    manifest_path = Path(tmp_path) / "project.json"
    manifest_path.write_text(
        json.dumps(
            {
                "preprocessing": {
                    "low_pass": "0.1",
                    "high_pass": "50.0",
                }
            }
        )
    )

    project = Project.load(tmp_path)
    assert project.preprocessing["low_pass"] == 50.0
    assert project.preprocessing["high_pass"] == 0.1
