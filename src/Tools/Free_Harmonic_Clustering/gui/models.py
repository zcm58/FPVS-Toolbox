"""Immutable presentation contracts for the embedded clustering page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

import math


class GuiAnalysisDesign(str, Enum):
    """User-facing names for the two supported exchangeability designs."""

    PAIRED_CONDITIONS = "paired_conditions"
    INDEPENDENT_GROUPS = "independent_groups"


class GuiHarmonicMode(str, Enum):
    """Harmonic-domain choices exposed by the v1 page."""

    AUTOMATIC = "automatic"
    FIXED_HIGHEST = "fixed_highest"


@dataclass(frozen=True, slots=True)
class ProjectFrequencySnapshot:
    """Read-only active Settings values used to inspect one project.

    The GUI deliberately accepts these values from the Main App instead of
    offering local overrides. ``max_harmonic_hz`` is optional because the
    backend can cap the domain from the common FullFFT grid.
    """

    oddball_frequency_hz: float
    base_frequency_hz: float
    max_harmonic_hz: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("oddball_frequency_hz", "base_frequency_hz"):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive.")
            object.__setattr__(self, field_name, value)
        if self.max_harmonic_hz is not None:
            maximum = float(self.max_harmonic_hz)
            if not math.isfinite(maximum) or maximum <= 0.0:
                raise ValueError("max_harmonic_hz must be finite and positive.")
            if maximum < self.oddball_frequency_hz:
                raise ValueError(
                    "max_harmonic_hz must include at least one oddball harmonic."
                )
            object.__setattr__(self, "max_harmonic_hz", maximum)

    @classmethod
    def coerce(
        cls,
        value: "ProjectFrequencySnapshot | Mapping[str, object]",
    ) -> "ProjectFrequencySnapshot":
        """Normalize a snapshot or a simple integration mapping."""

        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("frequency_snapshot must be a ProjectFrequencySnapshot.")
        oddball = value.get("oddball_frequency_hz", value.get("oddball_freq"))
        base = value.get("base_frequency_hz", value.get("base_freq"))
        maximum = value.get("max_harmonic_hz")
        return cls(
            oddball_frequency_hz=float(oddball),
            base_frequency_hz=float(base),
            max_harmonic_hz=None if maximum in (None, "") else float(maximum),
        )


@dataclass(frozen=True, slots=True)
class GroupChoice:
    """One canonical project group shown by label and retained by ID."""

    group_id: str
    label: str

    def __post_init__(self) -> None:
        group_id = str(self.group_id).strip()
        label = str(self.label).strip()
        if not group_id or not label:
            raise ValueError("Group choices require a canonical ID and label.")
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "label", label)


@dataclass(frozen=True, slots=True)
class ProjectAnalysisOptions:
    """Header-only, read-only project discovery shown by the page."""

    project_root: Path
    conditions: tuple[str, ...]
    groups: tuple[GroupChoice, ...]
    eligible_orders: tuple[int, ...]
    eligible_harmonics_hz: tuple[float, ...]
    excluded_base_orders: tuple[int, ...] = ()
    excluded_base_harmonics_hz: tuple[float, ...] = ()
    fft_upper_hz: float | None = None
    effective_harmonic_upper_hz: float | None = None
    frequency_resolution_hz: float | None = None
    grid_fingerprint: str | None = None
    grid_compatible: bool = True
    grid_compatibility_verified: bool = False
    compatibility_message: str = ""
    workbook_count: int = 0
    representative_workbook_relative_path: str = ""
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        root = Path(self.project_root).expanduser().resolve(strict=False)
        conditions = tuple(
            str(value).strip() for value in self.conditions if str(value).strip()
        )
        orders = tuple(int(value) for value in self.eligible_orders)
        harmonics = tuple(float(value) for value in self.eligible_harmonics_hz)
        if len(orders) != len(harmonics):
            raise ValueError("Eligible harmonic orders and frequencies must align.")
        if any(order < 1 for order in orders):
            raise ValueError("Eligible harmonic orders must be positive.")
        if any(not math.isfinite(value) or value <= 0.0 for value in harmonics):
            raise ValueError("Eligible harmonic frequencies must be positive.")
        excluded_orders = tuple(int(value) for value in self.excluded_base_orders)
        excluded_hz = tuple(float(value) for value in self.excluded_base_harmonics_hz)
        if len(excluded_orders) != len(excluded_hz):
            raise ValueError("Excluded harmonic orders and frequencies must align.")
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "groups", tuple(self.groups))
        object.__setattr__(self, "eligible_orders", orders)
        object.__setattr__(self, "eligible_harmonics_hz", harmonics)
        object.__setattr__(self, "excluded_base_orders", excluded_orders)
        object.__setattr__(self, "excluded_base_harmonics_hz", excluded_hz)
        object.__setattr__(
            self,
            "diagnostics",
            tuple(str(value).strip() for value in self.diagnostics if str(value).strip()),
        )


@dataclass(frozen=True, slots=True)
class AnalysisSetup:
    """One ordered contrast and harmonic domain prepared by the worker."""

    design: GuiAnalysisDesign
    condition_a: str
    condition_b: str | None
    group_ids: tuple[str, ...]
    harmonic_mode: GuiHarmonicMode
    fixed_highest_harmonic_order: int | None
    max_harmonic_hz: float


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Inference and its additive export receipt from one successful run."""

    result: object
    receipt: object


@dataclass(frozen=True, slots=True)
class AnalysisWorkerOutcome:
    """Transient prepared data and exported result returned to the GUI once."""

    prepared: object
    run_outcome: RunOutcome


__all__ = [
    "AnalysisSetup",
    "AnalysisWorkerOutcome",
    "GroupChoice",
    "GuiAnalysisDesign",
    "GuiHarmonicMode",
    "ProjectAnalysisOptions",
    "ProjectFrequencySnapshot",
    "RunOutcome",
]
