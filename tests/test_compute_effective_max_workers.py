import importlib.util
import math
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "_mp_env_test",
    Path(__file__).resolve().parents[1]
    / "src"
    / "Main_App"
    / "Performance"
    / "mp_env.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - defensive
    raise RuntimeError("Unable to load mp_env module for testing")
_MP_ENV = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MP_ENV)
compute_effective_max_workers = _MP_ENV.compute_effective_max_workers


def _bytes_for_gib(value: float) -> int:
    return int(math.floor(value * (1024 ** 3)))


def test_16_gib_tier_caps_workers():
    total_ram = _bytes_for_gib(15.0)
    assert compute_effective_max_workers(total_ram, cpu_count=12, project_max_workers=None) == 4
    assert compute_effective_max_workers(total_ram, cpu_count=12, project_max_workers=2) == 2
    assert compute_effective_max_workers(total_ram, cpu_count=12, project_max_workers=10) == 4
    assert compute_effective_max_workers(
        total_ram,
        cpu_count=12,
        project_max_workers=10,
        allow_ram_cap_bypass=True,
    ) == 10


def test_32_gib_tier_caps_workers():
    total_ram = _bytes_for_gib(30.0)
    # CPU cap smaller than RAM cap when cpu_count is small
    assert compute_effective_max_workers(total_ram, cpu_count=4, project_max_workers=None) == 3
    # With more CPUs we hit the RAM-based limit of 4 workers
    assert compute_effective_max_workers(total_ram, cpu_count=16, project_max_workers=None) == 4


def test_64_gib_tier_caps_workers():
    total_ram = _bytes_for_gib(60.0)
    assert compute_effective_max_workers(total_ram, cpu_count=32, project_max_workers=None) == 7
    # Overrides above the tier should be clamped
    assert compute_effective_max_workers(total_ram, cpu_count=32, project_max_workers=12) == 7
    # Explicit bypass allows values over the RAM recommendation
    assert compute_effective_max_workers(
        total_ram,
        cpu_count=32,
        project_max_workers=12,
        allow_ram_cap_bypass=True,
    ) == 12


def test_high_ram_respects_global_cap():
    total_ram = _bytes_for_gib(192.0)
    # No RAM tier cap here, so global cap is the limiter.
    assert compute_effective_max_workers(total_ram, cpu_count=24, project_max_workers=None) == 16
    assert compute_effective_max_workers(total_ram, cpu_count=24, project_max_workers=20) == 16


def test_minimum_worker_floor():
    total_ram = _bytes_for_gib(8.0)
    assert compute_effective_max_workers(total_ram, cpu_count=1, project_max_workers=None) == 1
    assert compute_effective_max_workers(total_ram, cpu_count=0, project_max_workers=0) == 1
