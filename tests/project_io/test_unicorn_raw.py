from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_profiles import (
    UNICORN_FACTORY_MAPPING_SOURCE_URL,
    UNICORN_FACTORY_RECORDED_LABEL_MAP,
)
from Main_App.io.load_utils import open_unicorn_recording_raw
from Main_App.io import unicorn_raw
from tests.bdf_factory import write_bdf


EEG = tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP)
AUXILIARIES = ("CNT", "VALID", "DT")


def _settings(*, annotations=False):
    return {"acquisition_profile": {
        "id": "unicorn_hybrid_black", "version": "1.0", "montage_id": "unicorn8",
        "montage_version": "1.0",
        "event_decoder_id": "explicit_annotations" if annotations else "unicorn_sample",
        "event_decoder_version": "1.0", "reference_policy": "average_scalp",
        "source_to_canonical": dict(UNICORN_FACTORY_RECORDED_LABEL_MAP),
        "label_mapping_evidence": {
            "status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL,
        },
    }}


def _fixture(path, **kwargs):
    values = {
        name: [[-8388608, -1000 * (index + 1), -1, 0, 1, 1000 * (index + 1), 8388607]
               + [index] * 243]
        for index, name in enumerate(EEG)
    }
    values.update({
        "CNT": [list(range(250))], "VALID": [[1] * 250], "DT": [[4] * 250],
        "Status": [[0, 55, 55, 1, 255] + [0] * 245],
    })
    options = {
        "variant": "BDF", "record_onsets": ("0",),
        "eeg_names": (*EEG, *AUXILIARIES), "unit": "?V",
        "physical_ranges": {name: (-750000, 750000) for name in EEG},
        "signal_units": {name: "" for name in AUXILIARIES}, "signal_values": values,
    }
    options.update(kwargs)
    return write_bdf(path, **options)


def _scratch_directories(project_root):
    return list((project_root / ".fpvs_processing" / "unicorn_reader").glob("reader-*"))


@pytest.mark.parametrize("preload", [False, True, "memmap"])
@pytest.mark.parametrize("variant", ["BDF", "BDF+C"])
def test_reader_corrects_only_verified_dimensions_with_lazy_full_disk_parity(tmp_path, preload, variant):
    source = _fixture(tmp_path / "source.bdf", variant=variant)
    original_bytes = source.read_bytes()
    expected = np.array([
        [float(Fraction(value + 8388608) * 1500000 / 16777215 - 750000) * 1e-6
         for value in [-8388608, -1000 * (index + 1), -1, 0, 1,
                       1000 * (index + 1), 8388607] + [index] * 243]
        for index in range(8)
    ])
    with open_unicorn_recording_raw(
        source, _settings(), project_root=tmp_path, event_authority="status", preload=preload,
    ) as recording:
        raw = recording.raw
        assert raw.ch_names == [*EEG, *AUXILIARIES, "Status"]
        assert raw.get_channel_types() == ["eeg"] * 8 + ["misc"] * 3 + ["stim"]
        assert raw.info["sfreq"] == 250
        assert raw.n_times == 250
        assert raw.preload is (preload is not False)
        np.testing.assert_allclose(raw.get_data(picks=list(EEG)), expected, rtol=1e-8, atol=1e-16)
        np.testing.assert_allclose(raw.get_data(picks=["CNT"])[0], np.arange(250))
        np.testing.assert_allclose(raw.get_data(picks=["VALID"])[0], 1)
        np.testing.assert_allclose(raw.get_data(picks=["DT"])[0], 4)
        np.testing.assert_array_equal(raw.get_data(picks=["Status"])[0], [0, 55, 55, 1, 255] + [0] * 245)
        assert [(event.sample, event.code) for event in recording.inspection.events.events] == [
            (1, 55), (2, 55), (3, 1), (4, 255),
        ]
        assert recording.scientific_processing_allowed is False
        assert recording.inspection.scientific_processing_allowed is False
        assert {issue.code for issue in recording.inspection.issues} == {
            "unqualified_acquisition", "integration_pending",
        }
        assert recording.inspection.source.file_sha256 == hashlib.sha256(original_bytes).hexdigest()
        assert all(signal.physical_dimension == "?V" for signal in recording.inspection.source.header.signals[:8])
        staged_path = Path(raw.filenames[0])
        assert staged_path != source
        assert staged_path.name == "reader.bdf"
        assert staged_path.parent.name.startswith("reader-")
        assert staged_path.parent.parent == tmp_path / ".fpvs_processing" / "unicorn_reader"
        staged_bytes = bytearray(original_bytes)
        signal_count = int(original_bytes[252:256])
        for index in range(8):
            start = 256 + 96 * signal_count + 8 * index
            staged_bytes[start:start + 8] = b"uV      "
        assert staged_path.read_bytes() == bytes(staged_bytes)
        if preload == "memmap":
            assert isinstance(raw._data, np.memmap)
            assert Path(raw._data.filename) == staged_path.parent / "samples.dat"
        assert source.read_bytes() == original_bytes
        receipt = recording.reader_provenance
        serialized = json.dumps(receipt)
        assert str(tmp_path) not in serialized
        assert hashlib.sha256(original_bytes).hexdigest() in serialized
        receipt["test_mutation"] = True
        assert "test_mutation" not in recording.reader_provenance
    assert not _scratch_directories(tmp_path)
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_corrected_and_proper_microvolt_headers_produce_identical_data(tmp_path, preload):
    broken = _fixture(tmp_path / "broken.bdf")
    proper = _fixture(tmp_path / "proper.bdf", unit="uV")
    snapshots = []
    for path in (broken, proper, broken):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status", preload=preload,
        ) as recording:
            snapshots.append(recording.raw.get_data())
    np.testing.assert_array_equal(snapshots[0], snapshots[1])
    np.testing.assert_array_equal(snapshots[0], snapshots[2])
    assert not _scratch_directories(tmp_path)


@pytest.mark.parametrize("unit,factor", [("uV", 1e-6), ("mV", 1e-3), ("V", 1)])
@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_recognized_units_receive_mne_conversion_exactly_once(tmp_path, unit, factor, preload):
    path = _fixture(
        tmp_path / "source.bdf", unit=unit, physical_ranges={},
        signal_values={name: [[10] * 250] for name in EEG},
    )
    with open_unicorn_recording_raw(
        path, _settings(), project_root=tmp_path, event_authority="status", preload=preload,
    ) as recording:
        np.testing.assert_allclose(recording.raw.get_data(picks=list(EEG)), 10 * factor)
        assert not any(channel.recorder_label_correction
                       for channel in recording.inspection.eeg_unit_policy.channels)


@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_annotations_and_fractional_time_origin_remain_original_evidence(tmp_path, preload):
    path = _fixture(
        tmp_path / "source.bdf", variant="BDF+C", record_onsets=("0.125",), status=False,
        annotations=([b"+0.129\x1455\x14\x00", b"+0.133\x1455\x14\x00",
                      b"+0.525\x150.1\x14Operator note\x14\x00"],),
    )
    original = path.read_bytes()
    with open_unicorn_recording_raw(
        path, _settings(annotations=True), project_root=tmp_path,
        event_authority="annotations", numeric_annotations=True, preload=preload,
    ) as recording:
        assert "Status" not in recording.raw.ch_names
        assert recording.raw.get_channel_types() == ["eeg"] * 8 + ["misc"] * 3
        assert [(event.sample, event.code) for event in recording.inspection.events.events] == [(1, 55), (2, 55)]
        assert str(recording.inspection.source.first_sample_onset) == "0.125"
        assert list(recording.raw.annotations.description) == ["55", "55", "Operator note"]
        np.testing.assert_allclose(recording.raw.annotations.duration, [0, 0, 0.1])
        assert recording.scientific_processing_allowed is False
    assert path.read_bytes() == original
    assert not _scratch_directories(tmp_path)


@pytest.mark.parametrize("explicit", [False, True])
def test_biosemi_rejected_before_source_or_project_io(tmp_path, explicit):
    settings = {"acquisition_profile": {
        "id": "biosemi_active_two_64", "version": "1.0", "montage_id": "biosemi64",
        "montage_version": "1.0", "event_decoder_id": "biosemi_edge",
        "event_decoder_version": "1.0", "reference_policy": "biosemi_exg_pair_then_average",
    }} if explicit else {}
    with pytest.raises(ValueError, match="(?i)Unicorn"):
        with open_unicorn_recording_raw(
            tmp_path / "missing.bdf", settings, project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("BioSemi must never enter the Unicorn reader.")
    assert not (tmp_path / ".fpvs_processing").exists()


@pytest.mark.parametrize("changes", [
    {"unit": "counts"},
    {"unit": "?v"},
    {"physical_ranges": {name: (-700000, 700000) for name in EEG}},
    {"signal_units": {EEG[0]: "uV", **dict.fromkeys(AUXILIARIES, "")}},
    {"samples_per_record": 200, "signal_values": {}},
    {"unit": "uV", "eeg_names": (*EEG, *AUXILIARIES, "Unknown")},
    {"variant": "BDF+D"},
    {"variant": "BDF+C", "record_onsets": ("0", "2"), "signal_values": {}},
])
def test_unqualified_source_fails_closed_without_retained_scratch(tmp_path, changes):
    path = _fixture(tmp_path / "source.bdf", **changes)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("An incompatible source cannot yield a Raw.")
    assert path.read_bytes() == original
    assert not _scratch_directories(tmp_path)


def test_mixed_rate_telemetry_is_rejected_before_mne_can_resample(tmp_path, monkeypatch):
    path = _fixture(tmp_path / "source.bdf")
    payload = bytearray(path.read_bytes())
    count = int(payload[252:256])
    header_bytes = int(payload[184:192])
    counter_index = len(EEG)
    samples_field = 256 + 216 * count + 8 * counter_index
    payload[samples_field:samples_field + 8] = b"125     "
    counter_start = header_bytes + counter_index * 250 * 3
    del payload[counter_start + 125 * 3:counter_start + 250 * 3]
    path.write_bytes(payload)

    def no_mne(*args, **kwargs):
        pytest.fail("Mixed-rate source reached MNE and could be resampled.")

    monkeypatch.setattr(mne.io, "read_raw_bdf", no_mne)
    with pytest.raises(ValueError):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("Mixed-rate telemetry must not be silently resampled.")
    assert not _scratch_directories(tmp_path)


@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_owned_scratch_is_removed_after_consumer_exception(tmp_path, preload):
    path = _fixture(tmp_path / "source.bdf")
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="consumer failure"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status", preload=preload,
        ) as recording:
            assert _scratch_directories(tmp_path)
            recording.raw.get_data(start=1, stop=4)
            raise RuntimeError("consumer failure")
    assert not _scratch_directories(tmp_path)
    assert path.read_bytes() == original


def test_owned_scratch_is_removed_when_mne_fails(tmp_path, monkeypatch):
    path = _fixture(tmp_path / "source.bdf")
    original = path.read_bytes()

    def fail_open(*args, **kwargs):
        assert _scratch_directories(tmp_path)
        raise RuntimeError("reader failure")

    monkeypatch.setattr(mne.io, "read_raw_bdf", fail_open)
    with pytest.raises(RuntimeError, match="reader failure"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status", preload="memmap",
        ):
            pytest.fail("An unsuccessful reader cannot yield a Raw.")
    assert not _scratch_directories(tmp_path)
    assert path.read_bytes() == original


def test_source_change_after_inspection_is_rejected_even_with_same_size_and_mtime(tmp_path, monkeypatch):
    path = _fixture(tmp_path / "source.bdf")
    inspect = unicorn_raw.inspect_eeg_recording

    def inspect_then_replace_samples(*args, **kwargs):
        result = inspect(*args, **kwargs)
        stat = path.stat()
        payload = bytearray(path.read_bytes())
        payload[result.source.header.header_bytes] ^= 1
        path.write_bytes(payload)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return result

    def no_mne(*args, **kwargs):
        pytest.fail("A source different from the inspected content reached MNE.")

    monkeypatch.setattr(unicorn_raw, "inspect_eeg_recording", inspect_then_replace_samples)
    monkeypatch.setattr(mne.io, "read_raw_bdf", no_mne)
    with pytest.raises(ValueError, match="changed after inspection"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("Changed source cannot be substituted for inspected samples.")
    assert not _scratch_directories(tmp_path)


def test_close_failure_still_releases_memmap_and_owned_files(tmp_path, monkeypatch):
    path = _fixture(tmp_path / "source.bdf")
    original = path.read_bytes()

    def fail_close():
        raise RuntimeError("close failure")

    with pytest.raises(RuntimeError, match="close failure"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status", preload="memmap",
        ) as recording:
            mmap = recording.raw._data._mmap
            monkeypatch.setattr(recording.raw, "close", fail_close)
    assert mmap.closed
    assert not _scratch_directories(tmp_path)
    assert path.read_bytes() == original


def test_partial_copy_failure_removes_only_owned_files(tmp_path, monkeypatch):
    path = _fixture(tmp_path / "source.bdf")
    original = path.read_bytes()
    unrelated = tmp_path / "unrelated.bdf"
    unrelated.write_bytes(b"unrelated source")

    def fail_copy(source, destination, inspection):
        destination.write_bytes(b"partial copy")
        raise OSError("copy failure")

    monkeypatch.setattr(unicorn_raw, "_copy_reader_source", fail_copy)
    with pytest.raises(OSError, match="copy failure"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("A partial reader copy cannot be used.")
    assert not _scratch_directories(tmp_path)
    assert path.read_bytes() == original
    assert unrelated.read_bytes() == b"unrelated source"


@pytest.mark.parametrize("preload", [False, True, "memmap"])
def test_permuted_source_order_preserves_signal_identity(tmp_path, preload):
    ordered = ("CNT", EEG[7], EEG[1], "DT", EEG[4], EEG[0], EEG[6], "VALID", EEG[3], EEG[2], EEG[5])
    path = _fixture(tmp_path / "source.bdf", eeg_names=ordered)
    with open_unicorn_recording_raw(
        path, _settings(), project_root=tmp_path, event_authority="status", preload=preload,
    ) as recording:
        assert recording.raw.ch_names == [*ordered, "Status"]
        types = dict(zip(recording.raw.ch_names, recording.raw.get_channel_types()))
        assert all(types[name] == "eeg" for name in EEG)
        assert all(types[name] == "misc" for name in AUXILIARIES)
        assert types["Status"] == "stim"
        for index, channel in enumerate(EEG):
            expected = float(Fraction(-1000 * (index + 1) + 8388608) * 1500000 / 16777215 - 750000) * 1e-6
            assert recording.raw.get_data(picks=[channel], start=1, stop=2)[0, 0] == pytest.approx(expected)


@pytest.mark.parametrize("limits", [("-1e308", "1e308"), ("0", "1e-9999"), ("0", "1e9999")])
def test_unrepresentable_calibration_fails_before_mne(tmp_path, monkeypatch, limits):
    path = _fixture(tmp_path / "source.bdf", unit="V", physical_ranges=dict.fromkeys(EEG, limits))

    def no_mne(*args, **kwargs):
        pytest.fail("Unrepresentable EEG calibration reached MNE.")

    monkeypatch.setattr(mne.io, "read_raw_bdf", no_mne)
    with pytest.raises(ValueError):
        with open_unicorn_recording_raw(
            path, _settings(), project_root=tmp_path, event_authority="status",
        ):
            pytest.fail("Unrepresentable EEG calibration cannot yield a Raw.")
    assert not _scratch_directories(tmp_path)


def test_relative_project_root_is_rejected(tmp_path):
    path = _fixture(tmp_path / "source.bdf")
    with pytest.raises(ValueError, match="absolute"):
        with open_unicorn_recording_raw(
            path, _settings(), project_root="relative-project", event_authority="status",
        ):
            pytest.fail("Reader scratch must belong to an absolute project root.")
    assert not _scratch_directories(tmp_path)


@pytest.mark.parametrize("preload", [None, 0, 1, "disk", "False", Path("samples.dat")])
def test_invalid_preload_modes_are_rejected_before_source_io(tmp_path, preload):
    with pytest.raises(ValueError, match="preload"):
        with open_unicorn_recording_raw(
            tmp_path / "missing.bdf", _settings(), project_root=tmp_path,
            event_authority="status", preload=preload,
        ):
            pytest.fail("Only explicit boolean or memmap preload modes are supported.")
    assert not (tmp_path / ".fpvs_processing").exists()
