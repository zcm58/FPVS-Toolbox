"""CPU/user ceilings for EEG stages that separately admit live memory."""

from types import SimpleNamespace

import pytest

from Main_App.workers import mp_env


@pytest.mark.parametrize("cpus,requested,expected", [
    (1, None, 1), (2, None, 1), (4, 0, 3), (8, None, 7),
    (24, None, 23), (64, None, 63), (24, 12, 12), (8, 12, 7),
    (24, 1, 1), (0, None, 1), (None, True, 1), (24, -1, 1),
    (24, "12", 1), (24, 12.0, 1),
])
def test_cpu_and_user_bounds_without_static_ram_or_twenty_worker_cap(monkeypatch, cpus, requested, expected):
    monkeypatch.setattr(mp_env, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: 24, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: SimpleNamespace(cpu_affinity=lambda: list(range(24))))
    assert mp_env.compute_dynamic_worker_ceiling(requested, cpu_count=cpus) == expected


@pytest.mark.parametrize("platform,requested,expected", [
    ("win32", None, 61), ("win32", 80, 61), ("win32", 12, 12),
    ("linux", None, 127), ("linux", 80, 80), ("linux", 12, 12),
])
def test_windows_executor_limit_is_a_runtime_bound_not_a_ram_tier(monkeypatch, platform, requested, expected):
    monkeypatch.setattr(mp_env, "sys", SimpleNamespace(platform=platform))
    assert mp_env.compute_dynamic_worker_ceiling(requested, cpu_count=128) == expected


@pytest.mark.parametrize("process_cpus,affinity,expected", [(24, 8, 7), (4, 24, 3), (None, 4, 3)])
def test_default_uses_stricter_available_process_cpu_and_affinity(monkeypatch, process_cpus, affinity, expected):
    monkeypatch.setattr(mp_env.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: process_cpus, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: SimpleNamespace(cpu_affinity=lambda: list(range(affinity))))
    assert mp_env.compute_dynamic_worker_ceiling() == expected


def test_affinity_failure_keeps_process_cpu_limit(monkeypatch):
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: 8, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: (_ for _ in ()).throw(mp_env.psutil.AccessDenied()))
    assert mp_env.compute_dynamic_worker_ceiling() == 7


def test_unavailable_process_cpu_probes_fall_back_to_host_count(monkeypatch):
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: (_ for _ in ()).throw(OSError()), raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: (_ for _ in ()).throw(mp_env.psutil.AccessDenied()))
    monkeypatch.setattr(mp_env.os, "cpu_count", lambda: 4)
    assert mp_env.compute_dynamic_worker_ceiling() == 3
    monkeypatch.setattr(mp_env.os, "cpu_count", lambda: None)
    assert mp_env.compute_dynamic_worker_ceiling() == 1


def test_legacy_tier_api_keeps_unadmitted_tool_policy():
    assert mp_env.compute_effective_max_workers(16 * 1024**3, 24, None) == 4
    assert mp_env.compute_effective_max_workers(192 * 1024**3, 64, None) == 20
