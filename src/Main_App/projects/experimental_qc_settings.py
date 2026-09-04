"""Project-owned settings for experimental QC features.

This module intentionally contains no GUI or processing imports.  It owns the
versioned project manifest record that later QC workflows consume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION = "1.0.0"
SUMMED_BCA_SCREENING_POLICY_VERSION = "1.0.0"
SUMMED_BCA_SCREENING_BRIEF_TEXT = (
    "Experimental summed-BCA screening flags unusually large frequency "
    "responses for review. These suggested limits come from FPVS Toolbox "
    "development experience and are not validated for every protocol. This "
    "check does not remove data by itself."
)


class ExperimentalQcSettingsError(ValueError):
    """Raised when project-owned experimental QC settings are invalid."""


def _finite_positive_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a finite positive number."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a finite positive number."
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a finite positive number."
        )
    return number


def _bounded_positive_integer(
    value: Any,
    *,
    field_name: str,
    maximum: int = 64,
) -> int:
    if isinstance(value, bool):
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a whole number from 1 through {maximum}."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a whole number from 1 through {maximum}."
        ) from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a whole number from 1 through {maximum}."
        )
    integer = int(number)
    if not 1 <= integer <= maximum:
        raise ExperimentalQcSettingsError(
            f"{field_name} must be a whole number from 1 through {maximum}."
        )
    return integer


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ExperimentalQcSettingsError(f"{field_name} must be true or false.")


@dataclass(frozen=True, slots=True)
class SummedBcaScreeningSettings:
    """Versioned review-only thresholds for experimental summed-BCA screening."""

    enabled: bool = True
    policy_version: str = SUMMED_BCA_SCREENING_POLICY_VERSION
    warning_summed_bca_uv: float = 10.0
    strong_warning_summed_bca_uv: float = 50.0
    extreme_review_summed_bca_uv: float = 250.0
    concentrated_review_flagged_cells: int = 5
    broad_extreme_review_unique_electrodes: int = 11
    cohort_warning_robust_score: float = 6.0
    cohort_extreme_robust_score: float = 10.0
    cohort_warning_sum_floor_uv: float = 5.0
    cohort_extreme_sum_floor_uv: float = 10.0
    cohort_warning_peak_floor_uv: float = 1.0
    cohort_extreme_peak_floor_uv: float = 2.0

    def __post_init__(self) -> None:
        enabled = _coerce_bool(self.enabled, field_name="enabled")
        policy_version = str(self.policy_version or "").strip()
        if policy_version != SUMMED_BCA_SCREENING_POLICY_VERSION:
            raise ExperimentalQcSettingsError(
                "Unsupported summed-BCA screening policy version "
                f"{self.policy_version!r}; expected "
                f"{SUMMED_BCA_SCREENING_POLICY_VERSION!r}."
            )

        warning = _finite_positive_float(
            self.warning_summed_bca_uv,
            field_name="warning_summed_bca_uv",
        )
        strong = _finite_positive_float(
            self.strong_warning_summed_bca_uv,
            field_name="strong_warning_summed_bca_uv",
        )
        extreme = _finite_positive_float(
            self.extreme_review_summed_bca_uv,
            field_name="extreme_review_summed_bca_uv",
        )
        if not warning < strong < extreme:
            raise ExperimentalQcSettingsError(
                "Summed-BCA amplitude thresholds must satisfy warning < "
                "strong warning < extreme review."
            )

        concentrated = _bounded_positive_integer(
            self.concentrated_review_flagged_cells,
            field_name="concentrated_review_flagged_cells",
        )
        broad = _bounded_positive_integer(
            self.broad_extreme_review_unique_electrodes,
            field_name="broad_extreme_review_unique_electrodes",
        )

        robust_warning = _finite_positive_float(
            self.cohort_warning_robust_score,
            field_name="cohort_warning_robust_score",
        )
        robust_extreme = _finite_positive_float(
            self.cohort_extreme_robust_score,
            field_name="cohort_extreme_robust_score",
        )
        sum_warning = _finite_positive_float(
            self.cohort_warning_sum_floor_uv,
            field_name="cohort_warning_sum_floor_uv",
        )
        sum_extreme = _finite_positive_float(
            self.cohort_extreme_sum_floor_uv,
            field_name="cohort_extreme_sum_floor_uv",
        )
        peak_warning = _finite_positive_float(
            self.cohort_warning_peak_floor_uv,
            field_name="cohort_warning_peak_floor_uv",
        )
        peak_extreme = _finite_positive_float(
            self.cohort_extreme_peak_floor_uv,
            field_name="cohort_extreme_peak_floor_uv",
        )
        ordered_pairs = (
            (robust_warning, robust_extreme, "cohort robust-score"),
            (sum_warning, sum_extreme, "cohort summed-BCA floor"),
            (peak_warning, peak_extreme, "cohort peak floor"),
        )
        for lower, upper, label in ordered_pairs:
            if lower >= upper:
                raise ExperimentalQcSettingsError(
                    f"The {label} warning value must be below its extreme value."
                )

        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "warning_summed_bca_uv", warning)
        object.__setattr__(self, "strong_warning_summed_bca_uv", strong)
        object.__setattr__(self, "extreme_review_summed_bca_uv", extreme)
        object.__setattr__(
            self,
            "concentrated_review_flagged_cells",
            concentrated,
        )
        object.__setattr__(
            self,
            "broad_extreme_review_unique_electrodes",
            broad,
        )
        object.__setattr__(self, "cohort_warning_robust_score", robust_warning)
        object.__setattr__(self, "cohort_extreme_robust_score", robust_extreme)
        object.__setattr__(self, "cohort_warning_sum_floor_uv", sum_warning)
        object.__setattr__(self, "cohort_extreme_sum_floor_uv", sum_extreme)
        object.__setattr__(self, "cohort_warning_peak_floor_uv", peak_warning)
        object.__setattr__(self, "cohort_extreme_peak_floor_uv", peak_extreme)

    @classmethod
    def from_manifest(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> "SummedBcaScreeningSettings":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ExperimentalQcSettingsError(
                "summed_bca_screening must be a JSON object."
            )
        defaults = cls()
        return cls(
            enabled=raw.get("enabled", defaults.enabled),
            policy_version=raw.get("policy_version", defaults.policy_version),
            warning_summed_bca_uv=raw.get(
                "warning_summed_bca_uv",
                defaults.warning_summed_bca_uv,
            ),
            strong_warning_summed_bca_uv=raw.get(
                "strong_warning_summed_bca_uv",
                defaults.strong_warning_summed_bca_uv,
            ),
            extreme_review_summed_bca_uv=raw.get(
                "extreme_review_summed_bca_uv",
                defaults.extreme_review_summed_bca_uv,
            ),
            concentrated_review_flagged_cells=raw.get(
                "concentrated_review_flagged_cells",
                defaults.concentrated_review_flagged_cells,
            ),
            broad_extreme_review_unique_electrodes=raw.get(
                "broad_extreme_review_unique_electrodes",
                defaults.broad_extreme_review_unique_electrodes,
            ),
            cohort_warning_robust_score=raw.get(
                "cohort_warning_robust_score",
                defaults.cohort_warning_robust_score,
            ),
            cohort_extreme_robust_score=raw.get(
                "cohort_extreme_robust_score",
                defaults.cohort_extreme_robust_score,
            ),
            cohort_warning_sum_floor_uv=raw.get(
                "cohort_warning_sum_floor_uv",
                defaults.cohort_warning_sum_floor_uv,
            ),
            cohort_extreme_sum_floor_uv=raw.get(
                "cohort_extreme_sum_floor_uv",
                defaults.cohort_extreme_sum_floor_uv,
            ),
            cohort_warning_peak_floor_uv=raw.get(
                "cohort_warning_peak_floor_uv",
                defaults.cohort_warning_peak_floor_uv,
            ),
            cohort_extreme_peak_floor_uv=raw.get(
                "cohort_extreme_peak_floor_uv",
                defaults.cohort_extreme_peak_floor_uv,
            ),
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "policy_version": self.policy_version,
            "warning_summed_bca_uv": self.warning_summed_bca_uv,
            "strong_warning_summed_bca_uv": self.strong_warning_summed_bca_uv,
            "extreme_review_summed_bca_uv": self.extreme_review_summed_bca_uv,
            "concentrated_review_flagged_cells": (
                self.concentrated_review_flagged_cells
            ),
            "broad_extreme_review_unique_electrodes": (
                self.broad_extreme_review_unique_electrodes
            ),
            "cohort_warning_robust_score": self.cohort_warning_robust_score,
            "cohort_extreme_robust_score": self.cohort_extreme_robust_score,
            "cohort_warning_sum_floor_uv": self.cohort_warning_sum_floor_uv,
            "cohort_extreme_sum_floor_uv": self.cohort_extreme_sum_floor_uv,
            "cohort_warning_peak_floor_uv": self.cohort_warning_peak_floor_uv,
            "cohort_extreme_peak_floor_uv": self.cohort_extreme_peak_floor_uv,
        }


@dataclass(frozen=True, slots=True)
class ExperimentalQcSettings:
    """Top-level project manifest settings for experimental QC features."""

    schema_version: str = EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION
    summed_bca_screening: SummedBcaScreeningSettings = field(
        default_factory=SummedBcaScreeningSettings
    )

    def __post_init__(self) -> None:
        schema_version = str(self.schema_version or "").strip()
        if schema_version != EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION:
            raise ExperimentalQcSettingsError(
                "Unsupported experimental QC settings schema version "
                f"{self.schema_version!r}; expected "
                f"{EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION!r}."
            )
        screening = normalize_summed_bca_screening_settings(
            self.summed_bca_screening
        )
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "summed_bca_screening", screening)

    @classmethod
    def from_manifest(cls, raw: Mapping[str, Any]) -> "ExperimentalQcSettings":
        if not isinstance(raw, Mapping):
            raise ExperimentalQcSettingsError(
                "experimental_qc must be a JSON object."
            )
        return cls(
            schema_version=raw.get(
                "schema_version",
                EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
            ),
            summed_bca_screening=SummedBcaScreeningSettings.from_manifest(
                raw.get("summed_bca_screening")
            ),
        )

    def with_summed_bca_screening(
        self,
        value: SummedBcaScreeningSettings | Mapping[str, Any],
    ) -> "ExperimentalQcSettings":
        return replace(
            self,
            summed_bca_screening=normalize_summed_bca_screening_settings(value),
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summed_bca_screening": self.summed_bca_screening.to_manifest(),
        }


def normalize_summed_bca_screening_settings(
    value: SummedBcaScreeningSettings | Mapping[str, Any] | None,
) -> SummedBcaScreeningSettings:
    if isinstance(value, SummedBcaScreeningSettings):
        return value
    return SummedBcaScreeningSettings.from_manifest(value)


def normalize_experimental_qc_settings(
    value: ExperimentalQcSettings | Mapping[str, Any] | None,
) -> ExperimentalQcSettings:
    if isinstance(value, ExperimentalQcSettings):
        return value
    if value is None:
        return ExperimentalQcSettings()
    return ExperimentalQcSettings.from_manifest(value)


__all__ = [
    "EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION",
    "SUMMED_BCA_SCREENING_BRIEF_TEXT",
    "SUMMED_BCA_SCREENING_POLICY_VERSION",
    "ExperimentalQcSettings",
    "ExperimentalQcSettingsError",
    "SummedBcaScreeningSettings",
    "normalize_experimental_qc_settings",
    "normalize_summed_bca_screening_settings",
]
