"""Planned windows resolve one exact target independent of observed duration."""

from fractions import Fraction

import numpy as np
import pytest

from Main_App.projects.analysis_window import AnalysisWindow, AnalysisWindowError
from Main_App.projects.frequency_protocol import FrequencyProtocol, FrequencyProtocolError
from Main_App.processing.marker_integrity import build_marker_integrity_plan


def _protocol(base=6, every=5):
    return FrequencyProtocol.from_recurrence(base, every)


@pytest.mark.parametrize("base,every,duration,sources,target,cycles", [
    (6, 5, 120, (2048,), 256, 144),
    (6, 5, 60, (512,), 256, 72),
    (6, 5, "121.5", (2048,), 300, 144),
    (6, 5, "122.5", (2048,), 300, 147),
    (3, 10, 60, (500,), 256, 18),
    (8, 2, "36.25", (250,), 256, 144),
    (10, 2, "29", (250,), 256, 145),
    (10, 2, "29", (250,), 200, 145),
    (6, 5, 120, (Fraction(256, 3),), 256, 144),
])
def test_duration_is_exact_on_original_and_effective_target_grids(
    base, every, duration, sources, target, cycles,
):
    protocol = _protocol(base, every).with_analyzed_duration(
        duration, target_sampling_rate_hz=target, source_sampling_rates_hz=sources,
    )
    assert protocol.expected_analyzed_oddball_cycles == cycles
    for grid in protocol.analysis_window.sampling_rates_hz:
        assert protocol.expected_analyzed_samples(grid) > 0
    assert protocol.derived_analyzed_seconds <= Fraction(duration)
    restored = FrequencyProtocol.from_manifest(protocol.to_manifest())
    assert restored == protocol
    assert restored.fingerprint == protocol.fingerprint


def test_source_rate_resolution_keeps_the_original_planned_bound():
    initial = _protocol(8, 2).with_studio_window(145, target_sampling_rate_hz=256)
    resolved = initial.resolve_analysis_window(
        target_sampling_rate_hz=256, source_sampling_rates_hz=(250,),
    )
    assert initial.expected_analyzed_oddball_cycles == 145
    assert resolved.expected_analyzed_oddball_cycles == 144
    assert resolved.analysis_window.maximum_oddball_cycles == 145
    assert resolved.analysis_window.sampling_rates_hz == (Fraction(250),)
    assert initial.fingerprint != resolved.fingerprint


def test_one_target_uses_every_source_grid_and_is_order_independent():
    initial = _protocol(8, 2).with_studio_window(145, target_sampling_rate_hz=256)
    first = initial.resolve_analysis_window(
        target_sampling_rate_hz=256, source_sampling_rates_hz=(256, 250),
    )
    second = initial.resolve_analysis_window(
        target_sampling_rate_hz=256, source_sampling_rates_hz=(250, 256, 250),
    )
    assert first.expected_analyzed_oddball_cycles == 144
    assert first.fingerprint == second.fingerprint


def test_advanced_count_override_removes_automatic_policy():
    automatic = _protocol().with_analyzed_duration(120, target_sampling_rate_hz=256)
    fixed = automatic.with_expected_cycles(72, source="manual")
    assert fixed.analysis_window is None
    assert fixed.version == "1.1.0"
    assert fixed.resolve_analysis_window(
        target_sampling_rate_hz=300, source_sampling_rates_hz=(250,),
    ) is fixed


def test_window_policy_coexists_with_marker_schemas():
    protocol = _protocol().with_studio_window(145, target_sampling_rate_hz=256)
    protocol = protocol.with_condition_oddball_marker_codes({1: 55})
    protocol = protocol.with_recording_oddball_marker_codes({"P1": {1: 55}})
    assert protocol.version == "1.4.0"
    assert FrequencyProtocol.from_manifest(protocol.to_manifest()) == protocol
    fixed = protocol.with_expected_cycles(72, source="manual")
    assert fixed.version == "1.3.0"
    assert fixed.recording_oddball_marker_codes == protocol.recording_oddball_marker_codes


@pytest.mark.parametrize("duration", [True, "", "NaN", "inf", -1, 0, "0.1"])
def test_unusable_duration_fails(duration):
    with pytest.raises(FrequencyProtocolError):
        _protocol().with_analyzed_duration(duration, target_sampling_rate_hz=256)


@pytest.mark.parametrize("field,value", [
    ("expected_analyzed_oddball_cycles", 147),
    ("expected_analyzed_oddball_cycles_source", "manual"),
    ("version", "1.1.0"),
    ("status", "incomplete"),
    ("analysis_window", {}),
    ("analysis_window", []),
])
def test_tampered_window_provenance_is_rejected(field, value):
    payload = _protocol().with_studio_window(145, target_sampling_rate_hz=256).to_manifest()
    payload[field] = value
    with pytest.raises(FrequencyProtocolError):
        FrequencyProtocol.from_manifest(payload)


def test_policy_rejects_unknown_fields_and_malformed_modes():
    payload = _protocol().with_studio_window(145, target_sampling_rate_hz=256).analysis_window.to_manifest()
    payload["mode"] = []
    with pytest.raises(AnalysisWindowError):
        AnalysisWindow.from_manifest(payload)
    payload["mode"] = "studio_planned"
    payload["unexpected"] = 1
    with pytest.raises(AnalysisWindowError):
        AnalysisWindow.from_manifest(payload)


def test_short_recording_does_not_shrink_the_planned_target():
    protocol = _protocol().with_studio_window(145, target_sampling_rate_hz=256)
    # Only 73 marker boundaries: 72 observed cycles versus the planned 144.
    events = np.asarray([[0, 0, 1], *[[100 + round(i * 256 / 1.2), 0, 55] for i in range(73)]])
    plan = build_marker_integrity_plan(
        events=events, sampling_rate_hz=256, first_samp=0,
        n_times=20000, event_map={"Faces": 1}, protocol=protocol,
    )
    assert plan.occurrences[0].requires_review
    assert "shorter_than_expected_analyzed_cycles" in plan.occurrences[0].review_reasons
    assert protocol.expected_analyzed_oddball_cycles == 144
    assert plan.occurrences[0].proposed_stop_sample is None
