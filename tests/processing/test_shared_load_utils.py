from __future__ import annotations

import logging
from fractions import Fraction
from io import BytesIO
from types import SimpleNamespace

import mne
import numpy as np
import pytest

import Main_App.Shared.load_utils as shared_load_utils
import Main_App.io.load_utils as load_utils
import Main_App.io.recording_inspection as recording_inspection
import Main_App.io.unicorn_raw as unicorn_raw
import Main_App.io.unicorn_units as unicorn_units
from Main_App.io.eeg_geometry import (
    BIOSEMI64_1020_AB_CHANNEL_MAP,
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    read_raw_biosemi64_geometry,
)
from Main_App.projects.preprocessing_settings import (
    ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
)


def _raw(channel_names=None):
    names = list(channel_names or [*BIOSEMI64_CHANNELS, "EXG1", "EXG2", "EXG3", "Status"])
    channel_types = ["stim" if name == "Status" else "eeg" for name in names]
    raw = mne.io.RawArray(
        np.zeros((len(names), 8), dtype=float),
        mne.create_info(names, 512.0, channel_types),
        verbose=False,
    )
    raw.close_calls = 0
    raw.load_data_calls = 0
    original_close = raw.close
    original_load_data = raw.load_data

    def _close():
        raw.close_calls += 1
        return original_close()

    def _load_data(*args, **kwargs):
        raw.load_data_calls += 1
        return original_load_data(*args, **kwargs)

    raw.close = _close
    raw.load_data = _load_data
    return raw


def _app(logs: list[str]):
    return SimpleNamespace(
        currentProject=SimpleNamespace(
            preprocessing={
                "ref_chan1": "EXG1",
                "ref_chan2": "EXG2",
                "stim_channel": "Status",
            }
        ),
        settings=SimpleNamespace(get=lambda section, key, default=None: default),
        log=logs.append,
    )


@pytest.fixture(params=("legacy_default", "explicit_biosemi"))
def biosemi_without_unicorn_units(monkeypatch, request):
    def _unexpected_unicorn_units(*_args, **_kwargs):
        pytest.fail("BioSemi production loading must never invoke Unicorn unit correction")

    for owner in (unicorn_units, unicorn_raw, recording_inspection, shared_load_utils, load_utils):
        for name in ("resolve_unicorn_unit_policy", "unicorn_eeg_samples_in_volts", "open_unicorn_recording_raw"):
            if hasattr(owner, name):
                monkeypatch.setattr(owner, name, _unexpected_unicorn_units)
    app = _app([])
    if request.param == "explicit_biosemi":
        app.currentProject.preprocessing.update({
            "electrode_montage": "biosemi64",
            "electrode_mapping_profile": "anatomical_labels",
            "acquisition_profile": {
                "id": "biosemi_active_two_64", "version": "1.0",
                "montage_id": "biosemi64", "montage_version": "1.0",
                "event_decoder_id": "biosemi_edge", "event_decoder_version": "1.0",
                "reference_policy": "biosemi_exg_pair_then_average",
            },
        })
    return app


def _write_bdf_header(path, *, header_bytes: int = 512, data_records: int = 0, channels: int = 1) -> None:
    header = bytearray(b" " * 256)

    def _put(start: int, stop: int, value: object) -> None:
        header[start:stop] = str(value).ljust(stop - start).encode("ascii")

    _put(184, 192, header_bytes)
    _put(236, 244, data_records)
    _put(244, 252, 1)
    _put(252, 256, channels)
    path.write_bytes(bytes(header) + (b" " * max(0, header_bytes - 256)))


def _write_sampling_bdf(
    path, *, labels=("Fp1", "EXG1", "Status"), samples=(512, 512, 512), duration="1"
):
    def _field(value, width):
        encoded = str(value).encode("ascii")
        assert len(encoded) <= width
        return encoded.ljust(width, b" ")

    channels = len(labels)
    fixed = bytearray(b" " * 256)
    fixed[:8] = b"\xffBIOSEMI"
    fixed[184:192] = _field((channels + 1) * 256, 8)
    fixed[192:236] = _field("24BIT", 44)
    fixed[236:244] = _field(1, 8)
    fixed[244:252] = _field(duration, 8)
    fixed[252:256] = _field(channels, 4)
    fields = (
        (labels, 16), (("",) * channels, 80), (("uV",) * channels, 8),
        ((-262144,) * channels, 8), ((262143,) * channels, 8),
        ((-8388608,) * channels, 8), ((8388607,) * channels, 8),
        (("",) * channels, 80), (samples, 8), (("",) * channels, 32),
    )
    signal_header = b"".join(_field(value, width) for values, width in fields for value in values)
    path.write_bytes(bytes(fixed) + signal_header + bytes(sum(samples) * 3))
    return (channels + 1) * 256


@pytest.mark.parametrize(
    ("duration", "samples", "expected"),
    [("1", 512, Fraction(512)), ("0.5", 1024, Fraction(2048)), ("0.3", 10, Fraction(100, 3))],
)
def test_sampling_rate_header_is_exact_and_reads_no_signal_samples(
    monkeypatch, tmp_path, duration, samples, expected
):
    path = tmp_path / "sampling.bdf"
    header_bytes = _write_sampling_bdf(path, samples=(samples,) * 3, duration=duration)
    original_bytes = path.read_bytes()

    class HeaderOnlyStream(BytesIO):
        def read(self, size=-1):
            if size < 0 or self.tell() + size > header_bytes:
                pytest.fail("Sampling-rate inspection attempted to read EEG samples")
            return super().read(size)

    monkeypatch.setattr(shared_load_utils.Path, "open", lambda *_a, **_k: HeaderOnlyStream(original_bytes))
    monkeypatch.setattr(
        shared_load_utils.mne.io, "read_raw_bdf", lambda *_a, **_k: pytest.fail("MNE was opened")
    )

    assert load_utils.read_bdf_sampling_rate_hz(path) == expected
    assert load_utils.read_bdf_sampling_rate_hz is shared_load_utils.read_bdf_sampling_rate_hz


def test_sampling_rate_header_ignores_annotation_rates_and_matches_custom_stim(tmp_path):
    path = tmp_path / "annotations.bdf"
    _write_sampling_bdf(
        path, labels=("Fp1", "Triggers", "BDF Annotations", "EDF Annotations"),
        samples=(512, 512, 80, 96),
    )

    assert load_utils.read_bdf_sampling_rate_hz(path, stim_channel="triggers") == Fraction(512)


@pytest.mark.parametrize("samples", [(256, 512, 512), (512, 512, 256)])
def test_sampling_rate_header_rejects_mixed_data_or_stim_rates(tmp_path, samples):
    path = tmp_path / "mixed.bdf"
    _write_sampling_bdf(path, samples=samples)

    with pytest.raises(ValueError, match="must share one sampling rate"):
        load_utils.read_bdf_sampling_rate_hz(path)


@pytest.mark.parametrize("labels", [("Fp1", "EXG1", "Triggers"), ("Fp1", "Status", "status")])
def test_sampling_rate_header_requires_one_configured_stim_channel(tmp_path, labels):
    path = tmp_path / "stim.bdf"
    _write_sampling_bdf(path, labels=labels)

    with pytest.raises(ValueError, match="exactly one 'Status'"):
        load_utils.read_bdf_sampling_rate_hz(path)


@pytest.mark.parametrize(
    ("start", "stop", "replacement", "message"),
    [
        (0, 8, b"0       ", "identification code"),
        (184, 192, b"512     ", "header length"),
        (252, 256, b"0   ", "channel count"),
        (236, 244, b"-2      ", "data record count"),
        (244, 252, b"0       ", "positive decimal"),
        (244, 252, b"NaN     ", "positive decimal"),
        (244, 252, b"1/2     ", "positive decimal"),
        (244, 252, b"1_0     ", "positive decimal"),
        (244, 252, b"\xff       ", "ASCII text"),
        (256, 272, b" " * 16, "channel labels"),
        (904, 912, b"0       ", "positive sample counts"),
        (904, 912, b"invalid ", "samples per data record"),
        (904, 912, b"5_12    ", "samples per data record"),
    ],
)
def test_sampling_rate_header_rejects_malformed_fields(tmp_path, start, stop, replacement, message):
    path = tmp_path / "malformed.bdf"
    _write_sampling_bdf(path)
    payload = bytearray(path.read_bytes())
    payload[start:stop] = replacement
    path.write_bytes(payload)

    with pytest.raises(ValueError, match=message):
        load_utils.read_bdf_sampling_rate_hz(path)


@pytest.mark.parametrize("retained_bytes", [255, 1023])
def test_sampling_rate_header_rejects_truncated_headers(tmp_path, retained_bytes):
    path = tmp_path / "truncated.bdf"
    _write_sampling_bdf(path)
    path.write_bytes(path.read_bytes()[:retained_bytes])

    with pytest.raises(ValueError, match="header is truncated"):
        load_utils.read_bdf_sampling_rate_hz(path)


def test_sampling_rate_header_preserves_not_started_detection(tmp_path):
    path = tmp_path / "not-started.bdf"
    header_bytes = _write_sampling_bdf(path)
    payload = bytearray(path.read_bytes()[:header_bytes])
    payload[236:244] = b"0       "
    path.write_bytes(payload)

    assert load_utils.is_bdf_recording_not_started(path)
    assert load_utils.read_bdf_sampling_rate_hz(path) == Fraction(512)


def test_sampling_rate_header_propagates_file_access_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_utils.read_bdf_sampling_rate_hz(tmp_path / "missing.bdf")


def test_shared_bdf_preflight_identifies_header_only_recording_not_started(tmp_path):
    path = tmp_path / "p16.bdf"
    _write_bdf_header(path, header_bytes=512, data_records=0, channels=1)

    info = load_utils.inspect_bdf_header(path)

    assert info is not None
    assert info.file_size == 512
    assert info.header_bytes == 512
    assert info.data_records == 0
    assert info.channel_count == 1
    assert info.recording_not_started is True
    assert load_utils.is_bdf_recording_not_started(path) is True


def test_shared_load_eeg_file_excludes_header_only_bdf_without_mne(monkeypatch, tmp_path):
    path = tmp_path / "p16.bdf"
    _write_bdf_header(path, header_bytes=512, data_records=0, channels=1)

    def _unexpected_read_raw_bdf(*_args, **_kwargs):
        raise AssertionError("header-only BDF should be excluded before MNE reads it")

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _unexpected_read_raw_bdf)

    logs: list[str] = []
    raw = load_utils.load_eeg_file(_app(logs), str(path))

    assert raw is None
    assert any("did not click Record in BioSemi" in message for message in logs)
    assert any("[LOADER EXCLUDED]" in message for message in logs)


def test_shared_load_eeg_file_preserves_bdf_channel_and_montage_contract(monkeypatch, tmp_path):
    header_raw = _raw()
    loaded_raw = _raw()
    calls = []

    def _fake_read_raw_bdf(filepath, **kwargs):
        calls.append((filepath, dict(kwargs)))
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _fake_read_raw_bdf)

    logs: list[str] = []
    path = tmp_path / "sample.bdf"

    raw = load_utils.load_eeg_file(_app(logs), str(path))

    assert raw is loaded_raw
    assert calls[0][0] == str(path)
    assert calls[0][1]["preload"] is False
    assert calls[1][1]["preload"] == str(tmp_path / "sample_raw.dat")
    assert calls[1][1]["stim_channel"] == "Status"
    assert loaded_raw.load_data_calls == 1
    types = dict(zip(loaded_raw.ch_names, loaded_raw.get_channel_types()))
    assert types["EXG1"] == types["EXG2"] == "eeg"
    assert types["EXG3"] == "misc"
    assert types["Status"] == "stim"
    identity = read_raw_biosemi64_geometry(loaded_raw)
    assert identity is not None
    assert identity["coordinate_fingerprint"] == BIOSEMI64_COORDINATE_FINGERPRINT
    assert identity["retained_scalp_channel_count"] == 64
    assert "BDF loaded successfully." in logs


def test_public_full_biosemi_loader_preserves_nonzero_volts_without_unicorn_correction(
    monkeypatch, tmp_path, biosemi_without_unicorn_units,
):
    header_raw, loaded_raw = _raw(), _raw()
    expected = np.arange(1, loaded_raw._data.size + 1, dtype=float).reshape(loaded_raw._data.shape) * 1e-6
    loaded_raw._data[:] = expected
    calls = []

    def _read(_filepath, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)
    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)

    raw = load_utils.load_eeg_file(biosemi_without_unicorn_units, str(tmp_path / "biosemi.bdf"))

    assert raw is loaded_raw
    np.testing.assert_array_equal(raw.get_data(), expected)
    assert len(calls) == 2
    assert calls[0]["preload"] is False
    assert calls[1]["preload"] == str(tmp_path / "biosemi_raw.dat")
    assert all("units" not in call for call in calls)
    assert loaded_raw.load_data_calls == 1
    assert load_utils.load_eeg_file is shared_load_utils.load_eeg_file


def test_public_lazy_biosemi_loader_preserves_nonzero_volts_without_unicorn_correction(
    monkeypatch, tmp_path, biosemi_without_unicorn_units,
):
    header_raw, lazy_raw = _raw(), _raw()
    expected = -np.arange(1, lazy_raw._data.size + 1, dtype=float).reshape(lazy_raw._data.shape) * 1e-6
    lazy_raw._data[:] = expected
    calls = []

    def _read(_filepath, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else lazy_raw

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)
    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: pytest.fail("Lazy load created a memmap"))

    with load_utils.open_preflight_eeg_file(
        biosemi_without_unicorn_units, str(tmp_path / "biosemi.bdf"),
    ) as raw:
        assert raw is lazy_raw
        np.testing.assert_array_equal(raw.get_data(), expected)
        assert lazy_raw.load_data_calls == 0
        assert lazy_raw.close_calls == 0

    assert len(calls) == 2
    assert all(call["preload"] is False and "units" not in call for call in calls)
    assert header_raw.close_calls == lazy_raw.close_calls == 1
    assert load_utils.open_preflight_eeg_file is shared_load_utils.open_preflight_eeg_file


def test_shared_load_eeg_file_ram_preload_uses_no_disk_map(monkeypatch, tmp_path):
    header_raw, loaded_raw = _raw(), _raw()
    calls = []

    def reader(_filepath, **kwargs):
        calls.append(kwargs)
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", reader)
    monkeypatch.setattr(
        shared_load_utils,
        "_memmap_dir_for_pid",
        lambda: pytest.fail("RAM mode created a disk preload directory"),
    )

    raw = load_utils.load_eeg_file(
        _app([]), str(tmp_path / "sample.bdf"), preload_in_memory=True
    )

    assert raw is loaded_raw
    assert calls[0]["preload"] is False
    assert calls[1]["preload"] is True
    assert loaded_raw.load_data_calls == 1
    assert read_raw_biosemi64_geometry(raw) is not None
    assert list(tmp_path.iterdir()) == []


def test_ram_preload_rejects_run_owned_disk_path(tmp_path):
    with pytest.raises(ValueError, match="cannot use a disk preload path"):
        load_utils.load_eeg_file(
            _app([]),
            str(tmp_path / "sample.bdf"),
            preload_path=tmp_path / "raw.dat",
            preload_in_memory=True,
        )


def test_run_owned_preload_preserves_geometry_and_uses_its_unique_path(monkeypatch, tmp_path):
    header_raw, loaded_raw = _raw(), _raw()
    calls = []

    def reader(_filepath, **kwargs):
        calls.append(kwargs)
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", reader)
    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: pytest.fail("Used shared PID path"))
    destination = tmp_path / "unique-source.dat"
    raw = load_utils.load_eeg_file(_app([]), str(tmp_path / "sample.bdf"), preload_path=destination)

    assert raw is loaded_raw
    assert calls[0]["preload"] is False
    assert calls[1]["preload"] == str(destination)
    assert read_raw_biosemi64_geometry(raw)["coordinate_fingerprint"] == BIOSEMI64_COORDINATE_FINGERPRINT
    assert destination.is_file()


@pytest.mark.parametrize("destination_kind", ["existing", "source", "relative"])
def test_run_owned_preload_never_overwrites_existing_or_source_files(monkeypatch, tmp_path, destination_kind):
    source = tmp_path / "sample.bdf"
    source.write_bytes(b"original EEG")
    destination = tmp_path / "owned.dat"
    destination.write_bytes(b"another active worker")
    selected = {"existing": destination, "source": source, "relative": "relative.dat"}[destination_kind]
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", lambda *_a, **_k: pytest.fail("Unsafe destination opened"))

    assert load_utils.load_eeg_file(_app([]), str(source), preload_path=selected) is None
    assert source.read_bytes() == b"original EEG"
    assert destination.read_bytes() == b"another active worker"


def test_shared_load_eeg_file_can_limit_bdf_to_first_channels_refs_and_stim(
    monkeypatch,
    tmp_path,
    caplog,
):
    header_raw = _raw()
    loaded_raw = _raw(["Fp1", "EXG1", "EXG2", "Status"])
    calls = []

    def _fake_read_raw_bdf(filepath, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _fake_read_raw_bdf)

    logs: list[str] = []
    path = tmp_path / "sample.bdf"

    with caplog.at_level(logging.DEBUG, logger=shared_load_utils.logger.name):
        raw = load_utils.load_eeg_file(
            _app(logs),
            str(path),
            ref_pair=("EXG1", "EXG2"),
            first_n_channels=1,
        )

    assert raw is loaded_raw
    assert calls[0]["preload"] is False
    assert "include" not in calls[0]
    assert calls[1]["include"] == ["Fp1", "EXG1", "EXG2", "Status"]
    assert calls[1]["preload"] == str(tmp_path / "sample_raw.dat")
    assert any("[LOADER CHANNEL SUBSET]" in message for message in logs)
    assert "stage=header_geometry_validation_start" in caplog.text
    assert "stage=read_raw_bdf_start" in caplog.text
    assert "stage=load_data_done" in caplog.text
    assert "stage=montage_apply_done" in caplog.text


def test_open_preflight_eeg_file_is_lazy_subsetted_and_context_managed(
    monkeypatch,
    tmp_path,
):
    header_raw = _raw()
    lazy_raw = _raw(["Fp1", "EXG1", "EXG2", "Status"])
    calls = []

    def _fake_read_raw_bdf(filepath, **kwargs):
        calls.append((filepath, dict(kwargs)))
        return header_raw if len(calls) == 1 else lazy_raw

    monkeypatch.setattr(
        shared_load_utils,
        "_resolve_stim",
        lambda _app: (_ for _ in ()).throw(
            AssertionError("explicit preflight stim channel must win")
        ),
    )
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _fake_read_raw_bdf)
    monkeypatch.setattr(
        shared_load_utils,
        "_memmap_dir_for_pid",
        lambda: (_ for _ in ()).throw(AssertionError("lazy loader must not create a memmap")),
    )

    logs: list[str] = []
    path = tmp_path / "sample.bdf"

    with load_utils.open_preflight_eeg_file(
        _app(logs),
        str(path),
        ref_pair=("EXG1", "EXG2"),
        first_n_channels=1,
        stim_channel="Status",
    ) as raw:
        assert raw is lazy_raw
        assert lazy_raw.load_data_calls == 0
        assert lazy_raw.close_calls == 0

    assert calls[0][0] == str(path)
    assert calls[0][1]["preload"] is False
    assert "include" not in calls[0][1]
    assert calls[1][1]["preload"] is False
    assert calls[1][1]["include"] == ["Fp1", "EXG1", "EXG2", "Status"]
    assert header_raw.close_calls == 1
    assert lazy_raw.close_calls == 1
    assert read_raw_biosemi64_geometry(lazy_raw)["retained_scalp_channels"] == ["Fp1"]
    assert any("[PREFLIGHT LAZY LOADER READY]" in message for message in logs)
    assert any("[PREFLIGHT LAZY LOADER CLOSED]" in message for message in logs)
    assert shared_load_utils.open_preflight_eeg_file is load_utils.open_preflight_eeg_file


def test_open_preflight_eeg_file_closes_when_caller_raises(monkeypatch, tmp_path):
    header_raw = _raw()
    lazy_raw = _raw()
    calls = []

    def _read(*_args, **_kwargs):
        calls.append(dict(_kwargs))
        return header_raw if len(calls) == 1 else lazy_raw

    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)

    with pytest.raises(RuntimeError, match="caller failed"):
        with load_utils.open_preflight_eeg_file(
            _app([]),
            str(tmp_path / "sample.bdf"),
        ) as raw:
            assert raw is lazy_raw
            raise RuntimeError("caller failed")

    assert lazy_raw.load_data_calls == 0
    assert lazy_raw.close_calls == 1


def test_shared_load_eeg_file_unsupported_extension_warns_and_returns_none(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(
        shared_load_utils.user_messages,
        "show_warning",
        lambda title, message: warnings.append((title, message)),
    )

    logs: list[str] = []

    raw = load_utils.load_eeg_file(_app(logs), str(tmp_path / "sample.set"))

    assert raw is None
    assert warnings == [("Unsupported File", "Format '.set' not supported. Only '.bdf' is supported.")]


def test_shared_loader_compatibility_alias_returns_biosemi64():
    assert tuple(load_utils._cached_1010().ch_names) == BIOSEMI64_CHANNELS
    assert load_utils._cached_1020 is load_utils._cached_1010


def test_shared_loader_applies_explicit_ab_1020_mapping_without_reordering_data(
    monkeypatch,
    tmp_path,
):
    source_scalp = list(reversed(tuple(BIOSEMI64_1020_AB_CHANNEL_MAP)))
    source_names = [*source_scalp, "EXG1", "EXG2", "Status"]
    header_raw = _raw(source_names)
    loaded_raw = _raw(source_names)
    loaded_raw._data[:, :] = np.arange(len(source_names), dtype=float)[:, np.newaxis]
    calls = []

    def _read(*_args, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)

    raw = load_utils.load_eeg_file(
        _app([]),
        str(tmp_path / "ab.bdf"),
        electrode_mapping_profile=ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
        electrode_montage="biosemi64",
    )

    assert raw is loaded_raw
    assert raw.ch_names[:3] == ["O2", "PO4", "PO8"]
    assert raw.ch_names[63] == "Fp1"
    assert np.array_equal(raw._data[:64, 0], np.arange(64, dtype=float))
    identity = read_raw_biosemi64_geometry(raw)
    assert identity["electrode_mapping_profile"] == "biosemi64_1020_ab_v1"


def test_shared_loader_rejects_ab_header_without_explicit_profile(monkeypatch, tmp_path):
    header_raw = _raw([*BIOSEMI64_1020_AB_CHANNEL_MAP, "EXG1", "EXG2", "Status"])
    calls = []
    errors = []

    def _read(*_args, **kwargs):
        calls.append(dict(kwargs))
        return header_raw

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)
    monkeypatch.setattr(
        shared_load_utils.user_messages,
        "show_error",
        lambda title, message: errors.append((title, message)),
    )

    raw = load_utils.load_eeg_file(_app([]), str(tmp_path / "ab.bdf"))

    assert raw is None
    assert len(calls) == 1
    assert errors and "Select the tested" in errors[0][1]


def test_channel_limit_never_hides_incomplete_full_acquisition(monkeypatch, tmp_path):
    header_raw = _raw([*BIOSEMI64_CHANNELS[:-1], "EXG1", "EXG2", "Status"])
    calls = []

    def _read(*_args, **kwargs):
        calls.append(dict(kwargs))
        return header_raw

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)
    monkeypatch.setattr(shared_load_utils.user_messages, "show_error", lambda *_args: None)

    raw = load_utils.load_eeg_file(
        _app([]),
        str(tmp_path / "incomplete.bdf"),
        first_n_channels=1,
    )

    assert raw is None
    assert len(calls) == 1
    assert calls[0]["preload"] is False


def test_shared_loader_rejects_unsupported_project_montage_before_read(monkeypatch, tmp_path):
    errors = []
    monkeypatch.setattr(
        shared_load_utils.mne.io,
        "read_raw_bdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported montage must fail before reading the BDF")
        ),
    )
    monkeypatch.setattr(
        shared_load_utils.user_messages,
        "show_error",
        lambda title, message: errors.append((title, message)),
    )

    raw = load_utils.load_eeg_file(
        _app([]),
        str(tmp_path / "sample.bdf"),
        electrode_montage="standard_1005",
    )

    assert raw is None
    assert errors and "Unsupported electrode montage" in errors[0][1]


def test_preflight_and_full_loader_attach_identical_geometry(monkeypatch, tmp_path):
    queue = [_raw(), _raw(), _raw(), _raw()]

    def _read(*_args, **_kwargs):
        return queue.pop(0)

    monkeypatch.setattr(shared_load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_load_utils.mne.io, "read_raw_bdf", _read)
    app = _app([])
    path = str(tmp_path / "sample.bdf")

    full_raw = load_utils.load_eeg_file(app, path)
    with load_utils.open_preflight_eeg_file(app, path) as preflight_raw:
        assert preflight_raw is not None
        assert read_raw_biosemi64_geometry(preflight_raw) == read_raw_biosemi64_geometry(
            full_raw
        )
        for channel in BIOSEMI64_CHANNELS:
            full_loc = full_raw.info["chs"][full_raw.ch_names.index(channel)]["loc"][:3]
            preflight_loc = preflight_raw.info["chs"][preflight_raw.ch_names.index(channel)][
                "loc"
            ][:3]
            assert np.array_equal(full_loc, preflight_loc)
