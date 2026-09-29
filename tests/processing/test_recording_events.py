from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import numpy as np
import pytest

from Main_App.io.recording_events import (
    RecordingAnnotation,
    RecordingEventError,
    decode_annotation_events,
    decode_sample_status,
    reconcile_event_sources,
)

pytestmark = pytest.mark.processing


def _annotation(order: int, onset: float, text: str, duration: float = 0.0) -> RecordingAnnotation:
    return RecordingAnnotation(f"annotation:{order}", order, onset, duration, text)


def _decode(annotations, **kwargs):
    settings = dict(sfreq=250, n_samples=1000, numeric_codes=True, named_codes={})
    settings.update(kwargs)
    return decode_annotation_events(annotations, **settings)


def test_status_preserves_all_codes_equal_and_decreasing_neighbors():
    values = np.asarray([0, *range(1, 256), 55, 55, 1, 0, 1, 1])
    result = decode_sample_status(values, sfreq=250, first_samp=900)
    expected_samples = np.flatnonzero(values)
    np.testing.assert_array_equal(result.as_mne_events()[:, 0], expected_samples + 900)
    np.testing.assert_array_equal(result.as_mne_events()[:, 2], values[expected_samples])
    assert len(result.events) == 260
    assert result.events[0].onset_seconds == 0.004
    assert result.events[0].source_order == 1
    assert result.events[0].source_id == "status:Status:1"
    assert result.events[0].source_channel == "Status"
    assert result.events[-1].quantization_residual_seconds == 0


def test_retained_receiver_receipt_recovers_all_426_recorded_code_sample_pairs():
    fixture = Path(__file__).parents[1] / "fixtures" / "unicorn_receiver" / "retained_426_marker_receipt.json"
    receipt = json.loads(fixture.read_text(encoding="utf-8"))
    assert receipt["source_kind"] == "retained_test_signal_receiver_receipt"
    assert receipt["source_bdf_sha256"] == "9fa2e01480fae7a1500f92cc8739fa2a036f9b87b1f00fef429712a73c6a6a0c"
    assert receipt["sampling_hz"] == 250
    assert receipt["sample_count"] == 22621
    assert receipt["recorded_markers"] == receipt["expected_markers"] == 426
    assert receipt["format"]["reserved"] == "24BIT"
    assert not receipt["format"]["bdf_plus_annotations_present"]
    expected = np.asarray([[event["sample"], 0, event["code"]] for event in receipt["events"]], dtype=np.int64)
    assert expected.shape == (426, 3)
    assert np.all(np.diff(expected[:, 0]) > 0)
    assert set(expected[:, 2]) == set(range(1, 256))
    # The portable receipt contains all nonzero source samples, not raw EEG.
    status = np.zeros(receipt["sample_count"], dtype=np.int64)
    status[expected[:, 0]] = expected[:, 2]
    result = decode_sample_status(status, sfreq=receipt["sampling_hz"], channel=receipt["format"]["status_label"])
    np.testing.assert_array_equal(result.as_mne_events(), expected)
    consecutive_equal = [
        previous.sample
        for previous, current in zip(result.events, result.events[1:])
        if current.sample == previous.sample + 1 and current.code == previous.code
    ]
    assert consecutive_equal == [16663, 16679, 16764, 16780]


@pytest.mark.parametrize("values", [[np.nan], [np.inf], [-1], [256], [1.5], [True], ["55"], [[1]]])
def test_status_rejects_malformed_samples(values):
    with pytest.raises(RecordingEventError):
        decode_sample_status(values, sfreq=250)


@pytest.mark.parametrize("rate", [0, -250, np.nan, np.inf, True, "250"])
def test_status_rejects_invalid_rate(rate):
    with pytest.raises(RecordingEventError):
        decode_sample_status([55], sfreq=rate)


def test_empty_events_are_shaped_and_return_independent_integer_arrays():
    empty = decode_sample_status([], sfreq=250)
    assert empty.as_mne_events().shape == (0, 3)
    assert empty.as_mne_events().dtype == np.dtype(np.int64)
    result = decode_sample_status([55], sfreq=250)
    mutable = result.as_mne_events()
    mutable[0, 2] = 1
    assert result.events[0].code == 55
    with pytest.raises(FrozenInstanceError):
        result.events[0].code = 1


def test_annotation_numeric_mapping_named_mapping_and_notes_preserve_source_order():
    source = (
        _annotation(2, 0.0, "Operator starts recording"),
        _annotation(3, 0.004, " 055 ", 0.008),
        _annotation(4, 0.007, "Artifact note", 0.3),
        _annotation(5, 0.008, "Faces"),
        _annotation(6, 0.012, "Faces"),
    )
    result = _decode(source, first_samp=700, named_codes={"Faces": 1})
    np.testing.assert_array_equal(result.as_mne_events(), [[701, 0, 55], [702, 0, 1], [703, 0, 1]])
    assert result.annotations == source
    assert result.events[0].annotation_text == " 055 "
    assert result.events[0].duration_seconds == 0.008
    assert result.events[1].source_id == "annotation:5"
    assert result.events[1].source_order == 5


def test_numeric_mapping_is_opt_in_and_no_alphabetical_ids_are_created():
    annotations = [_annotation(0, 0, "55"), _annotation(1, 0.004, "Faces")]
    result = _decode(annotations, numeric_codes=False)
    assert not result.events
    assert result.annotations == tuple(annotations)
    explicit = _decode(annotations, numeric_codes=False, named_codes={"Faces": 200})
    assert [event.code for event in explicit.events] == [200]


def test_format_timekeeping_notes_and_mapping_spelling_are_preserved():
    annotations = (
        _annotation(0, 0, ""),
        _annotation(1, 0.003, "faces"),
        _annotation(2, 0.004, "Faces"),
    )
    result = _decode(annotations, numeric_codes=False, named_codes={"Faces": 255})
    assert result.annotations == annotations
    assert [(event.sample, event.code) for event in result.events] == [(1, 255)]


def test_decoder_definition_versions_are_explicit():
    status = decode_sample_status([55], sfreq=250)
    annotations = _decode([_annotation(0, 0, "55")])
    assert (status.decoder_id, status.decoder_version) == ("unicorn_sample", "1.0")
    assert (annotations.decoder_id, annotations.decoder_version) == ("explicit_annotations", "1.0")
    result = reconcile_event_sources(status, annotations, authority="reconcile")
    assert result.decoder_id == "unicorn_sample+explicit_annotations"
    assert result.decoder_version == "1.0+1.0"


def test_unmapped_declared_marker_requires_decision():
    with pytest.raises(RecordingEventError, match="no explicit code mapping"):
        _decode([_annotation(0, 0, "Faces")], marker_labels=("Faces",))


def test_conflicting_numeric_and_named_rules_fail():
    with pytest.raises(RecordingEventError, match="conflicting numeric and named"):
        _decode([_annotation(0, 0, "55")], named_codes={"55": 54})


@pytest.mark.parametrize("label", ["0", "256", "9999999999999999999999999"])
def test_numeric_labels_outside_protocol_range_fail(label):
    with pytest.raises(RecordingEventError):
        _decode([_annotation(0, 0, label)])


@pytest.mark.parametrize("code", [0, 256, 1.5, True, "55"])
def test_invalid_named_codes_fail_even_when_label_is_absent(code):
    with pytest.raises(RecordingEventError):
        _decode([], named_codes={"Faces": code})


@pytest.mark.parametrize("onset", [0.002, 0.006, 0.0041, -0.002, -0.00000000001, 4.0])
def test_offgrid_ties_negative_onsets_and_out_of_bounds_are_rejected(onset):
    with pytest.raises(RecordingEventError):
        _decode([_annotation(0, onset, "55")])


def test_numeric_tolerance_retains_residual_and_does_not_shift_native_sample():
    result = _decode([_annotation(0, 0.004000000000000001, "55")], first_samp=350)
    assert result.events[0].sample == 351
    assert 0 < result.events[0].quantization_residual_seconds < 1e-15


@pytest.mark.parametrize("annotations,match", [
    ([_annotation(0, 0.004, "55"), _annotation(1, 0.004, "1")], "collide"),
    ([_annotation(0, 0.004, "55"), _annotation(1, 0.008, "1"), _annotation(2, 0.004, "2")], "collide"),
    ([_annotation(1, 0.004, "55"), _annotation(0, 0.008, "1")], "source order"),
    ([_annotation(0, 0.004, "55"), _annotation(0, 0.008, "1")], "identities must be unique"),
])
def test_annotation_identity_and_order_are_not_silently_repaired(annotations, match):
    with pytest.raises(RecordingEventError, match=match):
        _decode(annotations)


def test_bdf_plus_delayed_annotation_storage_preserves_source_order_in_evidence():
    source = (_annotation(0, 0.008, "55"), _annotation(1, 0.004, "1"))
    result = _decode(source)
    assert result.annotations == source
    assert [(event.sample, event.code, event.source_order) for event in result.events] == [(1, 1, 1), (2, 55, 0)]
    status = decode_sample_status([0, 1, 55], sfreq=250)
    reconciled = reconcile_event_sources(status, result, authority="reconcile")
    np.testing.assert_array_equal(reconciled.as_mne_events(), [[1, 0, 1], [2, 0, 55]])
    assert reconciled.annotations == source


@pytest.mark.parametrize("annotation", [
    _annotation(0, float("nan"), "Note"),
    _annotation(0, 0, "Note", -1),
    _annotation(0, 0, "Note", float("inf")),
    _annotation(0, 3.996, "55", 0.008),
])
def test_invalid_annotation_times_and_marker_duration_bounds_fail(annotation):
    with pytest.raises(RecordingEventError):
        _decode([annotation])


def test_last_sample_with_duration_to_exclusive_end_is_valid():
    result = _decode([_annotation(0, 3.996, "55", 0.004)])
    assert result.events[0].sample == 999


@pytest.mark.parametrize("authority", ["status", "annotations", "reconcile"])
def test_matching_dual_sources_emit_one_sequence_and_keep_notes(authority):
    status = decode_sample_status([0, 55, 55, 1], sfreq=250, first_samp=100)
    annotations = _decode([
        _annotation(0, 0, "Note"), _annotation(1, 0.004, "55"),
        _annotation(2, 0.008, "55"), _annotation(3, 0.012, "1"),
    ], first_samp=100)
    result = reconcile_event_sources(status, annotations, authority=authority)
    assert len(result.events) == 3
    assert result.annotations == annotations.annotations
    assert result.authority == authority
    np.testing.assert_array_equal(result.as_mne_events(), status.as_mne_events())


@pytest.mark.parametrize("authority", ["status", "annotations", "reconcile"])
@pytest.mark.parametrize("changes", ["code", "sample", "missing"])
def test_conflicting_sources_fail_even_with_explicit_single_authority(authority, changes):
    status = decode_sample_status([0, 55, 1], sfreq=250)
    source = [_annotation(0, 0.004, "55"), _annotation(1, 0.008, "1")]
    if changes == "code":
        source[1] = replace(source[1], text="2")
    elif changes == "sample":
        source[1] = replace(source[1], onset_seconds=0.012)
    else:
        source.pop()
    with pytest.raises(RecordingEventError, match="conflict"):
        reconcile_event_sources(status, _decode(source), authority=authority)


def test_single_authority_allows_absent_other_source_but_never_falls_back():
    status = decode_sample_status([55], sfreq=250)
    annotations = _decode([_annotation(0, 0, "55")])
    assert reconcile_event_sources(status, None, authority="status") == status
    assert reconcile_event_sources(None, annotations, authority="annotations") == annotations
    with pytest.raises(RecordingEventError, match="absent"):
        reconcile_event_sources(None, annotations, authority="status")
    with pytest.raises(RecordingEventError, match="requires both"):
        reconcile_event_sources(status, None, authority="reconcile")


def test_notes_only_source_is_retained_without_becoming_markers():
    status = decode_sample_status([55], sfreq=250)
    notes = _decode([_annotation(0, 0.001, "Operator note")])
    result = reconcile_event_sources(status, notes, authority="status")
    assert result.events == status.events
    assert result.annotations == notes.annotations
    with pytest.raises(RecordingEventError, match="conflict"):
        reconcile_event_sources(status, notes, authority="reconcile")


def test_wrong_authority_and_swapped_source_arguments_fail():
    status = decode_sample_status([55], sfreq=250)
    with pytest.raises(RecordingEventError, match="authority"):
        reconcile_event_sources(status, None, authority="automatic")
    with pytest.raises(RecordingEventError, match="original decoded"):
        reconcile_event_sources(None, status, authority="annotations")


@pytest.mark.parametrize("kwargs", [{"first_samp": True}, {"first_samp": 1.5}, {"first_samp": 2**63}])
def test_invalid_sample_origins_fail(kwargs):
    with pytest.raises(RecordingEventError):
        decode_sample_status([55], sfreq=250, **kwargs)
