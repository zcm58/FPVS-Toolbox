"""Mobile source preservation, event authority and invalid-source admission."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.io.bids_import import prepare_bids_recording, read_bids_recording
from Main_App.io.brain_products import close_brain_products_raw
from Main_App.io.hardware_loader import open_profiled_bdf_raw
from Main_App.io.pipeline_events import canonical_recording_events
from tests.project_io.test_unicorn_raw import _fixture, _settings


def _project_settings(root, *, annotations=False):
    settings = _settings(annotations=annotations)
    settings.update(project_root=str(root), hardware_platform="unicorn",
                    hardware_confirmed=True, electrode_montage="unicorn8",
                    electrode_mapping_profile="unicorn_factory_v1",
                    downsample_rate=250, stim_channel="Status")
    if annotations:
        settings["recording_event_policy"] = {
            "authority": "annotations", "numeric_annotations": True,
        }
    return settings


@pytest.mark.parametrize("preload", [False, True, "disk"])
@pytest.mark.parametrize("annotations", [False, True])
def test_mobile_bids_units_source_bytes_events_and_preload(tmp_path, preload, annotations):
    options = {"variant": "BDF+C", "status": False,
               "record_onsets": ("0.125",),
               "annotations": ([b"+0.129\x1455\x14\x00", b"+0.133\x1455\x14\x00"],)} if annotations else {}
    source = _fixture(tmp_path / "input.bdf", **options)
    original = source.read_bytes()
    settings = _project_settings(tmp_path, annotations=annotations)
    descriptor = prepare_bids_recording(source, project_root=tmp_path, settings=settings)
    manifest = json.loads(descriptor.manifest_path.read_text(encoding="utf-8"))
    assert (descriptor.dataset_root / "sourcedata" / manifest["subject"] / source.name).read_bytes() == original
    normalized = descriptor.header_path.read_bytes()
    header_size = int(original[184:192])
    assert normalized[header_size:] == original[header_size:]
    assert normalized != original  # Only reviewed ?V dimensions are corrected.
    assert source.read_bytes() == original
    assert prepare_bids_recording(source, project_root=tmp_path, settings=settings).reused
    mode = str(tmp_path / "samples.dat") if preload == "disk" else preload
    raw = open_profiled_bdf_raw(SimpleNamespace(), source, settings=settings, preload=mode)
    try:
        expected = [[1, 0, 55], [2, 0, 55]] if annotations else [[1, 0, 55], [2, 0, 55], [3, 0, 1], [4, 0, 255]]
        np.testing.assert_array_equal(canonical_recording_events(raw), expected)
        assert raw.ch_names[:8] == ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"]
        assert raw.get_channel_types() == ["eeg"] * 8 + ["misc"] * 3 + ["stim"]
        assert raw.info["sfreq"] == 250
        np.testing.assert_allclose(raw.get_data(picks=["Fz"])[0, [0, 6]], [-.75, .75], rtol=0, atol=1e-15)
        assert raw.preload is (preload is not False)
        if preload == "disk":
            assert isinstance(raw._data, np.memmap)
    finally:
        close_brain_products_raw(raw)
    if preload == "disk":
        Path(mode).unlink()
    assert source.read_bytes() == original


@pytest.mark.parametrize("channel,values,match", [
    ("VALID", [1] * 249 + [0], "VALID"),
    ("CNT", list(range(249)) + [250], "counter"),
    ("CNT", list(range(249)) + [248], "counter"),
])
def test_mobile_bids_rejects_observed_invalid_telemetry(tmp_path, channel, values, match):
    data = {"CNT": [list(range(250))], "VALID": [[1] * 250], "DT": [[4] * 250], channel: [values]}
    source = _fixture(tmp_path / "input.bdf", signal_values=data)
    with pytest.raises(ValueError, match=match):
        prepare_bids_recording(source, project_root=tmp_path, settings=_project_settings(tmp_path))
    assert not list((tmp_path / ".fpvs_cache" / "bids-import").glob("*/import.json"))


def test_mobile_bids_normalizes_uppercase_status(tmp_path):
    source = _fixture(tmp_path / "input.bdf", unit="uV")
    data = bytearray(source.read_bytes())
    index = data.index(b"Status          ")
    data[index:index + 16] = b"STATUS          "
    source.write_bytes(data)
    descriptor = prepare_bids_recording(source, project_root=tmp_path, settings=_project_settings(tmp_path))
    raw = read_bids_recording(descriptor)
    try:
        assert "Status" in raw.ch_names and "STATUS" not in raw.ch_names
        np.testing.assert_array_equal(canonical_recording_events(raw)[:, 2], [55, 55, 1, 255])
    finally:
        close_brain_products_raw(raw)


def test_mobile_bids_cache_key_includes_explicit_event_policy(tmp_path):
    source = _fixture(tmp_path / "input.bdf")
    settings = _project_settings(tmp_path)
    first = prepare_bids_recording(source, project_root=tmp_path, settings=settings)
    settings["recording_event_policy"] = {"authority": "status", "numeric_annotations": False}
    second = prepare_bids_recording(source, project_root=tmp_path, settings=settings)
    assert second.manifest_path != first.manifest_path


def test_mobile_bids_rejects_discontinuous_storage(tmp_path):
    source = _fixture(tmp_path / "input.bdf", variant="BDF+D")
    with pytest.raises(ValueError, match="discontinuous|BDF.D"):
        prepare_bids_recording(source, project_root=tmp_path, settings=_project_settings(tmp_path))


def test_mobile_bids_retains_quantized_counter_without_false_loss_claim(tmp_path):
    source = _fixture(tmp_path / "input.bdf", unit="uV", physical_ranges={"CNT": (0, 16000000)})
    descriptor = prepare_bids_recording(source, project_root=tmp_path, settings=_project_settings(tmp_path))
    raw = read_bids_recording(descriptor)
    try:
        values = raw.get_data(picks=["CNT"])[0]
        assert np.any(values != np.floor(values))
        assert raw._fpvs_mobile_import["telemetry"]["cnt"]["status"] == "calibration_semantics_unverified"
        assert raw._fpvs_mobile_import["telemetry"]["valid"]["status"] == "identity_counts_checked"
    finally:
        close_brain_products_raw(raw)


def test_mobile_bids_preserves_documented_motion_and_battery_as_auxiliary(tmp_path):
    from tests.project_io.test_unicorn_raw import EEG
    auxiliary = ("CNT", "VALID", "DT", "BAT", "ACC X", "ACC Y", "ACC Z", "GYR X", "GYR Y", "GYR Z")
    values = {name: [[2] * 250] for name in auxiliary}
    values.update(CNT=[list(range(250))], VALID=[[1] * 250])
    source = _fixture(tmp_path / "input.bdf", unit="uV", eeg_names=(*EEG, *auxiliary),
                      signal_units={name: "" for name in auxiliary}, signal_values=values)
    descriptor = prepare_bids_recording(source, project_root=tmp_path, settings=_project_settings(tmp_path))
    raw = read_bids_recording(descriptor)
    try:
        assert raw.get_channel_types(picks=list(auxiliary)) == ["misc"] * len(auxiliary)
        np.testing.assert_array_equal(raw.get_data(picks=["ACC X", "BAT"]), np.full((2, 250), 2))
    finally:
        close_brain_products_raw(raw)


def test_active_three_auxiliary_reference_keeps_voltage_calibration(tmp_path):
    from tests.bdf_factory import write_bdf
    from Main_App.processing.reference import apply_recorded_reference
    source = write_bdf(
        tmp_path / "input.bdf", variant="BDF", record_onsets=("0",), samples_per_record=256,
        eeg_names=("Fz", "Cz", "EXG3", "AUX1"), signal_units={"AUX1": ""},
        signal_values={name: [[value] * 256] for name, value in
                       (("Fz", 10), ("Cz", 20), ("EXG3", 4), ("AUX1", 100))},
    )
    settings = dict(project_root=str(tmp_path), hardware_platform="biosemi_active_three",
                    hardware_confirmed=True, electrode_montage="recorded",
                    initial_reference="channels", initial_reference_channels=["EXG3"],
                    drop_reference_channels=True, channel_types={"AUX1": "misc"})
    raw = open_profiled_bdf_raw(SimpleNamespace(), source, settings=settings, preload=True)
    try:
        np.testing.assert_allclose(raw.get_data(picks=["Fz", "Cz", "EXG3"])[:, 0], [10e-6, 20e-6, 4e-6], rtol=0, atol=1e-20)
        apply_recorded_reference(raw, settings, raw._fpvs_recording_contract)
        np.testing.assert_allclose(raw.get_data(picks=["Fz", "Cz"])[:, 0], [6e-6, 16e-6], rtol=0, atol=1e-20)
        assert "EXG3" not in raw.ch_names
        np.testing.assert_array_equal(raw.get_data(picks=["AUX1"]), np.full((1, 256), 100))
    finally:
        close_brain_products_raw(raw)
