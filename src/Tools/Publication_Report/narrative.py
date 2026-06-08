"""Narrative and document writers for publication reports."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from Tools.Publication_Report.models import (
    BASE_RATE_SUMMARY_SHEET,
    COMPARISON_AGREEMENT_SHEET,
    CONDITION_PAIRS_BY_ROI_SHEET,
    HARMONIC_SELECTION_SHEET,
    GROUP_ELECTRODE_SIGNIFICANCE_SHEET,
    INDIVIDUAL_DETECTABILITY_COUNTS_SHEET,
    PLANNED_LATERALIZATION_SHEET,
    ROI_RESPONSE_SUMMARY_SHEET,
    SEMANTIC_COLOR_RATIO_SUMMARY_SHEET,
    STATISTICAL_TEST_DECISIONS_SHEET,
    STATS_POSTHOC_SHEET,
    STATS_RM_ANOVA_SHEET,
    Z_SCORE_REPORT_SHEET,
    PublicationReportRequest,
)


def build_markdown(
    *,
    request: PublicationReportRequest,
    selected_conditions: tuple[str, ...],
    participant_inclusion: pd.DataFrame,
    analysis_frames: Mapping[str, pd.DataFrame] | None = None,
    warnings: tuple[str, ...],
) -> str:
    """Build a conservative Markdown draft Results section."""

    included_count = 0
    if not participant_inclusion.empty and "included" in participant_inclusion.columns:
        included_count = int(participant_inclusion["included"].fillna(False).sum())
    condition_text = ", ".join(selected_conditions) if selected_conditions else "no selected conditions"
    roi_text = ", ".join(_format_roi_text(roi) for roi in request.rois if roi.selected)
    if not roi_text:
        roi_text = "no selected ROIs"
    base_rate_roi_text = (
        request.base_rate_roi.name
        if request.base_rate_roi is not None and request.base_rate_roi.selected
        else "not configured"
    )

    lines = [
        f"# {request.report_label} Publication Report",
        "",
        "## Results Information Pack",
        "",
        (
            f"This report summarizes {included_count} included participant(s) "
            f"across the selected condition(s): {condition_text}."
        ),
        "",
        (
            f"The primary target response label is "
            f"\"{request.target_response_label}\". Report ROIs are: {roi_text}. "
            f"The base-rate ROI is {base_rate_roi_text}."
        ),
        "",
        *_analysis_sections(analysis_frames or {}),
        "",
        "## Reproducibility Notes",
        "",
        f"- Base-rate frequency: {request.base_frequency_hz:g} Hz",
        f"- BCA upper limit: {request.bca_upper_limit_hz:g} Hz",
        "- Z thresholds: " + ", ".join(f"{value:g}" for value in request.z_thresholds),
        "- Individual-level method: ROI-averaged summed-harmonic Z; electrode summaries use BH-FDR within participant x condition",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _format_roi_text(roi) -> str:
    electrodes = ", ".join(str(electrode) for electrode in roi.electrodes)
    if electrodes:
        return f"{roi.name} ({roi.role}; electrodes: {electrodes})"
    return f"{roi.name} ({roi.role}; electrodes: not configured)"


def _analysis_sections(frames: Mapping[str, pd.DataFrame]) -> list[str]:
    sections: list[str] = []
    sections.extend(_harmonic_selection_lines(frames.get(HARMONIC_SELECTION_SHEET)))
    sections.extend(_test_decision_lines(frames.get(STATISTICAL_TEST_DECISIONS_SHEET)))
    sections.extend(_roi_response_lines(frames.get(ROI_RESPONSE_SUMMARY_SHEET)))
    sections.extend(_semantic_color_ratio_lines(frames.get(SEMANTIC_COLOR_RATIO_SUMMARY_SHEET)))
    sections.extend(_stats_anova_lines(frames.get(STATS_RM_ANOVA_SHEET)))
    sections.extend(_stats_posthoc_lines(frames.get(STATS_POSTHOC_SHEET)))
    sections.extend(_planned_lateralization_lines(frames.get(PLANNED_LATERALIZATION_SHEET)))
    sections.extend(_condition_comparison_lines(frames.get(CONDITION_PAIRS_BY_ROI_SHEET)))
    sections.extend(_agreement_lines(frames.get(COMPARISON_AGREEMENT_SHEET)))
    sections.extend(_individual_count_lines(frames.get(INDIVIDUAL_DETECTABILITY_COUNTS_SHEET)))
    sections.extend(_electrode_summary_lines(frames.get(GROUP_ELECTRODE_SIGNIFICANCE_SHEET)))
    sections.extend(_base_rate_lines(frames.get(BASE_RATE_SUMMARY_SHEET)))
    sections.extend(_z_score_inventory_lines(frames.get(Z_SCORE_REPORT_SHEET)))
    if sections:
        return sections
    return [
        "The available source workbooks did not contain enough complete report inputs "
        "to generate statistical source tables. The workbook and audit trail still "
        "record project paths, selected conditions, ROI definitions, inclusion state, "
        "and warnings for follow-up.",
    ]


def _harmonic_selection_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty or "selected" not in frame.columns:
        return []
    selected = frame.loc[frame["selected"].fillna(False).astype(bool)]
    if selected.empty:
        return [
            "No oddball harmonics crossed the Stats group-level selection threshold "
            "for the selected conditions and included participants.",
        ]
    freqs = ", ".join(_format_hz(value) for value in selected["target_frequency_hz"])
    return [
        f"The Stats group-level harmonic selection retained {len(selected)} "
        f"oddball harmonic(s): {freqs}.",
    ]


def _test_decision_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    normality_source = frame["normality_p"] if "normality_p" in frame.columns else pd.Series(index=frame.index)
    normality_p = pd.to_numeric(normality_source, errors="coerce")
    selected_source = frame["selected_test"] if "selected_test" in frame.columns else pd.Series(index=frame.index)
    selected_tests = selected_source.astype(str)
    finite_normality = frame.loc[normality_p.notna()]
    nonnormal = frame.loc[normality_p < 0.05]
    wilcoxon_selected = frame.loc[selected_tests == "wilcoxon_signed_rank"]
    normality_not_tested = int(len(frame) - len(finite_normality))

    lines = ["", "### Statistical Test Decisions", ""]
    if finite_normality.empty:
        lines.append(
            "Shapiro-Wilk normality checks could not be completed for the planned "
            "ROI tests, usually because too few finite observations were available."
        )
    elif nonnormal.empty:
        lines.append(
            "All planned manuscript ROI tests with Shapiro-Wilk results met the "
            "normality assumption (all p >= .05); Wilcoxon signed-rank sensitivity "
            "p-values are exported in the source workbook."
        )
    else:
        labels = "; ".join(str(value) for value in nonnormal["comparison_id"].head(10))
        extra = len(nonnormal) - min(len(nonnormal), 10)
        suffix = f"; plus {extra} additional test(s)" if extra > 0 else ""
        lines.append(
            "Shapiro-Wilk indicated non-normality for "
            f"{len(nonnormal)} planned ROI test(s): {labels}{suffix}. "
            "Those rows select the Wilcoxon signed-rank result while retaining "
            "the parametric t-test as a sensitivity result."
        )
    if not wilcoxon_selected.empty and nonnormal.empty:
        labels = "; ".join(str(value) for value in wilcoxon_selected["comparison_id"].head(10))
        lines.append(
            f"Wilcoxon signed-rank was selected for {len(wilcoxon_selected)} row(s): {labels}."
        )
    if normality_not_tested:
        lines.append(
            f"Normality was not testable for {normality_not_tested} planned row(s); "
            "the workbook records the selected-test reason for each row."
        )
    lines.append(
        "Planned ROI manuscript comparisons use Holm correction on the selected "
        "p-values. BH-FDR is reserved for electrode-level individual detectability."
    )
    return lines


def _roi_response_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["### ROI-Level Target Response", ""]
    for row in frame.itertuples(index=False):
        lines.append(
            (
                f"For {row.condition} at the {row.roi} ROI, summed BCA across the "
                f"selected harmonic list was {_fmt(row.mean_summed_bca_uv)} +/- "
                f"{_fmt(row.sd_summed_bca_uv)} uV (n = {int(row.n)}; "
                f"t({ _fmt(row.df, decimals=0) }) = {_fmt(row.t_statistic)}, "
                f"parametric p = {_format_p(row.parametric_p)}, "
                f"Wilcoxon p = {_format_p(row.nonparametric_p)}, "
                f"selected {_test_label(row.selected_test)} p = {_format_p(row.selected_p)}, "
                f"Holm p = {_format_p(row.p_holm_planned_family)}, "
                f"Shapiro-Wilk p = {_format_p(row.normality_p)}, dz = {_fmt(row.cohens_dz)})."
            )
        )
    return lines


def _semantic_color_ratio_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Semantic-to-Color Response Ratio", ""]
    lines.append(
        "The semantic/color ratio was computed per participant as Semantic Response "
        "summed BCA divided by Color Response summed BCA using the same selected "
        "harmonic list. Descriptive summaries are shown both before and after "
        "dropping the single minimum and single maximum valid ratio per ROI."
    )
    for row in frame.itertuples(index=False):
        if int(row.n_valid_ratios) == 0:
            lines.append(f"No valid semantic/color ratios were available for {row.roi}.")
            continue
        lines.append(
            (
                f"For {row.roi}, the raw ratio distribution was "
                f"M = {_fmt(row.mean_ratio)}, median = {_fmt(row.median_ratio)}, "
                f"SD = {_fmt(row.sd_ratio)}, min = {_fmt(row.min_ratio)}, "
                f"max = {_fmt(row.max_ratio)} (n = {int(row.n_valid_ratios)}). "
                f"After excluding the minimum and maximum, the ratio was "
                f"M = {_fmt(row.trimmed_mean_ratio)}, median = {_fmt(row.trimmed_median_ratio)}, "
                f"SD = {_fmt(row.trimmed_sd_ratio)}, min = {_fmt(row.trimmed_min_ratio)}, "
                f"max = {_fmt(row.trimmed_max_ratio)} (n = {int(row.trimmed_n)}). "
                f"Participant-level stability: {_ratio_note_text(row.stability_note)} "
                f"({ _fmt(row.percent_within_20pct_of_median * 100 if pd.notna(row.percent_within_20pct_of_median) else None, decimals=0) }% "
                "within 20% of the ROI median)."
            )
        )
    return lines


def _planned_lateralization_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Planned LOT-ROT Lateralization", ""]
    lines.append(
        "These planned contrasts are reported outside the exploratory Stats posthoc "
        "source table and use Holm correction within the planned lateralization family."
    )
    condition_rows = frame.loc[frame["contrast_type"].astype(str) == "condition_lateralization"]
    for _index, row in condition_rows.iterrows():
        lines.append(
            (
                f"For {row['condition']}, the planned {row['right_roi']} minus "
                f"{row['left_roi']} contrast was {_fmt(row['mean_right_minus_left_uv'])} uV "
                f"({row['right_roi']} M = {_fmt(row['mean_right_uv'])}, "
                f"{row['left_roi']} M = {_fmt(row['mean_left_uv'])}; "
                f"n = {int(row['n_complete'])}; "
                f"t({_fmt(row['df'], decimals=0)}) = {_fmt(row['t_statistic'])}, "
                f"parametric p = {_format_p(row['parametric_p'])}, "
                f"Wilcoxon p = {_format_p(row['nonparametric_p'])}, "
                f"selected {_test_label(row['selected_test'])} p = {_format_p(row['selected_p'])}, "
                f"Holm p = {_format_p(row['p_holm_planned_family'])}, "
                f"Shapiro-Wilk p = {_format_p(row['normality_p'])}, "
                f"dz = {_fmt(row['cohens_dz'])}; {row['direction']})."
            )
        )

    difference_rows = frame.loc[frame["contrast_type"].astype(str) == "lateralization_difference"]
    for _index, row in difference_rows.iterrows():
        lines.append(
            (
                f"The direct asymmetry-difference contrast "
                f"(({row['right_roi']} - {row['left_roi']}) {row['condition_a']} "
                f"minus ({row['right_roi']} - {row['left_roi']}) {row['condition_b']}) "
                f"was {_fmt(row['mean_difference_of_lateralization_uv'])} uV "
                f"(n = {int(row['n_complete'])}; "
                f"t({_fmt(row['df'], decimals=0)}) = {_fmt(row['t_statistic'])}, "
                f"parametric p = {_format_p(row['parametric_p'])}, "
                f"Wilcoxon p = {_format_p(row['nonparametric_p'])}, "
                f"selected {_test_label(row['selected_test'])} p = {_format_p(row['selected_p'])}, "
                f"Holm p = {_format_p(row['p_holm_planned_family'])}, "
                f"Shapiro-Wilk p = {_format_p(row['normality_p'])}, "
                f"dz = {_fmt(row['cohens_dz'])}; {row['direction']})."
            )
        )
    return lines


def _condition_comparison_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Within-Subject Condition Pairs", ""]
    for row in frame.itertuples(index=False):
        if int(row.n_complete) < 2:
            lines.append(
                f"The {row.condition_a} vs {row.condition_b} comparison at {row.roi} "
                "did not have enough complete paired observations."
            )
            continue
        lines.append(
            (
                f"At {row.roi}, {row.condition_a} vs {row.condition_b} showed a "
                f"mean paired difference of {_fmt(row.mean_difference_a_minus_b)} uV "
                f"(t({ _fmt(row.df, decimals=0) }) = {_fmt(row.t_statistic)}, "
                f"parametric p = {_format_p(row.parametric_p)}, "
                f"Wilcoxon p = {_format_p(row.nonparametric_p)}, "
                f"selected {_test_label(row.selected_test)} p = {_format_p(row.selected_p)}, "
                f"Holm p = {_format_p(row.p_holm_planned_family)}, "
                f"Shapiro-Wilk p = {_format_p(row.normality_p)}, "
                f"dz = {_fmt(row.cohens_dz)}; "
                f"{row.direction})."
            )
        )
    return lines


def _stats_anova_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Stats RM-ANOVA", ""]
    for _index, row in frame.iterrows():
        effect = _cell(row, "Effect", "Effect")
        lines.append(
            (
                f"{effect}: F({_fmt(_cell(row, 'Num DF'), decimals=0)}, "
                f"{_fmt(_cell(row, 'Den DF'), decimals=0)}) = "
                f"{_fmt(_cell(row, 'F Value'))}, "
                f"p = {_format_p(_cell(row, 'Pr > F'))}, "
                f"GG p = {_format_p(_cell(row, 'Pr > F (GG)'))}, "
                f"HF p = {_format_p(_cell(row, 'Pr > F (HF)'))}, "
                f"partial eta squared = {_fmt(_cell(row, 'partial eta squared'))}."
            )
        )
    return lines


def _stats_posthoc_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    return [
        "",
        "### Exploratory Stats Posthoc Source Rows",
        "",
        (
            f"Stats posthoc source rows written: {len(frame)}. Planned manuscript ROI "
            "comparisons are reported separately with Shapiro-Wilk diagnostics, "
            "parametric and Wilcoxon signed-rank results, and Holm correction."
        ),
    ]


def _agreement_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Comparison Agreement", ""]
    for row in frame.itertuples(index=False):
        agreement = "agreed" if bool(row.agreement) else "differed or was incomplete"
        lines.append(
            f"{row.roi} {row.condition_a} vs {row.condition_b}: Stats posthoc and "
            f"direct pairwise check {agreement}."
        )
    return lines


def _individual_count_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Individual Detectability Counts", ""]
    for row in frame.itertuples(index=False):
        method = str(getattr(row, "threshold_method", "summed-harmonic Z"))
        lines.append(
            (
                f"{row.condition} / {row.roi}: "
                f"{int(row.participants_detectable)}/"
                f"{int(row.participant_count)} participants met {method}."
            )
        )
    return lines


def _electrode_summary_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    lines = ["", "### Significant Electrode Summaries", ""]
    key_rows = frame.loc[
        frame["threshold_method"].astype(str).isin(["fdr_q<=0.05", "z>3.1"])
    ] if "threshold_method" in frame.columns else frame
    for row in key_rows.head(30).itertuples(index=False):
        lines.append(
            (
                f"{row.condition} / {row.roi} / {row.threshold_method}: "
                f"{int(row.participants_with_significant_electrodes)}/"
                f"{int(row.participant_count)} participants had significant electrodes; "
                f"mean count = {_fmt(row.mean_significant_electrode_count)} "
                "using electrode-level summed-harmonic Z."
            )
        )
    if len(key_rows) > 30:
        lines.append(f"Additional significant-electrode summary rows: {len(key_rows) - 30}.")
    return lines


def _base_rate_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    z_frame = frame.loc[frame["metric"] == "Z"] if "metric" in frame.columns else pd.DataFrame()
    lines = ["", "### General Visual Base-Rate Response", ""]
    if z_frame.empty:
        lines.append("Base-rate source rows were written, but no base-rate Z rows were available.")
        return lines
    for condition, group in z_frame.groupby("condition", dropna=False):
        significant = group.loc[group["significant_z_gt_1_64"].fillna(False).astype(bool)]
        if significant.empty:
            lines.append(f"For {condition}, no base-rate harmonic exceeded Z > 1.64.")
            continue
        highest = significant.sort_values("base_harmonic_hz").iloc[-1]
        lines.append(
            (
                f"For {condition}, the base-rate response exceeded Z > 1.64 through "
                f"{_format_hz(highest['base_harmonic_hz'])} at the "
                f"{highest['roi']} ROI."
            )
        )
    return lines


def _z_score_inventory_lines(frame: pd.DataFrame | None) -> list[str]:
    if frame is None or frame.empty:
        return []
    if "z_source" not in frame.columns:
        return ["", "### Z-Score Inventory", "", f"Z-score rows written: {len(frame)}."]
    sources = ", ".join(sorted(str(value) for value in frame["z_source"].dropna().unique()))
    return [
        "",
        "### Z-Score Inventory",
        "",
        f"Z-score rows written: {len(frame)}. Sources: {sources}.",
    ]


def _format_hz(value: object) -> str:
    try:
        return f"{float(value):g} Hz"
    except (TypeError, ValueError):
        return f"{value} Hz"


def _fmt(value: object, *, decimals: int = 2) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "NA"
    if pd.isna(numeric):
        return "NA"
    return f"{numeric:.{decimals}f}"


def _format_p(value: object) -> str:
    try:
        p_value = float(value)
    except (TypeError, ValueError):
        return "NA"
    if pd.isna(p_value):
        return "NA"
    if p_value < 0.001:
        return "< .001"
    return f"{p_value:.3f}".replace("0.", ".")


def _test_label(value: object) -> str:
    key = str(value or "").strip().casefold()
    labels = {
        "one_sample_t": "one-sample t",
        "paired_t": "paired t",
        "wilcoxon_signed_rank": "Wilcoxon signed-rank",
    }
    return labels.get(key, key or "test")


def _ratio_note_text(value: object) -> str:
    key = str(value or "").strip().casefold()
    labels = {
        "high_stability_across_participants": "high stability across participants",
        "moderate_stability_across_participants": "moderate stability across participants",
        "variable_ratio_across_participants": "variable ratio across participants",
        "insufficient_valid_ratios_for_stability": "insufficient valid ratios for stability review",
    }
    return labels.get(key, key.replace("_", " ") or "stability not evaluated")


def _posthoc_context(row: pd.Series) -> str:
    direction = str(_cell(row, "Direction", "") or "")
    stratum = _cell(row, "Stratum", "")
    roi = _cell(row, "ROI", "")
    condition = _cell(row, "Condition", "")
    if direction == "condition_within_roi" and not _is_missing(roi):
        return f" / {roi}"
    if direction == "roi_within_condition" and not _is_missing(condition):
        return f" / {condition}"
    if not _is_missing(stratum):
        return f" / {stratum}"
    return ""


def _cell(row: pd.Series, column: str, default: object = None) -> object:
    if column in row.index:
        return row.get(column, default)
    return default


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_true(value: object) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "significant"}
    return bool(value)


def write_markdown(path: Path, text: str) -> Path:
    """Write Markdown text to disk."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def write_docx(path: Path, markdown_text: str) -> Path:
    """Write a minimal Word .docx without adding a runtime dependency."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = _markdown_to_paragraphs(markdown_text)
    document_xml = _document_xml(paragraphs)
    with ZipFile(target, "w", ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml())
        docx.writestr("_rels/.rels", _rels_xml())
        docx.writestr("word/document.xml", document_xml)
    return target


def _markdown_to_paragraphs(markdown_text: str) -> list[tuple[str, str]]:
    paragraphs: list[tuple[str, str]] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            paragraphs.append(("normal", ""))
        elif line.startswith("# "):
            paragraphs.append(("heading1", line[2:].strip()))
        elif line.startswith("## "):
            paragraphs.append(("heading2", line[3:].strip()))
        elif line.startswith("- "):
            paragraphs.append(("bullet", line[2:].strip()))
        else:
            paragraphs.append(("normal", line))
    return paragraphs


def _document_xml(paragraphs: list[tuple[str, str]]) -> str:
    body = "".join(_paragraph_xml(style, text) for style, text in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        "</w:sectPr></w:body></w:document>"
    )


def _paragraph_xml(style: str, text: str) -> str:
    ppr = ""
    if style == "heading1":
        ppr = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    elif style == "heading2":
        ppr = '<w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
    elif style == "bullet":
        text = f"- {text}"
    if not text:
        return f"<w:p>{ppr}</w:p>"
    return f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )


def _rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
