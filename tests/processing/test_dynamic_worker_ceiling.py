"""CPU/user ceilings for EEG stages that separately admit live memory."""

from types import SimpleNamespace

import pytest

from Main_App.workers import mp_env


@pytest.fixture(autouse=True)
def _unconstrained_host(monkeypatch):
    monkeypatch.setattr(mp_env, "cgroup_limits", lambda: (None, None, None))
    monkeypatch.setattr(mp_env.psutil, "virtual_memory", lambda: SimpleNamespace(total=192 * 1024**3))


@pytest.mark.parametrize("cpus,requested,expected", [
    (1, None, 1), (2, None, 1), (4, 0, 3), (8, None, 7),
    (24, None, 23), (64, None, 63), (24, 12, 12), (8, 12, 7),
    (24, 1, 1), (0, None, 1), (None, True, 1), (24, -1, 1),
    (24, "12", 1), (24, 12.0, 1),
])
def test_cpu_and_user_bounds_above_last_ram_tier(monkeypatch, cpus, requested, expected):
    monkeypatch.setattr(mp_env, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(mp_env.os, "process_cpu_count", lambda: 24, raising=False)
    monkeypatch.setattr(mp_env.psutil, "Process", lambda: SimpleNamespace(cpu_affinity=lambda: list(range(24))))
    assert mp_env.compute_dynamic_worker_ceiling(requested, cpu_count=cpus, total_ram_bytes=192 * 1024**3) == expected


@pytest.mark.parametrize("platform,requested,expected", [
    ("win32", None, 61), ("win32", 80, 61), ("win32", 12, 12),
    ("linux", None, 127), ("linux", 80, 80), ("linux", 12, 12),
])
def test_windows_executor_limit_is_a_runtime_bound_not_a_ram_tier(monkeypatch, platform, requested, expected):
    monkeypatch.setattr(mp_env, "sys", SimpleNamespace(platform=platform))
    assert mp_env.compute_dynamic_worker_ceiling(requested, cpu_count=128, total_ram_bytes=192 * 1024**3) == expected


@pytest.mark.parametrize("gib,requested,expected", [
    (8, 0, 2), (16, None, 4), (32, None, 4), (64, 0, 7),
    (127.73, None, 16), (127.73, 0, 16), (127.73, 16, 16),
    (127.73, 5, 5), (64, 16, 16), (192, 0, 23),
])
def test_automatic_ram_tiers_and_explicit_overrides(gib, requested, expected):
    assert mp_env.compute_dynamic_worker_ceiling(
        requested, cpu_count=24, total_ram_bytes=int(gib * 1024**3),
    ) == expected


@pytest.mark.parametrize("settings,options,expected", [
    ({"max_parallel_workers_override": "16"}, {"max_workers": 2}, 16),
    ({"max_parallel_workers": "5"}, {"max_workers": 12}, 5),
    ({"max_workers": 3}, {}, 3),
    ({"max_parallel_workers_override": 0, "max_workers": 9}, {"max_workers": "4"}, 4),
    ({"max_parallel_workers_override": "invalid"}, {}, None),
    ({}, {"max_workers": 0}, None),
])
def test_current_and_legacy_project_worker_settings(settings, options, expected):
    assert mp_env.project_worker_override(settings, options) == expected


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


def test_process_cgroup_bounds_automatic_and_explicit_workers_and_live_memory(monkeypatch):
    from Main_App.workers import review_resource_budget as budget

    gib = 1024**3
    def group():
        return 9, 32 * gib, 3 * gib
    monkeypatch.setattr(mp_env, "cgroup_limits", group)
    monkeypatch.setattr(budget, "cgroup_limits", group)
    monkeypatch.setattr(budget, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(mp_env.psutil, "virtual_memory", lambda: SimpleNamespace(total=128 * gib, available=80 * gib))
    assert mp_env.compute_dynamic_worker_ceiling(cpu_count=24) == 4
    assert mp_env.compute_dynamic_worker_ceiling(16, cpu_count=24) == 8
    snapshot = budget.probe_memory_snapshot()
    assert (snapshot.total_bytes, snapshot.physical_available_bytes) == (32 * gib, 3 * gib)


@pytest.mark.parametrize("unified", [True, False])
def test_linux_cgroup_inherits_strictest_visible_ancestor_budget(tmp_path, monkeypatch, unified):
    from Main_App.workers import linux_cgroup

    monkeypatch.setattr(linux_cgroup, "sys", SimpleNamespace(platform="linux"))
    group = tmp_path / "mounted"
    leaf = group / "parent" / "job"
    leaf.mkdir(parents=True)
    proc = tmp_path / "proc"
    proc.mkdir()
    mounts = "cgroup2 cgroup rw" if unified else "cgroup cgroup rw,cpu,memory"
    # The kernel uses octal escapes in mountinfo, including in test directories.
    mount = group.as_posix().replace(" ", r"\040")
    (proc / "mountinfo").write_text(f"31 23 0:27 / {mount} rw - {mounts}\n")
    (proc / "cgroup").write_text("0::/parent/job" if unified else "3:cpu,memory:/parent/job")
    total, usage = (("memory.max", "memory.current") if unified else ("memory.limit_in_bytes", "memory.usage_in_bytes"))
    (group / total).write_text("100")
    (group / usage).write_text("90")
    (leaf / total).write_text("60")
    (leaf / usage).write_text("15")
    if unified:
        (group / "cpu.max").write_text("350000 100000")
        (leaf / "cpu.max").write_text("max 100000")
    else:
        (group / "cpu.cfs_quota_us").write_text("350000")
        (group / "cpu.cfs_period_us").write_text("100000")
    assert linux_cgroup.cgroup_limits(proc) == (4, 60, 10)
