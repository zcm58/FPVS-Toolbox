"""New acquisition profiles enter the same immutable numerical contract."""

from copy import deepcopy
import json

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_metadata import (
    attach_processed_geometry,
    configured_channel_limit,
    freeze_retained_geometry,
    resolve_recording_contract,
)
from Main_App.io.acquisition_profiles import UNICORN_CHANNELS
from Main_App.io.geometry_metadata import configured_geometry_identity, project_spectral_geometry
from Main_App.io.hardware_identity import geometry_matches_configuration
from Main_App.io.recorded_eeg_geometry import (
    attach_raw_recorded_geometry,
    validate_raw_recorded_geometry,
    validate_recorded_geometry_identity,
)


def _settings(platform):
    return {"hardware_platform": platform, "hardware_confirmed": True}


def _unicorn_raw(sfreq=250):
    raw = mne.io.RawArray(
        np.zeros((9, 500)),
        mne.create_info([*UNICORN_CHANNELS, "Status"], sfreq, ["eeg"] * 8 + ["stim"]),
        verbose=False,
    )
    attach_raw_recorded_geometry(
        raw, montage_id="unicorn8", template_montage="standard_1020",
        hardware_platform="unicorn", interpolation_allowed=False,
    )
    return raw


def test_active_three_does_not_inherit_legacy_references_channel_limit_or_qc():
    settings = _settings("biosemi_active_three")
    policy = resolve_recording_contract(settings)
    assert policy.initial_reference_mode == "recorded"
    assert policy.load_reference_channels == ()
    assert policy.channel_limit is None
    assert policy.canonical_scalp_order is None
    assert not policy.raw_screening_supported
    assert not policy.kurtosis_screening_supported
    assert policy.event_kwargs == {}
    assert policy.provenance["hardware_platform"] == "biosemi_active_three"
    selected = resolve_recording_contract({
        **settings, "initial_reference": "channels", "initial_reference_channels": ["EXG3", "EXG4"],
        "drop_reference_channels": True, "max_idx_keep": 128,
    })
    assert selected.initial_reference_channels == ("EXG3", "EXG4")
    assert selected.drop_reference_channels and selected.channel_limit == 128
    assert selected.acquisition_fingerprint != policy.acquisition_fingerprint


def test_new_platforms_have_distinct_configuration_and_geometry_identities():
    identities = []
    for platform in ("brain_products", "biosemi_active_three"):
        settings = {**_settings(platform), "electrode_montage": "recorded"}
        raw = mne.io.RawArray(np.zeros((3, 20)), mne.create_info(["E9", "E1", "E4"], 100, "eeg"), verbose=False)
        geometry = attach_raw_recorded_geometry(raw, hardware_platform=platform)
        config = configured_geometry_identity(settings)
        assert geometry_matches_configuration(geometry, config)
        assert project_spectral_geometry(settings).matches_source(geometry)
        identities.append((geometry, config))
    assert identities[0] != identities[1]
    assert not geometry_matches_configuration(identities[0][0], identities[1][1])
    assert "interpolation_allowed" not in identities[0][0]


def test_unicorn_uses_explicit_native_grid_and_final_scalp_reference_without_exg():
    contract = resolve_recording_contract(_settings("unicorn"))
    assert contract.initial_reference_mode == "recorded"
    assert contract.initial_reference_channels == ()
    assert contract.provenance["reference_policy"] == "average_scalp"
    assert contract.canonical_scalp_order == UNICORN_CHANNELS
    assert contract.event_encoding == "sample"
    assert contract.required_sfreq == 250
    assert not contract.resampling_allowed
    assert not contract.interpolation_allowed
    assert not contract.kurtosis_screening_supported
    assert configured_channel_limit(_settings("unicorn")) is None
    contract.validate(_unicorn_raw(), {"downsample": 250, "downsample_rate": 250})
    identity = configured_geometry_identity(_settings("unicorn"))
    assert json.loads(json.dumps(identity)) == identity
    remapped = {**_settings("unicorn"), "recording_event_policy": {"authority": "status", "numeric_annotations": True}}
    assert configured_geometry_identity(remapped) != identity
    assert resolve_recording_contract(remapped).acquisition_fingerprint != contract.acquisition_fingerprint


@pytest.mark.parametrize("override", [
    {"initial_reference": "channels"}, {"initial_reference_channels": ["EXG1"]},
    {"drop_reference_channels": True},
])
def test_unicorn_does_not_silently_ignore_reference_overrides(override):
    with pytest.raises(ValueError, match="eight-scalp average"):
        resolve_recording_contract({**_settings("unicorn"), **override})


@pytest.mark.parametrize("requested", [128, 256, 0, True, "bad", float("nan")])
def test_unicorn_never_silently_changes_sampling_grid(requested):
    contract = resolve_recording_contract(_settings("unicorn"))
    with pytest.raises(ValueError, match="Resampling"):
        contract.validate(_unicorn_raw(), {"downsample_rate": requested})


def test_unicorn_rejects_non_native_source_and_partial_montage():
    contract = resolve_recording_contract(_settings("unicorn"))
    with pytest.raises(ValueError, match="native 250"):
        contract.validate(_unicorn_raw(256), {})
    raw = _unicorn_raw()
    raw.drop_channels(["Fz"])
    attach_raw_recorded_geometry(raw, montage_id="unicorn8")
    with pytest.raises(ValueError, match="complete configured scalp"):
        contract.validate(raw, {})


@pytest.mark.parametrize("key,value", [
    ("manual_removed_electrodes", {"P1": ["Oz"]}),
    ("manual_removed_electrodes_by_recording", {"file": ["Oz"]}),
    ("_fpvs_condition_interpolation_requests", {"faces": ["Oz"]}),
    ("condition_electrode_interpolation_requests", {"file": {"faces": ["Oz"]}}),
    ("manual_removed_electrodes_enabled", True),
    ("kurtosis_auto_interpolate_all", True),
    ("kurtosis_screening_enabled", True),
    ("raw_signal_screening_enabled", True),
])
def test_unicorn_rejects_unqualified_screening_and_every_repair_request(key, value):
    contract = resolve_recording_contract(_settings("unicorn"))
    with pytest.raises(ValueError):
        contract.validate(_unicorn_raw(), {key: value})


def test_unicorn_coordinates_do_not_enable_interpolation_and_cache_restores_contract():
    raw = _unicorn_raw()
    settings = _settings("unicorn")
    geometry = validate_raw_recorded_geometry(raw)
    assert geometry["montage_id"] == "unicorn8"
    assert geometry["geometry_status"] == "available"
    assert not geometry["interpolation_supported"]
    with pytest.raises(ValueError, match="Interpolation"):
        validate_raw_recorded_geometry(raw, require_coordinates=True)
    contract = resolve_recording_contract(settings, raw)
    frozen = freeze_retained_geometry(raw, settings, stim_channel="Status", recording_contract=contract)
    assert frozen == geometry
    attach_processed_geometry(raw, settings)
    assert raw._fpvs_recording_contract.event_encoding == "sample"
    raw.info["bads"] = ["Oz"]
    with pytest.raises(ValueError, match="Interpolation"):
        contract.validate(raw, {})


def test_new_geometry_identity_rejects_capability_or_platform_tampering():
    geometry = validate_raw_recorded_geometry(_unicorn_raw())
    for key, value in (("interpolation_allowed", True), ("hardware_platform", "brain_products")):
        altered = deepcopy(geometry)
        altered[key] = value
        with pytest.raises(ValueError, match="inconsistent"):
            validate_recorded_geometry_identity(altered)
