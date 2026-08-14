"""Settings and versioned method profiles for Stats Summed-BCA policies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

from Main_App import SettingsManager

FIXED_PREDEFINED_POLICY_NAME = "Fixed / predefined harmonic list"
FIXED_PREDEFINED_POLICY_ID = "fixed_predefined_harmonic_list"
FIXED_PREDEFINED_POLICY_LABEL = (
    "Fixed predefined harmonic list applied uniformly across participants, conditions, and ROIs"
)
FIXED_PREDEFINED_DEFAULT_FREQUENCIES = "1.2, 2.4, 3.6, 4.8, 7.2"
FIXED_PREDEFINED_BASE_OVERLAP_TOLERANCE_HZ = 0.01
FIXED_PREDEFINED_MATCHING_TOLERANCE_HZ = 0.01
FIXED_HARMONIC_INPUT_FREQUENCY_LIST = "frequency_list"
FIXED_HARMONIC_INPUT_UPPER_HARMONIC = "upper_harmonic_index"
FIXED_HARMONIC_INPUT_UPPER_FREQUENCY = "upper_frequency_hz"
GROUP_SIGNIFICANT_POLICY_NAME = "Group-level significant harmonics (Volfart/Retter/Rossion style)"
GROUP_SIGNIFICANT_POLICY_ID = "group_level_significant_harmonics"
GROUP_SIGNIFICANT_POLICY_LABEL = (
    "Group-level significant oddball harmonics from a grand-averaged amplitude spectrum"
)
GROUP_SIGNIFICANT_Z_THRESHOLD = 1.64
GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL = "all_scalp_electrodes"
GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION = "union_roi_electrodes"
GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN = "frozen_selection_electrodes"
GROUP_SIGNIFICANT_ELECTRODE_SCOPE = GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION
GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY = "significant_only"
GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST = "through_highest_significant"
GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES = "two_consecutive_failures"
GROUP_SIGNIFICANT_SUMMATION_METHOD = GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
LOCKED_ODDBALL_FREQUENCY_HZ = 1.2

HARMONIC_PROFILE_LEGACY_ID = "legacy_fpvs_toolbox"
HARMONIC_PROFILE_FIXED_ID = "fixed_preregistered_domain"
HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID = "significant_only_exploratory"
HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID = (
    "dzhelyova_poncet_two_consecutive_failures"
)
HARMONIC_PROFILE_VERSION_1 = "1.0"
LEGACY_HARMONIC_PROFILE_ID = HARMONIC_PROFILE_LEGACY_ID
NEW_PROJECT_HARMONIC_PROFILE_ID = HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID


@dataclass(frozen=True)
class HarmonicSelectionProfile:
    """Stable scientific identity and reporting contract for one method."""

    method_id: str
    version: str
    label: str
    adaptive: bool
    same_sample: bool
    pooling_method: str
    citation: str


HARMONIC_SELECTION_PROFILES = {
    HARMONIC_PROFILE_LEGACY_ID: HarmonicSelectionProfile(
        method_id=HARMONIC_PROFILE_LEGACY_ID,
        version=HARMONIC_PROFILE_VERSION_1,
        label="Legacy FPVS Toolbox",
        adaptive=True,
        same_sample=True,
        pooling_method="equal_available_workbook_amplitude_mean",
        citation="FPVS Toolbox legacy behavior retained for reproducibility",
    ),
    HARMONIC_PROFILE_FIXED_ID: HarmonicSelectionProfile(
        method_id=HARMONIC_PROFILE_FIXED_ID,
        version=HARMONIC_PROFILE_VERSION_1,
        label="Fixed / preregistered harmonic domain",
        adaptive=False,
        same_sample=False,
        pooling_method="not_applicable_fixed_domain",
        citation="A-priori harmonic domain",
    ),
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID: HarmonicSelectionProfile(
        method_id=HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
        version=HARMONIC_PROFILE_VERSION_1,
        label="Significant-only exploratory",
        adaptive=True,
        same_sample=True,
        pooling_method="balanced_group_condition_then_equal_condition_z",
        citation="Exploratory same-sample local-Z selection",
    ),
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID: HarmonicSelectionProfile(
        method_id=HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
        version=HARMONIC_PROFILE_VERSION_1,
        label="Dzhelyova/Poncet two consecutive failures",
        adaptive=True,
        same_sample=True,
        pooling_method="balanced_group_condition_then_equal_condition_z",
        citation="Dzhelyova et al. (2017); Poncet et al. (2019)",
    ),
}


@dataclass(frozen=True)
class DVPolicySettings:
    """Represent the DVPolicySettings part of the Stats tool."""
    name: str = GROUP_SIGNIFICANT_POLICY_NAME
    harmonic_selection_profile: str = HARMONIC_PROFILE_LEGACY_ID
    harmonic_selection_profile_version: str = HARMONIC_PROFILE_VERSION_1
    fixed_harmonic_frequencies_hz: str = FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    fixed_harmonic_input_mode: str = FIXED_HARMONIC_INPUT_FREQUENCY_LIST
    fixed_harmonic_upper_harmonic_index: int | None = None
    fixed_harmonic_upper_frequency_hz: float | None = None
    fixed_harmonic_auto_exclude_base: bool = True
    fixed_harmonic_base_tolerance_hz: float = FIXED_PREDEFINED_BASE_OVERLAP_TOLERANCE_HZ
    fixed_harmonic_matching_tolerance_hz: float = FIXED_PREDEFINED_MATCHING_TOLERANCE_HZ
    group_significant_z_threshold: float = GROUP_SIGNIFICANT_Z_THRESHOLD
    group_significant_electrode_scope: str = GROUP_SIGNIFICANT_ELECTRODE_SCOPE
    group_significant_selection_electrodes: tuple[str, ...] = ()
    group_significant_summation_method: str = GROUP_SIGNIFICANT_SUMMATION_METHOD
    group_significant_oddball_frequency_hz: float = LOCKED_ODDBALL_FREQUENCY_HZ

    @property
    def profile(self) -> HarmonicSelectionProfile:
        return HARMONIC_SELECTION_PROFILES[self.harmonic_selection_profile]

    def to_metadata(self, *, base_freq: float, selected_conditions: list[str]) -> dict:
        """Handle the to metadata step for the Stats workflow."""
        return {
            "policy_name": self.name,
            "harmonic_selection_profile": self.harmonic_selection_profile,
            "harmonic_selection_profile_version": self.harmonic_selection_profile_version,
            "harmonic_selection_profile_label": self.profile.label,
            "fixed_harmonic_frequencies_hz": str(self.fixed_harmonic_frequencies_hz),
            "fixed_harmonic_input_mode": self.fixed_harmonic_input_mode,
            "fixed_harmonic_upper_harmonic_index": self.fixed_harmonic_upper_harmonic_index,
            "fixed_harmonic_upper_frequency_hz": self.fixed_harmonic_upper_frequency_hz,
            "fixed_harmonic_auto_exclude_base": bool(self.fixed_harmonic_auto_exclude_base),
            "fixed_harmonic_base_tolerance_hz": float(self.fixed_harmonic_base_tolerance_hz),
            "fixed_harmonic_matching_tolerance_hz": float(self.fixed_harmonic_matching_tolerance_hz),
            "group_significant_z_threshold": float(self.group_significant_z_threshold),
            "group_significant_electrode_scope": str(self.group_significant_electrode_scope),
            "group_significant_selection_electrodes": list(
                self.group_significant_selection_electrodes
            ),
            "group_significant_summation_method": str(
                self.group_significant_summation_method
            ),
            "group_significant_oddball_frequency_hz": LOCKED_ODDBALL_FREQUENCY_HZ,
            "base_frequency_hz": float(base_freq),
            "selected_conditions": list(selected_conditions),
        }


def normalize_dv_policy(settings: dict[str, object] | None) -> DVPolicySettings:
    """Handle the normalize dv policy step for the Stats workflow."""
    if not settings:
        # Absence is deliberately Legacy. New-project creation must persist the
        # explicit NEW_PROJECT_HARMONIC_PROFILE_ID rather than relying on this.
        return DVPolicySettings()
    raw_name = str(settings.get("name", GROUP_SIGNIFICANT_POLICY_NAME))
    fixed_aliases = {
        FIXED_PREDEFINED_POLICY_NAME,
        "Current (Legacy)",
        "Fixed-K harmonics",
    }
    group_aliases = {
        GROUP_SIGNIFICANT_POLICY_NAME,
        "Rossion Method (common group-level harmonics)",
        "Rossion Method (Significant-only; stop after 2 failures)",
    }
    if raw_name in fixed_aliases:
        name = FIXED_PREDEFINED_POLICY_NAME
    elif raw_name in group_aliases:
        name = GROUP_SIGNIFICANT_POLICY_NAME
    else:
        name = GROUP_SIGNIFICANT_POLICY_NAME
    explicit_profile = _first_present(
        settings,
        "harmonic_selection_profile",
        "harmonic_selection_profile_id",
        "method_profile",
    )
    if explicit_profile is None:
        profile_id = (
            HARMONIC_PROFILE_FIXED_ID
            if name == FIXED_PREDEFINED_POLICY_NAME
            else HARMONIC_PROFILE_LEGACY_ID
        )
    else:
        profile_id = str(explicit_profile).strip()
        if profile_id not in HARMONIC_SELECTION_PROFILES:
            raise ValueError(f"Unknown harmonic-selection profile: {profile_id!r}.")
    profile = HARMONIC_SELECTION_PROFILES[profile_id]
    requested_version = settings.get("harmonic_selection_profile_version")
    if requested_version not in (None, "") and str(requested_version) != profile.version:
        raise ValueError(
            "Unsupported harmonic-selection profile version "
            f"{requested_version!r} for {profile_id!r}; expected {profile.version!r}."
        )
    name = (
        FIXED_PREDEFINED_POLICY_NAME
        if profile_id == HARMONIC_PROFILE_FIXED_ID
        else GROUP_SIGNIFICANT_POLICY_NAME
    )

    fixed_freqs = str(settings.get("fixed_harmonic_frequencies_hz", FIXED_PREDEFINED_DEFAULT_FREQUENCIES))
    raw_fixed_input_mode = settings.get("fixed_harmonic_input_mode")
    fixed_input_mode = (
        FIXED_HARMONIC_INPUT_FREQUENCY_LIST
        if raw_fixed_input_mode in (None, "")
        else str(raw_fixed_input_mode)
    )
    if fixed_input_mode not in {
        FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
        FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
        FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
    }:
        if profile_id == HARMONIC_PROFILE_FIXED_ID:
            raise ValueError(
                f"Unsupported fixed harmonic input mode: {fixed_input_mode!r}."
            )
        fixed_input_mode = FIXED_HARMONIC_INPUT_FREQUENCY_LIST
    fixed_upper_harmonic = _optional_positive_int(
        settings.get("fixed_harmonic_upper_harmonic_index")
    )
    fixed_upper_frequency = _optional_positive_float(
        settings.get("fixed_harmonic_upper_frequency_hz")
    )
    fixed_base_tol = float(
        settings.get("fixed_harmonic_base_tolerance_hz", FIXED_PREDEFINED_BASE_OVERLAP_TOLERANCE_HZ)
    )
    fixed_match_tol = float(
        settings.get("fixed_harmonic_matching_tolerance_hz", FIXED_PREDEFINED_MATCHING_TOLERANCE_HZ)
    )
    group_z = float(settings.get("group_significant_z_threshold", GROUP_SIGNIFICANT_Z_THRESHOLD))
    if not np.isfinite(group_z) or group_z <= 0:
        group_z = GROUP_SIGNIFICANT_Z_THRESHOLD
    group_scope = str(
        settings.get("group_significant_electrode_scope", GROUP_SIGNIFICANT_ELECTRODE_SCOPE)
    )
    scope_aliases = {
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
        "selected_roi_electrodes",
        "predefined_roi_union",
    }
    if group_scope not in scope_aliases:
        group_scope = GROUP_SIGNIFICANT_ELECTRODE_SCOPE
    if group_scope in {"selected_roi_electrodes", "predefined_roi_union"}:
        group_scope = GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION
    selection_electrodes = _normalize_electrode_mask(
        settings.get("group_significant_selection_electrodes")
    )
    if profile_id in {
        HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    }:
        if "group_significant_electrode_scope" not in settings:
            group_scope = GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL
        elif group_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION:
            raise ValueError(
                "Non-legacy harmonic profiles cannot derive their selection mask "
                "from mutable Stats ROIs; choose all scalp electrodes or a frozen mask."
            )
    if (
        profile_id != HARMONIC_PROFILE_FIXED_ID
        and group_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN
        and not selection_electrodes
    ):
        raise ValueError("A frozen harmonic-selection electrode mask cannot be empty.")
    raw_summation = str(
        settings.get(
            "group_significant_summation_method",
            GROUP_SIGNIFICANT_SUMMATION_METHOD,
        )
    )
    summation_aliases = {
        GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
        "significant_harmonics_only",
        "current",
        "legacy_significant_only",
        GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
        "through_highest",
        "all_through_highest",
    }
    if raw_summation not in summation_aliases:
        raw_summation = GROUP_SIGNIFICANT_SUMMATION_METHOD
    if raw_summation in {
        "significant_harmonics_only",
        "current",
        "legacy_significant_only",
    }:
        raw_summation = GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY
    if raw_summation in {"through_highest", "all_through_highest"}:
        raw_summation = GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
    if profile_id == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID:
        raw_summation = GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY
    elif profile_id == HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID:
        raw_summation = GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
    return DVPolicySettings(
        name=name,
        harmonic_selection_profile=profile_id,
        harmonic_selection_profile_version=profile.version,
        fixed_harmonic_frequencies_hz=fixed_freqs,
        fixed_harmonic_input_mode=fixed_input_mode,
        fixed_harmonic_upper_harmonic_index=fixed_upper_harmonic,
        fixed_harmonic_upper_frequency_hz=fixed_upper_frequency,
        fixed_harmonic_auto_exclude_base=(
            True
            if profile_id == HARMONIC_PROFILE_FIXED_ID
            else bool(settings.get("fixed_harmonic_auto_exclude_base", True))
        ),
        fixed_harmonic_base_tolerance_hz=fixed_base_tol,
        fixed_harmonic_matching_tolerance_hz=fixed_match_tol,
        group_significant_z_threshold=group_z,
        group_significant_electrode_scope=group_scope,
        group_significant_selection_electrodes=selection_electrodes,
        group_significant_summation_method=raw_summation,
        group_significant_oddball_frequency_hz=LOCKED_ODDBALL_FREQUENCY_HZ,
    )


def dv_policy_payload_from_selection_metadata(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """Return a policy payload whose identity follows canonical selection metadata."""

    raw_profile = metadata.get("harmonic_selection_profile")
    if raw_profile in (None, ""):
        profile_id = (
            HARMONIC_PROFILE_FIXED_ID
            if str(metadata.get("harmonic_policy") or "")
            == FIXED_PREDEFINED_POLICY_ID
            else HARMONIC_PROFILE_LEGACY_ID
        )
    else:
        profile_id = str(raw_profile).strip()
    if profile_id not in HARMONIC_SELECTION_PROFILES:
        raise ValueError(
            "Canonical harmonic-selection metadata contains an unknown profile: "
            f"{profile_id!r}."
        )
    profile = HARMONIC_SELECTION_PROFILES[profile_id]
    version = str(
        metadata.get("harmonic_selection_profile_version") or profile.version
    )
    if version != profile.version:
        raise ValueError(
            "Canonical harmonic-selection metadata uses unsupported profile version "
            f"{version!r} for {profile_id!r}; expected {profile.version!r}."
        )

    payload: dict[str, object] = {
        "name": (
            FIXED_PREDEFINED_POLICY_NAME
            if profile_id == HARMONIC_PROFILE_FIXED_ID
            else GROUP_SIGNIFICANT_POLICY_NAME
        ),
        "harmonic_selection_profile": profile_id,
        "harmonic_selection_profile_version": version,
    }
    if profile_id == HARMONIC_PROFILE_FIXED_ID:
        requested = metadata.get("fixed_harmonic_requested_frequencies_hz")
        if isinstance(requested, (list, tuple)):
            payload["fixed_harmonic_frequencies_hz"] = ", ".join(
                f"{float(value):g}" for value in requested
            )
        payload["fixed_harmonic_input_mode"] = metadata.get(
            "fixed_harmonic_input_mode",
            FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
        )
        payload["fixed_harmonic_auto_exclude_base"] = True
        for source_key, target_key in (
            ("base_overlap_tolerance_hz", "fixed_harmonic_base_tolerance_hz"),
            ("matching_tolerance_hz", "fixed_harmonic_matching_tolerance_hz"),
        ):
            if metadata.get(source_key) not in (None, ""):
                payload[target_key] = metadata[source_key]
    else:
        for source_key, target_key in (
            ("z_threshold", "group_significant_z_threshold"),
            ("electrode_scope", "group_significant_electrode_scope"),
            ("selection_electrode_mask", "group_significant_selection_electrodes"),
            ("summation_method", "group_significant_summation_method"),
        ):
            if metadata.get(source_key) not in (None, ""):
                payload[target_key] = metadata[source_key]
    # Apply the same profile/version/mode validation as every other caller.
    normalized = normalize_dv_policy(payload)
    payload["name"] = normalized.name
    payload["fixed_harmonic_auto_exclude_base"] = (
        normalized.fixed_harmonic_auto_exclude_base
    )
    return payload


def new_project_dv_policy_settings() -> DVPolicySettings:
    """Return the explicit recommended profile for a genuinely new project."""

    return normalize_dv_policy(
        {"harmonic_selection_profile": NEW_PROJECT_HARMONIC_PROFILE_ID}
    )


def _first_present(settings: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in settings and settings[key] not in (None, ""):
            return settings[key]
    return None


def _optional_positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return float(number) if np.isfinite(number) and number > 0 else None


def _optional_positive_int(value: object) -> int | None:
    number = _optional_positive_float(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _normalize_electrode_mask(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        values: Iterable[object] = value.replace(";", ",").split(",")
    elif isinstance(value, Iterable):
        values = value
    else:
        values = (value,)
    return tuple(
        sorted(
            {
                str(electrode).strip().upper()
                for electrode in values
                if str(electrode).strip()
            }
        )
    )


def _resolve_max_freq(max_freq: object | None) -> float | None:
    """Resolve harmonic max frequency from explicit input or persisted settings."""
    candidate = max_freq
    if candidate is None:
        try:
            candidate = SettingsManager().get("analysis", "bca_upper_limit", "16.8")
        except Exception:
            candidate = None
    if candidate is None:
        return None
    try:
        value = float(candidate)
    except Exception:
        return None
    if not np.isfinite(value) or value <= 0:
        return None
    return value
