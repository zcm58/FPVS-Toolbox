from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from Main_App.io.acquisition_profiles import (
    AcquisitionCapabilities,
    AcquisitionProfile,
    BUILTIN_REGISTRY,
    MontageDefinition,
    UNICORN_CHANNELS,
    UNICORN_FACTORY_MAPPING_SOURCE_URL,
    UNICORN_FACTORY_RECORDED_LABEL_MAP,
)
from Main_App.io.load_utils import inspect_eeg_recording
from tests.bdf_factory import write_bdf


def _settings(**overrides):
    return {"acquisition_profile": {
        "id": "unicorn_hybrid_black", "version": "1.0",
        "montage_id": "unicorn8", "montage_version": "1.0",
        "event_decoder_id": "unicorn_sample", "event_decoder_version": "1.0",
        "reference_policy": "average_scalp", **overrides,
    }}


def _status(events=((10, 1), (11, 1), (30, 255), (260, 3)), *, rate=250, records=2):
    rows = [[0] * rate for _ in range(records)]
    for sample, code in events:
        rows[sample // rate][sample % rate] = code
    return {"Status": rows}


def _tal(onset, label, duration=None):
    duration_field = "" if duration is None else f"\x15{duration}"
    return f"+{onset}{duration_field}\x14{label}\x14\x00".encode("utf-8")


def _inspect(path, settings=None, **kwargs):
    before = path.read_bytes()
    result = inspect_eeg_recording(path, _settings() if settings is None else settings, **kwargs)
    assert path.read_bytes() == before
    assert result.source.file_sha256 == hashlib.sha256(before).hexdigest()
    assert result.scientific_processing_allowed is False
    assert result.summary()["scientific_processing_allowed"] is False
    assert result.summary()["physical_timing"] == "unknown_uncalibrated"
    assert {"unqualified_acquisition", "integration_pending"} <= {issue.code for issue in result.issues}
    return result


def _pairs(result):
    assert result.events is not None
    return tuple((event.sample, event.code) for event in result.events.events)


def test_retained_marker_receipt_replays_through_generated_native_record_format(tmp_path):
    receipt = json.loads((Path(__file__).parents[1] / "fixtures" / "unicorn_receiver"
                          / "retained_426_marker_receipt.json").read_text(encoding="utf-8"))
    rows = [[0] for _ in range(receipt["sample_count"])]
    for event in receipt["events"]:
        rows[event["sample"]][0] = event["code"]
    # This is a generated format replay, not a copy of the original vendor BDF.
    path = write_bdf(tmp_path / "receipt_replay.bdf", variant="BDF",
                     record_onsets=("0",) * len(rows), record_duration="0.004",
                     samples_per_record=1, eeg_names=tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP),
                     unit="?V", signal_values={"Status": rows})
    result = _inspect(path, _settings(source_to_canonical=dict(UNICORN_FACTORY_RECORDED_LABEL_MAP),
                                      label_mapping_evidence={"status": "verified",
                                                              "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL}),
                      event_authority="status")
    assert result.source.file_sha256 != receipt["source_bdf_sha256"]
    assert _pairs(result) == tuple((event["sample"], event["code"]) for event in receipt["events"])
    assert len(result.events.events) == 426
    assert "unqualified_unit" in {issue.code for issue in result.issues}


def test_classic_and_continuous_status_annotation_and_dual_sources_agree(tmp_path) -> None:
    expected = ((10, 1), (11, 1), (30, 255), (260, 3))
    results = []
    for name, variant, authority, has_status, markers in (
        ("classic", "BDF", "status", True, False),
        ("continuous_status", "BDF+C", "status", True, False),
        ("annotations", "BDF+C", "annotations", False, True),
        ("dual", "BDF+C", "reconcile", True, True),
    ):
        annotations = (
            [_tal("0.04", "1"), _tal("0.044", "1"), _tal("0.12", "255")],
            [_tal("1.04", "3")],
        ) if markers else ()
        path = write_bdf(tmp_path / f"{name}.bdf", variant=variant, status=has_status,
                         eeg_names=UNICORN_CHANNELS, signal_values=_status(), annotations=annotations)
        settings = _settings(event_decoder_id="explicit_annotations" if authority == "annotations" else "unicorn_sample")
        results.append(_inspect(path, settings, event_authority=authority, numeric_annotations=markers))

    assert all(_pairs(result) == expected for result in results)
    assert results[0].source.header.variant == "BDF"
    assert results[0].source.annotations == ()
    assert results[-1].events.authority == "reconcile"
    assert results[-1].events.decoder_id == "unicorn_sample+explicit_annotations"
    assert all({issue.code for issue in result.issues} == {"unqualified_acquisition", "integration_pending"}
               for result in results)


def test_fractional_origin_named_markers_and_notes_retain_original_evidence(tmp_path) -> None:
    path = write_bdf(
        tmp_path / "fractional_origin.bdf", eeg_names=UNICORN_CHANNELS,
        record_onsets=("0.1", "1.1"), signal_values=_status(), annotations=(
            [_tal("0.14", "oddball", "0.008"), _tal("0.144", "oddball"),
             _tal("0.22", "255"), _tal("0.3", "operator note", "0.08")],
            [_tal("1.14", "3")],
        ),
    )

    result = _inspect(path, event_authority="reconcile", numeric_annotations=True,
                      named_annotation_codes={"oddball": 1}, marker_labels=("oddball",))

    assert _pairs(result) == ((10, 1), (11, 1), (30, 255), (260, 3))
    assert result.source.first_sample_onset == Decimal("0.1")
    original = next(annotation for annotation in result.source.annotations if annotation.text == "oddball")
    assert original.onset_seconds == Decimal("0.14")
    assert original.duration_seconds == Decimal("0.008")
    relative = next(annotation for annotation in result.events.annotations if annotation.text == "oddball")
    assert relative.onset_seconds == 0.04
    assert relative.duration_seconds == 0.008
    note = next(annotation for annotation in result.events.annotations if annotation.text == "operator note")
    assert note.onset_seconds == 0.2
    assert note.duration_seconds == 0.08
    summary = result.summary()
    assert summary["first_sample_onset_seconds"] == "0.1"
    assert summary["record_onsets_seconds"] == ["0.1", "1.1"]
    assert summary["annotation_count"] == len(summary["annotations"])
    original_note = next(annotation for annotation in summary["annotations"] if annotation["text"] == "operator note")
    assert original_note["onset_seconds"] == "0.3"
    assert original_note["duration_seconds"] == "0.08"
    assert original_note["source_id"] == note.source_id
    assert original_note["source_order"] == note.source_order
    assert original_note["record_index"] == 0
    assert not original_note["is_timekeeping"]


def test_summary_retains_exact_long_decimal_annotation_origin_and_duration(tmp_path) -> None:
    origin = "0.12345678901234567890123456789"
    onset = "0.16345678901234567890123456789"
    duration = "0.00800000000000000000000000000"
    path = write_bdf(tmp_path / "precise_origin.bdf", eeg_names=UNICORN_CHANNELS,
                     record_onsets=(origin,), status=False,
                     annotations=([_tal(onset, "1", duration)],))

    result = _inspect(path, _settings(event_decoder_id="explicit_annotations"),
                      event_authority="annotations", numeric_annotations=True)

    assert _pairs(result) == ((10, 1),)
    summary = json.loads(json.dumps(result.summary()))
    assert summary["record_onsets_seconds"] == [origin]
    marker = next(annotation for annotation in summary["annotations"] if annotation["text"] == "1")
    assert marker["onset_seconds"] == onset
    assert marker["duration_seconds"] == duration
    assert summary["annotations"][0]["is_timekeeping"] is True
    assert summary["annotations"][0]["duration_seconds"] is None


@pytest.mark.parametrize("authority", ["status", "annotations", "reconcile"])
def test_nonempty_conflicting_event_sources_never_fall_back(tmp_path, authority) -> None:
    path = write_bdf(tmp_path / "conflict.bdf", eeg_names=UNICORN_CHANNELS,
                     signal_values=_status(((10, 1),)), annotations=([_tal("0.04", "2")],))
    settings = _settings(event_decoder_id="explicit_annotations" if authority == "annotations" else "unicorn_sample")

    result = _inspect(path, settings, event_authority=authority, numeric_annotations=True)

    assert result.events is None
    assert any(issue.code == "event_contract" and "conflict" in issue.detail for issue in result.issues)


@pytest.mark.parametrize("annotations,fragment", [
    (([_tal("0.042", "1")],), "off the native sample grid"),
    (([_tal("0.04", "1"), _tal("0.04", "2")],), "collide"),
])
def test_off_grid_or_colliding_annotation_markers_are_blocked(tmp_path, annotations, fragment) -> None:
    path = write_bdf(tmp_path / "invalid_markers.bdf", eeg_names=UNICORN_CHANNELS,
                     status=False, annotations=annotations)

    result = _inspect(path, _settings(event_decoder_id="explicit_annotations"),
                      event_authority="annotations", numeric_annotations=True)

    assert result.events is None
    assert any(issue.code == "event_contract" and fragment in issue.detail for issue in result.issues)


def test_declared_unmapped_annotation_marker_requires_a_decision(tmp_path) -> None:
    path = write_bdf(tmp_path / "unmapped.bdf", eeg_names=UNICORN_CHANNELS, status=False,
                     annotations=([_tal("0.04", "condition_A")],))

    result = _inspect(path, _settings(event_decoder_id="explicit_annotations"),
                      event_authority="annotations", marker_labels=("condition_A",))

    assert result.events is None
    assert any("no explicit code mapping" in issue.detail for issue in result.issues)


def test_numbered_labels_are_not_inferred_and_factory_selection_is_explicit(tmp_path) -> None:
    path = write_bdf(tmp_path / "numbered.bdf", variant="BDF",
                     eeg_names=tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP), signal_values=_status())
    implicit = _inspect(path, event_authority="status")
    assert sum(issue.code == "missing_scalp_label" for issue in implicit.issues) == 8
    assert implicit.contract.source_to_canonical_items == tuple((name, name) for name in UNICORN_CHANNELS)

    explicit = _inspect(path, _settings(
        source_to_canonical=UNICORN_FACTORY_RECORDED_LABEL_MAP,
        label_mapping_evidence={"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL},
    ), event_authority="status")

    assert not any(issue.code in {"missing_scalp_label", "unverified_mapping"} for issue in explicit.issues)
    assert _pairs(explicit) == ((10, 1), (11, 1), (30, 255), (260, 3))
    assert explicit.inspection_fingerprint != implicit.inspection_fingerprint


def test_unverified_mapping_is_visible_and_evidence_changes_fingerprint(tmp_path) -> None:
    path = write_bdf(tmp_path / "mapping.bdf", variant="BDF",
                     eeg_names=tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP), signal_values=_status())
    settings = _settings(source_to_canonical=UNICORN_FACTORY_RECORDED_LABEL_MAP)
    unverified = _inspect(path, settings, event_authority="status")
    verified = _inspect(path, _settings(
        source_to_canonical=UNICORN_FACTORY_RECORDED_LABEL_MAP,
        label_mapping_evidence={"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL},
    ), event_authority="status")

    assert any(issue.code == "unverified_mapping" for issue in unverified.issues)
    assert unverified.inspection_fingerprint != verified.inspection_fingerprint
    assert unverified.summary()["acquisition"]["reference_policy"] == "average_scalp"


def test_native_rate_mismatch_prevents_canonical_event_grid(tmp_path) -> None:
    path = write_bdf(tmp_path / "wrong_rate.bdf", eeg_names=UNICORN_CHANNELS, samples_per_record=256)

    result = _inspect(path, event_authority="status")

    assert result.events is None
    assert sum(issue.code == "native_grid" for issue in result.issues) == 8
    assert all(channel["sampling_rate_hz"] == "256" for channel in result.summary()["channels"])


def test_unknown_units_are_reported_without_converting_samples(tmp_path) -> None:
    path = write_bdf(tmp_path / "unknown_units.bdf", eeg_names=UNICORN_CHANNELS,
                     unit="counts", signal_values=_status())

    result = _inspect(path, event_authority="status")

    assert sum(issue.code == "unqualified_unit" for issue in result.issues) == 8
    assert {signal.physical_dimension for signal in result.source.header.signals if signal.label in UNICORN_CHANNELS} == {"counts"}
    assert _pairs(result) == ((10, 1), (11, 1), (30, 255), (260, 3))


def test_discontinuous_bdf_preserves_gaps_and_notes_without_fake_continuous_events(tmp_path) -> None:
    path = write_bdf(tmp_path / "gap.bdf", variant="BDF+D", eeg_names=UNICORN_CHANNELS,
                     record_onsets=("0.1", "2.1"), signal_values=_status(),
                     annotations=([_tal("0.14", "1")], [_tal("2.14", "gap reviewed", "0.008")]))

    result = _inspect(path, event_authority="status", numeric_annotations=True)

    assert result.source.header.variant == "BDF+D"
    assert result.source.record_onsets == (Decimal("0.1"), Decimal("2.1"))
    assert result.events is None
    assert any(issue.code == "format_continuity" for issue in result.issues)
    assert any(annotation.text == "gap reviewed" and annotation.onset_seconds == Decimal("2.14")
               for annotation in result.source.annotations)
    summary = result.summary()
    assert summary["event_count"] is None
    assert summary["record_onsets_seconds"] == ["0.1", "2.1"]
    note = next(annotation for annotation in summary["annotations"] if annotation["text"] == "gap reviewed")
    assert note["onset_seconds"] == "2.14"
    assert note["duration_seconds"] == "0.008"
    assert note["record_index"] == 1


def test_legacy_default_cannot_accidentally_select_unicorn_sample_decoding(tmp_path) -> None:
    path = write_bdf(tmp_path / "legacy.bdf", eeg_names=UNICORN_CHANNELS)

    with pytest.raises(ValueError, match="explicit sample/annotation"):
        inspect_eeg_recording(path, {}, event_authority="status")


def test_classic_bdf_cannot_claim_absent_annotation_authority(tmp_path) -> None:
    path = write_bdf(tmp_path / "classic.bdf", variant="BDF", eeg_names=UNICORN_CHANNELS)

    result = _inspect(path, _settings(event_decoder_id="explicit_annotations"),
                      event_authority="annotations", numeric_annotations=True)

    assert result.events is None
    assert any(issue.code == "event_contract" and "absent" in issue.detail for issue in result.issues)


@pytest.mark.parametrize("authority,primary_decoder,secondary_decoder", [
    ("status", "unicorn_sample", "explicit_annotations"),
    ("annotations", "explicit_annotations", "unicorn_sample"),
])
@pytest.mark.parametrize("unsupported", ["profile", "version"])
def test_recorded_secondary_source_must_have_a_compatible_current_decoder(
    tmp_path, authority, primary_decoder, secondary_decoder, unsupported,
) -> None:
    path = write_bdf(tmp_path / "secondary.bdf", eeg_names=UNICORN_CHANNELS,
                     signal_values=_status(((10, 1),)), annotations=([_tal("0.04", "1")],))
    if unsupported == "profile":
        registry = replace(BUILTIN_REGISTRY, profiles=tuple(
            replace(profile, decoder_ids=(primary_decoder,)) if profile.id == "unicorn_hybrid_black" else profile
            for profile in BUILTIN_REGISTRY.profiles
        ))
    else:
        registry = replace(BUILTIN_REGISTRY, event_decoders=tuple(
            replace(decoder, version="2.0") if decoder.id == secondary_decoder else decoder
            for decoder in BUILTIN_REGISTRY.event_decoders
        ))

    result = _inspect(path, _settings(event_decoder_id=primary_decoder), registry=registry,
                      event_authority=authority, numeric_annotations=True)

    assert result.events is None
    failure = next(issue for issue in result.issues if issue.code == "event_contract")
    assert secondary_decoder in failure.detail
    assert ("does not support" if unsupported == "profile" else "Unsupported version") in failure.detail


def test_registered_but_unimplemented_format_version_cannot_reuse_bdf_inspector(tmp_path) -> None:
    registry = replace(BUILTIN_REGISTRY, format_adapters=tuple(
        replace(adapter, version="2.0") if adapter.id == "bdf" else adapter
        for adapter in BUILTIN_REGISTRY.format_adapters
    ))
    path = write_bdf(tmp_path / "new_format_version.bdf", eeg_names=UNICORN_CHANNELS)

    with pytest.raises(ValueError, match="requires a BDF profile"):
        inspect_eeg_recording(path, _settings(), event_authority="status", registry=registry)


def test_third_registered_profile_uses_identical_inspector_at_its_own_native_rate(tmp_path) -> None:
    montage = MontageDefinition("synthetic3", "2.0", ("A", "B", "C"),
                                (("Input A", "A"), ("Input B", "B"), ("Input C", "C")),
                                "Synthetic coordinates v2", "head")
    profile = AcquisitionProfile("synthetic_acquisition", "2.0", "bdf", ("synthetic3",), ("unicorn_sample",),
                                 AcquisitionCapabilities(125, False, False, False, False), ("average_scalp",))
    registry = replace(BUILTIN_REGISTRY, montages=(*BUILTIN_REGISTRY.montages, montage),
                       profiles=(*BUILTIN_REGISTRY.profiles, profile))
    settings = _settings(id="synthetic_acquisition", version="2.0", montage_id="synthetic3", montage_version="2.0")
    path = write_bdf(tmp_path / "synthetic.bdf", variant="BDF", eeg_names=("Input A", "Input B", "Input C"),
                     samples_per_record=125, signal_values=_status(((1, 3), (2, 3), (125, 255)), rate=125))

    result = _inspect(path, settings, event_authority="status", registry=registry)

    assert _pairs(result) == ((1, 3), (2, 3), (125, 255))
    assert result.events.events[0].onset_seconds == 0.008
    assert {issue.code for issue in result.issues} == {"unqualified_acquisition", "integration_pending"}
    assert result.contract.profile.id == "synthetic_acquisition"

    with pytest.raises(ValueError, match="decoder|compatible|authority"):
        inspect_eeg_recording(path, settings, event_authority="annotations", registry=registry)


def test_inspection_identity_is_path_free_detached_and_event_policy_sensitive(tmp_path) -> None:
    source = write_bdf(tmp_path / "first.bdf", eeg_names=UNICORN_CHANNELS, signal_values=_status())
    duplicate = tmp_path / "different_name.bdf"
    duplicate.write_bytes(source.read_bytes())
    first = _inspect(source, event_authority="status")
    second = _inspect(duplicate, event_authority="status")
    changed_policy = _inspect(source, event_authority="status", numeric_annotations=True)

    assert first.inspection_fingerprint == second.inspection_fingerprint
    assert first.inspection_fingerprint != changed_policy.inspection_fingerprint
    summary = first.summary()
    assert str(tmp_path) not in json.dumps(summary)
    summary["event_policy"]["authority"] = "changed"
    summary["annotations"][0]["text"] = "changed"
    summary["record_onsets_seconds"][0] = "1000"
    assert first.summary()["event_policy"]["authority"] == "status"
    assert first.summary()["annotations"][0]["text"] == ""
    assert first.summary()["record_onsets_seconds"][0] == "0"
