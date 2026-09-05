"""Data contracts for publication scalp maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from Main_App.exports.figure_style import FIGURE_EXPORT_DPI

if TYPE_CHECKING:
    import pandas as pd


DEFAULT_BCA_LOW_COLOR = "#2166ac"
DEFAULT_BCA_LOW_MID_COLOR = "#67a9cf"
DEFAULT_BCA_MID_COLOR = "#1a9850"
DEFAULT_BCA_UPPER_MID_COLOR = "#fee08b"
DEFAULT_BCA_HIGH_MID_COLOR = "#fdae61"
DEFAULT_BCA_HIGH_COLOR = "#b2182b"
DEFAULT_Z_SCORE_THRESHOLD = 1.64
DEFAULT_FIGURE_DPI = FIGURE_EXPORT_DPI


class PublicationMetric(str, Enum):
    """Supported publication scalp-map metric families."""

    BCA = "bca"
    SNR = "snr"
    Z_SCORE = "z_score"

    @property
    def display_name(self) -> str:
        if self is PublicationMetric.Z_SCORE:
            return "Z Score"
        if self is PublicationMetric.SNR:
            return "SNR"
        return "BCA"

    @property
    def source_sheet(self) -> str:
        if self is PublicationMetric.Z_SCORE:
            return "Z Score"
        if self is PublicationMetric.SNR:
            return "SNR"
        return "BCA (uV)"

    @property
    def value_column(self) -> str:
        if self is PublicationMetric.Z_SCORE:
            return "Z Score"
        if self is PublicationMetric.SNR:
            return "SNR"
        return "BCA (uV)"


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
    subject_exclusions: frozenset[str] = frozenset()
    metrics: tuple[PublicationMetric, ...] = (PublicationMetric.BCA,)
    color_bounds: dict[PublicationMetric, ColorBounds] = field(default_factory=dict)
    export_png: bool = True
    export_pdf: bool = True
    export_paired_figures: bool = False
    paired_conditions: tuple[str, ...] = ()
    export_group_comparison_figure: bool = False
    group_comparison_ids: tuple[str, ...] = ()
    png_dpi: int = DEFAULT_FIGURE_DPI
    project_root: Path | None = None
    group_id: str | None = None
    group_label: str | None = None
    group_folder: str | None = None
    session_ids: tuple[str, ...] = ()
    export_session_grid_figure: bool = False
    session_comparison_ids: tuple[str, ...] = ()
    export_paired_session_difference: bool = False


@dataclass(frozen=True)
class Diagnostic:
    """Single diagnostic generated while reading, aggregating, or rendering."""

    level: str
    message: str
    condition: str = ""
    workbook: str = ""
    detail: str = ""
    code: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "level": self.level,
            "code": self.code,
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
    group_id: str | None = None
    group_label: str | None = None
    group_folder: str | None = None
    sha256: str = ""
    size_bytes: int | None = None
    mtime_ns: int | None = None
    spectral_companion: dict[str, object] | None = field(default=None, hash=False)
    condition_companion: dict[str, object] | None = field(default=None, hash=False)

    @property
    def participant_id(self) -> str:
        """Return the canonical project participant identity."""

        return self.subject_id


@dataclass(frozen=True)
class ExcludedCohortEntry:
    """Canonical participant/workbook excluded from one map request."""

    participant_id: str
    condition: str
    reason: str
    path: Path | None = None
    group_id: str | None = None
    group_label: str | None = None
    group_folder: str | None = None


@dataclass
class PublicationMapResult:
    """Core result frames plus export artifacts."""

    long_values: pd.DataFrame
    grand_average_values: pd.DataFrame
    diagnostics: list[Diagnostic] = field(default_factory=list)
    figure_paths: list[Path] = field(default_factory=list)
    selected_harmonics_hz: tuple[float, ...] = ()
    selection_metadata: dict[str, object] = field(default_factory=dict)
    group_id: str | None = None
    group_label: str | None = None
    group_folder: str | None = None
    included_workbooks: tuple[WorkbookEntry, ...] = ()
    excluded_cohort: tuple[ExcludedCohortEntry, ...] = ()
    qc_provenance: dict[str, object] = field(default_factory=dict)


class PublicationMapError(RuntimeError):
    """Base error for a requested publication-map run."""


class PublicationMapCohortError(PublicationMapError):
    """Raised when canonical project cohort selection is unsafe or empty."""


class PublicationMapInputError(PublicationMapError):
    """Raised when an active requested workbook cannot supply exact inputs."""


@dataclass(frozen=True)
class FrequencyColumn:
    """Frequency column matched without nearest-bin fallback."""

    requested_hz: float
    column_hz: float
    column_name: str
    exact_label_match: bool
