"""Simulation-based sensitivity analysis for the FPVS linear mixed model."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Literal
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm
import statsmodels.formula.api as smf

LmmEffectTarget = Literal["condition", "roi", "interaction"]
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class LmmSimulationCancelled(RuntimeError):
    """Raised when a running simulation is cancelled by the caller."""


@dataclass(frozen=True)
class LmmSensitivityConfig:
    """Input-only assumptions for the FPVS random-intercept LMM simulation."""

    sample_size: int
    conditions: int
    rois: int
    target: LmmEffectTarget
    power: float = 0.80
    alpha: float = 0.05
    correlation: float = 0.50
    simulations: int = 400
    seed: int = 2026
    search_iterations: int = 7


@dataclass(frozen=True)
class LmmSensitivityResult:
    """Approximate minimum detectable standardized contrast from simulation."""

    effect_size: float
    estimated_power: float
    power_ci_low: float
    power_ci_high: float
    simulations: int
    successful_fits: int
    failed_fits: int
    singular_fits: int
    target: LmmEffectTarget
    seed: int


@dataclass(frozen=True)
class _SimulationOutcome:
    p_value: float
    converged: bool
    singular: bool


@dataclass(frozen=True)
class _PowerEstimate:
    detected: int
    attempted: int
    successful: int
    failed: int
    singular: int

    @property
    def power(self) -> float:
        return self.detected / self.attempted if self.attempted else 0.0


def validate_lmm_config(config: LmmSensitivityConfig) -> None:
    """Validate assumptions required by the supported FPVS LMM simulation."""

    if config.sample_size < 3:
        raise ValueError("Analyzable participants must be at least 3.")
    if config.conditions < 2 or config.rois < 2:
        raise ValueError(
            "Linear mixed-model simulation requires at least 2 conditions and 2 ROIs."
        )
    if config.target not in {"condition", "roi", "interaction"}:
        raise ValueError("Unsupported linear mixed-model effect target.")
    if not 0 < config.power < 1:
        raise ValueError("Desired power must be between 0 and 1.")
    if not 0 < config.alpha < 1:
        raise ValueError("Alpha must be between 0 and 1.")
    if not 0 <= config.correlation < 0.95:
        raise ValueError(
            "Within-participant correlation must be at least 0 and less than 0.95."
        )
    if not 20 <= config.simulations <= 5_000:
        raise ValueError("Simulations must be between 20 and 5,000.")
    if not 3 <= config.search_iterations <= 10:
        raise ValueError("Search iterations must be between 3 and 10.")


def _fixed_cell_pattern(
    conditions: int,
    rois: int,
    target: LmmEffectTarget,
    effect_size: float,
) -> np.ndarray:
    """Build the documented two-level contrast signal in residual-SD units."""

    means = np.zeros((conditions, rois), dtype=float)
    if target == "condition":
        means[0, :] = -effect_size / 2
        means[1, :] = effect_size / 2
    elif target == "roi":
        means[:, 0] = -effect_size / 2
        means[:, 1] = effect_size / 2
    else:
        quarter = effect_size / 4
        means[0, 0] = quarter
        means[0, 1] = -quarter
        means[1, 0] = -quarter
        means[1, 1] = quarter
    return means


def _target_parameter_indices(names: list[str], target: LmmEffectTarget) -> list[int]:
    """Resolve the fixed-effect coefficient block tested by the omnibus Wald test."""

    if target == "condition":
        return [
            index
            for index, name in enumerate(names)
            if "C(condition, Sum)" in name and ":" not in name
        ]
    if target == "roi":
        return [
            index
            for index, name in enumerate(names)
            if "C(roi, Sum)" in name and ":" not in name
        ]
    return [index for index, name in enumerate(names) if ":" in name]


def _simulate_one(
    config: LmmSensitivityConfig,
    effect_size: float,
    seed: int,
) -> _SimulationOutcome:
    """Simulate one balanced dataset, fit the planned LMM, and test the target."""

    rng = np.random.default_rng(seed)
    observations_per_subject = config.conditions * config.rois
    subjects = np.repeat(np.arange(config.sample_size), observations_per_subject)
    condition_codes = np.tile(
        np.repeat(np.arange(config.conditions), config.rois),
        config.sample_size,
    )
    roi_codes = np.tile(np.arange(config.rois), config.sample_size * config.conditions)

    residual_sd = 1.0
    random_intercept_sd = math.sqrt(config.correlation / (1 - config.correlation))
    random_intercepts = rng.normal(0, random_intercept_sd, config.sample_size)
    cell_means = _fixed_cell_pattern(
        config.conditions,
        config.rois,
        config.target,
        effect_size,
    )
    values = (
        cell_means[condition_codes, roi_codes]
        + random_intercepts[subjects]
        + rng.normal(0, residual_sd, subjects.size)
    )
    frame = pd.DataFrame(
        {
            "subject": subjects,
            "condition": [f"C{value}" for value in condition_codes],
            "roi": [f"R{value}" for value in roi_codes],
            "value": values,
        }
    )
    formula = "value ~ C(condition, Sum) * C(roi, Sum)"
    model = smf.mixedlm(
        formula,
        frame,
        groups=frame["subject"],
        re_formula="1",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = model.fit(
                reml=True,
                method="lbfgs",
                maxiter=500,
                full_output=True,
                disp=False,
            )
        except Exception as _fit_error:  # noqa: BLE001 - optimizer fallback boundary
            result = model.fit(
                reml=True,
                method="powell",
                maxiter=500,
                full_output=True,
                disp=False,
            )

    parameter_names = list(result.fe_params.index)
    target_indices = _target_parameter_indices(parameter_names, config.target)
    if not target_indices:
        raise RuntimeError("The fitted model did not expose the requested effect block.")
    restriction = np.zeros((len(target_indices), len(result.params)), dtype=float)
    for row, index in enumerate(target_indices):
        restriction[row, index] = 1.0
    test = result.wald_test(restriction, scalar=True)
    p_value = float(np.asarray(test.pvalue).squeeze())
    converged = bool(getattr(result, "converged", False)) and math.isfinite(p_value)
    singular = False
    try:
        covariance = np.asarray(result.cov_re, dtype=float)
        singular = bool(covariance.size and np.min(np.linalg.eigvalsh(covariance)) < 1e-8)
    except (AttributeError, TypeError, ValueError, np.linalg.LinAlgError):
        pass
    return _SimulationOutcome(
        p_value=p_value,
        converged=converged,
        singular=singular,
    )


def _wilson_interval(successes: int, attempts: int, confidence: float = 0.95) -> tuple[float, float]:
    if attempts <= 0:
        return 0.0, 0.0
    z_value = float(norm.ppf(1 - (1 - confidence) / 2))
    proportion = successes / attempts
    denominator = 1 + (z_value**2 / attempts)
    center = (proportion + z_value**2 / (2 * attempts)) / denominator
    half_width = (
        z_value
        * math.sqrt(
            proportion * (1 - proportion) / attempts
            + z_value**2 / (4 * attempts**2)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def calculate_lmm_sensitivity(
    config: LmmSensitivityConfig,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> LmmSensitivityResult:
    """Search for the contrast magnitude corresponding to the target simulated power."""

    validate_lmm_config(config)
    search_simulations = max(30, min(150, config.simulations // 4))
    total_attempts = (
        (config.search_iterations + 1) * search_simulations + config.simulations
    )
    completed_attempts = 0
    last_progress = -1
    seed_sequence = np.random.SeedSequence(config.seed)
    seeds = [
        int(child.generate_state(1, dtype=np.uint32)[0])
        for child in seed_sequence.spawn(config.simulations)
    ]

    def check_cancelled() -> None:
        if should_cancel is not None and should_cancel():
            raise LmmSimulationCancelled("Linear mixed-model simulation cancelled.")

    def estimate(
        effect_size: float,
        simulation_seeds: list[int],
        phase: str,
    ) -> _PowerEstimate:
        nonlocal completed_attempts, last_progress
        detected = successful = failed = singular = 0
        for seed in simulation_seeds:
            check_cancelled()
            try:
                outcome = _simulate_one(config, effect_size, seed)
            except Exception as _simulation_error:  # noqa: BLE001 - replicate boundary
                failed += 1
            else:
                if outcome.converged:
                    successful += 1
                    singular += int(outcome.singular)
                    detected += int(outcome.p_value < config.alpha)
                else:
                    failed += 1
            completed_attempts += 1
            percent = min(100, round(completed_attempts * 100 / total_attempts))
            if progress is not None and percent != last_progress:
                progress(percent, phase)
                last_progress = percent
        return _PowerEstimate(
            detected=detected,
            attempted=len(simulation_seeds),
            successful=successful,
            failed=failed,
            singular=singular,
        )

    search_seeds = seeds[:search_simulations]
    low_effect = 0.0
    high_effect = 4.0
    high_estimate = estimate(high_effect, search_seeds, "Finding an effect-size range")
    if high_estimate.power < config.power:
        raise ValueError(
            "The requested power was not reached within the supported standardized "
            "contrast range (0 to 4)."
        )

    for step in range(config.search_iterations):
        midpoint = (low_effect + high_effect) / 2
        estimate_at_midpoint = estimate(
            midpoint,
            search_seeds,
            f"Refining the detectable effect ({step + 1}/{config.search_iterations})",
        )
        if estimate_at_midpoint.power >= config.power:
            high_effect = midpoint
        else:
            low_effect = midpoint

    final_estimate = estimate(
        high_effect,
        seeds,
        "Confirming power at the estimated effect",
    )
    ci_low, ci_high = _wilson_interval(
        final_estimate.detected,
        final_estimate.attempted,
    )
    if progress is not None:
        progress(100, "Simulation complete")
    return LmmSensitivityResult(
        effect_size=high_effect,
        estimated_power=final_estimate.power,
        power_ci_low=ci_low,
        power_ci_high=ci_high,
        simulations=final_estimate.attempted,
        successful_fits=final_estimate.successful,
        failed_fits=final_estimate.failed,
        singular_fits=final_estimate.singular,
        target=config.target,
        seed=config.seed,
    )


__all__ = (
    "LmmEffectTarget",
    "LmmSensitivityConfig",
    "LmmSensitivityResult",
    "LmmSimulationCancelled",
    "calculate_lmm_sensitivity",
    "validate_lmm_config",
)
