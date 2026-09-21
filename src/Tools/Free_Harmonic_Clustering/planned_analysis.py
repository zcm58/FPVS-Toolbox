"""Whole-participant inference and planned-family multiplicity for FHC v2."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import math
from typing import Callable

from .analysis import analyze_prepared_contrast, global_cluster_two_sided_p_value, holm_adjust_p_values
from .analysis_plan import AnalysisPlan, PlannedComparison
from .inputs import _check_cancel
from .models import ClusterPermutationResult, FreeHarmonicMethodSpec, PreparedContrast
from .planned_inputs import PreparedAnalysisPlan, prepare_analysis_plan


def derive_planned_comparison_seed(base_seed: int, comparison_id: str) -> int:
    """V2 seed identity depends only on the calculation, never Holm membership."""
    if isinstance(base_seed, bool) or int(base_seed) < 0:
        raise ValueError("base_seed must be a non-negative integer.")
    if not str(comparison_id).strip():
        raise ValueError("comparison_id must not be empty.")
    digest = sha256(f"fpvs-fhc-planned-comparison-seed-v2\0{int(base_seed)}\0{comparison_id}".encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big") & ((1 << 63) - 1)


@dataclass(frozen=True, slots=True)
class PlannedComparisonOutcome:
    comparison: PlannedComparison
    contrast: PreparedContrast
    result: ClusterPermutationResult
    derived_seed: int
    global_p: float
    family_adjusted_p: float
    batch_adjusted_p: float

    def __post_init__(self) -> None:
        request = self.contrast.request
        if (request.design, request.condition_a, request.condition_b, request.group_ids, request.session_ids) != (
            self.comparison.design,
            self.comparison.condition_a,
            self.comparison.condition_b,
            self.comparison.group_ids,
            self.comparison.session_ids,
        ) or request.contrast_family_id != (self.comparison.comparison_id if self.comparison.session_ids else None):
            raise ValueError("Outcome contrast request must match its planned comparison identity.")
        if self.result.seed != self.derived_seed or self.contrast.method.seed != self.derived_seed:
            raise ValueError("Planned outcome method and inference must match its derived seed.")
        for name in ("global_p", "family_adjusted_p", "batch_adjusted_p"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Planned result p values must be finite probabilities.")
        if self.family_adjusted_p < self.global_p or self.batch_adjusted_p < self.global_p:
            raise ValueError("Holm-adjusted p values must not be below the run-global p value.")

    @property
    def global_two_sided_p_value(self) -> float:
        return self.global_p

    @property
    def holm_within_family_p_value(self) -> float:
        return self.family_adjusted_p

    @property
    def holm_all_batch_p_value(self) -> float:
        return self.batch_adjusted_p

    @property
    def family_id(self) -> str:
        return self.comparison.family_id

    @property
    def condition(self) -> str:
        return self.comparison.condition


@dataclass(frozen=True, slots=True)
class PlannedAnalysisResult:
    plan: AnalysisPlan
    prepared: PreparedAnalysisPlan
    outcomes: tuple[PlannedComparisonOutcome, ...]

    def __post_init__(self) -> None:
        if self.plan.fingerprint != self.prepared.plan.fingerprint:
            raise ValueError("Planned result and prepared plan identity differ.")
        if tuple(row.comparison for row in self.outcomes) != self.plan.comparisons:
            raise ValueError("Every planned comparison must have exactly one outcome in plan order.")


def analyze_prepared_analysis_plan(
    prepared: PreparedAnalysisPlan,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    batch_size: int = 256,
) -> PlannedAnalysisResult:
    """Apply unchanged inference engines, then Holm to the complete frozen plan."""
    outcomes = []
    number_comparisons = len(prepared.plan.comparisons)
    for number, (comparison, contrast) in enumerate(zip(prepared.plan.comparisons, prepared.contrasts, strict=True)):
        _check_cancel(cancel_check)
        seed = derive_planned_comparison_seed(prepared.method.seed, comparison.comparison_id)
        contrast = replace(contrast, method=replace(contrast.method, seed=seed))

        def progress(done: int, total: int, *, offset: int = number) -> None:
            if progress_callback is not None:
                progress_callback("inference", offset * total + done, number_comparisons * total)

        result = analyze_prepared_contrast(
            contrast, batch_size=batch_size, progress=progress, cancel_check=cancel_check
        )
        outcomes.append((comparison, contrast, result, seed))
    _check_cancel(cancel_check)
    raw = tuple(global_cluster_two_sided_p_value(row[2]) for row in outcomes)
    all_adjusted = holm_adjust_p_values(raw)
    family_adjusted = [1.0] * len(raw)
    members: dict[str, list[int]] = {}
    for number, comparison in enumerate(prepared.plan.comparisons):
        members.setdefault(comparison.family_id, []).append(number)
    for indices in members.values():
        adjusted = holm_adjust_p_values(tuple(raw[index] for index in indices))
        for index, p_value in zip(indices, adjusted, strict=True):
            family_adjusted[index] = p_value
    if progress_callback is not None:
        progress_callback("multiplicity", len(raw), len(raw))
    return PlannedAnalysisResult(
        prepared.plan,
        prepared,
        tuple(
            PlannedComparisonOutcome(
                comparison, contrast, result, seed, raw[number], family_adjusted[number], all_adjusted[number]
            )
            for number, (comparison, contrast, result, seed) in enumerate(outcomes)
        ),
    )


def run_analysis_plan(
    plan: AnalysisPlan,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    batch_size: int = 256,
) -> PlannedAnalysisResult:
    """Prepare and analyze a complete plan; result publication is separate."""

    def preparation_progress(done: int, total: int) -> None:
        if progress_callback is not None:
            progress_callback("preparation", done, total)

    prepared = prepare_analysis_plan(plan, spec, progress_callback=preparation_progress, cancel_check=cancel_check)
    return analyze_prepared_analysis_plan(
        prepared, progress_callback=progress_callback, cancel_check=cancel_check, batch_size=batch_size
    )


__all__ = [
    "PreparedAnalysisPlan",
    "PlannedComparisonOutcome",
    "PlannedAnalysisResult",
    "derive_planned_comparison_seed",
    "prepare_analysis_plan",
    "analyze_prepared_analysis_plan",
    "run_analysis_plan",
]
