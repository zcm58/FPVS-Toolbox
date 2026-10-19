"""Exercise the shared engine without a manufacturer or native file format."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import mne
import numpy as np
import pytest

from Main_App.io import acquisition_metadata
from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
from Main_App.io.recording_contract import RecordingContract
from Main_App.processing import preprocess


def _admitted_recording():
    names = ["E9", "E1", "E4", "E2", "R1", "R2", "Trigger"]
    data = np.random.default_rng(2718).normal(scale=1e-6, size=(len(names), 20000))
    data[-1] = 0
    for start, marker in [(0, 22), (4, 21), (400, 22), (404, 21), (12000, 22)]:
        data[-1, start:start + 4] = marker
    raw = mne.io.RawArray(
        data, mne.create_info(names, 256, ["eeg"] * 6 + ["stim"]), verbose=False,
    )
    geometry = attach_raw_recorded_geometry(raw)
    contract = RecordingContract(
        initial_reference_mode="channels", initial_reference_channels=("R1", "R2"),
        drop_reference_channels=True, max_idx_keep=3, canonical_scalp_order=None,
        recorded_channel_geometry=True, kurtosis_screening_supported=False,
        strict_processing_errors=True, geometry_fingerprint=geometry["geometry_version"],
        acquisition_label="EEG", marker_impulses=True,
        provenance_json=json.dumps({"method_version": "explicit_channels_v1"}),
        montage_id="recorded", mapping_profile="recorded_labels",
        fingerprint_montage="recorded", fingerprint_mapping="recorded_labels",
        stim_channel="Trigger", load_reference_channels=("R1", "R2"),
        channel_limit=3, geometry_json=json.dumps(geometry),
    )
    return raw, contract


@pytest.mark.parametrize("filter_and_resample", [False, True])
def test_explicit_metadata_pipeline_matches_independent_mne_without_hardware_resolution(
    monkeypatch, filter_and_resample,
):
    from Main_App.projects import hardware

    raw, contract = _admitted_recording()
    expected = raw.copy()
    expected.set_eeg_reference(["R1", "R2"], projection=False, verbose=False)
    expected.drop_channels(["R1", "R2"])
    expected.pick_channels(["E9", "E1", "E4", "Trigger"], ordered=False)
    if filter_and_resample:
        expected.filter(
            0.1, 40.0, method="fir", phase="zero-double", fir_window="hamming",
            fir_design="firwin", l_trans_bandwidth=0.1, h_trans_bandwidth=0.1,
            filter_length=16897, skip_by_annotation="edge", verbose=False,
        )
        expected.resample(128, npad="auto", window="hann", verbose=False)
    expected.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    expected.apply_proj(verbose=False)
    expected_events = mne.find_events(
        expected, stim_channel="Trigger", shortest_event=1,
        initial_event=True, consecutive=True, verbose=False,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Numerical processing attempted to resolve acquisition hardware.")

    monkeypatch.setattr(hardware, "resolve_hardware", forbidden)
    monkeypatch.setattr(acquisition_metadata, "resolve_recording_contract", forbidden)
    monkeypatch.setattr(acquisition_metadata, "resolve_acquisition_policy", forbidden)
    monkeypatch.setattr(preprocess, "resolve_recording_contract", forbidden)
    settings = {
        "high_pass": 0.1 if filter_and_resample else None,
        "low_pass": 40.0 if filter_and_resample else None,
        "downsample_rate": 128 if filter_and_resample else None,
        "line_noise_filter_enabled": False, "kurtosis_screening_enabled": False,
        "raw_signal_screening_enabled": False, "removed_electrode_detection_mode": "off",
        "auto_detect_removed_electrodes": False,
    }
    logs = []
    processed, rejected = preprocess.perform_preprocessing(
        raw, settings, logs.append, "admitted-recording", recording_contract=contract,
    )
    assert processed is not None, settings.get("_fpvs_preprocessing_error")
    assert rejected == 0
    assert processed.ch_names == ["E9", "E1", "E4", "Trigger"]
    assert processed.info["sfreq"] == expected.info["sfreq"]
    np.testing.assert_array_equal(processed.get_data(), expected.get_data())
    actual_events = mne.find_events(
        processed, stim_channel=contract.stim_channel, shortest_event=1,
        **contract.event_kwargs, verbose=False,
    )
    np.testing.assert_array_equal(actual_events, expected_events)
    assert actual_events[:, 2].tolist() == [22, 21, 22, 21, 22]
    assert settings["_fpvs_initial_ref_pair"] == ("R1", "R2")
    assert settings["_fpvs_kurtosis_checkpoint_status"] == "disabled"
    assert settings["_fpvs_geometry"]["retained_scalp_channels"] == ["E9", "E1", "E4"]
    assert settings["_fpvs_interpolated_channels"] == []
    assert settings["_fpvs_pipeline_policy"] == {"method_version": "explicit_channels_v1"}
    assert "hardware_platform" not in settings
    assert not any("_fpvs_preprocessing_error" in item for item in logs)


@pytest.mark.parametrize("relative_path", [
    "src/Main_App/processing/preprocess.py",
    "src/Main_App/processing/reference.py",
    "src/Main_App/processing/preflight_qc.py",
    "src/Main_App/processing/kurtosis_review_scan.py",
    "src/Main_App/workers/process_runner.py",
])
def test_shared_processing_imports_no_manufacturer_implementations(relative_path):
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
    forbidden_modules = {
        "Main_App.io.eeg_geometry", "Main_App.io.brain_products",
        "Main_App.io.brainvision", "Main_App.io.unicorn_raw",
    }
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in forbidden_modules:
                violations.append((node.lineno, node.module))
            for name in node.names:
                if any(token in name.name.casefold() for token in ("biosemi", "brain_products", "brainvision", "unicorn")):
                    violations.append((node.lineno, name.name))
        elif isinstance(node, ast.Import):
            violations.extend((node.lineno, name.name) for name in node.names if name.name in forbidden_modules)
    assert not violations, f"Manufacturer interpretation belongs upstream: {violations}"
