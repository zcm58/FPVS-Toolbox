"""Exact characterization against the pre-shortcut connected-component engine."""

from __future__ import annotations

import dataclasses
import struct
import sys
import warnings
from collections.abc import Sequence

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering import analysis


def _baseline_groups(
    active: np.ndarray,
    *,
    spatial_edges: Sequence[tuple[int, int]],
    active_nodes: np.ndarray | None = None,
) -> tuple[list[int], ...]:
    """Frozen implementation from 164e6dce; keep its operation and node order."""
    sensor_count, harmonic_count = active.shape
    node_count = sensor_count * harmonic_count
    parent = np.full(node_count, -1, dtype=np.int64)
    rank = np.zeros(node_count, dtype=np.uint8)
    nodes = np.flatnonzero(active.reshape(-1)) if active_nodes is None else active_nodes
    parent[nodes] = nodes

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = int(parent[root])
        while parent[node] != node:
            next_node = int(parent[node])
            parent[node] = root
            node = next_node
        return root

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1

    for sensor in range(sensor_count):
        harmonics = np.flatnonzero(active[sensor])
        if harmonics.size > 1:
            first = sensor * harmonic_count + int(harmonics[0])
            for harmonic in harmonics[1:]:
                union(first, sensor * harmonic_count + int(harmonic))

    for left_sensor, right_sensor in spatial_edges:
        shared_harmonics = np.flatnonzero(np.logical_and(active[left_sensor], active[right_sensor]))
        for harmonic in shared_harmonics:
            harmonic_index = int(harmonic)
            union(
                left_sensor * harmonic_count + harmonic_index,
                right_sensor * harmonic_count + harmonic_index,
            )

    grouped: dict[int, list[int]] = {}
    for node in nodes:
        node_index = int(node)
        grouped.setdefault(find(node_index), []).append(node_index)
    return tuple(grouped.values())


def _assert_exact(expected: object, actual: object) -> None:
    assert type(actual) is type(expected)
    if isinstance(expected, np.ndarray):
        assert (actual.dtype, actual.shape, actual.strides) == (expected.dtype, expected.shape, expected.strides)
        assert (actual.flags.c_contiguous, actual.flags.f_contiguous, actual.flags.writeable) == (
            expected.flags.c_contiguous, expected.flags.f_contiguous, expected.flags.writeable
        )
        assert actual.tobytes(order="A") == expected.tobytes(order="A")
    elif dataclasses.is_dataclass(expected):
        for field in dataclasses.fields(expected):
            if field.name == "timing_seconds":
                assert [name for name, _ in actual.timing_seconds] == [name for name, _ in expected.timing_seconds]
            else:
                _assert_exact(getattr(expected, field.name), getattr(actual, field.name))
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for left, right in zip(expected, actual):
            _assert_exact(left, right)
    elif isinstance(expected, float):
        assert struct.pack("d", actual) == struct.pack("d", expected)
    else:
        assert actual == expected


def _edges() -> tuple[tuple[int, int], ...]:
    return analysis.spatial_edges_from_adjacency(analysis.biosemi64_spatial_adjacency())


@pytest.mark.parametrize("harmonics", [1, 2, 6, 24])
@pytest.mark.parametrize("density", [0.0, 0.01, 0.1, 0.5, 1.0])
@pytest.mark.parametrize("layout", ["C", "F", "strided"])
def test_groups_and_union_call_order_match_frozen_baseline(harmonics, density, layout) -> None:
    active = np.random.default_rng(771).random((64, harmonics)) < density
    if layout == "F":
        active = np.asfortranarray(active)
    elif layout == "strided":
        storage = np.zeros((64, harmonics * 2), dtype=bool)
        storage[:, ::2] = active
        active = storage[:, ::2][::-1]
    before = active.tobytes()
    calls = []

    def capture_union(frame, event, _arg):
        if event == "call" and frame.f_code.co_name == "union":
            calls.append((frame.f_locals["left"], frame.f_locals["right"]))

    outcomes = []
    original_profile = sys.getprofile()
    try:
        for function in (_baseline_groups, analysis._union_find_active_node_groups):
            calls.clear()
            sys.setprofile(capture_union)
            groups = function(active, spatial_edges=_edges())
            sys.setprofile(original_profile)
            outcomes.append((groups, tuple(calls)))
    finally:
        sys.setprofile(original_profile)
    _assert_exact(*outcomes)
    assert active.tobytes() == before


@pytest.mark.parametrize("node_count", [0, 1, 2, 31, 32, 33, 128])
def test_sparse_guard_boundary_and_dense_fallback(monkeypatch, node_count) -> None:
    active = np.zeros((64, 2), dtype=bool)
    active.reshape(-1)[:node_count] = True
    expected = _baseline_groups(active, spatial_edges=_edges())
    original_any = np.any
    calls = []

    def tracked_any(values, *args, **kwargs):
        calls.append((values.shape, kwargs.get("axis")))
        return original_any(values, *args, **kwargs)

    edges = _edges()
    monkeypatch.setattr(analysis.np, "any", tracked_any)
    actual = analysis._union_find_active_node_groups(
        active, spatial_edges=edges, active_nodes=np.flatnonzero(active.reshape(-1))
    )
    _assert_exact(expected, actual)
    assert calls == ([((64, 2), 1)] if node_count < 32 else [])


@pytest.mark.parametrize("shape", [(0, 0), (0, 2), (2, 0), (1, 1)])
def test_empty_and_single_sensor_domains_preserve_groups(shape) -> None:
    active = np.zeros(shape, dtype=bool)
    _assert_exact(
        _baseline_groups(active, spatial_edges=()),
        analysis._union_find_active_node_groups(active, spatial_edges=()),
    )


@pytest.mark.parametrize("positive", [True, False])
@pytest.mark.parametrize("dense", [False, True])
def test_mass_bytes_and_warnings_match_for_zero_nonfinite_and_extreme_values(monkeypatch, positive, dense) -> None:
    active = np.full((64, 6), dense, dtype=bool)
    active[:3, :2] = True
    current = analysis._union_find_active_node_groups
    for values in ([0.0, -0.0], [np.inf, -np.inf], [np.nan, 1.0], [1e308, -1e308], [1e-310, -1e-310]):
        t_map = np.resize(np.asarray(values), active.shape)
        before = t_map.tobytes()
        outcomes = []
        for function in (_baseline_groups, current):
            monkeypatch.setattr(analysis, "_union_find_active_node_groups", function)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                mass = analysis._extreme_cluster_mass(t_map, active=active, spatial_edges=_edges(), positive=positive)
            outcomes.append((mass, tuple((item.category, str(item.message)) for item in caught)))
        _assert_exact(*outcomes)
        assert t_map.tobytes() == before


@pytest.mark.parametrize("design", ["independent_groups", "paired_conditions"])
@pytest.mark.parametrize("harmonics", [2, 6, 24])
def test_complete_inference_and_changed_inputs_match_frozen_baseline(monkeypatch, design, harmonics) -> None:
    rng = np.random.default_rng(921)
    first = rng.normal(size=(18, 64, harmonics))
    second = np.asfortranarray(rng.normal(size=(16 if design == "independent_groups" else 18, 64, harmonics)))
    first[:, 20:26, :2] += 1.5
    current = analysis._union_find_active_node_groups
    for seed in (42, 1729):
        first[0, 0, 0] = np.nextafter(first[0, 0, 0], np.inf)
        before = first.tobytes(), second.tobytes()
        outcomes = []
        for function in (_baseline_groups, current):
            monkeypatch.setattr(analysis, "_union_find_active_node_groups", function)
            progress = []
            result = analysis.run_cluster_permutation_core(
                first, second, design=design, spatial_adjacency=analysis.biosemi64_spatial_adjacency(),
                permutation_count=29, batch_size=11, seed=seed,
                progress=lambda complete, total: progress.append((complete, total)),
            )
            outcomes.append((result, progress))
        _assert_exact(*outcomes)
        assert before == (first.tobytes(), second.tobytes())


@pytest.mark.parametrize("case", ["cancel_first", "cancel_second", "cancel_final", "nan", "inf", "shape", "count"])
def test_errors_cancellation_and_progress_match_frozen_baseline(monkeypatch, case) -> None:
    rng = np.random.default_rng(91)
    first = rng.normal(size=(5, 64, 2))
    second = rng.normal(size=first.shape)
    current = analysis._union_find_active_node_groups
    outcomes = []
    for function in (_baseline_groups, current):
        monkeypatch.setattr(analysis, "_union_find_active_node_groups", function)
        progress = []
        calls = 0
        target = {"cancel_first": 1, "cancel_second": 2, "cancel_final": 4}.get(case, 999)

        def cancel():
            nonlocal calls
            calls += 1
            return calls == target

        if case in ("nan", "inf"):
            first[0, 0, 0] = float(case)
        with pytest.raises((ValueError, analysis.AnalysisCancelled)) as caught:
            analysis.run_cluster_permutation_core(
                first, second[:, :, :1] if case == "shape" else second,
                design="paired_conditions", spatial_adjacency=analysis.biosemi64_spatial_adjacency(),
                permutation_count=0 if case == "count" else 9, batch_size=3, cancel_check=cancel,
                progress=lambda complete, total: progress.append((complete, total)),
            )
        outcomes.append((type(caught.value), str(caught.value), calls, progress))
    _assert_exact(*outcomes)
