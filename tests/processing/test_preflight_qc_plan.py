from __future__ import annotations

import numpy as np
import pytest

from Main_App.processing.preflight_qc_plan import (
    plan_preflight_qc_events,
    resolve_preflight_spectral_bounds,
)
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol


def _protocol(cycles: int = 3) -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=cycles,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _events(*rows: tuple[int, int]) -> np.ndarray:
    return np.asarray([(sample, 0, code) for sample, code in rows], dtype=int)


def test_plan_uses_locked_onbin_crop_for_time_and_spectral_qc() -> None:
    events = _events(
        (100, 1),
        (300, 55),
        (513, 55),
        (727, 55),
        (940, 55),
        (40_000, 1),
        (40_200, 55),
        (40_413, 55),
        (40_627, 55),
        (40_840, 55),
    )

    plan = plan_preflight_qc_events(
        events=events,
        event_map={"Faces": 1},
        sfreq=256.0,
        n_times=100_000,
        frequency_protocol=_protocol(),
    )

    assert plan.n_step == 640
    assert [(span.time_start_sample, span.time_stop_sample) for span in plan.spans] == [
        (300, 940),
        (40_200, 40_840),
    ]
    assert [span.spectral_sample_count for span in plan.spans] == [640, 640]
    assert [(span.spectral_start_sample, span.spectral_stop_sample) for span in plan.spans] == [
        (300, 940),
        (40_200, 40_840),
    ]


def test_plan_excludes_onset_lead_in_and_post_crop_samples() -> None:
    plan = plan_preflight_qc_events(
        events=_events(
            (100, 1),
            (300, 55),
            (513, 55),
            (727, 55),
            (940, 55),
            (1_000, 2),
            (1_100, 55),
            (1_313, 55),
            (1_527, 55),
            (1_740, 55),
        ),
        event_map={"First": 1, "Second": 2},
        sfreq=256.0,
        n_times=2_000,
        frequency_protocol=_protocol(),
    )

    assert [(span.condition_label, span.time_start_sample, span.time_stop_sample) for span in plan.spans] == [
        ("First", 300, 940),
        ("Second", 1_100, 1_740),
    ]


def test_marker_gap_pauses_only_the_affected_occurrence() -> None:
    plan = plan_preflight_qc_events(
        events=_events(
            (100, 1),
            (300, 55),
            (940, 55),
            (5_000, 55),
            (10_000, 1),
            (10_200, 55),
            (10_413, 55),
            (10_627, 55),
            (10_840, 55),
        ),
        event_map={"Short": 1},
        sfreq=256.0,
        n_times=20_000,
        frequency_protocol=_protocol(),
    )

    assert len(plan.unresolved_occurrences) == 1
    assert plan.unresolved_occurrences[0]["condition_code"] == 1
    assert plan.unresolved_occurrences[0]["repetition_index"] == 0
    assert plan.unresolved_occurrences[0]["review_reasons"] == [
        "missing_marker_gap"
    ]
    assert len(plan.spans) == 1
    assert (plan.spans[0].time_start_sample, plan.spans[0].time_stop_sample) == (
        10_200,
        10_840,
    )


def test_plan_is_deterministic_for_unsorted_event_input() -> None:
    sorted_events = _events(
        (100, 1),
        (300, 55),
        (513, 55),
        (727, 55),
        (940, 55),
    )
    reversed_events = sorted_events[::-1]

    first = plan_preflight_qc_events(
        events=sorted_events,
        event_map={"Condition": 1},
        sfreq=256.0,
        n_times=2_000,
        frequency_protocol=_protocol(),
    )
    second = plan_preflight_qc_events(
        events=reversed_events,
        event_map={"Condition": 1},
        sfreq=256.0,
        n_times=2_000,
        frequency_protocol=_protocol(),
    )

    assert second == first
    assert second.to_payload() == first.to_payload()


@pytest.mark.parametrize("duration_s", [30.0, 90.0, 180.0])
def test_plan_accepts_arbitrary_marker_derived_onbin_durations(
    duration_s: float,
) -> None:
    sfreq = 256.0
    start = 300
    n_samples = int(duration_s * sfreq)
    cycles = int(duration_s * 1.2)
    marker_samples = [
        start + round(index * sfreq / 1.2)
        for index in range(cycles + 1)
    ]

    plan = plan_preflight_qc_events(
        events=_events((100, 1), *((sample, 55) for sample in marker_samples)),
        event_map={"Condition": 1},
        sfreq=sfreq,
        n_times=start + n_samples + 1_000,
        frequency_protocol=_protocol(cycles),
    )

    assert len(plan.spans) == 1
    span = plan.spans[0]
    assert span.time_sample_count == n_samples
    assert span.spectral_sample_count == n_samples
    assert (span.time_start_sample, span.time_stop_sample) == (
        span.spectral_start_sample,
        span.spectral_stop_sample,
    )


def test_plan_returns_unresolved_marker_evidence_instead_of_crossing_it() -> None:
    plan = plan_preflight_qc_events(
        events=_events((100, 1), (300, 55)),
        event_map={"Condition": 1},
        sfreq=256.0,
        n_times=2_000,
        frequency_protocol=_protocol(),
    )

    assert plan.spans == ()
    assert plan.unresolved_occurrences[0]["review_reasons"] == [
        "insufficient_project_oddball_markers"
    ]


def test_plan_hard_fails_when_sampling_rate_has_no_exact_declared_grid() -> None:
    with pytest.raises(ValueError, match="incompatible with the sampling-rate grid"):
        plan_preflight_qc_events(
            events=_events((100, 1), (300, 55), (940, 55)),
            event_map={"Condition": 1},
            sfreq=256.5,
            n_times=2_000,
            frequency_protocol=_protocol(),
        )


def test_plan_tolerates_configured_condition_absent_from_recording() -> None:
    plan = plan_preflight_qc_events(
        events=_events(
            (100, 1),
            (300, 55),
            (513, 55),
            (727, 55),
            (940, 55),
        ),
        event_map={"Present": 1, "Absent": 2},
        sfreq=256.0,
        n_times=2_000,
        frequency_protocol=_protocol(),
    )

    assert [span.condition_label for span in plan.spans] == ["Present"]
    assert "condition=2:missing_onset" in plan.warnings


def test_plan_requires_at_least_one_configured_condition_onset() -> None:
    with pytest.raises(ValueError, match="No configured condition onset"):
        plan_preflight_qc_events(
            events=_events((100, 99), (200, 55)),
            event_map={"Condition": 1},
            sfreq=256.0,
            n_times=2_000,
            frequency_protocol=_protocol(),
        )


@pytest.mark.parametrize(
    ("settings", "source_sfreq", "expected"),
    [
        ({"low_pass": 50.0, "downsample": 256}, 2_048.0, (0.0, 50.0)),
        ({"high_pass": 1.0, "low_pass": 100.0, "downsample": 256}, 2_048.0, (1.0, 100.0)),
        ({"high_pass": 1.0, "low_pass": 200.0, "downsample": 256}, 2_048.0, (1.0, 128.0)),
        ({"high_pass": 0.5, "low_pass": None, "downsample": 256}, 200.0, (0.5, 100.0)),
    ],
)
def test_spectral_bounds_follow_filter_limit_and_256_hz_target_nyquist(
    settings: dict[str, float | int | None],
    source_sfreq: float,
    expected: tuple[float, float],
) -> None:
    assert resolve_preflight_spectral_bounds(
        settings,
        source_sfreq=source_sfreq,
    ) == expected
