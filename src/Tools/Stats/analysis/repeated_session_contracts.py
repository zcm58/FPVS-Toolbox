"""Versioned scientific contract for two-visit repeated-session inference.

This contract is intentionally separate from Standard FPVS Screening.  It
defines a narrow complete-pair analysis for exactly two stable participant
groups and exactly two ordered recording sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from Tools.Stats.analysis.inference_contracts import CorrectionMethod, FamilySpec


REPEATED_SESSION_INFERENCE_CONTRACT_VERSION = "1.0.0"
SESSION_PHASE_AT_VISIT_TERM = "session/phase-at-visit"
FIXED_ORDER_CONFOUNDING = (
    "Session/phase-at-visit is perfectly aligned with visit order in this design; "
    "the contrast cannot isolate physiological phase from order, elapsed time, "
    "repetition, practice, or habituation."
)
PRIMARY_DELTA_FAMILY_ID = "repeated_session_primary_delta_groups"
SECONDARY_CHANGE_FAMILY_ID = "repeated_session_secondary_within_groups"


def _two_nonempty_strings(values: object, *, field: str) -> tuple[str, str]:
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise ValueError(f"{field} must contain exactly two values.")
    normalized = tuple(str(value).strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{field} values must be non-empty.")
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RepeatedSessionInferenceContract:
    """Locked inputs and labels for repeated-session inference version 1."""

    group_ids: tuple[str, str]
    session_ids: tuple[str, str]
    session_labels: tuple[str, str]
    group_labels: tuple[str, str] | None = None
    visit_indices: tuple[int, int] = (1, 2)
    alpha: float = 0.05

    def __post_init__(self) -> None:
        group_ids = _two_nonempty_strings(self.group_ids, field="group_ids")
        session_ids = _two_nonempty_strings(self.session_ids, field="session_ids")
        session_labels = _two_nonempty_strings(
            self.session_labels,
            field="session_labels",
        )
        group_labels = (
            group_ids
            if self.group_labels is None
            else _two_nonempty_strings(self.group_labels, field="group_labels")
        )
        if group_ids[0].casefold() == group_ids[1].casefold():
            raise ValueError("group_ids must identify two distinct stable groups.")
        if session_ids[0].casefold() == session_ids[1].casefold():
            raise ValueError("session_ids must identify two distinct sessions.")
        if session_labels[0].casefold() == session_labels[1].casefold():
            raise ValueError("session_labels must distinguish the two sessions.")
        if tuple(self.visit_indices) != (1, 2):
            raise ValueError(
                "Repeated-session inference version 1 requires visit_indices=(1, 2)."
            )
        try:
            alpha = float(self.alpha)
        except (TypeError, ValueError) as exc:
            raise ValueError("alpha must be numeric and strictly between 0 and 1.") from exc
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1.")

        object.__setattr__(self, "group_ids", group_ids)
        object.__setattr__(self, "session_ids", session_ids)
        object.__setattr__(self, "session_labels", session_labels)
        object.__setattr__(self, "group_labels", group_labels)
        object.__setattr__(self, "visit_indices", (1, 2))
        object.__setattr__(self, "alpha", alpha)

    @property
    def schema_version(self) -> str:
        return REPEATED_SESSION_INFERENCE_CONTRACT_VERSION

    @property
    def group_label_map(self) -> dict[str, str]:
        assert self.group_labels is not None
        return dict(zip(self.group_ids, self.group_labels))

    @property
    def session_label_map(self) -> dict[str, str]:
        return dict(zip(self.session_ids, self.session_labels))

    @property
    def session_visit_map(self) -> dict[str, int]:
        return dict(zip(self.session_ids, self.visit_indices))

    @property
    def session_contrast_label(self) -> str:
        return (
            f"{SESSION_PHASE_AT_VISIT_TERM}: visit 2 ({self.session_labels[1]}) "
            f"minus visit 1 ({self.session_labels[0]})"
        )

    @property
    def primary_family(self) -> FamilySpec:
        return FamilySpec(
            family_id=PRIMARY_DELTA_FAMILY_ID,
            family_label=(
                "Primary between-group comparisons of participant "
                f"{SESSION_PHASE_AT_VISIT_TERM} deltas"
            ),
            method=CorrectionMethod.HOLM,
            alpha=self.alpha,
        )

    @property
    def secondary_family(self) -> FamilySpec:
        return FamilySpec(
            family_id=SECONDARY_CHANGE_FAMILY_ID,
            family_label=(
                "Secondary paired within-group "
                f"{SESSION_PHASE_AT_VISIT_TERM} changes"
            ),
            method=CorrectionMethod.HOLM,
            alpha=self.alpha,
        )

    def to_metadata(self) -> dict[str, object]:
        """Return stable, workbook-ready contract metadata."""

        assert self.group_labels is not None
        return {
            "repeated_session_inference_contract_version": self.schema_version,
            "analysis_label": f"Repeated {SESSION_PHASE_AT_VISIT_TERM} change analysis",
            "group_1_id": self.group_ids[0],
            "group_1_label": self.group_labels[0],
            "group_2_id": self.group_ids[1],
            "group_2_label": self.group_labels[1],
            "visit_1_session_id": self.session_ids[0],
            "visit_1_session_label": self.session_labels[0],
            "visit_2_session_id": self.session_ids[1],
            "visit_2_session_label": self.session_labels[1],
            "session_contrast_label": self.session_contrast_label,
            "primary_estimand": (
                "Group 1 minus Group 2 in participant "
                f"{SESSION_PHASE_AT_VISIT_TERM} delta"
            ),
            "secondary_estimand": (
                f"Paired within-group {SESSION_PHASE_AT_VISIT_TERM} change"
            ),
            "primary_test": "two-sided Welch comparison of participant deltas",
            "secondary_test": "two-sided one-sample t-test of paired deltas",
            "primary_correction_family": self.primary_family.family_id,
            "secondary_correction_family": self.secondary_family.family_id,
            "correction_method": CorrectionMethod.HOLM.value,
            "alpha": self.alpha,
            "missing_data_handling": (
                "complete observed pair per declared Condition x ROI outcome; "
                "no imputation and no cross-outcome participant deletion"
            ),
            "fixed_order_confounding": FIXED_ORDER_CONFOUNDING,
            "fallback_method": "none",
        }

    def to_metadata_frame(self) -> pd.DataFrame:
        return pd.DataFrame([self.to_metadata()])


__all__ = [
    "FIXED_ORDER_CONFOUNDING",
    "PRIMARY_DELTA_FAMILY_ID",
    "REPEATED_SESSION_INFERENCE_CONTRACT_VERSION",
    "SECONDARY_CHANGE_FAMILY_ID",
    "SESSION_PHASE_AT_VISIT_TERM",
    "RepeatedSessionInferenceContract",
]
