from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui.signal_review_model import SignalReviewItem, episode_view_context, review_time_scope


def test_complete_evidence_and_export_row_are_preserved() -> None:
    evidence = (
        "T7 had a transient high amplitude flag in Positive, occurrence 2, "
        "across 9 overlapping diagnostic window(s). Reported coverage is the "
        "union of flagged windows, not measured artifact duration.\n"
        "Analyzed samples: [718565, 964325]. Category: low_variance."
    )
    row = ("P13", "Patient group", "p13.bdf", evidence)
    item = SignalReviewItem(
        row, "Transient signal", "High amplitude", "Positive", "2", "T7"
    )

    assert item.export_row == row
    assert item.details == evidence
    assert item.participant == "P13"
    assert item.group == "Patient group"
    assert item.source_file == "p13.bdf"
    assert (item.recording, item.session, item.visit) == ("", "", "")
    for term in ("patient group", "718565", "positive", "transient signal", "t7"):
        assert term in item.search_text


def test_recording_identity_keeps_session_visit_and_missing_labels() -> None:
    row = (
        "P13",
        "Not registered",
        "Missing session",
        "Missing visit",
        "Patient group",
        "p13.bdf",
        "Assessment unavailable.",
    )
    item = SignalReviewItem(row, "Assessment status", "Not assessed")

    assert item.export_row == row
    assert item.recording == "Not registered"
    assert item.session == "Missing session"
    assert item.visit == "Missing visit"
    assert item.group == "Patient group"
    assert item.source_file == "p13.bdf"
    for value in row[:-1]:
        assert value in item.recording_label
        assert value.casefold() in item.search_text


def test_same_participant_and_filename_do_not_merge_distinct_recordings() -> None:
    first = SignalReviewItem(
        ("P13", "recording-1", "Baseline", "1", "Patient", "p13.bdf", "Finding A"),
        "Channel signal",
        "Low variance",
    )
    second = SignalReviewItem(
        ("P13", "recording-2", "Follow-up", "2", "Patient", "p13.bdf", "Finding A"),
        "Channel signal",
        "Low variance",
    )
    same_recording = SignalReviewItem(
        (*first.export_row[:-1], "Finding B"), "Channel signal", "High amplitude"
    )

    assert first.recording_key != second.recording_key
    assert first.recording_label != second.recording_label
    assert first.recording_key == same_recording.recording_key


@pytest.mark.parametrize("column_count", (0, 3, 5, 6, 8))
def test_invalid_export_shape_is_rejected(column_count: int) -> None:
    with pytest.raises(ValueError, match="four or seven"):
        SignalReviewItem(("value",) * column_count, "Review item", "Finding")


def test_structured_evidence_is_snapshotted_and_searchable_without_changing_export():
    payload = {"flagged_window_union_spans": [[100, 200]], "authority": "review_only"}
    row = ("P13", "Patient", "p13.bdf", "Original complete details")
    item = SignalReviewItem(
        row, "Transient signals", "High amplitude", "Positive", "1", "Oz",
        source_path="/project/p13.bdf", time_spans_s=((1.0, 2.0),),
        time_scope="diagnostic_windows", evidence=payload,
    )
    payload["flagged_window_union_spans"][0][0] = 900
    assert item.evidence["flagged_window_union_spans"] == [[100, 200]]
    assert item.export_row == row
    assert item.details == row[-1]
    assert "review_only" in item.search_text
    assert "100" in item.search_text
    assert item.evidence_text.startswith(row[-1])


def test_distinct_source_paths_do_not_merge_identical_display_names():
    row = ("P13", "Patient", "p13.bdf", "Original complete details")
    first = SignalReviewItem(row, "Signal", "Review", source_path="/project/first/p13.bdf")
    second = SignalReviewItem(row, "Signal", "Review", source_path="/project/second/p13.bdf")
    assert first.recording_key != second.recording_key


def test_review_time_scope_uses_source_first_sample_and_preserves_disjoint_spans():
    event_plan = {"sfreq": 100.0, "first_samp": 1000, "n_times": 1000}
    finding = {"flagged_window_union_spans": [[1200, 1300], [1800, 1950]]}
    assert review_time_scope(finding, event_plan) == (
        ((2.0, 3.0), (8.0, 9.5)), "diagnostic_windows",
    )
    assert review_time_scope({"start_sample": 1000, "stop_sample": 2000}, event_plan) == (
        ((0.0, 10.0),), "occurrence",
    )


@pytest.mark.parametrize("finding", [
    {"analyzed_duration_s": 10, "occurrence_display": 1},
    {"diagnostic_window_count": 4},
    {"start_sample": 999, "stop_sample": 1200},
    {"start_sample": 1100, "stop_sample": 2001},
    {"start_sample": 1100, "stop_sample": 1100},
    {"start_sample": 1100.5, "stop_sample": 1200},
    {"start_sample": True, "stop_sample": 1200},
    {"flagged_window_union_spans": [[1100, 1200], [1300, None]]},
    {"flagged_window_union_spans": [], "start_sample": 1000, "stop_sample": 2000},
])
def test_review_time_scope_never_invents_bounds_for_incomplete_or_invalid_evidence(finding):
    assert review_time_scope(finding, {"sfreq": 100, "first_samp": 1000, "n_times": 1000}) == (
        (), "unlocalized",
    )


@pytest.mark.parametrize("event_plan", [
    None, {}, {"sfreq": 100, "first_samp": 0},
    {"sfreq": 0, "first_samp": 0, "n_times": 1000},
    {"sfreq": float("nan"), "first_samp": 0, "n_times": 1000},
    {"sfreq": True, "first_samp": 0, "n_times": 1000},
    {"sfreq": 100, "first_samp": 0, "n_times": 0},
])
def test_review_time_scope_requires_a_complete_source_timebase(event_plan):
    assert review_time_scope({"start_sample": 100, "stop_sample": 200}, event_plan) == (
        (), "unlocalized",
    )


def _context_plan():
    return {
        "sfreq": 1000.0, "first_samp": 1000, "n_times": 100000,
        "spans": [{"condition_label": "Faces", "repetition_index": 0,
                   "time_start_sample": 11000, "time_stop_sample": 51000}],
    }


def _episode(spans=((30.0, 30.02),), *, condition="Faces", occurrence="1"):
    return SimpleNamespace(time_spans_s=spans, condition=condition, occurrence=occurrence)


def test_short_episode_opens_full_analyzed_occurrence_with_one_second_of_context():
    assert episode_view_context(_episode(), _context_plan()) == (
        ((10.0, 50.0),), ("Faces · occurrence 1",), 29.0, 0,
    )


@pytest.mark.parametrize(("spans", "expected_start"), [
    (((10.2, 10.22),), 10.0),
    (((10.0, 10.02),), 10.0),
    (((49.98, 50.0),), 48.98),
    (((12.0, 12.02), (32.0, 32.02)), 11.0),
])
def test_episode_context_never_starts_before_the_analyzed_interval(spans, expected_start):
    bounds, labels, start, index = episode_view_context(_episode(spans), _context_plan())
    assert bounds == ((10.0, 50.0),)
    assert labels == ("Faces · occurrence 1",)
    assert start == pytest.approx(expected_start)
    assert index == 0


def test_episode_context_matches_condition_and_one_based_occurrence_when_intervals_overlap():
    plan = _context_plan()
    plan["spans"].extend((
        {"condition_label": "Objects", "repetition_index": 0,
         "time_start_sample": 11000, "time_stop_sample": 51000},
        {"condition_label": "Faces", "repetition_index": 1,
         "time_start_sample": 21000, "time_stop_sample": 61000},
    ))
    assert episode_view_context(_episode(), plan) == (
        ((10.0, 50.0),), ("Faces · occurrence 1",), 29.0, 0,
    )
    assert episode_view_context(_episode(occurrence="2"), plan) == (
        ((20.0, 60.0),), ("Faces · occurrence 2",), 29.0, 0,
    )
    assert episode_view_context(_episode(condition="Objects"), plan) == (
        ((10.0, 50.0),), ("Objects · occurrence 1",), 29.0, 0,
    )


@pytest.mark.parametrize(("condition", "occurrence"), [
    ("", ""), ("", "1"), ("Faces", ""), ("Other condition", "1"),
    ("Faces", "3"), ("Faces", "invalid"), ("Faces", "0"), ("Faces", True),
])
def test_ambiguous_or_mismatched_episode_identity_keeps_original_intervals(condition, occurrence):
    plan = _context_plan()
    plan["spans"].extend((
        {"condition_label": "Objects", "repetition_index": 0,
         "time_start_sample": 11000, "time_stop_sample": 51000},
        {"condition_label": "Faces", "repetition_index": 1,
         "time_start_sample": 11000, "time_stop_sample": 51000},
    ))
    assert episode_view_context(_episode(condition=condition, occurrence=occurrence), plan) == (
        ((30.0, 30.02),), ("Review interval 1",), 30.0, 0,
    )


def test_no_occurrence_identity_can_use_only_one_unambiguous_containing_interval():
    assert episode_view_context(_episode(condition="", occurrence=""), _context_plan()) == (
        ((10.0, 50.0),), ("Faces · occurrence 1",), 29.0, 0,
    )


def test_episode_context_does_not_bridge_separate_analyzed_occurrences():
    plan = _context_plan()
    plan["spans"].append({
        "condition_label": "Faces", "repetition_index": 1,
        "time_start_sample": 71000, "time_stop_sample": 91000,
    })
    spans = ((30.0, 30.02), (80.0, 80.02))
    assert episode_view_context(_episode(spans, occurrence=""), plan) == (
        spans, ("Review interval 1", "Review interval 2"), 30.0, 0,
    )


@pytest.mark.parametrize("plan_change", [
    {"sfreq": 0}, {"sfreq": float("nan")}, {"first_samp": -1}, {"n_times": 100},
    {"spans": None}, {"spans": "not spans"}, {"spans": []},
    {"spans": [{"condition_label": "Faces", "repetition_index": 0,
                "time_start_sample": 0, "time_stop_sample": 51000}]},
    {"spans": [{"condition_label": "Faces", "repetition_index": 0,
                "time_start_sample": 11000, "time_stop_sample": 101001}]},
    {"spans": [{"condition_label": "Faces", "repetition_index": 0,
                "time_start_sample": 11000, "time_stop_sample": None}]},
])
def test_invalid_context_plan_does_not_invent_or_expand_time_bounds(plan_change):
    plan = {**_context_plan(), **plan_change}
    assert episode_view_context(_episode(), plan) == (
        ((30.0, 30.02),), ("Review interval 1",), 30.0, 0,
    )


@pytest.mark.parametrize("spans", [
    (), None, "30,31", ((30, None),), ((31, 30),), ((-1, 1),),
    ((True, 2),), ((30, float("inf")),), ((float("nan"), 31),),
])
def test_unlocalized_or_malformed_episode_never_acquires_invented_context(spans):
    assert episode_view_context(_episode(spans), _context_plan()) == ((), (), None, 0)


@pytest.mark.parametrize("timing", [
    {"flagged_window_union_spans": [[999, 1200]]},
    {"flagged_window_union_spans": []},
    {"start_sample": 999, "stop_sample": 1200},
    {"start_sample": 1100},
])
def test_actual_workflow_row_adapter_keeps_invalid_explicit_spectral_times_unlocalized(timing):
    # Extract only the widget-neutral nested adapter; importing the workflow
    # would require Qt. This executes its real source with inert display labels.
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/preprocessing_qc_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if getattr(node, "name", "") == "_remaining_review_rows")
    append = next(node for node in owner.body if getattr(node, "name", "") == "append_row")
    payload_list = next(node for node in tree.body if getattr(node, "name", "") == "_payload_list")
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        payload_list, append,
    ], type_ignores=[])
    items = []
    namespace = {
        "Mapping": Mapping, "Sequence": Sequence, "SignalReviewItem": SignalReviewItem,
        "review_time_scope": review_time_scope, "recording_mode": False,
        "rows": [], "review_items": items, "labels": {},
        "_result_group_display_name": lambda *_args: "Group",
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    plan = {"sfreq": 100.0, "first_samp": 1000, "n_times": 1000,
            "spans": [{"condition_label": "Faces", "repetition_index": 0,
                       "time_start_sample": 1000, "time_stop_sample": 2000}]}
    finding = dict(condition_label="Faces", occurrence=0, occurrence_display=1, channel="P8", **timing)
    result = SimpleNamespace(path=Path("source.bdf"), participant_id="P1", condition_qc={"event_plan": plan})
    namespace["append_row"](result, "Full evidence", kind="Spectral", finding=finding)
    assert items[0].time_spans_s == ()
    assert items[0].time_scope == "unlocalized"
    assert items[0].evidence == finding
