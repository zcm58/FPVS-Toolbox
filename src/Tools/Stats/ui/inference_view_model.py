"""GUI-neutral configuration and progress helpers for native Stats inference."""

from __future__ import annotations

from dataclasses import dataclass

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    HarmonicProvenance,
    STANDARD_SCREENING_CORRECTION,
    STANDARD_SCREENING_RESPONSE_ALTERNATIVE,
    STANDARD_SCREENING_SCOPE,
    build_standard_screening_run_spec,
)
from Tools.Stats.analysis.prepared_analysis import AnalysisMode
from Tools.Stats.common.stats_core import PipelineId, StepId


PIPELINE_STEP_ORDER: dict[PipelineId, tuple[StepId, ...]] = {
    PipelineId.SINGLE: (
        StepId.PREPARE_ANALYSIS,
        StepId.BASELINE_VS_ZERO,
        StepId.MIXED_MODEL,
        StepId.RM_ANOVA,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ),
    PipelineId.MULTI: (
        StepId.PREPARE_ANALYSIS,
        StepId.BASELINE_VS_ZERO,
        StepId.MULTIGROUP_MODEL,
        StepId.RM_ANOVA,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ),
}

STEP_PHASE_LABELS: dict[StepId, str] = {
    StepId.PREPARE_ANALYSIS: "Preparing and checking the shared dataset",
    StepId.RM_ANOVA: "Checking balanced-data ANOVA compatibility",
    StepId.MIXED_MODEL: "Fitting the Condition × ROI mixed model",
    StepId.INTERACTION_POSTHOCS: "Running interaction follow-up comparisons",
    StepId.BASELINE_VS_ZERO: "Testing for positive oddball responses",
    StepId.MULTIGROUP_MODEL: "Fitting the multi-group mixed model",
    StepId.GROUP_CELL_COMPARISONS: "Comparing groups within condition × ROI cells",
    StepId.SENSITIVITIES: "Running sensitivity checks",
    StepId.REPORT_BUNDLE: "Building and exporting the results report",
}


def _normalized_token(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def coerce_analysis_mode(
    value: object,
    *,
    project_is_multigroup: bool,
) -> AnalysisMode:
    """Resolve an explicit UI mode, or infer it from project metadata."""

    token = _normalized_token(value)
    if token in {"", "auto", "automatic", "project_default"}:
        return AnalysisMode.MULTI if project_is_multigroup else AnalysisMode.SINGLE
    return AnalysisMode.coerce(token)


def infer_harmonic_provenance(
    *,
    independently_selected: bool,
    same_sample_adaptive: bool,
) -> HarmonicProvenance:
    """Map the plain-language UI attestation to the scientific contract."""

    if same_sample_adaptive:
        return HarmonicProvenance.SAME_SAMPLE_ADAPTIVE
    if independently_selected:
        return HarmonicProvenance.INDEPENDENTLY_SELECTED
    return HarmonicProvenance.USER_FIXED_UNVERIFIED


@dataclass(frozen=True, slots=True)
class NativeInferenceOptions:
    """Validated values collected from the Stats controls before a run."""

    mode: AnalysisMode
    profile: AnalysisProfile
    correction: CorrectionMethod
    alternative: Alternative
    harmonic_provenance: HarmonicProvenance
    alpha: float
    analysis_scope: str = STANDARD_SCREENING_SCOPE
    strict_omnibus_family: bool = True
    selected_group_pair: tuple[str, str] | None = None
    run_robust: bool = True
    run_resampling: bool = True
    run_stability: bool = True
    n_resamples: int = 10_000
    seed: int = 20_250_521

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", AnalysisMode.coerce(self.mode))
        object.__setattr__(self, "profile", AnalysisProfile.coerce(self.profile))
        object.__setattr__(
            self,
            "correction",
            CorrectionMethod.coerce(self.correction),
        )
        object.__setattr__(
            self,
            "alternative",
            Alternative.coerce(self.alternative),
        )
        object.__setattr__(
            self,
            "harmonic_provenance",
            HarmonicProvenance.coerce(self.harmonic_provenance),
        )
        # These fields remain accepted while the legacy GUI controls are
        # phased out, but standard screening has one locked scientific
        # contract in both project modes.
        object.__setattr__(
            self,
            "correction",
            STANDARD_SCREENING_CORRECTION,
        )
        object.__setattr__(
            self,
            "alternative",
            STANDARD_SCREENING_RESPONSE_ALTERNATIVE,
        )
        object.__setattr__(self, "strict_omnibus_family", True)
        alpha = float(self.alpha)
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1.")
        object.__setattr__(self, "alpha", alpha)
        scope = _normalized_token(self.analysis_scope)
        if scope not in {"complete_core", "available_case"}:
            raise ValueError(
                "analysis_scope must be 'complete_core' or 'available_case'."
            )
        scope = STANDARD_SCREENING_SCOPE
        object.__setattr__(self, "analysis_scope", scope)
        if scope == "available_case":
            # Max-|t| resampling currently relies on one complete participant-by-
            # cell matrix. Do not silently rebuild a complete-case subset inside
            # an analysis explicitly selected to retain incomplete participants.
            object.__setattr__(self, "run_resampling", False)
        if self.mode is AnalysisMode.SINGLE and self.selected_group_pair is not None:
            raise ValueError("selected_group_pair is only valid in multi-group mode.")
        pair = self.selected_group_pair
        if self.mode is AnalysisMode.MULTI and pair is None:
            raise ValueError(
                "selected_group_pair is required in multi-group mode."
            )
        if pair is not None:
            if len(pair) != 2:
                raise ValueError("selected_group_pair must contain exactly two IDs.")
            normalized_pair = tuple(str(value).strip() for value in pair)
            if (
                not all(normalized_pair)
                or normalized_pair[0].casefold() == normalized_pair[1].casefold()
            ):
                raise ValueError(
                    "selected_group_pair must contain two distinct group IDs."
                )
            object.__setattr__(self, "selected_group_pair", normalized_pair)
        if isinstance(self.n_resamples, bool) or int(self.n_resamples) < 1:
            raise ValueError("n_resamples must be a positive integer.")
        object.__setattr__(self, "n_resamples", int(self.n_resamples))
        if isinstance(self.seed, bool) or int(self.seed) < 0:
            raise ValueError("seed must be a non-negative integer.")
        object.__setattr__(self, "seed", int(self.seed))

    def build_run_spec(self) -> AnalysisRunSpec:
        """Build the immutable scientific settings shared by every worker."""

        return build_standard_screening_run_spec(
            profile=self.profile,
            harmonic_provenance=self.harmonic_provenance,
            alpha=self.alpha,
        )

    def sensitivity_config(self) -> dict[str, object]:
        """Return bounded worker settings without importing Qt or a worker."""

        return {
            "run_robust": bool(self.run_robust),
            "run_resampling": bool(self.run_resampling),
            "run_stability": bool(self.run_stability),
            "n_resamples": self.n_resamples,
            "seed": self.seed,
            # Harmonic independence and nested adaptive re-selection are
            # separate scientific claims. Phase 6 has no nesting attestation.
            "selection_nesting_attested": False,
        }


def pipeline_steps_for_options(
    options: NativeInferenceOptions,
) -> tuple[StepId, ...]:
    """Return the analysis-scope-specific native worker queue."""

    enabled = any(
        (
            options.run_robust,
            options.run_resampling,
            options.run_stability,
        )
    )
    pipeline_id = (
        PipelineId.MULTI
        if options.mode is AnalysisMode.MULTI
        else PipelineId.SINGLE
    )
    return tuple(
        step_id
        for step_id in PIPELINE_STEP_ORDER[pipeline_id]
        if enabled or step_id is not StepId.SENSITIVITIES
    )


def phase_label(step_id: StepId) -> str:
    """Return a short non-technical label for a pipeline step."""

    return STEP_PHASE_LABELS.get(step_id, step_id.name.replace("_", " ").title())


def overall_progress(
    pipeline_id: PipelineId,
    step_id: StepId,
    step_percent: int | float,
    *,
    step_order: tuple[StepId, ...] | None = None,
) -> int:
    """Map one worker's 0-100 progress into the full pipeline's 0-100 range."""

    order = tuple(step_order or PIPELINE_STEP_ORDER[pipeline_id])
    if not order:
        return max(0, min(100, int(round(float(step_percent)))))
    try:
        index = order.index(step_id)
    except ValueError:
        return max(0, min(100, int(round(float(step_percent)))))
    within = max(0.0, min(100.0, float(step_percent))) / 100.0
    return int(round(100.0 * (index + within) / len(order)))


__all__ = [
    "NativeInferenceOptions",
    "PIPELINE_STEP_ORDER",
    "STEP_PHASE_LABELS",
    "coerce_analysis_mode",
    "infer_harmonic_provenance",
    "overall_progress",
    "phase_label",
    "pipeline_steps_for_options",
]
