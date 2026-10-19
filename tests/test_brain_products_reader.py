"""Known-amplitude, sample-exact BrainVision import contracts without Qt."""
from __future__ import annotations

import json

import mne
import numpy as np
import pytest

from Main_App.io.brain_products import (
    BrainProductsFormatError,
    decode_brain_products_events,
    open_brain_products_recording,
    read_brain_products_raw,
    read_sampling_rate,
    source_files,
    validate_electrical_channel_units,
)


pytestmark = [pytest.mark.processing, pytest.mark.project_io]


def _write_bvcdf(tmp_path):
    path = tmp_path / "recording.vhdr"
    path.write_text(
        "Brain Vision Data Exchange Header File Version 1.0\n"
        "[Common Infos]\nCodepage=UTF-8\nDataFile=signal.eeg\nMarkerFile=events.vmrk\n"
        "DataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels=2\nSamplingInterval=1000\n"
        "[Binary Infos]\nBinaryFormat=INT_16\n[Channel Infos]\nCh1=Fz,,0.5,µV\nCh2=Cz,,2,µV\n",
        encoding="utf-8",
    )
    (tmp_path / "events.vmrk").write_text(
        "Brain Vision Data Exchange Marker File, Version 1.0\n"
        "[Common Infos]\nCodepage=UTF-8\nDataFile=signal.eeg\n[Marker Infos]\n"
        "Mk1=New Segment,,1,1,0\nMk2=Stimulus,S  1,1,1,0\n"
        "Mk3=Response,R  1,3,1,0\nMk4=Stimulus,S  2,6,1,0\n",
        encoding="utf-8",
    )
    counts = np.arange(20, dtype="<i2").reshape(10, 2)
    counts.tofile(tmp_path / "signal.eeg")
    return path, counts.T * np.array([0.5e-6, 2e-6])[:, None]


def _write_bvrf(tmp_path, dtype="Int16"):
    path = tmp_path / "recording.bvrh"
    header = {
        "BVRF": {"Version": "1.0.0"}, "BVRFHeaderFile": {"Version": "1.0.0"},
        "EEGModality": {
            "BVRFFiles": {"DataFile": {"Version": "1.0.0", "NumericDataType": dtype},
                          "MarkerFile": {"Version": "1.0.0"}},
            "DataSpecific": {"SamplingFrequencyInHertz": 1000},
            "Channels": [{"Name": "Fz", "Type": "EEG", "Unit": "µV", "ResolutionPerBit": 0.5},
                         {"Name": "Cz", "Type": "EEG", "Unit": "mV", "ResolutionPerBit": 2}],
        },
    }
    path.write_text(json.dumps(header), encoding="utf-8")
    (tmp_path / "recording.bvrm").write_text(
        "Sample\tType\tCode\tValue\tComment\n0\tStimulus\tS\t1\tfirst sample\n"
        "2\tResponse\tR\t1\tbutton\n5\tStimulus\tS\t2\tcondition two\n", encoding="utf-8",
    )
    counts = np.arange(20, dtype={"Int16": "<i2", "Int32": "<i4", "Single": "<f4", "Double": "<f8"}[dtype]).reshape(10, 2)
    counts.tofile(tmp_path / "recording.bvrd")
    return path, counts.T * np.array([0.5e-6, 2e-3])[:, None]


@pytest.mark.parametrize("writer", [_write_bvcdf, _write_bvrf])
@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_reader_preserves_calibration_and_exact_stimulus_samples(tmp_path, writer, preload):
    path, expected = writer(tmp_path)
    mmap = tmp_path / "scratch.dat"
    selected = str(mmap) if preload == "memmap" else preload
    with open_brain_products_recording(path, preload=selected) as raw:
        assert raw.ch_names == ["Fz", "Cz", "Status"]
        assert raw.info["sfreq"] == read_sampling_rate(path) == 1000
        assert raw.preload == (preload is not False)
        np.testing.assert_allclose(raw.get_data()[:2], expected, atol=1e-15)
        np.testing.assert_allclose(raw.get_data(start=2, stop=8)[:2], expected[:, 2:8])
        assert raw._fpvs_brain_products_events.tolist() == [[0, 0, 1], [5, 0, 2]]
        events = mne.find_events(raw, stim_channel="Status", initial_event=True, shortest_event=1, verbose=False)
        np.testing.assert_array_equal(events, raw._fpvs_brain_products_events)
        assert any(description.startswith("Response/") for description in raw.annotations.description)
        # Selection and copies must still stream the correct physical channels.
        np.testing.assert_allclose(raw.copy().pick(["Cz"]).get_data()[0], expected[1])
    if mmap.exists():
        mmap.unlink()  # Deterministic release matters on Windows.


@pytest.mark.parametrize("dtype", ["Int16", "Int32", "Single", "Double"])
def test_bvrf_numeric_formats(tmp_path, dtype):
    path, expected = _write_bvrf(tmp_path, dtype)
    with open_brain_products_recording(path, synthesize_status=False) as raw:
        np.testing.assert_allclose(raw.get_data(), expected)
        assert raw._fpvs_brain_products_marker_rows[0]["Comment"] == "first sample"


def test_bvrf_rational_calibration_is_applied_after_resolution(tmp_path):
    path, _ = _write_bvrf(tmp_path)
    header = json.loads(path.read_text())
    header["EEGModality"]["Channels"][0]["Coefficients"] = {"Num": [1, 2], "Denom": [1, 0.5]}
    path.write_text(json.dumps(header))
    with open_brain_products_recording(path) as raw:
        values = np.arange(0, 20, 2) * 0.5
        np.testing.assert_allclose(raw.get_data()[0], (1 + 2 * values) / (1 + 0.5 * values) * 1e-6)


def test_bvrf_truncated_frame_rejected(tmp_path):
    path, _ = _write_bvrf(tmp_path)
    with path.with_suffix(".bvrd").open("ab") as handle:
        handle.write(b"x")
    with pytest.raises(BrainProductsFormatError, match="incomplete sample"):
        read_brain_products_raw(path)


@pytest.mark.parametrize("mutation,match", [
    (lambda h: h["BVRF"].update(Version="2.0.0"), "Only BVRF"),
    (lambda h: h["EEGModality"]["Channels"][0].update(Unit="unknown"), "unsupported unit"),
    (lambda h: h["EEGModality"]["Channels"][0].update(ResolutionPerBit=float("nan")), "finite"),
    (lambda h: h.update(Participants=[{"Id": "P1"}, {"Id": "P2"}]), "Multi-participant"),
    (lambda h: h["EEGModality"]["Channels"][1].update(Name="fz"), "unique"),
])
def test_bvrf_ambiguous_metadata_fails_closed(tmp_path, mutation, match):
    path, _ = _write_bvrf(tmp_path)
    header = json.loads(path.read_text())
    mutation(header)
    path.write_text(json.dumps(header))
    with pytest.raises(BrainProductsFormatError, match=match):
        read_brain_products_raw(path)


@pytest.mark.parametrize("writer", [_write_bvcdf, _write_bvrf])
def test_configured_codes_and_missing_marker_files(tmp_path, writer):
    path, _ = writer(tmp_path)
    with open_brain_products_recording(path, event_codes=[2]) as raw:
        assert raw._fpvs_brain_products_events.tolist() == [[5, 0, 2]]
    with pytest.raises(BrainProductsFormatError, match="No configured"):
        read_brain_products_raw(path, event_codes=[99])
    source_files(path)[2].unlink()
    with pytest.raises(FileNotFoundError, match="missing"):
        read_brain_products_raw(path)


def test_sources_follow_vhdr_links_and_bvrf_optional_impedance(tmp_path):
    path, _ = _write_bvcdf(tmp_path)
    assert [p.name for p in source_files(path)] == ["recording.vhdr", "signal.eeg", "events.vmrk"]
    path, _ = _write_bvrf(tmp_path)
    path.with_suffix(".bvri").write_text("impedances retained for provenance")
    assert source_files(path)[-1].suffix == ".bvri"


def test_preload_cannot_overwrite_existing_or_source_file(tmp_path):
    path, _ = _write_bvcdf(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        read_brain_products_raw(path, preload=str(path))
    assert path.read_bytes() == before


def test_invalid_calibration_releases_failed_memmap(tmp_path):
    path, _ = _write_bvrf(tmp_path)
    header = json.loads(path.read_text())
    header["EEGModality"]["Channels"][0]["Coefficients"] = {"Num": [0, 1], "Denom": [1, -1]}
    path.write_text(json.dumps(header))
    target = tmp_path / "scratch.dat"
    with pytest.raises(BrainProductsFormatError, match="zero denominator"):
        read_brain_products_raw(path, preload=str(target))
    assert not target.exists()


def test_companion_data_disagreement_rejected(tmp_path):
    path, _ = _write_bvcdf(tmp_path)
    other = tmp_path / "other.eeg"
    other.write_bytes(b"unrelated source")
    marker = tmp_path / "events.vmrk"
    marker.write_text(marker.read_text(encoding="utf-8").replace("signal.eeg", "other.eeg"), encoding="utf-8")
    with pytest.raises(BrainProductsFormatError, match="different data files"):
        source_files(path)


@pytest.mark.parametrize("writer", [_write_bvcdf, _write_bvrf])
@pytest.mark.parametrize("kind", ["New Segment", "Bad Interval", "Time 0", "Data Error"])
def test_processing_rejects_declared_discontinuities(tmp_path, writer, kind):
    path, _ = writer(tmp_path)
    if path.suffix == ".vhdr":
        marker = tmp_path / "events.vmrk"
        with marker.open("a", encoding="utf-8") as handle:
            handle.write(f"Mk5={kind},,4,1,0\n")
    else:
        with path.with_suffix(".bvrm").open("a", encoding="utf-8") as handle:
            handle.write(f"3\t{kind}\t\t\tinterrupted\n")
    with pytest.raises(BrainProductsFormatError, match="continuous"):
        read_brain_products_raw(path)
    with open_brain_products_recording(path, synthesize_status=False) as raw:
        assert any(description.startswith(kind + "/") for description in raw.annotations.description)


def test_bvcdf_averaged_data_is_not_treated_as_continuous(tmp_path):
    path, _ = _write_bvcdf(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("[Binary Infos]", "Averaged=YES\n[Binary Infos]"), encoding="utf-8")
    with pytest.raises(BrainProductsFormatError, match="unaveraged"):
        read_brain_products_raw(path)


def _with_captrak_header(path):
    header = json.loads(path.read_text())
    eeg = header["EEGModality"]
    eeg["CoordinateSystems"] = {"EEGCoordinateSystem": "CapTrak", "EEGCoordinateUnit": "mm",
                                "FiducialsCoordinateSystem": "CapTrak", "FiducialsCoordinateUnit": "mm"}
    eeg["Fiducials"] = [{"Coordinates": {"Nasion": [1000, 1100, 1000], "LPA": [900, 1000, 1000],
                                        "RPA": [1100, 1000, 1000]}}]
    eeg["Electrodes"] = [{"Name": "Electrode1", "Coordinates": [1000, 1080, 1050]},
                         {"Name": "Electrode2", "Coordinates": [1000, 1000, 1100]}]
    for index, channel in enumerate(eeg["Channels"], 1):
        channel["Composition"] = {"Plus": {"Name": f"Electrode{index}", "Section": "Electrodes"},
                                  "Minus": {"Name": "REF", "Section": "References"}}
    path.write_text(json.dumps(header))
    return header


def test_bvrf_captrak_composition_uses_fiducials_and_mm_to_head_transform(tmp_path):
    path, _ = _write_bvrf(tmp_path)
    _with_captrak_header(path)
    with open_brain_products_recording(path) as raw:
        montage = raw.get_montage().get_positions()
        assert montage["coord_frame"] == "head"
        np.testing.assert_allclose(montage["ch_pos"]["Fz"], [0, .08, .05], atol=1e-12)
        np.testing.assert_allclose(montage["ch_pos"]["Cz"], [0, 0, .10], atol=1e-12)


@pytest.mark.parametrize("mutation", [
    lambda eeg: eeg.pop("Fiducials"),
    lambda eeg: eeg["CoordinateSystems"].update(EEGCoordinateSystem="MNI"),
    lambda eeg: eeg["Channels"][0].pop("Composition"),
])
def test_bvrf_unanchored_geometry_never_becomes_head_coordinates(tmp_path, mutation):
    path, _ = _write_bvrf(tmp_path)
    header = _with_captrak_header(path)
    mutation(header["EEGModality"])
    path.write_text(json.dumps(header))
    with open_brain_products_recording(path) as raw:
        assert raw.get_montage() is None
        assert raw._fpvs_brain_products_header["EEGModality"]["Electrodes"]


def test_bvrf_bipolar_derivations_are_not_averaged_as_scalp_potentials(tmp_path):
    path, _ = _write_bvrf(tmp_path)
    header = _with_captrak_header(path)
    header["EEGModality"]["Channels"][0]["Composition"]["Minus"] = {"Section": "Electrodes", "Name": "Electrode2"}
    path.write_text(json.dumps(header))
    with pytest.raises(BrainProductsFormatError, match="Bipolar"):
        read_brain_products_raw(path)


def test_bvcdf_nonvoltage_auxiliary_cannot_be_retyped_to_eeg(tmp_path):
    path, _ = _write_bvcdf(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("Ch2=Cz,,2,µV", "Ch2=AUX,,2,m/s"), encoding="utf-8")
    with open_brain_products_recording(path) as raw:
        assert raw.get_channel_types() == ["eeg", "misc", "stim"]
        with pytest.raises(BrainProductsFormatError, match="voltage calibration"):
            validate_electrical_channel_units(raw, {"AUX": "eeg"})
        validate_electrical_channel_units(raw, {"AUX": "misc"})


def test_bvrf_uppercase_companion_extensions_remain_portable(tmp_path):
    path, expected = _write_bvrf(tmp_path)
    for suffix in (".bvrd", ".bvrm"):
        path.with_suffix(suffix).rename(path.with_suffix(suffix.upper()))
    with open_brain_products_recording(path) as raw:
        np.testing.assert_allclose(raw.get_data()[:2], expected)


@pytest.mark.parametrize("onsets,labels,match", [
    ([0, 0], ["Stimulus/S1", "Stimulus/S2"], "same sample"),
    ([0, .001], ["Stimulus/S1", "Stimulus/S1"], "Adjacent identical"),
    ([0], ["Response/R1"], "No configured"),
])
def test_status_adapter_rejects_lossy_event_interpretation(onsets, labels, match):
    raw = mne.io.RawArray(np.zeros((1, 10)), mne.create_info(["Fz"], 1000, "eeg"), verbose=False)
    raw.set_annotations(mne.Annotations(onsets, np.zeros(len(onsets)), labels))
    with pytest.raises(BrainProductsFormatError, match=match):
        decode_brain_products_events(raw)
