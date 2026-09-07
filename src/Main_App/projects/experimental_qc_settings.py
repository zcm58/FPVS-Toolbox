"""Project-owned settings for experimental QC features.

This module intentionally contains no GUI or processing imports.  It owns the
versioned project manifest record that later QC workflows consume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION = "1.2.0"
LEGACY_EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION = "1.0.0"
SUMMED_BCA_SCREENING_POLICY_VERSION = "1.0.0"
RAW_SPECTRAL_SCREENING_POLICY_VERSION = "1.0.0"
SUMMED_BCA_SCREENING_BRIEF_TEXT = (
    "Experimental summed-BCA screening flags unusually large frequency "
    "responses for review. These suggested limits come from FPVS Toolbox "
    "development experience and are not validated for every protocol. This "
    "check does not remove data by itself."
)
RAW_SPECTRAL_SCREENING_BRIEF_TEXT = (
    "Experimental. Flags unusually large narrow-frequency signals in each "
    "analyzed condition for review. Thresholds are provisional, and this "
    "check never removes data automatically."
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
        # Retired ROI cohort thresholds in older manifests are ignored.
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
        }


@dataclass(frozen=True, slots=True)
class RawSpectralScreeningSettings:
    """Locked, review-only settings for condition raw-spectral screening.

    The numerical values are persisted so reports and cache identities reproduce
    the effective screen. They are deliberately locked to ``policy_version``;
    changing them requires a new calibrated policy instead of an untracked
    project-specific threshold edit.
    """

    enabled: bool = True
    policy_version: str = RAW_SPECTRAL_SCREENING_POLICY_VERSION
    minimum_frequency_hz: float = 0.5
    minimum_legacy_hann_spectrum_score: float = 250.0
    minimum_local_mean_ratio: float = 25.0
    minimum_local_standardized_score: float = 12.0
    widespread_channel_fraction: float = 0.75
    widespread_min_channels: int = 48
    notch_half_width_hz: float = 0.5
    noise_window_bins: int = 12
    noise_candidate_bins: int = 22
    noise_retained_bins: int = 20

    def __post_init__(self) -> None:
        enabled = _coerce_bool(self.enabled, field_name="enabled")
        policy_version = str(self.policy_version or "").strip()
        if policy_version != RAW_SPECTRAL_SCREENING_POLICY_VERSION:
            raise ExperimentalQcSettingsError(
                "Unsupported raw-spectral screening policy version "
                f"{self.policy_version!r}; expected "
                f"{RAW_SPECTRAL_SCREENING_POLICY_VERSION!r}."
            )

        locked_values: tuple[tuple[str, object, object], ...] = (
            ("minimum_frequency_hz", self.minimum_frequency_hz, 0.5),
            (
                "minimum_legacy_hann_spectrum_score",
                self.minimum_legacy_hann_spectrum_score,
                250.0,
            ),
            ("minimum_local_mean_ratio", self.minimum_local_mean_ratio, 25.0),
            (
                "minimum_local_standardized_score",
                self.minimum_local_standardized_score,
                12.0,
            ),
            ("widespread_channel_fraction", self.widespread_channel_fraction, 0.75),
            ("widespread_min_channels", self.widespread_min_channels, 48),
            ("notch_half_width_hz", self.notch_half_width_hz, 0.5),
            ("noise_window_bins", self.noise_window_bins, 12),
            ("noise_candidate_bins", self.noise_candidate_bins, 22),
            ("noise_retained_bins", self.noise_retained_bins, 20),
        )
        for field_name, value, expected in locked_values:
            if isinstance(expected, int):
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError) as exc:
                    raise ExperimentalQcSettingsError(
                        f"{field_name} must equal the locked value {expected}."
                    ) from exc
                if (
                    isinstance(value, bool)
                    or not math.isfinite(numeric_value)
                    or not numeric_value.is_integer()
                    or int(numeric_value) != expected
                ):
                    raise ExperimentalQcSettingsError(
                        f"{field_name} must equal the locked value {expected}."
                    )
            else:
                try:
                    normalized = float(value)
                except (TypeError, ValueError) as exc:
                    raise ExperimentalQcSettingsError(
                        f"{field_name} must equal the locked value {expected}."
                    ) from exc
                if not math.isfinite(normalized) or normalized != expected:
                    raise ExperimentalQcSettingsError(
                        f"{field_name} must equal the locked value {expected}."
                    )
            object.__setattr__(self, field_name, expected)

        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "policy_version", policy_version)

    @classmethod
    def from_manifest(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> "RawSpectralScreeningSettings":
        if raw is None:
            # Missing legacy state migrates to On because this feature was
            # already evaluated and remains review-only.
            return cls()
        if not isinstance(raw, Mapping):
            raise ExperimentalQcSettingsError(
                "raw_spectral_screening must be a JSON object."
            )
        defaults = cls()
        return cls(
            enabled=raw.get("enabled", defaults.enabled),
            policy_version=raw.get("policy_version", defaults.policy_version),
            minimum_frequency_hz=raw.get(
                "minimum_frequency_hz", defaults.minimum_frequency_hz
            ),
            minimum_legacy_hann_spectrum_score=raw.get(
                "minimum_legacy_hann_spectrum_score",
                defaults.minimum_legacy_hann_spectrum_score,
            ),
            minimum_local_mean_ratio=raw.get(
                "minimum_local_mean_ratio", defaults.minimum_local_mean_ratio
            ),
            minimum_local_standardized_score=raw.get(
                "minimum_local_standardized_score",
                defaults.minimum_local_standardized_score,
            ),
            widespread_channel_fraction=raw.get(
                "widespread_channel_fraction",
                defaults.widespread_channel_fraction,
            ),
            widespread_min_channels=raw.get(
                "widespread_min_channels", defaults.widespread_min_channels
            ),
            notch_half_width_hz=raw.get(
                "notch_half_width_hz", defaults.notch_half_width_hz
            ),
            noise_window_bins=raw.get(
                "noise_window_bins", defaults.noise_window_bins
            ),
            noise_candidate_bins=raw.get(
                "noise_candidate_bins", defaults.noise_candidate_bins
            ),
            noise_retained_bins=raw.get(
                "noise_retained_bins", defaults.noise_retained_bins
            ),
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "policy_version": self.policy_version,
            "minimum_frequency_hz": self.minimum_frequency_hz,
            "minimum_legacy_hann_spectrum_score": (
                self.minimum_legacy_hann_spectrum_score
            ),
            "minimum_local_mean_ratio": self.minimum_local_mean_ratio,
            "minimum_local_standardized_score": (
                self.minimum_local_standardized_score
            ),
            "widespread_channel_fraction": self.widespread_channel_fraction,
            "widespread_min_channels": self.widespread_min_channels,
            "notch_half_width_hz": self.notch_half_width_hz,
            "noise_window_bins": self.noise_window_bins,
            "noise_candidate_bins": self.noise_candidate_bins,
            "noise_retained_bins": self.noise_retained_bins,
        }

    def with_enabled(self, enabled: bool) -> "RawSpectralScreeningSettings":
        return replace(self, enabled=enabled)


@dataclass(frozen=True, slots=True)
class ExperimentalQcSettings:
    """Top-level project manifest settings for experimental QC features."""

    schema_version: str = EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION
    summed_bca_screening: SummedBcaScreeningSettings = field(
        default_factory=SummedBcaScreeningSettings
    )
    raw_spectral_screening: RawSpectralScreeningSettings = field(
        default_factory=RawSpectralScreeningSettings
    )
    condition_specific_interpolation_enabled: bool = False

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
        raw_spectral = normalize_raw_spectral_screening_settings(
            self.raw_spectral_screening
        )
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "summed_bca_screening", screening)
        object.__setattr__(self, "raw_spectral_screening", raw_spectral)
        object.__setattr__(
            self, "condition_specific_interpolation_enabled",
            _coerce_bool(
                self.condition_specific_interpolation_enabled,
                field_name="condition_specific_interpolation_enabled",
            ),
        )

    @classmethod
    def from_manifest(cls, raw: Mapping[str, Any]) -> "ExperimentalQcSettings":
        if not isinstance(raw, Mapping):
            raise ExperimentalQcSettingsError(
                "experimental_qc must be a JSON object."
            )
        schema_version = str(
            raw.get("schema_version", EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION)
            or ""
        ).strip()
        if schema_version not in {
            LEGACY_EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
            "1.1.0",
            EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
        }:
            raise ExperimentalQcSettingsError(
                "Unsupported experimental QC settings schema version "
                f"{schema_version!r}; expected "
                f"{EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION!r}."
            )
        return cls(
            schema_version=EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
            summed_bca_screening=SummedBcaScreeningSettings.from_manifest(
                raw.get("summed_bca_screening")
            ),
            raw_spectral_screening=RawSpectralScreeningSettings.from_manifest(
                raw.get("raw_spectral_screening")
            ),
            condition_specific_interpolation_enabled=raw.get(
                "condition_specific_interpolation_enabled", False
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

    def with_raw_spectral_screening(
        self,
        value: RawSpectralScreeningSettings | Mapping[str, Any],
    ) -> "ExperimentalQcSettings":
        return replace(
            self,
            raw_spectral_screening=normalize_raw_spectral_screening_settings(value),
        )

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "summed_bca_screening": self.summed_bca_screening.to_manifest(),
            "raw_spectral_screening": self.raw_spectral_screening.to_manifest(),
            "condition_specific_interpolation_enabled": (
                self.condition_specific_interpolation_enabled
            ),
        }

    def with_condition_specific_interpolation_enabled(
        self, enabled: bool,
    ) -> "ExperimentalQcSettings":
        return replace(self, condition_specific_interpolation_enabled=enabled)


def normalize_summed_bca_screening_settings(
    value: SummedBcaScreeningSettings | Mapping[str, Any] | None,
) -> SummedBcaScreeningSettings:
    if isinstance(value, SummedBcaScreeningSettings):
        return value
    return SummedBcaScreeningSettings.from_manifest(value)


def normalize_raw_spectral_screening_settings(
    value: RawSpectralScreeningSettings | Mapping[str, Any] | None,
) -> RawSpectralScreeningSettings:
    if isinstance(value, RawSpectralScreeningSettings):
        return value
    return RawSpectralScreeningSettings.from_manifest(value)


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
    "LEGACY_EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION",
    "RAW_SPECTRAL_SCREENING_BRIEF_TEXT",
    "RAW_SPECTRAL_SCREENING_POLICY_VERSION",
    "SUMMED_BCA_SCREENING_BRIEF_TEXT",
    "SUMMED_BCA_SCREENING_POLICY_VERSION",
    "ExperimentalQcSettings",
    "ExperimentalQcSettingsError",
    "RawSpectralScreeningSettings",
    "SummedBcaScreeningSettings",
    "normalize_experimental_qc_settings",
    "normalize_raw_spectral_screening_settings",
    "normalize_summed_bca_screening_settings",
]
