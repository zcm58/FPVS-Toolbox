"""Input-only idealized design sensitivity for the FPVS linear mixed model."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import nullcontext
from dataclasses import dataclass
import math
from multiprocessing import get_context
import os
from typing import Callable, Literal
import warnings

import numpy as np
import pandas as pd
import psutil
from scipy.stats import norm
import statsmodels.formula.api as smf

from Main_App.Performance.mp_env import (
    compute_effective_max_workers,
    set_blas_threads_multiprocess,
)

try:
    from threadpoolctl import threadpool_limits
except ImportError:  # pragma: no cover - optional runtime optimization
    threadpool_limits = None

_MAX_PARALLEL_WORKERS = 8
_PARALLEL_MINIMUM_SIMULATIONS = 1_000
_PROCESS_BATCH_SIZE = 25
_SEARCH_INITIAL_SIMULATIONS = 200
_SEARCH_BATCH_SIZE = 200
_SEARCH_MAX_SIMULATIONS = 2_000
_MAX_CONFIRMATION_ROUNDS = 2

LmmEffectTarget = Literal["condition", "roi", "interaction"]
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class LmmSimulationCancelled(RuntimeError):
    """Raised when a running simulation is cancelled by the caller."""


@dataclass(frozen=True)
class LmmSensitivityConfig:
    """Manual assumptions for the idealized FPVS random-intercept LMM design."""

    sample_size: int
    conditions: int
    rois: int
    target: LmmEffectTarget
    power: float = 0.80
    alpha: float = 0.05
    correlation: float = 0.50
    simulations: int = 10_000
    seed: int = 2026
    search_iterations: int = 9


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
    search_simulations: int = 0
    search_effect_low: float = 0.0
    search_effect_high: float = 0.0
    workers_used: int = 1
    confirmation_rounds: int = 1
    target_power_met: bool = True


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
    if not 100 <= config.simulations <= 50_000:
        raise ValueError("Simulations must be between 100 and 50,000.")
    if not 3 <= config.search_iterations <= 12:
        raise ValueError("Search iterations must be between 3 and 12.")


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


def _simulation_worker_init() -> None:
    """Configure child processes for predictable mixed-model throughput."""

    set_blas_threads_multiprocess()


def _simulate_batch(
    config: LmmSensitivityConfig,
    effect_size: float,
    seeds: tuple[int, ...],
) -> list[_SimulationOutcome | None]:
    """Run a small spawn-safe batch, preserving failures as non-detections."""

    limit_context = (
        threadpool_limits(limits=1) if threadpool_limits is not None else nullcontext()
    )
    outcomes: list[_SimulationOutcome | None] = []
    with limit_context:
        for seed in seeds:
            try:
                outcomes.append(_simulate_one(config, effect_size, seed))
            except Exception:  # noqa: BLE001 - replicate failure boundary
                outcomes.append(None)
    return outcomes


def _resolve_worker_count(
    config: LmmSensitivityConfig,
    requested: int | None,
) -> int:
    """Choose a conservative process count for repeated MixedLM fits."""

    if requested is not None:
        return max(1, min(int(requested), _MAX_PARALLEL_WORKERS))
    if config.simulations < _PARALLEL_MINIMUM_SIMULATIONS:
        return 1
    try:
        recommended = compute_effective_max_workers(
            total_ram_bytes=int(psutil.virtual_memory().total),
            cpu_count=os.cpu_count() or 1,
            project_max_workers=None,
        )
    except Exception:  # pragma: no cover - defensive host inspection fallback
        recommended = max(1, (os.cpu_count() or 2) - 1)
    return max(1, min(recommended, _MAX_PARALLEL_WORKERS))


def _spawn_seed_values(sequence: np.random.SeedSequence, count: int) -> list[int]:
    """Create deterministic independent uint32 seeds from a SeedSequence."""

    return [
        int(child.generate_state(1, dtype=np.uint32)[0])
        for child in sequence.spawn(count)
    ]


def _combine_estimates(left: _PowerEstimate, right: _PowerEstimate) -> _PowerEstimate:
    return _PowerEstimate(
        detected=left.detected + right.detected,
        attempted=left.attempted + right.attempted,
        successful=left.successful + right.successful,
        failed=left.failed + right.failed,
        singular=left.singular + right.singular,
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
    max_workers: int | None = None,
) -> LmmSensitivityResult:
    """Estimate a detectable contrast with adaptive search and independent confirmation."""

    validate_lmm_config(config)
    worker_count = _resolve_worker_count(config, max_workers)
    search_max = min(
        _SEARCH_MAX_SIMULATIONS,
        max(_SEARCH_INITIAL_SIMULATIONS, config.simulations // 5),
    )
    search_initial = min(_SEARCH_INITIAL_SIMULATIONS, search_max)
    search_batch = min(_SEARCH_BATCH_SIZE, search_max)
    max_search_attempts = (config.search_iterations + 1) * search_max

    root_sequence = np.random.SeedSequence(config.seed)
    search_one_sequence, final_one_sequence, search_two_sequence, final_two_sequence = (
        root_sequence.spawn(4)
    )
    search_one_seeds = _spawn_seed_values(search_one_sequence, search_max)
    final_one_seeds = _spawn_seed_values(final_one_sequence, config.simulations)

    stage_completed = {
        "search_one": 0,
        "final_one": 0,
        "search_two": 0,
        "final_two": 0,
    }
    stage_ranges = {
        "search_one": (1, 35, max_search_attempts),
        "final_one": (35, 95, config.simulations),
        "search_two": (95, 97, max_search_attempts),
        "final_two": (97, 99, config.simulations),
    }
    last_progress = -1
    search_attempts_total = 0
    cancelled_run = False
    executor: ProcessPoolExecutor | None = None

    def check_cancelled() -> None:
        nonlocal cancelled_run
        if should_cancel is not None and should_cancel():
            cancelled_run = True
            raise LmmSimulationCancelled("Linear mixed-model simulation cancelled.")

    def emit_attempt_progress(stage: str, increment: int, phase: str) -> None:
        nonlocal last_progress, search_attempts_total
        stage_completed[stage] += increment
        if stage.startswith("search"):
            search_attempts_total += increment
        start, stop, maximum = stage_ranges[stage]
        fraction = min(1.0, stage_completed[stage] / max(1, maximum))
        percent = max(last_progress, min(99, round(start + (stop - start) * fraction)))
        if progress is not None and percent != last_progress:
            progress(percent, phase)
            last_progress = percent

    def summarize(outcomes: list[_SimulationOutcome | None]) -> _PowerEstimate:
        detected = successful = failed = singular = 0
        for outcome in outcomes:
            if outcome is None or not outcome.converged:
                failed += 1
                continue
            successful += 1
            singular += int(outcome.singular)
            detected += int(outcome.p_value < config.alpha)
        return _PowerEstimate(
            detected=detected,
            attempted=len(outcomes),
            successful=successful,
            failed=failed,
            singular=singular,
        )

    def estimate_slice(
        effect_size: float,
        simulation_seeds: list[int],
        phase: str,
        stage: str,
    ) -> _PowerEstimate:
        check_cancelled()
        if executor is None:
            outcomes: list[_SimulationOutcome | None] = []
            for seed in simulation_seeds:
                check_cancelled()
                try:
                    outcomes.append(_simulate_one(config, effect_size, seed))
                except Exception:  # noqa: BLE001 - replicate boundary
                    outcomes.append(None)
                emit_attempt_progress(stage, 1, phase)
            return summarize(outcomes)

        chunks = [
            tuple(simulation_seeds[index : index + _PROCESS_BATCH_SIZE])
            for index in range(0, len(simulation_seeds), _PROCESS_BATCH_SIZE)
        ]
        pending = {
            executor.submit(_simulate_batch, config, effect_size, chunk): chunk
            for chunk in chunks
        }
        combined = _PowerEstimate(0, 0, 0, 0, 0)
        while pending:
            check_cancelled()
            completed, _not_done = wait(
                pending,
                timeout=0.10,
                return_when=FIRST_COMPLETED,
            )
            if not completed:
                continue
            for future in completed:
                chunk = pending.pop(future)
                try:
                    outcomes = future.result()
                except Exception as exc:
                    for remaining in pending:
                        remaining.cancel()
                    raise RuntimeError(
                        "A parallel mixed-model simulation worker failed. "
                        "Restart the simulation or use a smaller run."
                    ) from exc
                if len(outcomes) != len(chunk):
                    raise RuntimeError("A simulation worker returned an incomplete batch.")
                combined = _combine_estimates(combined, summarize(outcomes))
                emit_attempt_progress(stage, len(outcomes), phase)
        return combined

    def adaptive_estimate(
        effect_size: float,
        simulation_seeds: list[int],
        phase: str,
        stage: str,
    ) -> tuple[_PowerEstimate, Literal["above", "below"], bool]:
        estimate = _PowerEstimate(0, 0, 0, 0, 0)
        used = 0
        while used < len(simulation_seeds):
            take = search_initial if used == 0 else search_batch
            next_used = min(len(simulation_seeds), used + take)
            estimate = _combine_estimates(
                estimate,
                estimate_slice(
                    effect_size,
                    simulation_seeds[used:next_used],
                    phase,
                    stage,
                ),
            )
            used = next_used
            ci_low, ci_high = _wilson_interval(estimate.detected, estimate.attempted)
            if ci_high < config.power:
                return estimate, "below", True
            if ci_low >= config.power:
                return estimate, "above", True
        classification: Literal["above", "below"] = (
            "above" if estimate.power >= config.power else "below"
        )
        return estimate, classification, False

    def search_effect(
        simulation_seeds: list[int],
        stage: str,
        *,
        low_effect: float,
        high_effect: float,
        label: str,
        verify_high: bool = True,
    ) -> tuple[float, float]:
        if verify_high:
            _high_estimate, high_classification, _resolved = adaptive_estimate(
                high_effect,
                simulation_seeds,
                f"{label}: checking the upper effect range",
                stage,
            )
            if high_classification != "above":
                raise ValueError(
                    "The requested power was not reached within the supported "
                    "standardized contrast range (0 to 4)."
                )
        for step in range(config.search_iterations):
            midpoint = (low_effect + high_effect) / 2
            _mid_estimate, classification, _resolved = adaptive_estimate(
                midpoint,
                simulation_seeds,
                f"{label}: refining the effect ({step + 1}/{config.search_iterations})",
                stage,
            )
            if classification == "above":
                high_effect = midpoint
            else:
                low_effect = midpoint
        return low_effect, high_effect

    if progress is not None:
        progress(0, f"Preparing {worker_count} simulation worker(s)")
    if worker_count > 1:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=get_context("spawn"),
            initializer=_simulation_worker_init,
        )

    try:
        search_low, search_high = search_effect(
            search_one_seeds,
            "search_one",
            low_effect=0.0,
            high_effect=4.0,
            label="Adaptive search",
        )
        confirmation_rounds = 1
        final_estimate = estimate_slice(
            search_high,
            final_one_seeds,
            f"Confirming power with {config.simulations:,} independent studies",
            "final_one",
        )

        if final_estimate.power < config.power and search_high < 4.0:
            confirmation_rounds = 2
            search_two_seeds = _spawn_seed_values(search_two_sequence, search_max)
            final_two_seeds = _spawn_seed_values(
                final_two_sequence,
                config.simulations,
            )
            correction_low = search_high
            step_size = max(0.05, search_high - search_low)
            correction_high = min(4.0, correction_low + step_size)
            while True:
                _estimate, classification, _resolved = adaptive_estimate(
                    correction_high,
                    search_two_seeds,
                    "Independent correction: finding a higher effect",
                    "search_two",
                )
                if classification == "above":
                    break
                if correction_high >= 4.0:
                    raise ValueError(
                        "Independent confirmation did not reach the requested power "
                        "within the supported standardized contrast range (0 to 4)."
                    )
                correction_low = correction_high
                step_size *= 2
                correction_high = min(4.0, correction_high + step_size)
            search_low, search_high = search_effect(
                search_two_seeds,
                "search_two",
                low_effect=correction_low,
                high_effect=correction_high,
                label="Independent correction",
                verify_high=False,
            )
            final_estimate = estimate_slice(
                search_high,
                final_two_seeds,
                "Reconfirming power with a fresh independent run",
                "final_two",
            )
    finally:
        if executor is not None:
            executor.shutdown(wait=not cancelled_run, cancel_futures=True)

    ci_low, ci_high = _wilson_interval(
        final_estimate.detected,
        final_estimate.attempted,
    )
    if progress is not None:
        progress(100, "Simulation complete")
    return LmmSensitivityResult(
        effect_size=search_high,
        estimated_power=final_estimate.power,
        power_ci_low=ci_low,
        power_ci_high=ci_high,
        simulations=final_estimate.attempted,
        successful_fits=final_estimate.successful,
        failed_fits=final_estimate.failed,
        singular_fits=final_estimate.singular,
        target=config.target,
        seed=config.seed,
        search_simulations=search_attempts_total,
        search_effect_low=search_low,
        search_effect_high=search_high,
        workers_used=worker_count,
        confirmation_rounds=confirmation_rounds,
        target_power_met=final_estimate.power >= config.power,
    )


__all__ = (
    "LmmEffectTarget",
    "LmmSensitivityConfig",
    "LmmSensitivityResult",
    "LmmSimulationCancelled",
    "calculate_lmm_sensitivity",
    "validate_lmm_config",
)
