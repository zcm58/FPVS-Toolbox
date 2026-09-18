"""Review episodes preserve evidence identities without inventing artifact times."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from Main_App.processing.qc_review_episodes import group_review_episodes


def _finding(spans=(), **changes):
    values = {
        "recording_key": ("P1", "recording-1"),
        "source_path": "/project/p1.bdf",
        "condition": "Positive",
        "occurrence": "1",
        "time_spans_s": spans,
        "time_scope": "diagnostic_windows" if spans else "unlocalized",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_overlapping_findings_across_detectors_and_channels_share_episode():
    items = [
        _finding(((10, 20),), kind="Amplitude", channels="Oz"),
        _finding(((15, 25),), kind="Transient signals", channels="T7"),
        _finding(((24, 28),), kind="Channel quality", channels="Fz"),
    ]
    before = deepcopy(items)

    episodes = group_review_episodes(items)

    assert items == before
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.item_indices == (0, 1, 2)
    assert episode.time_spans_s == ((10.0, 28.0),)
    assert episode.source_path == "/project/p1.bdf"
    assert "review-interval coverage" in episode.timing_note
    assert "not validated artifact duration" in episode.timing_note
    assert "not independent confirmations" in episode.timing_note


@pytest.mark.parametrize("changes", [
    {"recording_key": ("P1", "recording-2")},
    {"source_path": "/project/other/p1.bdf"},
    {"condition": "Negative"},
    {"occurrence": "2"},
])
def test_overlapping_windows_never_cross_recording_condition_or_occurrence(changes):
    episodes = group_review_episodes([
        _finding(((10, 20),)), _finding(((12, 18),), **changes),
    ])
    assert [episode.item_indices for episode in episodes] == [(0,), (1,)]


def test_disjoint_spans_retain_one_finding_in_each_actual_episode():
    episodes = group_review_episodes([
        _finding(((10, 15), (80, 85))),
        _finding(((12, 14),)),
        _finding(((81, 83),)),
    ])
    assert [episode.time_spans_s for episode in episodes] == [((10.0, 15.0),), ((80.0, 85.0),)]
    assert [episode.item_indices for episode in episodes] == [(0, 1), (0, 2)]
    assert {index for episode in episodes for index in episode.item_indices} == {0, 1, 2}


def test_occurrence_summary_cannot_bridge_separate_transient_episodes():
    episodes = group_review_episodes([
        _finding(((0, 100),), time_scope="occurrence"),
        _finding(((10, 20),)),
        _finding(((70, 80),)),
        _finding((), kind="Kurtosis"),
    ])
    assert len(episodes) == 4
    assert episodes[0].time_scope == "occurrence"
    assert "do not locate an artifact" in episodes[0].timing_note
    assert [episode.item_indices for episode in episodes] == [(0,), (1,), (2,), (3,)]
    assert episodes[-1].start_seconds is None
    assert episodes[-1].end_seconds is None


def test_identical_occurrence_summaries_group_without_absorbing_transients():
    episodes = group_review_episodes([
        _finding(((0, 100),), time_scope="occurrence"),
        _finding(((0, 100),), time_scope="occurrence"),
        _finding(((10, 20),)),
    ])
    assert [episode.item_indices for episode in episodes] == [(0, 1), (2,)]
    assert episodes[0].time_scope == "occurrence"


def test_adjacent_half_open_windows_are_not_reported_as_overlapping():
    episodes = group_review_episodes([_finding(((0, 10),)), _finding(((10, 20),))])
    assert [episode.item_indices for episode in episodes] == [(0,), (1,)]


@pytest.mark.parametrize("spans", [
    ((float("nan"), 20),), ((0, float("inf")),), ((10, 10),),
    ((-1, 20),), ((True, 20),), ((0, 10, 20),), "10–20", ((0, "unknown"),),
    ((0, 5), (10, None)),
])
def test_invalid_time_metadata_remains_unlocalized_without_losing_findings(spans):
    item = _finding(spans, time_scope="diagnostic_windows")
    episode, = group_review_episodes([item])
    assert episode.item_indices == (0,)
    assert episode.time_spans_s == ()
    assert episode.time_scope == "unlocalized"
    assert "No localized interval" in episode.timing_note


def test_unknown_time_scope_does_not_turn_bounds_into_an_artifact_interval():
    episode, = group_review_episodes([_finding(((0, 100),), time_scope="unknown")])
    assert episode.time_spans_s == ()
    assert episode.item_indices == (0,)


def test_duplicate_findings_and_unlocalized_items_remain_individually_addressable():
    item = _finding(((1, 2),))
    episodes = group_review_episodes([item, item, _finding(), _finding()])
    assert [episode.item_indices for episode in episodes] == [(0, 1), (2,), (3,)]
    assert group_review_episodes([]) == ()
