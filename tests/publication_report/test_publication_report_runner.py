from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
from openpyxl import load_workbook

from Tools.Publication_Report.analysis_tables import (
    _planned_lateralization_contrasts,
    _z_score_report,
)
from Tools.Publication_Report.models import (
    BASE_RATE_SUMMARY_SHEET,
    COMPARISON_AGREEMENT_SHEET,
    CONDITION_ROLES_SHEET,
    CONDITION_COMPARISONS_SHEET,
    CONDITION_PAIRS_BY_ROI_SHEET,
    ELECTRODE_Z_SCORES_SHEET,
    FIGURE_MANIFEST_SHEET,
    GROUP_ELECTRODE_SIGNIFICANCE_SHEET,
    HARMONIC_SELECTION_SHEET,
    INDIVIDUAL_DETECTABILITY_SHEET,
    INDIVIDUAL_DETECTABILITY_COUNTS_SHEET,
    PARTICIPANT_INCLUSION_SHEET,
    PLANNED_LATERALIZATION_SHEET,
    ROI_HARMONIC_SUMMARY_SHEET,
    ROI_HARMONIC_VALUES_SHEET,
    ROI_DEFINITIONS_SHEET,
    ROI_RESPONSE_SUMMARY_SHEET,
    RUN_SUMMARY_SHEET,
    STATS_POSTHOC_SHEET,
    STATS_RM_ANOVA_SHEET,
    STATS_WORKFLOW_SUMMARY_SHEET,
    WARNINGS_SHEET,
    Z_SCORE_REPORT_SHEET,
    PublicationReportRequest,
    ReportOutputOptions,
    report_rois_from_settings_pairs,
)
from Tools.Publication_Report.runner import generate_publication_report


def _write_result_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"Electrode": ["P7"], "1.2000_Hz": [0.1]})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)


def _write_project_manifest(root: Path, *, groups: dict[str, object] | None = None) -> None:
    payload: dict[str, object] = {
        "name": "PublicationReportProject",
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
    }
    if groups is not None:
        payload["groups"] = groups
    (root / "project.json").write_text(json.dumps(payload), encoding="utf-8")


def _build_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    excel_root = root / "1 - Excel Data Files"
    _write_project_manifest(root)
    _write_result_workbook(excel_root / "CondA" / "P01_CondA_Results.xlsx")
    _write_result_workbook(excel_root / "CondA" / "P02_CondA_Results.xlsx")
    _write_result_workbook(excel_root / "CondB" / "P01_CondB_Results.xlsx")
    _write_result_workbook(excel_root / "CondB" / "P03_CondB_Results.xlsx")
    return root


def test_generate_publication_report_writes_initial_bundle(tmp_path: Path) -> None:
    root = _build_project(tmp_path)
    request = PublicationReportRequest(
        project_root=root,
        selected_conditions=("CondA", "CondB"),
        manual_excluded_subjects=frozenset({"P02"}),
        qc_excluded_subjects=frozenset({"P03"}),
        output_options=ReportOutputOptions(
            markdown=True,
            docx=True,
            workbook=True,
            audit_json=True,
            spectra=True,
            scalp_maps=True,
            individual_figures=True,
        ),
    )

    result = generate_publication_report(request)

    assert result.output_root == root / "5 - Publication Report"
    assert result.markdown_path is not None and result.markdown_path.exists()
    assert result.docx_path is not None and result.docx_path.exists()
    assert result.workbook_path is not None and result.workbook_path.exists()
    assert result.audit_path is not None and result.audit_path.exists()
    assert result.log_path is not None and result.log_path.exists()

    markdown_text = result.markdown_path.read_text(encoding="utf-8")
    assert "# Semantic categories Publication Report" in markdown_text
    assert "CondA, CondB" in markdown_text
    assert "1 included participant(s)" in markdown_text

    with ZipFile(result.docx_path) as docx:
        assert "word/document.xml" in docx.namelist()

    workbook = load_workbook(result.workbook_path, read_only=True)
    assert {
        RUN_SUMMARY_SHEET,
        PARTICIPANT_INCLUSION_SHEET,
        CONDITION_ROLES_SHEET,
        ROI_DEFINITIONS_SHEET,
        FIGURE_MANIFEST_SHEET,
        WARNINGS_SHEET,
        HARMONIC_SELECTION_SHEET,
        ROI_HARMONIC_VALUES_SHEET,
        ROI_HARMONIC_SUMMARY_SHEET,
        ROI_RESPONSE_SUMMARY_SHEET,
        CONDITION_COMPARISONS_SHEET,
        STATS_RM_ANOVA_SHEET,
        STATS_POSTHOC_SHEET,
        STATS_WORKFLOW_SUMMARY_SHEET,
        CONDITION_PAIRS_BY_ROI_SHEET,
        COMPARISON_AGREEMENT_SHEET,
        PLANNED_LATERALIZATION_SHEET,
        ELECTRODE_Z_SCORES_SHEET,
        GROUP_ELECTRODE_SIGNIFICANCE_SHEET,
        INDIVIDUAL_DETECTABILITY_SHEET,
        INDIVIDUAL_DETECTABILITY_COUNTS_SHEET,
        Z_SCORE_REPORT_SHEET,
        BASE_RATE_SUMMARY_SHEET,
    }.issubset(set(workbook.sheetnames))

    participants = pd.read_excel(result.workbook_path, sheet_name=PARTICIPANT_INCLUSION_SHEET)
    inclusion_by_subject = {
        str(row.subject_id): bool(row.included)
        for row in participants.itertuples(index=False)
    }
    assert inclusion_by_subject == {"P01": True, "P02": False, "P03": False}

    audit = json.loads(result.audit_path.read_text(encoding="utf-8"))
    assert audit["selected_conditions"] == ["CondA", "CondB"]
    assert audit["manual_excluded_subjects"] == ["P02"]
    assert audit["qc_excluded_subjects"] == ["P03"]
    assert [roi["roi"] for roi in audit["rois"]] == ["LOT", "ROT", "Central"]


def test_generate_publication_report_rejects_missing_selected_condition(tmp_path: Path) -> None:
    root = _build_project(tmp_path)

    with pytest.raises(RuntimeError, match="Selected condition folder"):
        generate_publication_report(
            PublicationReportRequest(
                project_root=root,
                selected_conditions=("CondA", "MissingCondition"),
            )
        )


def test_generate_publication_report_rejects_multi_group_project(tmp_path: Path) -> None:
    root = _build_project(tmp_path)
    _write_project_manifest(root, groups={"Control": {}, "Patient": {}})

    with pytest.raises(RuntimeError, match="single-group workflow"):
        generate_publication_report(PublicationReportRequest(project_root=root))


def test_z_score_report_preserves_mean_column_values() -> None:
    roi_harmonic_summary = pd.DataFrame(
        [
            {
                "condition": "CondA",
                "roi": "LOT",
                "harmonic_hz": 2.4,
                "metric": "Z",
                "mean": 3.25,
                "z_one_tailed_p": 0.0006,
                "z_gt_1.64": True,
            }
        ]
    )
    base_rate_summary = pd.DataFrame(
        [
            {
                "condition": "CondA",
                "roi": "Bilateral OT",
                "base_harmonic_hz": 6.0,
                "metric": "Z",
                "mean": 12.5,
                "z_one_tailed_p": 0.0,
                "significant_z_gt_1_64": True,
            }
        ]
    )

    report = _z_score_report(
        harmonic_selection=pd.DataFrame(),
        roi_harmonic_summary=roi_harmonic_summary,
        base_rate_summary=base_rate_summary,
    )

    assert report["z_score"].tolist() == [3.25, 12.5]


def test_report_rois_from_settings_pairs_marks_semantic_defaults() -> None:
    rois = report_rois_from_settings_pairs(
        [
            ("Left Occipito-Temporal", ["p7", "po7"]),
            ("Right Occipito-Temporal", ["p8", "po8"]),
            ("Central", ["cz"]),
            ("Left Parietal", ["p3"]),
        ]
    )

    by_name = {roi.name: roi for roi in rois}
    assert by_name["Left Occipito-Temporal"].selected is True
    assert by_name["Left Occipito-Temporal"].role == "primary"
    assert by_name["Right Occipito-Temporal"].selected is True
    assert by_name["Right Occipito-Temporal"].role == "primary"
    assert by_name["Central"].selected is True
    assert by_name["Left Parietal"].selected is False


def test_planned_lateralization_contrasts_use_right_minus_left_and_interaction() -> None:
    rows = []
    for subject, semantic_left, semantic_right, color_left, color_right in [
        ("S01", 1.00, 1.40, 1.00, 1.02),
        ("S02", 1.10, 1.35, 0.90, 0.88),
        ("S03", 0.95, 1.30, 1.10, 1.11),
        ("S04", 1.05, 1.45, 0.95, 0.94),
    ]:
        for condition, left, right in [
            ("Semantic Response", semantic_left, semantic_right),
            ("Color Response", color_left, color_right),
        ]:
            rows.append(
                {
                    "condition": condition,
                    "subject_id": subject,
                    "roi": "Left Occipito-Temporal",
                    "roi_role": "primary",
                    "summed_bca_uv": left,
                }
            )
            rows.append(
                {
                    "condition": condition,
                    "subject_id": subject,
                    "roi": "Right Occipito-Temporal",
                    "roi_role": "primary",
                    "summed_bca_uv": right,
                }
            )

    contrasts = _planned_lateralization_contrasts(pd.DataFrame(rows))

    assert contrasts["contrast_type"].tolist() == [
        "condition_lateralization",
        "condition_lateralization",
        "lateralization_difference",
    ]
    semantic = contrasts.loc[contrasts["condition"] == "Semantic Response"].iloc[0]
    color = contrasts.loc[contrasts["condition"] == "Color Response"].iloc[0]
    interaction = contrasts.loc[
        contrasts["contrast_type"] == "lateralization_difference"
    ].iloc[0]
    assert semantic["mean_right_minus_left_uv"] == pytest.approx(0.35)
    assert semantic["direction"] == "right_greater_than_left"
    assert color["mean_right_minus_left_uv"] == pytest.approx(0.0)
    assert color["direction"] == "no_direction"
    assert semantic["p_holm_planned_family"] == pytest.approx(
        min(float(semantic["p_value_two_tailed"]) * 2, 1.0)
    )
    assert interaction["mean_difference_of_lateralization_uv"] == pytest.approx(0.35)
    assert interaction["condition_a"] == "Semantic Response"
    assert interaction["condition_b"] == "Color Response"
