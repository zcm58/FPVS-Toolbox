"""GUI-neutral configuration and progress helpers for native Stats inference."""

from __future__ import annotations

from dataclasses import dataclass

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    FollowupProvenance,
    HarmonicProvenance,
)
from Tools.Stats.analysis.prepared_analysis import AnalysisMode
from Tools.Stats.common.stats_core import PipelineId, StepId


PIPELINE_STEP_ORDER: dict[PipelineId, tuple[StepId, ...]] = {
    PipelineId.SINGLE: (
        StepId.PREPARE_ANALYSIS,
        StepId.RM_ANOVA,
        StepId.MIXED_MODEL,
        StepId.INTERACTION_POSTHOCS,
        StepId.BASELINE_VS_ZERO,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ),
    PipelineId.MULTI: (
        StepId.PREPARE_ANALYSIS,
        StepId.MULTIGROUP_MODEL,
        StepId.GROUP_CELL_COMPARISONS,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ),
}

STEP_PHASE_LABELS: dict[StepId, str] = {
    StepId.PREPARE_ANALYSIS: "Preparing and checking the shared dataset",
    StepId.RM_ANOVA: "Running the repeated-measures ANOVA",
    StepId.MIXED_MODEL: "Fitting the single-group mixed model",
    StepId.INTERACTION_POSTHOCS: "Running interaction follow-up comparisons",
    StepId.BASELINE_VS_ZERO: "Testing responses against zero",
    StepId.MULTIGROUP_MODEL: "Fitting the multi-group mixed model",
    StepId.GROUP_CELL_COMPARISONS: "Comparing groups within condition × ROI cells",
    StepId.SENSITIVITIES: "Running robust and resampling checks",
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
    analysis_scope: str = "complete_core"
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
        alpha = float(self.alpha)
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1.")
        object.__setattr__(self, "alpha", alpha)
        scope = _normalized_token(self.analysis_scope)
        if scope != "complete_core":
            raise ValueError(
                "The native analysis currently supports complete-core coverage only."
            )
        object.__setattr__(self, "analysis_scope", scope)
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

        families = [
            FamilySpec(
                family_id="response_core_cells",
                family_label="Response-versus-zero condition × ROI tests",
                method=self.correction,
                alpha=self.alpha,
            ),
            FamilySpec(
                family_id="group_core_cells",
                family_label="Group contrasts across condition × ROI cells",
                method=self.correction,
                alpha=self.alpha,
            ),
            FamilySpec(
                family_id="planned_contrasts",
                family_label="Condition × ROI interaction follow-ups",
                method=self.correction,
                alpha=self.alpha,
            ),
        ]
        if self.strict_omnibus_family:
            families.append(
                FamilySpec(
                    family_id="omnibus_effects_strict",
                    family_label="Primary factorial omnibus effects",
                    method=self.correction,
                    alpha=self.alpha,
                )
            )
        return AnalysisRunSpec(
            profile=self.profile,
            harmonic_provenance=self.harmonic_provenance,
            alpha=self.alpha,
            response_alternative=self.alternative,
            families=tuple(families),
            followup_provenance=(
                FollowupProvenance.OMNIBUS_TRIGGERED
                if self.strict_omnibus_family
                else FollowupProvenance.EXPLORATORY_MANUAL
            ),
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
    """Return the native queue, omitting sensitivity work only when disabled."""

    enabled = any(
        (
            options.run_robust,
            options.run_resampling,
            options.run_stability,
        )
    )
    return tuple(
        step_id
        for step_id in PIPELINE_STEP_ORDER[
            (
                PipelineId.MULTI
                if options.mode is AnalysisMode.MULTI
                else PipelineId.SINGLE
            )
        ]
        if enabled or step_id is not StepId.SENSITIVITIES
    )


def phase_label(step_id: StepId) -> str:
    """Return a short non-technical label for a pipeline step."""

    return STEP_PHASE_LABELS.get(step_id, step_id.name.replace("_", " ").title())


def overall_progress(
    pipeline_id: PipelineId,
    step_id: StepId,
    step_percent: int | float,
) -> int:
    """Map one worker's 0-100 progress into the full pipeline's 0-100 range."""

    order = PIPELINE_STEP_ORDER[pipeline_id]
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
