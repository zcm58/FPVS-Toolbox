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
    _simulate_one,
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
