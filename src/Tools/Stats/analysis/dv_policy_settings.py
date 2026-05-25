"""Settings and constants for Stats DV policies."""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class DVPolicySettings:
    """Represent the DVPolicySettings part of the Stats tool."""
    name: str = FIXED_PREDEFINED_POLICY_NAME
    fixed_harmonic_frequencies_hz: str = FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    fixed_harmonic_auto_exclude_base: bool = True
    fixed_harmonic_base_tolerance_hz: float = FIXED_PREDEFINED_BASE_OVERLAP_TOLERANCE_HZ
    fixed_harmonic_matching_tolerance_hz: float = FIXED_PREDEFINED_MATCHING_TOLERANCE_HZ

    def to_metadata(self, *, base_freq: float, selected_conditions: list[str]) -> dict:
        """Handle the to metadata step for the Stats workflow."""
        return {
            "policy_name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": str(self.fixed_harmonic_frequencies_hz),
            "fixed_harmonic_auto_exclude_base": bool(self.fixed_harmonic_auto_exclude_base),
            "fixed_harmonic_base_tolerance_hz": float(self.fixed_harmonic_base_tolerance_hz),
            "fixed_harmonic_matching_tolerance_hz": float(self.fixed_harmonic_matching_tolerance_hz),
            "base_frequency_hz": float(base_freq),
            "selected_conditions": list(selected_conditions),
        }


def normalize_dv_policy(settings: dict[str, object] | None) -> DVPolicySettings:
    """Handle the normalize dv policy step for the Stats workflow."""
    if not settings:
        return DVPolicySettings()
    fixed_freqs = str(settings.get("fixed_harmonic_frequencies_hz", FIXED_PREDEFINED_DEFAULT_FREQUENCIES))
    fixed_base_tol = float(
        settings.get("fixed_harmonic_base_tolerance_hz", FIXED_PREDEFINED_BASE_OVERLAP_TOLERANCE_HZ)
    )
    fixed_match_tol = float(
        settings.get("fixed_harmonic_matching_tolerance_hz", FIXED_PREDEFINED_MATCHING_TOLERANCE_HZ)
    )
    return DVPolicySettings(
        name=FIXED_PREDEFINED_POLICY_NAME,
        fixed_harmonic_frequencies_hz=fixed_freqs,
        fixed_harmonic_auto_exclude_base=bool(settings.get("fixed_harmonic_auto_exclude_base", True)),
        fixed_harmonic_base_tolerance_hz=fixed_base_tol,
        fixed_harmonic_matching_tolerance_hz=fixed_match_tol,
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
