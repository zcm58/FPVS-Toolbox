from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_profiles import (
    BUILTIN_REGISTRY, UNICORN_FACTORY_MAPPING_SOURCE_URL,
    UNICORN_FACTORY_RECORDED_LABEL_MAP, resolve_acquisition_contract,
)
from Main_App.io.bdf_format import inspect_bdf_format
from Main_App.io.load_utils import inspect_eeg_recording
from Main_App.io.unicorn_units import (
    UnicornUnitError, resolve_unicorn_unit_policy, unicorn_eeg_samples_in_volts,
)
from tests.bdf_factory import write_bdf


EEG = tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP)


def _settings():
    return {"acquisition_profile": {
        "id": "unicorn_hybrid_black", "version": "1.0", "montage_id": "unicorn8",
        "montage_version": "1.0", "event_decoder_id": "unicorn_sample",
        "event_decoder_version": "1.0", "reference_policy": "average_scalp",
        "source_to_canonical": dict(UNICORN_FACTORY_RECORDED_LABEL_MAP),
        "label_mapping_evidence": {"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL},
    }}


def _fixture(tmp_path, **kwargs):
    options = {
        "variant": "BDF", "record_onsets": ("0",), "eeg_names": EEG,
        "unit": "?V", "physical_ranges": {name: (-750000, 750000) for name in EEG},
        "signal_values": {name: [[-8388608, -1, 0, 1, 8388607] + [0] * 245] for name in EEG},
    }
    options.update(kwargs)
    return write_bdf(tmp_path / "source.bdf", **options)


@pytest.mark.parametrize("variant", ["BDF", "BDF+C"])
def test_explicit_unicorn_corrects_verified_header_preserving_source_and_events(tmp_path, variant):
    status = [0, 55, 55, 1, 255] + [0] * 245
    values = {name: [[-8388608, -1, 0, 1, 8388607] + [0] * 245] for name in EEG}
    values.update({"Status": [status], "CNT": [list(range(250))], "VALID": [[1] * 250], "DT": [[4] * 250]})
    path = _fixture(tmp_path, variant=variant, eeg_names=(*EEG, "CNT", "VALID", "DT"),
                    signal_units={"CNT": "", "VALID": "", "DT": ""}, signal_values=values)
    before = path.read_bytes()
    header_only = inspect_eeg_recording(path, _settings(), event_authority="status")
    result = inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)
    source = inspect_bdf_format(path, digital_channels=(*EEG, "Status", "CNT", "VALID", "DT"))
    samples = dict(result.eeg_samples_volts)

    assert tuple(samples) == EEG
    expected = np.array([float(Fraction(value + 8388608) * 1500000 / 16777215 - 750000) * 1e-6
                         for value in values[EEG[0]][0]])
    for data in samples.values():
        np.testing.assert_allclose(data, expected, rtol=1e-8, atol=1e-16)
        assert data[0] == -0.75
        assert data[4] == 0.75
        assert data[2] > 0  # Asymmetric digital endpoints give a nonzero physical offset.
    original_digital = source.digital_signals
    assert unicorn_eeg_samples_in_volts(result.contract, source) == result.eeg_samples_volts
    assert unicorn_eeg_samples_in_volts(result.contract, source) == result.eeg_samples_volts
    assert source.digital_signals == original_digital
    assert dict(source.digital_signals)["CNT"] == tuple(range(250))
    assert dict(source.digital_signals)["Status"] == tuple(status)
    assert result.events == header_only.events
    assert [(event.sample, event.code) for event in result.events.events] == [(1, 55), (2, 55), (3, 1), (4, 255)]
    assert header_only.eeg_samples_volts is None
    assert result.inspection_fingerprint == header_only.inspection_fingerprint
    assert path.read_bytes() == before
    assert result.source.file_sha256 == hashlib.sha256(before).hexdigest()
    assert result.scientific_processing_allowed is False
    assert {issue.code for issue in result.issues} == {"unqualified_acquisition", "integration_pending"}
    receipt = result.summary()["eeg_unit_policy"]
    assert receipt["version"] == "1.0"
    assert receipt["input"] == "original_bdf_digital_samples"
    assert receipt["output_unit"] == "V"
    assert receipt["hardware_amplitude_calibration"] == "unverified"
    assert all(channel["recorded_unit"] == "?V" and channel["interpreted_unit"] == "uV"
               and channel["physical_to_volts"] == 1e-6 and channel["recorder_label_correction"]
               for channel in receipt["channels"])
    assert result.source.header.signals[0].physical_dimension == "?V"
    assert str(tmp_path) not in json.dumps(receipt)
    changed = replace(result, eeg_unit_policy=replace(result.eeg_unit_policy, channels=(
        replace(result.eeg_unit_policy.channels[0], physical_to_volts=1), *result.eeg_unit_policy.channels[1:],
    )))
    assert changed.inspection_fingerprint != result.inspection_fingerprint
    receipt["channels"][0]["physical_to_volts"] = 1
    assert result.summary()["eeg_unit_policy"]["channels"][0]["physical_to_volts"] == 1e-6


@pytest.mark.parametrize("unit,factor", [("uV", 1e-6), ("mV", 1e-3), ("V", 1)])
@pytest.mark.parametrize("preload", [False, True])
def test_recognized_units_match_mne_without_double_conversion(tmp_path, unit, factor, preload):
    path = _fixture(tmp_path, unit=unit, physical_ranges={},
                    signal_values={name: [[10] * 250] for name in EEG})
    result = inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)
    expected = np.array([samples for _, samples in result.eeg_samples_volts])
    with mne.io.read_raw_bdf(path, preload=preload, verbose=False) as raw:
        np.testing.assert_allclose(expected, raw.get_data(picks=list(EEG)))
    np.testing.assert_allclose(expected, 10 * factor)
    assert not any(channel.recorder_label_correction for channel in result.eeg_unit_policy.channels)


def test_corrected_known_microvolt_tone_returns_microvolt_fft_units(tmp_path):
    target_uv = 10 * np.sin(2 * np.pi * 5 * np.arange(250) / 250)
    digital = np.rint((target_uv + 750000) * 16777215 / 1500000 - 8388608).astype(int)
    path = _fixture(tmp_path, signal_values={name: [digital] for name in EEG})
    result = inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)
    volts = np.array(result.eeg_samples_volts[0][1])
    # The unchanged post-processing contract converts V to uV before FFT.
    amplitude_uv = 2 * np.abs(np.fft.rfft(volts * 1e6)) / len(volts)
    assert amplitude_uv[5] == pytest.approx(10, abs=0.02)


@pytest.mark.parametrize("explicit", [False, True])
def test_biosemi_never_activates_unit_policy_or_sample_conversion(tmp_path, explicit):
    settings = {"acquisition_profile": {
        "id": "biosemi_active_two_64", "version": "1.0", "montage_id": "biosemi64",
        "montage_version": "1.0", "event_decoder_id": "biosemi_edge",
        "event_decoder_version": "1.0", "reference_policy": "biosemi_exg_pair_then_average",
    }} if explicit else {}
    contract = resolve_acquisition_contract(settings)
    identity = contract.identity
    source = inspect_bdf_format(_fixture(tmp_path), digital_channels=EEG)
    with pytest.raises(UnicornUnitError, match="never BioSemi"):
        resolve_unicorn_unit_policy(contract, source.header)
    with pytest.raises(UnicornUnitError, match="never BioSemi"):
        unicorn_eeg_samples_in_volts(contract, source)
    # Rejection occurs before even opening the selected file.
    with pytest.raises(UnicornUnitError, match="never BioSemi"):
        inspect_eeg_recording(tmp_path / "does_not_exist.bdf", settings,
                              event_authority="status", include_eeg_samples=True)
    assert contract.identity == identity
    assert "eeg_unit_policy" not in contract.identity


@pytest.mark.parametrize("field,value", [("id", "other_device"), ("version", "2.0")])
def test_similar_custom_profiles_cannot_activate_correction(tmp_path, field, value):
    builtin = BUILTIN_REGISTRY.lookup("profiles", "unicorn_hybrid_black")
    custom = replace(builtin, **{field: value})
    registry = replace(BUILTIN_REGISTRY, profiles=tuple(
        custom if profile == builtin else profile for profile in BUILTIN_REGISTRY.profiles
    ))
    settings = _settings()
    settings["acquisition_profile"][field] = value
    contract = resolve_acquisition_contract(settings, registry=registry)
    source = inspect_bdf_format(_fixture(tmp_path), digital_channels=EEG)
    with pytest.raises(UnicornUnitError, match="explicit built-in Unicorn"):
        unicorn_eeg_samples_in_volts(contract, source)


@pytest.mark.parametrize("field,value", [
    ("physical_minimum", Decimal(-700000)), ("physical_maximum", Decimal(700000)),
    ("digital_minimum", -8388607), ("digital_maximum", 8388606),
    ("samples_per_record", 256), ("label", "Other"), ("physical_dimension", "uV"),
])
def test_malformed_unit_exception_requires_complete_verified_header(tmp_path, field, value):
    source = inspect_bdf_format(_fixture(tmp_path), digital_channels=EEG)
    header = replace(source.header, signals=(replace(source.header.signals[0], **{field: value}),
                                            *source.header.signals[1:]))
    with pytest.raises(UnicornUnitError):
        unicorn_eeg_samples_in_volts(resolve_acquisition_contract(_settings()), replace(source, header=header))


@pytest.mark.parametrize("unit", ["counts", "", "?v"])
def test_unknown_units_remain_blocked_and_never_gain_one(tmp_path, unit):
    path = _fixture(tmp_path, unit=unit)
    inspected = inspect_eeg_recording(path, _settings(), event_authority="status")
    assert inspected.eeg_unit_policy is None
    assert "unqualified_unit" in {issue.code for issue in inspected.issues}
    with pytest.raises(UnicornUnitError, match="Unsupported"):
        inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)


@pytest.mark.parametrize("variant,onsets", [("BDF+D", ("0",)), ("BDF+C", ("0", "2"))])
def test_unit_correction_cannot_release_discontinuous_sample_view(tmp_path, variant, onsets):
    path = _fixture(tmp_path, variant=variant, record_onsets=onsets, signal_values={})
    with pytest.raises(UnicornUnitError, match="Continuous"):
        inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)


def test_converter_does_not_accept_already_converted_samples(tmp_path):
    source = inspect_bdf_format(_fixture(tmp_path), digital_channels=EEG)
    contract = resolve_acquisition_contract(_settings())
    converted = unicorn_eeg_samples_in_volts(contract, source)
    with pytest.raises(UnicornUnitError, match="original integer"):
        unicorn_eeg_samples_in_volts(contract, replace(source, digital_signals=converted))


@pytest.mark.parametrize("limits", [("-1e308", "1e308"), ("0", "1e-9999"), ("0", "1e9999")])
def test_unrepresentable_calibration_is_rejected_instead_of_nonfinite_or_zero_output(tmp_path, limits):
    path = _fixture(tmp_path, unit="V", physical_ranges={name: limits for name in EEG})
    with pytest.raises(UnicornUnitError, match="calibration"):
        inspect_eeg_recording(path, _settings(), event_authority="status", include_eeg_samples=True)


def test_annotation_only_sample_inspection_does_not_decode_eeg_as_status(tmp_path):
    path = _fixture(tmp_path, variant="BDF+C", status=False,
                    annotations=([b"+0.004\x14" b"55\x14\x00"],))
    settings = _settings()
    settings["acquisition_profile"]["event_decoder_id"] = "explicit_annotations"
    result = inspect_eeg_recording(path, settings, event_authority="annotations",
                                   numeric_annotations=True, include_eeg_samples=True)
    assert [(event.sample, event.code) for event in result.events.events] == [(1, 55)]
    assert len(result.eeg_samples_volts) == 8


def test_status_cannot_be_reinterpreted_as_a_scalp_eeg_channel(tmp_path):
    with pytest.raises(ValueError, match="roles must not overlap"):
        inspect_eeg_recording(tmp_path / "absent.bdf", _settings(), event_authority="status",
                              status_channel="EEG 1", include_eeg_samples=True)
