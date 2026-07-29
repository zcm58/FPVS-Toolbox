"""Method-aware agreement summaries for statistical sensitivity analyses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


SENSITIVITY_SUMMARY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SensitivityConclusion:
    """One normalized inferential conclusion used in an agreement check."""

    method_id: str
    method_label: str
    estimand: str
    supported: bool | None
    status: str = "estimated"
    direction: str | None = None

    def __post_init__(self) -> None:
        for name in ("method_id", "method_label", "estimand", "status"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must be non-empty.")
            object.__setattr__(self, name, value)
        if self.supported is not None and not isinstance(self.supported, bool):
            raise TypeError("supported must be True, False, or None.")
        if self.direction is not None:
            direction = str(self.direction).strip()
            object.__setattr__(self, "direction", direction or None)

    @property
    def estimable(self) -> bool:
        """Return whether this conclusion can participate in agreement checks."""

        return self.status.casefold() in {
            "estimated",
            "estimable",
            "ok",
        } and self.supported is not None


@dataclass(frozen=True, slots=True)
class SensitivityAgreement:
    """Plain-language and table-ready sensitivity agreement result."""

    status: str
    plain_language: str
    primary: SensitivityConclusion
    sensitivities: tuple[SensitivityConclusion, ...]

    @property
    def method_dependent(self) -> bool:
        return self.status == "method_dependent"

    def to_frame(self) -> pd.DataFrame:
        """Return one explicit row per method with shared interpretation fields."""

        rows = []
        for role, conclusion in (
            ("primary", self.primary),
            *(("sensitivity", item) for item in self.sensitivities),
        ):
            rows.append(
                {
                    "sensitivity_summary_schema_version": (
                        SENSITIVITY_SUMMARY_SCHEMA_VERSION
                    ),
                    "role": role,
                    "method_id": conclusion.method_id,
                    "method_label": conclusion.method_label,
                    "estimand": conclusion.estimand,
                    "method_status": conclusion.status,
                    "estimable": conclusion.estimable,
                    "supported": conclusion.supported,
                    "direction": conclusion.direction,
                    "agreement_status": self.status,
                    "method_dependent": self.method_dependent,
                    "plain_language": self.plain_language,
                }
            )
        return pd.DataFrame(rows)


def summarize_sensitivity_agreement(
    primary: SensitivityConclusion,
    sensitivities: Iterable[SensitivityConclusion],
) -> SensitivityAgreement:
    """Compare conclusions without pretending different estimands are identical."""

    if not isinstance(primary, SensitivityConclusion):
        raise TypeError("primary must be a SensitivityConclusion.")
    normalized = tuple(sensitivities)
    if not all(isinstance(item, SensitivityConclusion) for item in normalized):
        raise TypeError("sensitivities must contain SensitivityConclusion records.")

    if not primary.estimable:
        return SensitivityAgreement(
            status="primary_not_estimable",
            plain_language=(
                "The primary result was not estimable, so sensitivity methods "
                "cannot confirm or overturn a primary conclusion."
            ),
            primary=primary,
            sensitivities=normalized,
        )

    estimable = tuple(item for item in normalized if item.estimable)
    if not estimable:
        return SensitivityAgreement(
            status="no_estimable_sensitivities",
            plain_language=(
                "No sensitivity analysis was estimable, so stability across "
                "methods could not be assessed."
            ),
            primary=primary,
            sensitivities=normalized,
        )

    supported = tuple(item for item in estimable if item.supported)
    unsupported = tuple(item for item in estimable if not item.supported)
    threshold_agrees = all(
        item.supported is primary.supported for item in estimable
    )
    distinct_estimands = {
        item.estimand.casefold() for item in (primary, *estimable)
    }
    estimand_note = (
        " These methods target related but not identical estimands."
        if len(distinct_estimands) > 1
        else ""
    )

    if threshold_agrees and primary.supported:
        direction_records = (primary, *estimable)
        directions_known = all(
            item.direction is not None for item in direction_records
        )
        direction_keys = {
            str(item.direction).casefold()
            for item in direction_records
            if item.direction is not None
        }
        if directions_known and len(direction_keys) > 1:
            direction_text = "; ".join(
                f"{item.method_label}: {item.direction}"
                for item in direction_records
            )
            return SensitivityAgreement(
                status="method_dependent",
                plain_language=(
                    "The conclusion depended on the analysis method. All "
                    "estimable methods met the prespecified evidence threshold, "
                    f"but their estimated directions differed ({direction_text})."
                    f"{estimand_note}"
                ),
                primary=primary,
                sensitivities=normalized,
            )
        if not directions_known:
            return SensitivityAgreement(
                status="consistent_threshold_only",
                plain_language=(
                    "The primary and sensitivity analyses all met the "
                    "prespecified evidence threshold, but effect-direction "
                    f"agreement was not fully specified.{estimand_note}"
                ),
                primary=primary,
                sensitivities=normalized,
            )

    if threshold_agrees:
        direction = (
            "supported the same conclusion"
            if primary.supported
            else "also did not meet the prespecified evidence threshold"
        )
        language = (
            f"The estimable sensitivity analyses {direction} as the primary "
            f"{primary.method_label} analysis.{estimand_note}"
        )
        return SensitivityAgreement(
            status="consistent",
            plain_language=language,
            primary=primary,
            sensitivities=normalized,
        )

    supporting_labels = ", ".join(
        item.method_label for item in ((primary,) if primary.supported else ()) + supported
    )
    nonsupporting_labels = ", ".join(
        item.method_label
        for item in ((primary,) if not primary.supported else ()) + unsupported
    )
    language = (
        "The conclusion depended on the analysis method. "
        f"Evidence met the prespecified threshold for {supporting_labels}; "
        f"it did not for {nonsupporting_labels}.{estimand_note}"
    )
    return SensitivityAgreement(
        status="method_dependent",
        plain_language=language,
        primary=primary,
        sensitivities=normalized,
    )


__all__ = [
    "SENSITIVITY_SUMMARY_SCHEMA_VERSION",
    "SensitivityAgreement",
    "SensitivityConclusion",
    "summarize_sensitivity_agreement",
]
