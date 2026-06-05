"""GUI-agnostic publication report runner."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from Tools.Publication_Report.analysis_tables import build_analysis_frames
from Tools.Publication_Report.discovery import (
    discover_conditions,
    discover_workbooks,
    participant_ids,
    resolve_project_paths,
    selected_condition_names,
    validate_single_group_project,
)
from Tools.Publication_Report.models import (
    REPORT_AUDIT_NAME,
    REPORT_DOCX_NAME,
    REPORT_LOG_NAME,
    REPORT_MARKDOWN_NAME,
    REPORT_WORKBOOK_NAME,
    PublicationReportRequest,
    PublicationReportResult,
    ReportRoi,
    default_base_rate_roi,
    default_report_rois,
)
from Tools.Publication_Report.narrative import build_markdown, write_docx, write_markdown
from Tools.Publication_Report.workbook import build_initial_frames, write_audit_json, write_report_workbook

ProgressCallback = Callable[[int, str], None]


def generate_publication_report(
    request: PublicationReportRequest,
    *,
    progress: ProgressCallback | None = None,
) -> PublicationReportResult:
    """Generate the initial publication report bundle."""

    def emit(value: int, message: str) -> None:
        if progress is not None:
            progress(value, message)

    emit(5, "Resolving project paths...")
    effective = _effective_request(request)
    output_root = Path(effective.output_root or resolve_project_paths(effective.project_root)[2])
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir = output_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / REPORT_LOG_NAME

    warnings: list[str] = []
    if (
        effective.output_options.spectra
        or effective.output_options.scalp_maps
        or effective.output_options.individual_figures
    ):
        warnings.append(
            "Figure rendering is recorded in the manifest for this implementation "
            "slice; automated figure export will be attached in the next slice."
        )
    _write_log(log_path, "Publication Report run started.")

    emit(15, "Validating project...")
    validate_single_group_project(effective.project_root)
    discovered = discover_conditions(effective.excel_root or resolve_project_paths(effective.project_root)[1])
    selected_conditions = selected_condition_names(request=effective, discovered=discovered)
    if not selected_conditions:
        raise RuntimeError("No processed condition workbooks were found for publication reporting.")

    emit(30, "Discovering workbooks...")
    workbooks = discover_workbooks(effective.excel_root or resolve_project_paths(effective.project_root)[1], selected_conditions)
    if not workbooks:
        raise RuntimeError("No result workbooks were found for the selected publication-report conditions.")

    participants = participant_ids(workbooks)
    inclusion_df = _participant_inclusion_frame(effective, participants)
    included_subjects = _included_subjects(inclusion_df)
    condition_roles_df = _condition_roles_frame(effective, selected_conditions)
    roi_definitions_df = _roi_definitions_frame(effective)
    figure_manifest_df = _figure_manifest_frame(effective)

    emit(40, "Building report analysis tables...")
    analysis_frames = build_analysis_frames(
        request=effective,
        workbooks=workbooks,
        included_subjects=included_subjects,
        selected_conditions=selected_conditions,
        warnings=warnings,
    )
    warnings_df = pd.DataFrame({"warning": warnings})
    run_summary_df = _run_summary_frame(
        effective,
        selected_conditions=selected_conditions,
        participant_count=len(participants),
        included_count=int(inclusion_df["included"].sum()),
    )

    emit(45, "Building source workbook frames...")
    frames = build_initial_frames(
        run_summary=run_summary_df,
        participant_inclusion=inclusion_df,
        condition_roles=condition_roles_df,
        roi_definitions=roi_definitions_df,
        figure_manifest=figure_manifest_df,
        warnings=warnings_df,
    )
    frames.update(analysis_frames)

    generated: list[Path] = []
    workbook_path = None
    if effective.output_options.workbook:
        emit(60, "Writing source workbook...")
        workbook_path = write_report_workbook(output_root / REPORT_WORKBOOK_NAME, frames)
        generated.append(workbook_path)

    emit(70, "Writing draft narrative...")
    markdown_text = build_markdown(
        request=effective,
        selected_conditions=selected_conditions,
        participant_inclusion=inclusion_df,
        analysis_frames=frames,
        warnings=tuple(warnings),
    )
    markdown_path = None
    if effective.output_options.markdown:
        markdown_path = write_markdown(output_root / REPORT_MARKDOWN_NAME, markdown_text)
        generated.append(markdown_path)

    docx_path = None
    if effective.output_options.docx:
        docx_path = write_docx(output_root / REPORT_DOCX_NAME, markdown_text)
        generated.append(docx_path)

    audit_path = None
    if effective.output_options.audit_json:
        emit(85, "Writing audit JSON...")
        audit_payload = _audit_payload(
            effective,
            selected_conditions=selected_conditions,
            participants=participants,
            generated=generated,
            warnings=warnings,
        )
        audit_path = write_audit_json(output_root / REPORT_AUDIT_NAME, audit_payload)
        generated.append(audit_path)

    _write_log(log_path, "Publication Report run completed.")
    generated.append(log_path)
    emit(100, "Publication report complete.")
    return PublicationReportResult(
        output_root=output_root,
        markdown_path=markdown_path,
        docx_path=docx_path,
        workbook_path=workbook_path,
        audit_path=audit_path,
        log_path=log_path,
        generated_files=tuple(generated),
        warnings=tuple(warnings),
    )


def _effective_request(request: PublicationReportRequest) -> PublicationReportRequest:
    root, excel_root, output_root = resolve_project_paths(request.project_root)
    return replace(
        request,
        project_root=root,
        excel_root=Path(request.excel_root).resolve() if request.excel_root else excel_root,
        output_root=Path(request.output_root).resolve() if request.output_root else output_root,
        rois=request.rois or default_report_rois(),
        base_rate_roi=request.base_rate_roi or default_base_rate_roi(),
    )


def _participant_inclusion_frame(
    request: PublicationReportRequest,
    participants: tuple[str, ...],
) -> pd.DataFrame:
    manual = {subject.upper() for subject in request.manual_excluded_subjects}
    qc = {subject.upper() for subject in request.qc_excluded_subjects}
    rows: list[dict[str, object]] = []
    for subject in participants:
        subject_upper = subject.upper()
        reasons: list[str] = []
        if subject_upper in manual:
            reasons.append("manual_exclusion")
        if subject_upper in qc:
            reasons.append("qc_exclusion")
        rows.append(
            {
                "subject_id": subject,
                "included": not reasons,
                "manual_excluded": subject_upper in manual,
                "qc_excluded": subject_upper in qc,
                "exclusion_reason": "; ".join(reasons),
            }
        )
    return pd.DataFrame(rows)


def _included_subjects(participant_inclusion: pd.DataFrame) -> tuple[str, ...]:
    if participant_inclusion.empty:
        return ()
    frame = participant_inclusion.copy()
    frame["included"] = frame["included"].fillna(False).astype(bool)
    return tuple(str(value) for value in frame.loc[frame["included"], "subject_id"])


def _condition_roles_frame(
    request: PublicationReportRequest,
    selected_conditions: tuple[str, ...],
) -> pd.DataFrame:
    rows = [
        {
            "condition": condition,
            "label": request.condition_labels.get(condition, condition),
            "role": "selected",
        }
        for condition in selected_conditions
    ]
    return pd.DataFrame(rows)


def _roi_definitions_frame(request: PublicationReportRequest) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for roi in [*request.rois, request.base_rate_roi]:
        if roi is None:
            continue
        rows.append(_roi_row(roi))
    return pd.DataFrame(rows)


def _roi_row(roi: ReportRoi) -> dict[str, object]:
    return {
        "roi": roi.name,
        "role": roi.role,
        "selected": bool(roi.selected),
        "electrode_count": len(roi.electrodes),
        "electrodes": ", ".join(roi.electrodes),
    }


def _figure_manifest_frame(request: PublicationReportRequest) -> pd.DataFrame:
    rows = [
        ("spectra", request.output_options.spectra),
        ("scalp_maps", request.output_options.scalp_maps),
        ("individual_detectability", request.output_options.individual_figures),
    ]
    return pd.DataFrame(
        [
            {
                "figure_family": family,
                "requested": bool(requested),
                "status": "planned_next_slice" if requested else "disabled",
                "path": "",
            }
            for family, requested in rows
        ]
    )


def _run_summary_frame(
    request: PublicationReportRequest,
    *,
    selected_conditions: tuple[str, ...],
    participant_count: int,
    included_count: int,
) -> pd.DataFrame:
    rows = [
        ("timestamp", datetime.now().isoformat(timespec="seconds")),
        ("project_root", str(request.project_root)),
        ("excel_root", str(request.excel_root)),
        ("output_root", str(request.output_root)),
        ("report_label", request.report_label),
        ("target_response_label", request.target_response_label),
        ("selected_conditions", "; ".join(selected_conditions)),
        ("participant_count", participant_count),
        ("included_participant_count", included_count),
        ("base_frequency_hz", request.base_frequency_hz),
        ("bca_upper_limit_hz", request.bca_upper_limit_hz),
        ("z_thresholds", "; ".join(f"{value:g}" for value in request.z_thresholds)),
        ("individual_bh_fdr_default", True),
    ]
    return pd.DataFrame(rows, columns=["field", "value"])


def _audit_payload(
    request: PublicationReportRequest,
    *,
    selected_conditions: tuple[str, ...],
    participants: tuple[str, ...],
    generated: list[Path],
    warnings: list[str],
) -> dict[str, object]:
    return {
        "project_root": str(request.project_root),
        "excel_root": str(request.excel_root),
        "output_root": str(request.output_root),
        "report_label": request.report_label,
        "target_response_label": request.target_response_label,
        "selected_conditions": list(selected_conditions),
        "participants": list(participants),
        "manual_excluded_subjects": sorted(request.manual_excluded_subjects),
        "qc_excluded_subjects": sorted(request.qc_excluded_subjects),
        "base_frequency_hz": request.base_frequency_hz,
        "bca_upper_limit_hz": request.bca_upper_limit_hz,
        "z_thresholds": list(request.z_thresholds),
        "rois": [_roi_row(roi) for roi in request.rois],
        "base_rate_roi": _roi_row(request.base_rate_roi) if request.base_rate_roi else None,
        "generated_files": [str(path) for path in generated],
        "warnings": list(warnings),
    }


def _write_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
