from __future__ import annotations

import math

import numpy as np
import pytest

from Tools.Sensitivity_Analysis import lmm_simulation
from Tools.Sensitivity_Analysis.lmm_simulation import (
    LmmSensitivityConfig,
    LmmSimulationCancelled,
    _SimulationOutcome,
    _fixed_cell_pattern,
    _resolve_worker_count,
    _simulate_one,
    _spawn_seed_values,
    _target_parameter_indices,
    _wilson_interval,
    calculate_lmm_sensitivity,
    validate_lmm_config,
)


def _config(**overrides) -> LmmSensitivityConfig:
    values = {
        "sample_size": 24,
        "conditions": 3,
        "rois": 2,
        "target": "condition",
        "simulations": 100,
        "search_iterations": 5,
    }
    values.update(overrides)
    return LmmSensitivityConfig(**values)


def test_lmm_config_requires_supported_balanced_design() -> None:
    with pytest.raises(ValueError, match="at least 2 conditions and 2 ROIs"):
        validate_lmm_config(_config(rois=1))

    with pytest.raises(ValueError, match="correlation"):
        validate_lmm_config(_config(correlation=-0.10))

    validate_lmm_config(_config(simulations=10_000))
    with pytest.raises(ValueError, match="between 100 and 50,000"):
        validate_lmm_config(_config(simulations=50_001))


def test_fixed_patterns_encode_documented_standardized_contrasts() -> None:
    condition = _fixed_cell_pattern(3, 2, "condition", 0.60)
    assert np.allclose(condition[1] - condition[0], 0.60)
    assert np.allclose(condition[2], 0.0)

    roi = _fixed_cell_pattern(2, 3, "roi", 0.40)
    assert np.allclose(roi[:, 1] - roi[:, 0], 0.40)
    assert np.allclose(roi[:, 2], 0.0)

    interaction = _fixed_cell_pattern(2, 2, "interaction", 0.80)
    difference_in_differences = (
        interaction[1, 1]
        - interaction[1, 0]
        - interaction[0, 1]
        + interaction[0, 0]
    )
    assert difference_in_differences == pytest.approx(0.80)
    assert interaction.mean(axis=0) == pytest.approx([0.0, 0.0])
    assert interaction.mean(axis=1) == pytest.approx([0.0, 0.0])


def test_target_parameter_indices_separate_main_and_interaction_blocks() -> None:
    names = [
        "Intercept",
        "C(condition, Sum)[S.C0]",
        "C(roi, Sum)[S.R0]",
        "C(condition, Sum)[S.C0]:C(roi, Sum)[S.R0]",
    ]
    assert _target_parameter_indices(names, "condition") == [1]
    assert _target_parameter_indices(names, "roi") == [2]
    assert _target_parameter_indices(names, "interaction") == [3]


def test_simulated_search_finds_threshold_and_reports_monte_carlo_interval(
    monkeypatch,
) -> None:
    def fake_simulation(config, effect_size, seed):
        del config, seed
        p_value = 0.01 if effect_size >= 0.75 else 0.50
        return _SimulationOutcome(p_value=p_value, converged=True, singular=False)

    monkeypatch.setattr(lmm_simulation, "_simulate_one", fake_simulation)
    result = calculate_lmm_sensitivity(_config())

    assert 0.75 <= result.effect_size < 0.88
    assert result.estimated_power == pytest.approx(1.0)
    assert result.successful_fits == 100
    assert result.failed_fits == 0
    assert result.power_ci_low < result.estimated_power <= result.power_ci_high
    assert result.search_simulations > 150
    assert result.search_effect_low < result.effect_size == result.search_effect_high
    assert result.workers_used == 1
    assert result.confirmation_rounds == 1
    assert result.target_power_met


def test_search_and_confirmation_use_independent_reproducible_seed_streams() -> None:
    root_one = np.random.SeedSequence(2026)
    first_search, first_final = root_one.spawn(2)
    search_seeds = _spawn_seed_values(first_search, 200)
    final_seeds = _spawn_seed_values(first_final, 200)

    root_two = np.random.SeedSequence(2026)
    second_search, second_final = root_two.spawn(2)

    assert set(search_seeds).isdisjoint(final_seeds)
    assert search_seeds == _spawn_seed_values(second_search, 200)
    assert final_seeds == _spawn_seed_values(second_final, 200)


def test_below_target_confirmation_triggers_fresh_search_and_reconfirmation(
    monkeypatch,
) -> None:
    config = _config()
    root = np.random.SeedSequence(config.seed)
    search_one, final_one, search_two, final_two = root.spawn(4)
    search_one_seeds = set(_spawn_seed_values(search_one, 200))
    final_one_seeds = set(_spawn_seed_values(final_one, config.simulations))
    search_two_seeds = set(_spawn_seed_values(search_two, 200))
    final_two_seeds = set(_spawn_seed_values(final_two, config.simulations))

    def fake_simulation(config, effect_size, seed):
        del config
        if seed in final_one_seeds:
            detected = False
        elif seed in search_one_seeds:
            detected = effect_size >= 0.75
        elif seed in search_two_seeds or seed in final_two_seeds:
            detected = effect_size >= 0.85
        else:  # pragma: no cover - every deterministic seed belongs to one stream
            raise AssertionError("Unexpected simulation seed")
        return _SimulationOutcome(
            p_value=0.01 if detected else 0.50,
            converged=True,
            singular=False,
        )

    monkeypatch.setattr(lmm_simulation, "_simulate_one", fake_simulation)
    result = calculate_lmm_sensitivity(config, max_workers=1)

    assert result.confirmation_rounds == 2
    assert result.effect_size >= 0.85
    assert result.estimated_power == pytest.approx(1.0)
    assert result.target_power_met


def test_worker_count_is_serial_for_small_runs_and_capped_for_large_runs() -> None:
    assert _resolve_worker_count(_config(), requested=None) == 1
    assert _resolve_worker_count(_config(simulations=10_000), requested=99) == 8


def test_simulation_can_be_cancelled(monkeypatch) -> None:
    calls = 0

    def fake_simulation(config, effect_size, seed):
        nonlocal calls
        del config, effect_size, seed
        calls += 1
        return _SimulationOutcome(p_value=0.50, converged=True, singular=False)

    monkeypatch.setattr(lmm_simulation, "_simulate_one", fake_simulation)

    with pytest.raises(LmmSimulationCancelled):
        calculate_lmm_sensitivity(_config(), should_cancel=lambda: calls >= 3)


def test_wilson_interval_is_finite_and_contains_observed_power() -> None:
    low, high = _wilson_interval(80, 100)
    assert math.isfinite(low) and math.isfinite(high)
    assert low < 0.80 < high


def test_single_real_mixed_model_simulation_returns_valid_wald_test() -> None:
    outcome = _simulate_one(
        _config(conditions=2, rois=2),
        effect_size=0.75,
        seed=2026,
    )

    assert outcome.converged
    assert math.isfinite(outcome.p_value)
    assert 0 <= outcome.p_value <= 1
