"""No EEG reads or Qt execution: native approved plans and synthetic geometry."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers import processing_resource_budget as budget
from Main_App.workers.review_resource_budget import ReviewGeometry

pytestmark = pytest.mark.processing


@pytest.fixture
def case(tmp_path: Path, monkeypatch):
    path = tmp_path / "P1.bdf"
    protocol = FrequencyProtocol.from_recurrence(
        6, 3, expected_analyzed_oddball_cycles=4,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    events = np.asarray([[0, 0, 1], [10, 0, 55], [16, 0, 55],
                         [22, 0, 55], [28, 0, 55], [34, 0, 55]], dtype=int)
    event_map = {"Faces": 1}
    plan = plan_preflight_qc_events(
        events=events, event_map=event_map, sfreq=12, n_times=1_000_000,
        first_samp=0, frequency_protocol=protocol,
    ).to_payload()
    geometry = ReviewGeometry(67, 65, 64, 1_000_000, 12, 6, 67 * 12 * 3, 12)
    monkeypatch.setattr(budget, "_supported_runtime", lambda: True)
    monkeypatch.setattr(budget, "read_review_geometry", lambda _path, _settings: geometry)
    settings = {"frequency_protocol": protocol, "downsample_rate": 6, "line_noise_filter_enabled": False,
                "_fpvs_preflight_event_plans_by_file": {str(path.resolve()): plan}}
    return path, settings, event_map, geometry


def _estimate(case):
    result = budget.build_processing_estimate(*case[:3])
    assert result is not None
    return result


def test_native_plan_supports_target_and_source_rate_fallback(case):
    result = _estimate(case)
    assert result.healthy_bytes >= result.tail_bytes(65, 500_000, 6)
    assert result.fullrate_bytes >= result.tail_bytes(65, 1_000_000, 12)
    assert result.emergency_extra_bytes > 0
    assert result.fullrate_bytes == result.healthy_bytes + result.emergency_extra_bytes


def test_cache_publication_is_covered_before_tail_barrier(case):
    result = _estimate(case)
    phases = dict(result.components)
    assert result.healthy_bytes >= phases["target_cache"]
    assert result.fullrate_bytes >= phases["source_cache"]
    assert phases["source_cache"] > phases["target_cache"]


def test_storage_mode_does_not_assume_memmaps_are_nonresident(case):
    path, settings, event_map, _geometry = case
    settings["experimental_ram_preload"] = False
    off = budget.build_processing_estimate(path, settings, event_map)
    settings["experimental_ram_preload"] = True
    on = budget.build_processing_estimate(path, settings, event_map)
    assert off is not None and on is not None
    assert (off.healthy_bytes, off.emergency_extra_bytes) == (on.healthy_bytes, on.emergency_extra_bytes)


def test_default_enabled_notch_has_explicit_whole_source_prefix(case):
    disabled = _estimate(case)
    case[1].pop("line_noise_filter_enabled")
    enabled = _estimate(case)
    notch = dict(enabled.components)["fft_notch"]
    assert notch > 8 * case[3].loaded_channels * case[3].source_n_times
    assert enabled.healthy_bytes >= notch
    assert enabled.healthy_bytes > disabled.healthy_bytes


def test_notch_workspace_uses_recording_not_short_approved_window(case):
    result = _estimate(case)
    ordinary = budget._notch_prefix_bytes(result.geometry)
    doubled = budget._notch_prefix_bytes(replace(result.geometry, source_n_times=2_000_000))
    assert doubled > ordinary
    assert ordinary > result.tail_bytes(65, 500_000, 6)


@pytest.mark.parametrize("index,replacement", [
    (0, "pypy"), (1, (3, 14)), (2, "1.10.0"), (3, "2.4.0"),
    (4, "1.17.0"), (5, "2.4.0"),
])
def test_changed_native_allocation_runtime_is_not_characterized(monkeypatch, index, replacement):
    signature = list(budget._SUPPORTED_RUNTIME)
    signature[index] = replacement
    monkeypatch.setattr(budget, "_runtime_signature", lambda: tuple(signature))
    assert budget._supported_runtime() is False


def test_characterized_runtime_signature_is_accepted(monkeypatch):
    monkeypatch.setattr(budget, "_runtime_signature", lambda: budget._SUPPORTED_RUNTIME)
    assert budget._supported_runtime() is True


def test_unknown_runtime_uses_exclusive_native_route_before_header_read(case, monkeypatch):
    monkeypatch.setattr(budget, "_supported_runtime", lambda: False)

    def forbidden(*_args):
        raise AssertionError("Unknown runtime must not inspect BDF geometry")

    monkeypatch.setattr(budget, "read_review_geometry", forbidden)
    assert budget.build_processing_estimate(*case[:3]) is None


def test_source_plan_and_settings_are_not_mutated(case):
    before = copy.deepcopy(case[1])
    result = _estimate(case)
    result.tail_bytes(65, 500_000, 6)
    assert case[1] == before


def test_repairs_are_reserved_before_kurtosis_tail_transition(case):
    ordinary = _estimate(case)
    case[1]["_fpvs_condition_interpolation_requests"] = [{"condition_label": "Faces", "channels": ["P9"]}]
    repaired = _estimate(case)
    phases = dict(repaired.components)
    assert phases["target_repairs"] > 0
    assert phases["source_repairs"] > phases["target_repairs"]
    assert repaired.healthy_bytes >= phases["target_repairs"]
    assert repaired.fullrate_bytes >= phases["source_repairs"]
    assert repaired.healthy_bytes >= ordinary.healthy_bytes


def test_occurrence_storage_retains_multiplicity_instead_of_union(case):
    result = _estimate(case)
    # Stress the credit calculation directly with coincident storage requests.
    # Native marker approval remains a separate, unchanged producer contract.
    repeated = replace(result, source_spans=result.source_spans * 50_000)
    assert repeated.tail_bytes(65, 500_000, 6) > result.tail_bytes(65, 500_000, 6)


def test_multiple_conditions_retain_all_epochs(case):
    result = _estimate(case)
    many = replace(result, source_spans=tuple((f"C{index}", 10, 24) for index in range(20_000)))
    assert many.tail_bytes(65, 500_000, 6) > result.tail_bytes(65, 500_000, 6)


@pytest.mark.parametrize("shape", [
    (64, 500_000, 6), (66, 500_000, 6), (65, 1_000_001, 6),
    (65, 999_999, 12), (65, 500_000, 5), (65, 500_000, 24),
    (65, 0, 6), (True, 500_000, 6), (65, True, 6),
    (65, 500_000, True), (65, 500_000, float("nan")),
])
def test_uncharacterized_actual_raw_shapes_reject_before_allocation(case, shape):
    with pytest.raises(ValueError):
        _estimate(case).tail_bytes(*shape)


def test_integral_duration_and_actual_mapped_extent_are_checked(case):
    result = _estimate(case)
    fractional = replace(result, source_spans=(("Faces", 10, 25),))
    with pytest.raises(ValueError, match="integral"):
        fractional.tail_bytes(65, 500_000, 6)
    outside = replace(result, source_spans=(("Faces", 999_990, 24),))
    with pytest.raises(ValueError, match="exceeds"):
        outside.tail_bytes(65, 500_000, 6)


def test_actual_rounded_target_count_is_used_for_window_mapping(case):
    result = _estimate(case)
    assert result.tail_bytes(65, 499_999, 6) <= result.fullrate_bytes


def test_unknown_header_route_returns_exclusive_sentinel(case, monkeypatch):
    monkeypatch.setattr(budget, "read_review_geometry", lambda *_args: None)
    assert budget.build_processing_estimate(*case[:3]) is None


def test_noncanonical_retained_channel_route_is_not_inferred(case, monkeypatch):
    geometry = replace(case[3], retained_channels=66)
    monkeypatch.setattr(budget, "read_review_geometry", lambda *_args: geometry)
    assert budget.build_processing_estimate(*case[:3]) is None


def test_stale_protocol_and_event_map_select_native_fallback(case):
    path, settings, event_map, _geometry = case
    assert budget.build_processing_estimate(path, settings, {"Objects": 1}) is None
    settings["frequency_protocol"] = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=4,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    assert budget.build_processing_estimate(path, settings, event_map) is None


def test_header_must_match_approved_source_grid(case, monkeypatch):
    monkeypatch.setattr(budget, "read_review_geometry", lambda *_args: replace(case[3], source_n_times=999_999))
    assert budget.build_processing_estimate(*case[:3]) is None


def test_missing_native_plan_is_not_replaced_by_duration_guess(case):
    case[1].pop("_fpvs_preflight_event_plans_by_file")
    assert budget.build_processing_estimate(*case[:3]) is None


def test_raw_health_statistics_remain_reserved_with_auto_detector_disabled(case, monkeypatch):
    native = budget.estimate_review_memory
    observed = []

    def inspect(geometry, **kwargs):
        observed.append(kwargs)
        return native(geometry, **kwargs)

    monkeypatch.setattr(budget, "estimate_review_memory", inspect)
    case[1]["auto_detect_removed_electrodes"] = False
    _estimate(case)
    assert observed[0]["raw_qc_enabled"] is True
    assert observed[0]["raw_union_samples"] == 24


def test_long_export_identity_and_condition_labels_use_native_fallback(case):
    path, settings, event_map, _geometry = case
    assert budget.build_processing_estimate(path, settings, {"C" * 257: 1}) is None
    settings["_fpvs_recording_id_by_file"] = {str(path.resolve()): "P" * 257}
    assert budget.build_processing_estimate(path, settings, event_map) is None


@pytest.mark.parametrize("payload", [object(), lambda: None, np.zeros(1), float("inf")])
def test_custom_or_unbounded_metadata_uses_exclusive_native_route(case, payload):
    case[1]["custom"] = payload
    assert budget.build_processing_estimate(*case[:3]) is None


def test_cyclic_metadata_uses_exclusive_native_route(case):
    case[1]["cyclic"] = case[1]
    assert budget.build_processing_estimate(*case[:3]) is None


def test_metadata_growth_and_source_size_increase_credits(case):
    ordinary = _estimate(case)
    case[1]["review_notes"] = "reviewed " * 50_000
    larger = _estimate(case)
    assert larger.metadata_bytes > ordinary.metadata_bytes
    assert larger.healthy_bytes > ordinary.healthy_bytes


def test_plain_metadata_credit_rejects_cycles_and_preserves_input():
    value = {"conditions": ["Faces", "Objects"], "reviewed": True}
    before = copy.deepcopy(value)
    assert budget.plain_metadata_bytes(value) > budget.plain_metadata_bytes({"reviewed": True})
    assert value == before
    value["cycle"] = value
    with pytest.raises(ValueError, match="Cyclic"):
        budget.plain_metadata_bytes(value)


def test_estimator_does_not_probe_installed_ram_or_choose_worker_tiers(case, monkeypatch):
    from Main_App.workers import review_resource_budget

    def forbidden():
        raise AssertionError("Per-file geometry must not cache current host availability")

    monkeypatch.setattr(review_resource_budget, "probe_memory_snapshot", forbidden)
    assert _estimate(case).healthy_bytes > 0
