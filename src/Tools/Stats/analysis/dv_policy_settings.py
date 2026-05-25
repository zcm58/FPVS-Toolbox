"""Settings and constants for Stats DV policies."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from Main_App import SettingsManager

LEGACY_POLICY_NAME = "Current (Legacy)"
FIXED_K_POLICY_NAME = "Fixed-K harmonics"
ROSSION_POLICY_NAME = "Rossion Method (Significant-only; stop after 2 failures)"
GROUP_MEAN_Z_POLICY_NAME = ROSSION_POLICY_NAME

EMPTY_LIST_FALLBACK_FIXED_K = "Fallback to Fixed-K"
EMPTY_LIST_SET_ZERO = "Set DV=0"
EMPTY_LIST_ERROR = "Error"


@dataclass(frozen=True)
class DVPolicySettings:
    """Represent the DVPolicySettings part of the Stats tool."""
    name: str = LEGACY_POLICY_NAME
    fixed_k: int = 5
    exclude_harmonic1: bool = False
    exclude_base_harmonics: bool = True
    z_threshold: float = 1.64
    empty_list_policy: str = EMPTY_LIST_ERROR

    def to_metadata(self, *, base_freq: float, selected_conditions: list[str]) -> dict:
        """Handle the to metadata step for the Stats workflow."""
        return {
            "policy_name": self.name,
            "fixed_k": int(self.fixed_k),
            "exclude_harmonic1": bool(self.exclude_harmonic1),
            "exclude_base_harmonics": bool(self.exclude_base_harmonics),
            "z_threshold": float(self.z_threshold),
            "empty_list_policy": str(self.empty_list_policy),
            "base_frequency_hz": float(base_freq),
            "selected_conditions": list(selected_conditions),
        }


def normalize_dv_policy(settings: dict[str, object] | None) -> DVPolicySettings:
    """Handle the normalize dv policy step for the Stats workflow."""
    if not settings:
        return DVPolicySettings()
    name = str(settings.get("name", LEGACY_POLICY_NAME))
    if name not in (
        LEGACY_POLICY_NAME,
        FIXED_K_POLICY_NAME,
        ROSSION_POLICY_NAME,
    ):
        name = LEGACY_POLICY_NAME
    fixed_k = int(settings.get("fixed_k", 5))
    if fixed_k < 1:
        fixed_k = 1
    empty_list_policy = str(settings.get("empty_list_policy", EMPTY_LIST_ERROR))
    if empty_list_policy not in (
        EMPTY_LIST_FALLBACK_FIXED_K,
        EMPTY_LIST_SET_ZERO,
        EMPTY_LIST_ERROR,
    ):
        empty_list_policy = EMPTY_LIST_ERROR
    z_threshold = float(settings.get("z_threshold", 1.64))
    return DVPolicySettings(
        name=name,
        fixed_k=fixed_k,
        exclude_harmonic1=bool(settings.get("exclude_harmonic1", False)),
        exclude_base_harmonics=bool(settings.get("exclude_base_harmonics", True)),
        z_threshold=z_threshold,
        empty_list_policy=empty_list_policy,
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
