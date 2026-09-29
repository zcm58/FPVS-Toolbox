from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from Main_App.io.acquisition_profiles import (
    AcquisitionCapabilities,
    AcquisitionProfile,
    AcquisitionProfileError,
    AcquisitionRegistry,
    BUILTIN_REGISTRY,
    EventDecoderDefinition,
    FormatAdapterDefinition,
    MontageDefinition,
    UNICORN_CHANNELS,
    UNICORN_FACTORY_MAPPING_SOURCE_URL,
    UNICORN_FACTORY_RECORDED_LABEL_MAP,
    resolve_acquisition_contract,
)


def _unicorn(**overrides):
    return {"acquisition_profile": {
        "id": "unicorn_hybrid_black", "version": "1.0",
        "montage_id": "unicorn8", "montage_version": "1.0",
        "event_decoder_id": "unicorn_sample", "event_decoder_version": "1.0",
        "reference_policy": "average_scalp", **overrides,
    }}


def test_absent_profile_is_runtime_only_biosemi_default() -> None:
    settings = {"downsample": 256, "ref_channel1": "EXG1", "electrode_montage": "biosemi64"}
    original = deepcopy(settings)
    original_serialization = json.dumps(settings)

    result = resolve_acquisition_contract(settings)

    assert result.legacy_default
    assert result.profile.id == "biosemi_active_two_64"
    assert result.reference_policy == "biosemi_exg_pair_then_average"
    assert result.profile.capabilities.allow_interpolation
    assert result.profile.capabilities.allow_resampling
    assert settings == original
    assert json.dumps(settings) == original_serialization
    assert "acquisition_profile" not in settings
    assert resolve_acquisition_contract(None).fingerprint == result.fingerprint


def test_legacy_registered_biosemi_wiring_mapping_is_preserved() -> None:
    result = resolve_acquisition_contract({"electrode_mapping_profile": "biosemi64_1020_ab_v1"})

    assert dict(result.source_to_canonical_items)["B6"] == "Fz"
    assert result.label_mapping_evidence_status == "registered"
    assert result.label_mapping_evidence_reference == "biosemi64_1020_ab_v1"
    assert result.fingerprint != resolve_acquisition_contract({}).fingerprint


def test_unicorn_freezes_native_policy_and_only_anatomical_mapping() -> None:
    settings = _unicorn()
    original = deepcopy(settings)
    result = resolve_acquisition_contract(settings)

    assert result.montage.channel_names == UNICORN_CHANNELS
    assert result.profile.capabilities == AcquisitionCapabilities(250, False, False, False, False)
    assert result.source_to_canonical_items == tuple((name, name) for name in UNICORN_CHANNELS)
    assert "EEG 1" not in dict(result.source_to_canonical_items)
    assert "standard_1020" in result.montage.coordinate_source
    assert "1.9.0" in result.montage.coordinate_source
    assert result.montage.coordinate_frame == "head"
    assert not result.legacy_default
    assert settings == original
    assert json.loads(json.dumps(result.identity))["profile"]["id"] == "unicorn_hybrid_black"


@pytest.mark.parametrize("field", ["id", "version", "montage_id", "montage_version", "event_decoder_id", "event_decoder_version"])
def test_unknown_definition_or_version_is_rejected(field) -> None:
    with pytest.raises(AcquisitionProfileError):
        resolve_acquisition_contract(_unicorn(**{field: "unknown"}))


@pytest.mark.parametrize("field,value", [
    ("montage_id", "biosemi64"), ("event_decoder_id", "biosemi_edge"),
    ("reference_policy", "biosemi_exg_pair_then_average"),
])
def test_known_but_incompatible_combination_is_rejected(field, value) -> None:
    with pytest.raises(AcquisitionProfileError, match="incompatible"):
        resolve_acquisition_contract(_unicorn(**{field: value}))


@pytest.mark.parametrize("value", [None, "unicorn_hybrid_black", {}, {"id": "unicorn_hybrid_black"}])
def test_explicit_invalid_profile_never_falls_back(value) -> None:
    with pytest.raises(AcquisitionProfileError):
        resolve_acquisition_contract({"acquisition_profile": value})


def test_unicorn_reference_policy_must_be_explicit_and_affects_identity() -> None:
    settings = _unicorn()
    del settings["acquisition_profile"]["reference_policy"]
    with pytest.raises(AcquisitionProfileError):
        resolve_acquisition_contract(settings)
    with pytest.raises(AcquisitionProfileError, match="reference policy"):
        resolve_acquisition_contract(_unicorn(reference_policy="retain_acquired"))
    assert resolve_acquisition_contract(_unicorn()).profile.reference_policies == ("average_scalp",)


def test_documented_factory_mapping_is_immutable_and_requires_explicit_selection() -> None:
    expected = dict(zip((f"EEG {number}" for number in range(1, 9)), UNICORN_CHANNELS, strict=True))
    assert dict(UNICORN_FACTORY_RECORDED_LABEL_MAP) == expected
    with pytest.raises(TypeError):
        UNICORN_FACTORY_RECORDED_LABEL_MAP["EEG 1"] = "Oz"
    assert dict(resolve_acquisition_contract(_unicorn()).source_to_canonical_items) != expected

    explicit = resolve_acquisition_contract(_unicorn(
        source_to_canonical=UNICORN_FACTORY_RECORDED_LABEL_MAP,
        label_mapping_evidence={"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL},
    ))
    assert dict(explicit.source_to_canonical_items) == expected
    assert explicit.label_mapping_evidence_reference == UNICORN_FACTORY_MAPPING_SOURCE_URL


def test_annotation_decoder_is_explicitly_compatible_with_unicorn() -> None:
    result = resolve_acquisition_contract(_unicorn(event_decoder_id="explicit_annotations"))

    assert result.event_decoder.id == "explicit_annotations"
    assert result.event_decoder.version == "1.0"
    assert result.fingerprint != resolve_acquisition_contract(_unicorn()).fingerprint


def test_custom_mapping_is_frozen_with_independent_evidence() -> None:
    mapping = {f"Recorded {index}": name for index, name in enumerate(UNICORN_CHANNELS)}
    settings = _unicorn(source_to_canonical=mapping)
    result = resolve_acquisition_contract(settings)
    assert result.label_mapping_evidence_status == "unverified"
    assert result.label_mapping_evidence_reference == ""
    mapping["Recorded 0"] = "Oz"
    assert dict(result.source_to_canonical_items)["Recorded 0"] == "Fz"
    verified = resolve_acquisition_contract(_unicorn(
        source_to_canonical=result.source_to_canonical_items,
        label_mapping_evidence={"status": "verified", "reference": "fixture-wiring-review-sha256:example"},
    ))
    assert verified.label_mapping_evidence_status == "verified"
    assert verified.fingerprint != result.fingerprint


@pytest.mark.parametrize("evidence", [
    {"status": "verified"}, {"status": "registered"}, {"status": "unknown"}, {"status": []}, None,
])
def test_custom_mapping_cannot_claim_verification_without_evidence(evidence) -> None:
    with pytest.raises(AcquisitionProfileError):
        resolve_acquisition_contract(_unicorn(
            source_to_canonical=dict(zip(UNICORN_CHANNELS, UNICORN_CHANNELS, strict=True)),
            label_mapping_evidence=evidence,
        ))


@pytest.mark.parametrize("mapping", [
    (("one", "Fz"),),
    tuple(("same", name) for name in UNICORN_CHANNELS),
    tuple((name, "Fz") for name in UNICORN_CHANNELS),
    tuple((name, "unknown" if name == "Fz" else name) for name in UNICORN_CHANNELS),
])
def test_mapping_must_be_complete_and_unambiguous(mapping) -> None:
    with pytest.raises(AcquisitionProfileError):
        resolve_acquisition_contract(_unicorn(source_to_canonical=mapping))


def test_third_profile_uses_same_resolver_and_does_not_change_existing_identity() -> None:
    montage = MontageDefinition("synthetic3", "2.0", ["A", "B", "C"],
                                [("input1", "A"), ("input2", "B"), ("input3", "C")],
                                "synthetic coordinates v2", "head")
    profile = AcquisitionProfile("synthetic", "2.0", "bdf", ["synthetic3"], ["unicorn_sample"],
                                 AcquisitionCapabilities(250, False, False, False, False), ["retain_acquired"])
    registry = replace(BUILTIN_REGISTRY, montages=(*BUILTIN_REGISTRY.montages, montage),
                       profiles=(*BUILTIN_REGISTRY.profiles, profile))
    result = resolve_acquisition_contract(_unicorn(id="synthetic", version="2.0",
                                                 montage_id="synthetic3", montage_version="2.0",
                                                 reference_policy="retain_acquired"), registry=registry)

    assert result.montage.channel_names == ("A", "B", "C")
    assert result.source_to_canonical_items == (("input1", "A"), ("input2", "B"), ("input3", "C"))
    assert result.event_decoder.id == "unicorn_sample"
    assert result.label_mapping_evidence_status == "registered"
    assert result.label_mapping_evidence_reference == "synthetic3/2.0"
    assert resolve_acquisition_contract({}, registry=registry).fingerprint == resolve_acquisition_contract({}).fingerprint
    assert isinstance(montage.channel_names, tuple)


def test_registry_rejects_duplicate_ids_and_unregistered_dependencies() -> None:
    with pytest.raises(AcquisitionProfileError, match="unique"):
        replace(BUILTIN_REGISTRY, event_decoders=(*BUILTIN_REGISTRY.event_decoders, EventDecoderDefinition("biosemi_edge", "2.0")))
    with pytest.raises(AcquisitionProfileError, match="Unknown"):
        replace(BUILTIN_REGISTRY, profiles=(replace(BUILTIN_REGISTRY.profiles[0], format_id="unknown"),))
    with pytest.raises(AcquisitionProfileError, match="definitions"):
        AcquisitionRegistry((), (), (), ())


def test_definitions_and_resolution_are_deeply_immutable() -> None:
    result = resolve_acquisition_contract(_unicorn())
    for obj, field, value in ((result, "reference_policy", "other"),
                              (result.profile.capabilities, "allow_resampling", True),
                              (BUILTIN_REGISTRY, "profiles", ())):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
    identity = result.identity
    identity["profile"]["capabilities"]["allow_interpolation"] = True
    identity["source_to_canonical_items"][0][0] = "Changed"
    assert not result.identity["profile"]["capabilities"]["allow_interpolation"]
    assert result.identity["source_to_canonical_items"][0][0] == "Fz"
    reconstructed = replace(result, source_to_canonical_items=[list(pair) for pair in result.source_to_canonical_items])
    assert isinstance(reconstructed.source_to_canonical_items, tuple)
    with pytest.raises(AcquisitionProfileError, match="incompatible"):
        replace(result, reference_policy="biosemi_exg_pair_then_average")


def test_explicit_biosemi_policy_matches_legacy_resolution_identity() -> None:
    legacy = resolve_acquisition_contract({})
    explicit = resolve_acquisition_contract({"acquisition_profile": {
        "id": "biosemi_active_two_64", "version": "1.0",
        "montage_id": "biosemi64", "montage_version": "1.0",
        "event_decoder_id": "biosemi_edge", "event_decoder_version": "1.0",
        "reference_policy": "biosemi_exg_pair_then_average",
    }})

    assert not explicit.legacy_default
    assert legacy.fingerprint == explicit.fingerprint


@pytest.mark.parametrize("value", [True, 0, -250, float("inf"), float("nan"), "250"])
def test_invalid_native_sample_rate_is_rejected(value) -> None:
    with pytest.raises(AcquisitionProfileError):
        AcquisitionCapabilities(value, False, False, False, False)


def test_definition_input_validation() -> None:
    with pytest.raises(AcquisitionProfileError):
        FormatAdapterDefinition("bdf", "", (".bdf",))
    with pytest.raises(AcquisitionProfileError):
        FormatAdapterDefinition("bdf", "1.0", ("BDF",))
    with pytest.raises(AcquisitionProfileError):
        AcquisitionCapabilities(250, "false", False, False, False)
    with pytest.raises(AcquisitionProfileError, match="explicit acquisition"):
        resolve_acquisition_contract({"electrode_montage": "unicorn8"})
