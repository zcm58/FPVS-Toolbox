"""Project-local validation report for generated source-localization outputs.

The report summarizes already-written prepared source payloads and sidecars.
It does not calculate source estimates, inspect renderer state, or mutate
project inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload

SOURCE_VALIDATION_REPORT_FORMAT = "fpvs-loreta-source-validation-report-v1"
DEFAULT_SOURCE_VALIDATION_REPORT_JSON_NAME = "source_validation_report.json"
DEFAULT_SOURCE_VALIDATION_REPORT_MARKDOWN_NAME = "source_validation_report.md"


@dataclass(frozen=True)
class SourceValidationReportResult:
    """Files emitted for a project-local source-validation report."""

    json_path: Path
    markdown_path: Path


def write_project_source_validation_report(
    *,
    output_dir: str | Path,
    manifest_path: str | Path,
    payloads: Sequence[ProducedPayload],
    project_inputs: Any,
    export_model: str,
    participant_sidecar_path: str | Path | None = None,
    lateralization_summary_path: str | Path | None = None,
    lateralization_summary_csv_path: str | Path | None = None,
    forward_model_metadata: dict[str, Any] | None = None,
    json_name: str = DEFAULT_SOURCE_VALIDATION_REPORT_JSON_NAME,
    markdown_name: str = DEFAULT_SOURCE_VALIDATION_REPORT_MARKDOWN_NAME,
) -> SourceValidationReportResult:
    """Write JSON and Markdown validation summaries beside generated payloads."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest_file = Path(manifest_path)
    participant_file = Path(participant_sidecar_path) if participant_sidecar_path is not None else None
    lateralization_file = Path(lateralization_summary_path) if lateralization_summary_path is not None else None
    lateralization_csv_file = (
        Path(lateralization_summary_csv_path) if lateralization_summary_csv_path is not None else None
    )

    manifest = _read_json(manifest_file)
    payload_summaries = [_payload_summary(payload) for payload in payloads]
    participant_summary = _participant_sidecar_summary(participant_file)
    lateralization_summary = _lateralization_summary(lateralization_file)
    report = {
        "format": SOURCE_VALIDATION_REPORT_FORMAT,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_scope": "project-local generated source outputs",
        "project_name": Path(getattr(project_inputs, "project_root", "")).name,
        "output_dir": str(output_path),
        "export_model": str(export_model),
        "source_method_status": "beta",
        "input_summary": _input_summary(project_inputs),
        "manifest": {
            "path": str(manifest_file),
            "file": manifest_file.name,
            "label": str(manifest.get("label", "")),
            "condition_count": len(manifest.get("conditions", [])),
        },
        "generated_files": _generated_files(
            manifest_file=manifest_file,
            payloads=payloads,
            participant_file=participant_file,
            lateralization_file=lateralization_file,
            lateralization_csv_file=lateralization_csv_file,
        ),
        "payload_summaries": payload_summaries,
        "participant_sidecar_summary": participant_summary,
        "lateralization_summary": lateralization_summary,
        "forward_model_summary": _forward_model_summary(forward_model_metadata or {}),
        "validation_checks": _validation_checks(
            payloads=payloads,
            participant_summary=participant_summary,
            lateralization_summary=lateralization_summary,
        ),
        "limitations": _beta_limitations(),
        "recommended_manual_checks": _recommended_manual_checks(),
    }

    json_path = output_path / json_name
    markdown_path = output_path / markdown_name
    _write_json(json_path, report)
    _write_text(markdown_path, _markdown_report(report))
    return SourceValidationReportResult(json_path=json_path, markdown_path=markdown_path)


def _payload_summary(payload: ProducedPayload) -> dict[str, Any]:
    raw = _read_json(payload.payload_path)
    values = [float(value) for value in raw.get("values", [])]
    metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
    cluster_vertex_count = _int_or_none(metadata.get("cluster_mask_vertex_count"))
    return {
        "condition_id": payload.condition_id,
        "label": payload.label,
        "file": payload.payload_path.name,
        "validation_label": payload.validation.label,
        "source_model": str(raw.get("source_model", "")),
        "kind": str(raw.get("kind", "")),
        "coordinate_space": str(raw.get("coordinate_space", "")),
        "value_label": str(raw.get("value_label", "")),
        "source_value_unit": str(metadata.get("source_value_unit", "")),
        "participant_zscore_aggregation": str(metadata.get("participant_zscore_aggregation", "")),
        "source_count": len(raw.get("points", [])),
        "value_min": min(values) if values else None,
        "value_max": max(values) if values else None,
        "positive_value_count": sum(1 for value in values if value > 0.0),
        "cluster_mask": str(metadata.get("cluster_mask", "none")),
        "cluster_mask_status": str(metadata.get("cluster_mask_status", "")),
        "cluster_mask_vertex_count": cluster_vertex_count,
        "cluster_mask_primary_display": bool(metadata.get("cluster_mask_primary_display", False)),
        "selected_harmonics_hz": list(metadata.get("selected_harmonics_hz", [])),
    }


def _participant_sidecar_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"available": False}
    raw = _read_json(path)
    conditions = raw.get("conditions", [])
    condition_rows = []
    for condition in conditions if isinstance(conditions, list) else []:
        if not isinstance(condition, dict):
            continue
        cluster_mask = condition.get("cluster_mask", {})
        if not isinstance(cluster_mask, dict):
            cluster_mask = {}
        condition_rows.append(
            {
                "condition_id": str(condition.get("condition_id", "")),
                "label": str(condition.get("label", "")),
                "participant_count": _int_or_none(condition.get("participant_count")),
                "cluster_mask": str(cluster_mask.get("cluster_mask", "none")),
                "cluster_mask_status": str(cluster_mask.get("cluster_mask_status", "")),
                "cluster_mask_vertex_count": _int_or_none(cluster_mask.get("cluster_mask_vertex_count")),
            }
        )
    return {
        "available": True,
        "file": path.name,
        "source_model": str(raw.get("source_model", "")),
        "source_value_unit": str(raw.get("source_value_unit", "")),
        "condition_count": len(condition_rows),
        "conditions": condition_rows,
    }


def _lateralization_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"available": False}
    raw = _read_json(path)
    rows = raw.get("rows", [])
    row_list = [row for row in rows if isinstance(row, dict)]
    primary_rows = [
        _lateralization_row_summary(row)
        for row in row_list
        if row.get("roi_id") == "desikan_killiany_temporal_hauk" and row.get("map_type") == "group_summary"
    ]
    return {
        "available": True,
        "file": path.name,
        "row_count": len(row_list),
        "primary_roi_id": "desikan_killiany_temporal_hauk",
        "primary_group_rows": primary_rows,
        "metadata": raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {},
    }


def _lateralization_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition_id": str(row.get("condition_id", "")),
        "condition_label": str(row.get("condition_label", "")),
        "aggregation": str(row.get("aggregation", "")),
        "lateralization_index_sum": _float_or_none(row.get("lateralization_index_sum")),
        "dominant_hemisphere": str(row.get("dominant_hemisphere", "")),
        "left_sum_positive_z": _float_or_none(row.get("left_sum_positive_z")),
        "right_sum_positive_z": _float_or_none(row.get("right_sum_positive_z")),
    }


def _input_summary(project_inputs: Any) -> dict[str, Any]:
    bin_plan = getattr(project_inputs, "bin_plan", None)
    summaries = []
    for summary in getattr(project_inputs, "summaries", ()):
        summaries.append(
            {
                "condition": str(getattr(summary, "condition", "")),
                "workbook_count": int(getattr(summary, "workbook_count", 0)),
                "included_subject_count": int(getattr(summary, "included_subject_count", 0)),
                "included_subjects": list(getattr(summary, "included_subjects", ())),
                "flagged_subjects": list(getattr(summary, "flagged_subjects", ())),
            }
        )
    return {
        "sheet_name": str(getattr(project_inputs, "sheet_name", "")),
        "selected_harmonics_hz": list(getattr(project_inputs, "selected_harmonics_hz", ())),
        "condition_count": len(getattr(project_inputs, "conditions", ())),
        "excluded_subjects": list(getattr(project_inputs, "excluded_subjects", ())),
        "flagged_subjects": list(getattr(project_inputs, "flagged_subjects", ())),
        "diagnostics": list(getattr(project_inputs, "diagnostics", ())),
        "frequency_resolution_hz": getattr(bin_plan, "frequency_resolution_hz", None),
        "noise_window_bins": getattr(bin_plan, "noise_window_bins", None),
        "excluded_noise_offsets": list(getattr(bin_plan, "excluded_offsets", ())),
        "min_noise_bins": getattr(bin_plan, "min_noise_bins", None),
        "condition_summaries": summaries,
    }


def _generated_files(
    *,
    manifest_file: Path,
    payloads: Sequence[ProducedPayload],
    participant_file: Path | None,
    lateralization_file: Path | None,
    lateralization_csv_file: Path | None,
) -> dict[str, Any]:
    return {
        "manifest": manifest_file.name,
        "payloads": [payload.payload_path.name for payload in payloads],
        "participant_sidecar": participant_file.name if participant_file is not None and participant_file.exists() else "",
        "lateralization_json": (
            lateralization_file.name if lateralization_file is not None and lateralization_file.exists() else ""
        ),
        "lateralization_csv": (
            lateralization_csv_file.name
            if lateralization_csv_file is not None and lateralization_csv_file.exists()
            else ""
        ),
    }


def _forward_model_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    interesting_keys = (
        "forward_model_status",
        "inverse_backend",
        "orientation_constraint",
        "loose_orientation",
        "fixed_orientation",
        "depth_weighting",
        "noise_normalization",
        "fsaverage_subject",
        "fsaverage_spacing",
        "sensor_modalities",
        "subject_mri",
    )
    return {key: metadata[key] for key in interesting_keys if key in metadata}


def _validation_checks(
    *,
    payloads: Sequence[ProducedPayload],
    participant_summary: dict[str, Any],
    lateralization_summary: dict[str, Any],
) -> dict[str, Any]:
    payload_count = len(payloads)
    cluster_masked_payloads = sum(
        1 for payload in payloads if _payload_summary(payload).get("cluster_mask") == "source_space_cluster_permutation"
    )
    return {
        "manifest_validated": True,
        "payload_count": payload_count,
        "all_payloads_validated": all(bool(payload.validation.label) for payload in payloads),
        "cluster_masked_payload_count": cluster_masked_payloads,
        "participant_sidecar_available": bool(participant_summary.get("available")),
        "lateralization_summary_available": bool(lateralization_summary.get("available")),
    }


def _beta_limitations() -> list[str]:
    return [
        "This is a beta source-localization workflow.",
        "The current real-project method is EEG-only L2-MNE on an fsaverage/template cortical surface.",
        "The workflow does not use subject-specific MRIs or subject-specific forward models.",
        "Cluster masks are source-space producer outputs; the renderer only displays prepared masks.",
        "Source-space lateralization summaries are descriptive companion metrics and do not replace sensor-space BCA lateralization statistics.",
    ]


def _recommended_manual_checks() -> list[str]:
    return [
        "Compare publication split-hemisphere maps against matching scalp maps.",
        "Compare cluster-masked maps against unmasked/exploratory threshold views.",
        "Review flagged-participant include/exclude behavior when relevant.",
        "Compare source lateralization rows against known sensor-space BCA lateralization results.",
        "Record unresolved assumptions before selecting the next source method.",
    ]


def _markdown_report(report: dict[str, Any]) -> str:
    input_summary = report["input_summary"]
    validation = report["validation_checks"]
    lateralization = report["lateralization_summary"]
    lines = [
        "# Source Localization Validation Report",
        "",
        f"- Project: {report['project_name']}",
        f"- Export model: {report['export_model']}",
        f"- Source method status: {report['source_method_status']}",
        f"- Manifest: {report['manifest']['file']}",
        f"- Conditions: {input_summary['condition_count']}",
        f"- Payloads: {validation['payload_count']}",
        f"- Cluster-masked payloads: {validation['cluster_masked_payload_count']}",
        f"- Selected harmonics: {_join_values(input_summary['selected_harmonics_hz'])}",
        "",
        "## Validation Checks",
        "",
        f"- Manifest validated: {_yes_no(validation['manifest_validated'])}",
        f"- All payloads validated: {_yes_no(validation['all_payloads_validated'])}",
        f"- Participant sidecar available: {_yes_no(validation['participant_sidecar_available'])}",
        f"- Lateralization summary available: {_yes_no(validation['lateralization_summary_available'])}",
        "",
        "## Lateralization Highlights",
        "",
    ]
    primary_rows = lateralization.get("primary_group_rows", []) if lateralization.get("available") else []
    if primary_rows:
        lines.extend(
            (
                "| Condition | Aggregation | LI | Dominant hemisphere |",
                "| --- | --- | ---: | --- |",
            )
        )
        for row in primary_rows:
            lines.append(
                "| "
                f"{row['condition_label']} | {row['aggregation']} | "
                f"{_format_number(row['lateralization_index_sum'])} | {row['dominant_hemisphere']} |"
            )
    else:
        lines.append("- No Desikan-Killiany temporal group lateralization rows were available.")
    lines.extend(
        (
            "",
            "## Payload Summary",
            "",
            "| Payload | Source model | Aggregation | Value range | Cluster vertices |",
            "| --- | --- | --- | ---: | ---: |",
        )
    )
    for payload in report["payload_summaries"]:
        value_range = f"{_format_number(payload['value_min'])} to {_format_number(payload['value_max'])}"
        lines.append(
            "| "
            f"{payload['file']} | {payload['source_model']} | "
            f"{payload['participant_zscore_aggregation']} | {value_range} | "
            f"{_format_number(payload['cluster_mask_vertex_count'])} |"
        )
    lines.extend(("", "## Limitations", ""))
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(("", "## Recommended Manual Checks", ""))
    lines.extend(f"- {item}" for item in report["recommended_manual_checks"])
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(_json_safe(payload), handle, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def _write_text(path: Path, text: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _join_values(values: Sequence[Any]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{numeric:.4g}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return str(value)
