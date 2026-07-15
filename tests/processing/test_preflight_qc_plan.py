from __future__ import annotations

import numpy as np
import pytest

from Main_App.processing.preflight_qc_plan import (
    plan_preflight_qc_events,
    resolve_preflight_spectral_bounds,
)


def _events(*rows: tuple[int, int]) -> np.ndarray:
    return np.asarray([(sample, 0, code) for sample, code in rows], dtype=int)


def test_plan_uses_onset_to_configured_completion_and_locked_onbin_crop() -> None:
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
        epoch_end_s=125.0,
    )

    assert plan.n_step == 640
    assert [(span.time_start_sample, span.time_stop_sample) for span in plan.spans] == [
        (100, 32_100),
        (40_000, 72_000),
    ]
    assert [span.spectral_sample_count for span in plan.spans] == [640, 640]
    assert [(span.spectral_start_sample, span.spectral_stop_sample) for span in plan.spans] == [
        (300, 940),
        (40_200, 40_840),
    ]


def test_plan_clamps_condition_completion_to_next_onset_and_recording_end() -> None:
    plan = plan_preflight_qc_events(
        events=_events(
            (100, 1),
            (300, 55),
            (940, 55),
            (1_000, 2),
            (1_100, 55),
            (1_740, 55),
        ),
        event_map={"First": 1, "Second": 2},
        sfreq=256.0,
        n_times=2_000,
        epoch_end_s=125.0,
    )

    assert [(span.condition_label, span.time_start_sample, span.time_stop_sample) for span in plan.spans] == [
        ("First", 100, 1_000),
        ("Second", 1_000, 2_000),
    ]


def test_locked_crop_extends_completion_without_following_a_marker_gap() -> None:
    plan = plan_preflight_qc_events(
        events=_events(
            (100, 1),
            (300, 55),
            (940, 55),
            (5_000, 55),
            (10_000, 1),
            (10_200, 55),
            (10_840, 55),
        ),
        event_map={"Short": 1},
        sfreq=256.0,
        n_times=20_000,
        epoch_end_s=1.0,
    )

    first, second = plan.spans
    assert (first.time_start_sample, first.time_stop_sample) == (100, 940)
    assert (first.spectral_start_sample, first.spectral_stop_sample) == (300, 940)
    assert first.last_oddball_sample == 5_000
    assert first.spectral_fallback_reason is None
    assert (second.time_start_sample, second.time_stop_sample) == (10_000, 10_840)
    assert (
        "condition=1:rep=0:completion_extended_to_locked_spectral_span"
        in plan.warnings
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
        epoch_end_s=5.0,
    )
    second = plan_preflight_qc_events(
        events=reversed_events,
        event_map={"Condition": 1},
        sfreq=256.0,
        n_times=2_000,
        epoch_end_s=5.0,
    )

    assert second == first
    assert second.to_payload() == first.to_payload()


def test_plan_requires_at_least_one_configured_condition_onset() -> None:
    with pytest.raises(ValueError, match="No configured condition onset"):
        plan_preflight_qc_events(
            events=_events((100, 99), (200, 55)),
            event_map={"Condition": 1},
            sfreq=256.0,
            n_times=2_000,
            epoch_end_s=125.0,
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
