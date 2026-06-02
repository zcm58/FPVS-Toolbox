"""Data contracts for publication scalp maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


LONG_VALUES_SHEET = "Long_Values"
GRAND_AVERAGE_SHEET = "Grand_Average"
DIAGNOSTICS_SHEET = "Diagnostics"
PARAMETERS_SHEET = "Parameters"
SOURCE_WORKBOOK_NAME = "Publication_Scalp_Maps_Source_Data.xlsx"
DEFAULT_BCA_LOW_COLOR = "#2166ac"
DEFAULT_BCA_LOW_MID_COLOR = "#67a9cf"
DEFAULT_BCA_HIGH_MID_COLOR = "#fdae61"
DEFAULT_BCA_HIGH_COLOR = "#b2182b"


class PublicationMetric(str, Enum):
    """Supported publication scalp-map metric families."""

    BCA = "bca"

    @property
    def display_name(self) -> str:
        return "BCA"

    @property
    def source_sheet(self) -> str:
        return "BCA (uV)"

    @property
    def value_column(self) -> str:
        return "BCA (uV)"


class HarmonicMode(str, Enum):
    """User-visible harmonic selection modes."""

    SINGLE = "single_frequency"
    EXPLICIT_LIST = "explicit_frequency_list"
    HIGHEST_ODDBALL = "highest_oddball_harmonic"
    STATS_SIGNIFICANT = "stats_selected_significant_harmonics"


@dataclass(frozen=True)
class ColorBounds:
    """Rendering bounds for one metric."""

    auto_scale: bool = True
    vmin: float | None = None
    vmax: float | None = None
    low_color: str = DEFAULT_BCA_LOW_COLOR
    high_color: str = DEFAULT_BCA_HIGH_COLOR


@dataclass(frozen=True)
class PublicationMapRequest:
    """Request for building and exporting publication scalp maps."""

    input_root: Path
    output_root: Path
    conditions: tuple[str, ...]
    harmonic_mode: HarmonicMode = HarmonicMode.STATS_SIGNIFICANT
    harmonic_label: str = ""
    base_frequency_hz: float = 6.0
    max_frequency_hz: float | None = None
    subject_exclusions: frozenset[str] = frozenset()
    color_bounds: dict[PublicationMetric, ColorBounds] = field(default_factory=dict)
    export_png: bool = True
    export_svg: bool = True
    export_paired_figures: bool = False
    paired_conditions: tuple[str, ...] = ()
    png_dpi: int = 300
    project_root: Path | None = None

    def selected_harmonics_label(self, values: tuple[float, ...]) -> str:
        return ", ".join(f"{freq:g}" for freq in values)


@dataclass(frozen=True)
class Diagnostic:
    """Single diagnostic generated while reading, aggregating, or rendering."""

    level: str
    message: str
    condition: str = ""
    workbook: str = ""
    detail: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "level": self.level,
            "condition": self.condition,
            "workbook": self.workbook,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ConditionInfo:
    """Discovered condition folder summary."""

    name: str
    path: Path
    files: tuple[Path, ...]


@dataclass(frozen=True)
class WorkbookEntry:
    """Workbook selected for one condition."""

    condition: str
    subject_id: str
    path: Path


@dataclass
class PublicationMapResult:
    """Core result frames plus export artifacts."""

    long_values: pd.DataFrame
    grand_average_values: pd.DataFrame
    diagnostics: list[Diagnostic] = field(default_factory=list)
    figure_paths: list[Path] = field(default_factory=list)
    source_workbook_path: Path | None = None
    selected_harmonics_hz: tuple[float, ...] = ()
    selection_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FrequencyColumn:
    """Frequency column matched without nearest-bin fallback."""

    requested_hz: float
    column_hz: float
    column_name: str
    exact_label_match: bool
