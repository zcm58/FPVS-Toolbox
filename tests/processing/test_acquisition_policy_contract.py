"""Keep normalized recording policy independent of the original file container."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError

import mne
import numpy as np
import pytest

from Main_App.processing.acquisition_policy import (
    attach_acquisition_policy,
    event_detection_kwargs,
    resolve_acquisition_policy,
)
from Main_App.processing.preprocess import _build_preproc_fingerprint
from Main_App.io.acquisition_metadata import (
    attach_recording_contract,
    configured_channel_limit,
    resolve_recording_contract,
    source_identity,
    source_load_kwargs,
)
from Main_App.io.recording_contract import RecordingContract


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, "c60bcf90383526bcf68acb5b2164dbd1e4078bac87b7c4441646791ecdf5fc35"),
        (
            {"hardware_platform": "biosemi", "ref_channel1": "EXG3", "ref_channel2": "EXG4", "max_idx_keep": 32, "kurtosis_screening_enabled": False},
            "ab36fc3a71e00f093b23d779d8068fd8873887733dbaf95000df9d19da7ae2db",
        ),
        (
            {"hardware_platform": "brain_products", "hardware_confirmed": True, "electrode_montage": "recorded", "initial_reference": "recorded", "kurtosis_screening_enabled": False},
            "82bf0e2ebf531455f6178dd14f3a50f553c05899c340b617011fba62ef6a5e6f",
        ),
        (
            {"hardware_platform": "brain_products", "hardware_confirmed": True, "electrode_montage": "standard_1020", "initial_reference": "channels", "initial_reference_channels": ["TP9", "TP10"], "drop_reference_channels": True, "max_idx_keep": 32, "kurtosis_screening_enabled": False},
            "9bfb09d2b7d38a3160c76dbdc31f6d29fc934bd2004560485930b165bc33872e",
        ),
    ],
)
def test_pre_bids_scientific_fingerprints_are_unchanged(settings, expected):
    # Captured independently from the pre-refactor da14edaa implementation.
    assert hashlib.sha256(_build_preproc_fingerprint(settings).encode()).hexdigest() == expected


def test_normalized_policy_keeps_recorded_channel_order_and_marker_edges():
    raw = mne.io.RawArray(
        np.zeros((4, 64)),
        mne.create_info(["E9", "E1", "E4", "Status"], 64, ["eeg"] * 3 + ["stim"]),
        verbose=False,
    )
    settings = {"hardware_platform": "brain_products", "hardware_confirmed": True}
    policy = attach_acquisition_policy(raw, settings)
    assert policy.scalp_channels(raw) == ["E9", "E1", "E4"]
    assert policy.ordered_scalp_channels(raw) == ["E9", "E1", "E4"]
    assert event_detection_kwargs(raw=raw.copy()) == {"initial_event": True, "consecutive": True}
    with pytest.raises(FrozenInstanceError):
        policy.marker_impulses = False


def test_legacy_montage_order_and_event_defaults_survive_container_change():
    raw = mne.io.RawArray(
        np.zeros((4, 64)),
        mne.create_info(["O1", "Fp1", "P1", "Status"], 64, ["eeg"] * 3 + ["stim"]),
        verbose=False,
    )
    policy = attach_acquisition_policy(raw, {"hardware_platform": "biosemi"})
    assert policy.initial_reference_channels == ("EXG1", "EXG2")
    assert policy.scalp_channels(raw) == ["O1", "Fp1", "P1"]
    assert policy.ordered_scalp_channels(raw) == ["Fp1", "P1", "O1"]
    assert event_detection_kwargs(raw=raw) == {}
    assert resolve_acquisition_policy({"source_format": "bdf"}) == resolve_acquisition_policy({"source_format": "brainvision"})


def test_policy_reference_provenance_is_detached_from_mutable_project_settings():
    settings = {
        "hardware_platform": "brain_products", "hardware_confirmed": True,
        "initial_reference": "channels", "initial_reference_channels": ["R1", "R2"],
        "channel_types": {"ECG": "ecg"},
    }
    policy = resolve_acquisition_policy(settings)
    settings["initial_reference_channels"].append("R3")
    settings["channel_types"]["ECG"] = "eeg"
    provenance = policy.provenance
    assert policy.initial_reference_channels == ("R1", "R2")
    assert provenance["initial_reference_channels"] == ["R1", "R2"]
    assert provenance["channel_types"] == {"ECG": "ecg"}
    provenance["channel_types"].clear()
    assert policy.provenance["channel_types"] == {"ECG": "ecg"}


@pytest.mark.parametrize("platform", ["unknown_device", None])
def test_explicit_unsupported_hardware_never_selects_legacy_policy(platform):
    with pytest.raises(ValueError, match="Unsupported EEG hardware"):
        resolve_acquisition_policy({"hardware_platform": platform, "hardware_confirmed": True})


def test_hardware_normalization_agrees_with_project_admission():
    assert resolve_acquisition_policy({
        "hardware_platform": " Brain_Products ", "hardware_confirmed": True,
    }) == resolve_acquisition_policy({
        "hardware_platform": "brain_products", "hardware_confirmed": True,
    })


def test_generic_contract_runs_without_manufacturer_resolution(monkeypatch):
    import Main_App.projects.hardware as hardware

    def forbidden(*args, **kwargs):
        raise AssertionError("Generic contract consumers must not resolve acquisition hardware.")

    monkeypatch.setattr(hardware, "resolve_hardware", forbidden)
    raw = mne.io.RawArray(
        np.zeros((4, 64)),
        mne.create_info(["E9", "E1", "E4", "Trigger"], 64, ["eeg"] * 3 + ["stim"]),
        verbose=False,
    )
    contract = RecordingContract(
        initial_reference_mode="recorded", initial_reference_channels=(),
        drop_reference_channels=False, max_idx_keep=None, canonical_scalp_order=None,
        recorded_channel_geometry=False, kurtosis_screening_supported=False,
        strict_processing_errors=True, geometry_fingerprint="provided_geometry_v1",
        marker_impulses=True, stim_channel="Trigger",
    )
    assert attach_recording_contract(raw, recording_contract=contract) is contract
    assert contract.scalp_channels(raw) == ["E9", "E1", "E4"]
    assert contract.ordered_scalp_channels(raw) == ["E9", "E1", "E4"]
    assert event_detection_kwargs(raw=raw.copy()) == {"initial_event": True, "consecutive": True}
    assert event_detection_kwargs(recording_contract=contract) == contract.event_kwargs
    contract.validate(raw, {"kurtosis_screening_enabled": False})


def test_resolved_contract_preserves_fingerprint_defaults_and_explicit_none():
    default = resolve_recording_contract({})
    explicit_none = resolve_recording_contract({"electrode_montage": None, "electrode_mapping_profile": None})
    assert default.fingerprint_montage == "biosemi64"
    assert default.fingerprint_mapping == "anatomical_labels"
    assert explicit_none.fingerprint_montage is None
    assert explicit_none.fingerprint_mapping is None
    assert explicit_none.montage_id == default.montage_id
    assert explicit_none.mapping_profile == default.mapping_profile


def test_loader_aliases_and_review_fingerprint_reference_are_resolved_upstream():
    settings = {"ref_chan1": "EXG3", "ref_ch2": "EXG4", "max_chan_idx_keep": "32", "stim": "Trigger"}
    contract = resolve_recording_contract(settings)
    assert contract.load_reference_channels == ("EXG3", "EXG4")
    assert contract.review_reference_pair == ("EXG3", "EXG4")
    assert contract.channel_limit == 32
    assert contract.stim_channel == "Trigger"
    assert source_load_kwargs(settings)["ref_pair"] == contract.load_reference_channels
    recorded = resolve_recording_contract({
        "hardware_platform": "brain_products", "hardware_confirmed": True,
        "initial_reference": "channels", "initial_reference_channels": ["R1", "R2"],
    })
    assert recorded.initial_reference_channels == ("R1", "R2")
    assert recorded.review_reference_pair == ("", "")
    assert not recorded.raw_screening_supported
    assert not recorded.condition_repair_supported


@pytest.mark.parametrize("limit", [True, 0, 65, 3.25, "invalid"])
def test_upstream_channel_limit_rejects_unqualified_template_selection(limit):
    with pytest.raises(ValueError, match="channel limit"):
        configured_channel_limit({"max_idx_keep": limit})


def test_geometry_and_source_identity_are_detached_snapshots():
    raw = mne.io.RawArray(np.zeros((1, 16)), mne.create_info(["Fp1"], 16, "eeg"), verbose=False)
    raw._fpvs_eeg_geometry = {"retained_scalp_channels": ["Fp1"]}
    settings = {"channel_types": {"Fp1": "eeg"}}
    contract = resolve_recording_contract(settings, raw)
    source = source_identity(settings)
    raw._fpvs_eeg_geometry["retained_scalp_channels"].clear()
    settings["channel_types"].clear()
    exposed = contract.geometry
    exposed["retained_scalp_channels"].clear()
    assert contract.geometry == {"retained_scalp_channels": ["Fp1"]}
    assert source == {"channel_types": {"Fp1": "eeg"}}
