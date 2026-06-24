"""Data contracts for publication report generation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

PUBLICATION_REPORT_OUTPUT_FOLDER = "5 - Publication Report"
REPORT_MARKDOWN_NAME = "Publication_Report.md"
REPORT_DOCX_NAME = "Publication_Report.docx"
REPORT_WORKBOOK_NAME = "Publication_Report_Data.xlsx"
REPORT_AUDIT_NAME = "Publication_Report_Audit.json"
REPORT_LOG_NAME = "publication_report_log.txt"

RUN_SUMMARY_SHEET = "Run_Summary"
PARTICIPANT_INCLUSION_SHEET = "Participant_Inclusion"
CONDITION_ROLES_SHEET = "Condition_Roles"
ROI_DEFINITIONS_SHEET = "ROI_Definitions"
FIGURE_MANIFEST_SHEET = "Figure_Manifest"
WARNINGS_SHEET = "Warnings"
HARMONIC_SELECTION_SHEET = "Harmonic_Selection"
ROI_HARMONIC_VALUES_SHEET = "ROI_Harmonic_Values"
ROI_HARMONIC_SUMMARY_SHEET = "ROI_Harmonic_Summary"
ROI_RESPONSE_SUMMARY_SHEET = "ROI_Response_Summary"
SEMANTIC_COLOR_RATIO_VALUES_SHEET = "Semantic_Color_Ratio_Values"
SEMANTIC_COLOR_RATIO_SUMMARY_SHEET = "Semantic_Color_Ratio_Summary"
CONDITION_COMPARISONS_SHEET = "Condition_Comparisons"
STATS_RM_ANOVA_SHEET = "Stats_RM_ANOVA"
STATS_POSTHOC_SHEET = "Stats_Posthoc"
STATS_WORKFLOW_SUMMARY_SHEET = "Stats_Workflow_Summary"
CONDITION_PAIRS_BY_ROI_SHEET = "Condition_Pairs_By_ROI"
COMPARISON_AGREEMENT_SHEET = "Comparison_Agreement"
PLANNED_LATERALIZATION_SHEET = "Planned_Lateralization"
NORMALITY_CHECKS_SHEET = "Normality_Checks"
PARAMETRIC_VS_NONPARAMETRIC_TESTS_SHEET = "Parametric_vs_Nonparametric_Tests"
PLANNED_ROI_COMPARISONS_HOLM_SHEET = "Planned_ROI_Comparisons_Holm"
STATISTICAL_TEST_DECISIONS_SHEET = "Statistical_Test_Decisions"
GROUP_ELECTRODE_SIGNIFICANCE_SHEET = "Group_Electrode_Significance"
INDIVIDUAL_DETECTABILITY_SHEET = "Individual_Detectability"
INDIVIDUAL_DETECTABILITY_COUNTS_SHEET = "Individual_Detectability_Counts"
ELECTRODE_Z_SCORES_SHEET = "Electrode_Z_Scores"
INDIVIDUAL_ROI_SUMMED_Z_SHEET = "Individual_ROI_Summed_Z"
INDIVIDUAL_ELECTRODE_SUMMED_Z_SHEET = "Individual_Electrode_Summed_Z"
INDIVIDUAL_ELECTRODE_FDR_SHEET = "Individual_Electrode_FDR"
OLD_VS_NEW_DETECTABILITY_COMPARISON_SHEET = "Old_vs_New_Detectability_Comparison"
Z_SCORE_REPORT_SHEET = "Z_Score_Report"
BASE_RATE_SUMMARY_SHEET = "Base_Rate_Summary"
QC_OUTLIER_VALUES_SHEET = "QC_Outlier_Values"
QC_OUTLIER_SUMMARY_SHEET = "QC_Outlier_Summary"
QC_NORMALITY_CHECKS_SHEET = "QC_Normality_Checks"

DEFAULT_REPORT_LABEL = "Semantic categories"
DEFAULT_TARGET_RESPONSE_LABEL = "semantic categorization response"
DEFAULT_BASE_FREQUENCY_HZ = 6.0
DEFAULT_BCA_UPPER_LIMIT_HZ = 40.0
DEFAULT_Z_THRESHOLDS = (1.64, 2.32, 3.1)

LOT_ROI_NAME = "LOT"
ROT_ROI_NAME = "ROT"
CENTRAL_ROI_NAME = "Central"
BILATERAL_OT_ROI_NAME = "Bilateral OT"

_LOT_ALIASES = {"lot", "left ot", "left occipito-temporal", "left occipito temporal"}
_ROT_ALIASES = {"rot", "right ot", "right occipito-temporal", "right occipito temporal"}
_CENTRAL_ALIASES = {"central", "central lobe"}


@dataclass(frozen=True)
class ReportRoi:
    """ROI definition and manuscript role."""

    name: str
    electrodes: tuple[str, ...]
    role: str = "supporting"
    selected: bool = True


@dataclass(frozen=True)
class ReportCondition:
    """Condition selected for a report."""

    name: str
    label: str
    role: str = "selected"


@dataclass(frozen=True)
class WorkbookEntry:
    """Workbook discovered for a participant x condition cell."""

    condition: str
    subject_id: str
    path: Path


@dataclass(frozen=True)
class DiscoveredCondition:
    """Condition folder and workbook count."""

    name: str
    path: Path
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ReportOutputOptions:
    """Output families controlled by the embedded tool."""

    markdown: bool = True
    docx: bool = True
    workbook: bool = True
    audit_json: bool = True
    spectra: bool = True
    scalp_maps: bool = True
    individual_figures: bool = True
    qc_figures: bool = True


@dataclass(frozen=True)
class PublicationReportRequest:
    """GUI-agnostic publication report request."""

    project_root: Path
    excel_root: Path | None = None
    output_root: Path | None = None
    selected_conditions: tuple[str, ...] = ()
    condition_labels: dict[str, str] = field(default_factory=dict)
    report_label: str = DEFAULT_REPORT_LABEL
    target_response_label: str = DEFAULT_TARGET_RESPONSE_LABEL
    rois: tuple[ReportRoi, ...] = field(default_factory=tuple)
    base_rate_roi: ReportRoi | None = None
    manual_excluded_subjects: frozenset[str] = frozenset()
    qc_excluded_subjects: frozenset[str] = frozenset()
    base_frequency_hz: float = DEFAULT_BASE_FREQUENCY_HZ
    bca_upper_limit_hz: float = DEFAULT_BCA_UPPER_LIMIT_HZ
    z_thresholds: tuple[float, ...] = DEFAULT_Z_THRESHOLDS
    output_options: ReportOutputOptions = field(default_factory=ReportOutputOptions)


@dataclass(frozen=True)
class PublicationReportResult:
    """Generated publication report artifacts."""

    output_root: Path
    markdown_path: Path | None = None
    docx_path: Path | None = None
    workbook_path: Path | None = None
    audit_path: Path | None = None
    log_path: Path | None = None
    generated_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


def default_report_rois() -> tuple[ReportRoi, ...]:
    """Return the default semantic-report target ROI definitions."""

    return (
        ReportRoi(
            name=LOT_ROI_NAME,
            electrodes=("P7", "P9", "PO7", "PO3", "O1"),
            role="primary",
            selected=True,
        ),
        ReportRoi(
            name=ROT_ROI_NAME,
            electrodes=("P8", "P10", "PO8", "PO4", "O2"),
            role="primary",
            selected=True,
        ),
        ReportRoi(
            name=CENTRAL_ROI_NAME,
            electrodes=("FCz", "Cz", "CPz", "CP1", "C1", "FC1"),
            role="supporting/exploratory",
            selected=True,
        ),
    )


def default_base_rate_roi() -> ReportRoi:
    """Return the default bilateral occipito-temporal base-rate ROI."""

    return ReportRoi(
        name=BILATERAL_OT_ROI_NAME,
        electrodes=("P7", "P9", "PO7", "PO3", "O1", "P8", "P10", "PO8", "PO4", "O2"),
        role="base-rate",
        selected=True,
    )


def report_rois_from_settings_pairs(
    pairs: Iterable[tuple[str, Sequence[str]]],
) -> tuple[ReportRoi, ...]:
    """Convert Settings-menu ROI pairs into Publication Report ROI choices."""

    rois: list[ReportRoi] = []
    seen: set[str] = set()
    for raw_name, raw_electrodes in pairs:
        name = str(raw_name).strip()
        if not name or name.casefold() in seen:
            continue
        electrodes = tuple(
            str(electrode).strip()
            for electrode in raw_electrodes
            if str(electrode).strip()
        )
        if not electrodes:
            continue
        seen.add(name.casefold())
        rois.append(
            ReportRoi(
                name=name,
                electrodes=electrodes,
                role=_report_roi_role(name),
                selected=_report_roi_selected_by_default(name),
            )
        )
    return tuple(rois)


def _report_roi_role(name: str) -> str:
    key = _roi_name_key(name)
    if key in _LOT_ALIASES or key in _ROT_ALIASES:
        return "primary"
    if key in _CENTRAL_ALIASES:
        return "supporting/exploratory"
    return "settings ROI"


def _report_roi_selected_by_default(name: str) -> bool:
    key = _roi_name_key(name)
    return key in _LOT_ALIASES or key in _ROT_ALIASES or key in _CENTRAL_ALIASES


def _roi_name_key(name: str) -> str:
    return " ".join(str(name).strip().casefold().replace("_", " ").replace("-", " ").split())
