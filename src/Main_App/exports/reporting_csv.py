"""Serialize accepted canonical ROI results without recomputing their values."""

from __future__ import annotations

import csv
import hashlib
import io
import math
from pathlib import Path
from typing import Any

from Main_App.reporting.snapshots import dataset_identity
from Main_App.reporting.provenance import recording_identity, scoped_identity as scoped_identity

CSV_COLUMNS = ("subject_id", "group", "condition", "roi", "summed_bca_uv", "recording_id", "session_id", "visit_id")


def _text(value: object, *, required: bool = True) -> str:
    original = str(value or "")
    text = original.strip()
    if (
        (required and not text)
        or len(text) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in original)
    ):
        raise ValueError("Reporting labels must be short, nonempty text without control characters.")
    if text.startswith(("=", "+", "-", "@")):
        raise ValueError("Reporting labels cannot start with spreadsheet formulas.")
    return text


def canonical_rows_to_csv(rows: list[dict[str, Any]], dataset_id: str) -> tuple[str, dict[str, int]]:
    """Keep finite canonical values; unavailable/excluded cells stay in QC counts."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    subjects: set[str] = set()
    recordings: set[str] = set()
    seen: set[tuple[str, ...]] = set()
    unavailable = 0
    for row in rows:
        excluded = row.get("Current Toolbox Exclusion")
        if excluded is True or str(excluded).strip().casefold() in {"true", "yes", "1"}:
            unavailable += 1
            continue
        raw = row.get("Raw Summed BCA")
        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            unavailable += 1
            continue
        if not math.isfinite(numeric):
            unavailable += 1
            continue
        identity = recording_identity(
            dataset_id, row.get("PID"), row.get("Recording ID"), row.get("Session ID"), row.get("Visit Index")
        )
        exported = {
            **identity,
            "group": _text(row.get("Group ID") or row.get("Group")),
            "condition": _text(row.get("Condition")),
            "roi": _text(row.get("ROI")),
            "summed_bca_uv": repr(numeric),
        }
        identity = tuple(
            exported[key] for key in ("subject_id", "recording_id", "session_id", "visit_id", "condition", "roi")
        )
        if identity in seen:
            raise ValueError("Canonical reporting data repeats a recording-condition-ROI cell.")
        seen.add(identity)
        writer.writerow(exported)
        subjects.add(exported["subject_id"])
        recordings.add(exported["recording_id"])
        if len(seen) > 10_000:
            raise ValueError("Reporting data exceeds the 10,000-row limit.")
    if not seen:
        raise ValueError("Reporting requires at least one finite canonical ROI result.")
    return output.getvalue(), {
        "subjects": len(subjects),
        "recordings": len(recordings),
        "rows": len(seen),
        "unavailable_roi_cells": unavailable,
    }


def export_reporting_csv(project_root: Path, scope: dict[str, str]) -> tuple[dict[str, Any], str]:
    from Main_App.exports.analysis_ready_workbook import (
        ROI_LONG_SHEET,
        _load_current_processing_selection_metadata,
        _load_selection_frames,
        _selected_harmonics_from_frames,
    )
    from Main_App.processing.artifact_freshness import canonical_artifact_path, require_current_artifact
    from Main_App.processing.roi_coverage import require_project_final_release
    from Main_App.processing.expected_processing_ledger import load_expected_recording_condition_plan
    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.projects.project import Project
    from Main_App.updates.application import APP_VERSION
    import pandas as pd

    root = Path(project_root).resolve()
    _outcomes, coverage, receipt = require_project_final_release(root)
    plan = load_expected_recording_condition_plan(root)
    if plan is None or plan.fingerprint != _outcomes.expected_plan_fingerprint:
        raise ValueError("Reporting requires the current processing plan fingerprint.")
    artifact = "analysis_ready_full_audit"
    path = canonical_artifact_path(root, artifact)
    freshness = require_current_artifact(root, artifact, path)
    selection = _load_current_processing_selection_metadata(root)
    frames, _source = _load_selection_frames(
        root, selection_metadata=selection, expected_release_fingerprint=receipt.fingerprint
    )
    harmonics = _selected_harmonics_from_frames(frames)
    if not harmonics or len(harmonics) > 512:
        raise ValueError("Canonical reporting harmonic list is invalid.")
    project = Project.load(root)
    cohort = project.manifest.get("tools", {}).get("studio_cohort", {})
    result = cohort.get("current_result", {})
    if (
        not result
        or result.get("roster_revision") != cohort.get("roster_revision")
        or result.get("processing_run_id") != plan.run_id
        or result.get("release_fingerprint") != receipt.fingerprint
        or result.get("versions") != cohort.get("versions")
        or result.get("workbook") != path.relative_to(root).as_posix()
    ):
        raise ValueError("Complete the full-audit release for this reviewed roster before sharing study results.")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != result.get("workbook_sha256"):
            raise ValueError("The released workbook changed. Generate it again before sharing.")
        stream.seek(0)
        identity_columns = ("PID", "Group ID", "Group", "Condition", "ROI", "Recording ID", "Session ID")
        rows = pd.read_excel(
            stream, sheet_name=ROI_LONG_SHEET, keep_default_na=False, dtype={name: str for name in identity_columns}
        ).to_dict("records")
    identifier = dataset_identity(root)
    results_csv, counts = canonical_rows_to_csv(rows, identifier)
    counts["excluded_cells"] = sum(
        cell.downstream_cell_excluded or cell.source_evidence is None for cell in coverage.cells
    )
    rois = [{"name": _text(roi.name), "electrodes": list(roi.electrodes)} for roi in coverage.roi_snapshot.rois]
    if not rois or len(rois) > 128:
        raise ValueError("Canonical reporting ROI definitions are invalid.")
    from Main_App.reporting.provenance import acquisition_provenance, reviewed_coverage, reporting_scope
    from Main_App.reporting.electrode_exclusions import build_electrode_exclusions

    entries = load_ledger(root).get("entries", {})
    if reporting_scope(project) != scope:
        raise ValueError("The reviewed project's study link changed. Review the destination again.")
    contributing = {str(cell.recording_id).casefold() for cell in coverage.cells if cell.source_evidence is not None}
    source_entries = {str(processing_id).casefold(): entry for processing_id, entry in entries.items()}
    rates = {
        (
            source_entries.get(key, {}).get("native_sampling_rate_hz"),
            source_entries.get(key, {}).get("analysis_sampling_rate_hz"),
        )
        for key in contributing
    }
    if len(rates) != 1 or None in next(iter(rates)):
        raise ValueError("Reprocess the cohort to record a common native and analysis sampling rate before sharing.")
    csv_rows = list(csv.DictReader(io.StringIO(results_csv)))
    csv_recordings = {row["recording_id"] for row in csv_rows}
    electrode_exclusions = build_electrode_exclusions(project, plan, entries, identifier, csv_recordings)
    identities = {
        row["recording_id"]: tuple(row[key] for key in ("subject_id", "session_id", "visit_id"))
        for row in electrode_exclusions["recordings"]
    }
    for row in csv_rows:
        if identities.get(row["recording_id"]) != tuple(row[key] for key in ("subject_id", "session_id", "visit_id")):
            raise ValueError("Canonical ROI identity differs from the current recording plan.")
    executions = {
        row["studio_execution_id"]
        for row in electrode_exclusions["recordings"]
        if row["recording_id"] in csv_recordings
    }
    excluded = {cell.recording_id for cell in coverage.cells if cell.downstream_cell_excluded}
    excluded.difference_update(cell.recording_id for cell in coverage.cells if not cell.downstream_cell_excluded)
    roster = reviewed_coverage(cohort, executions, excluded)
    manifest = {
        "schema_version": "1.2",
        **scope,
        "dataset_id": identifier,
        "toolbox_version": APP_VERSION,
        "roster_coverage": roster,
        "acquisition": acquisition_provenance(project.preprocessing, *next(iter(rates))),
        "roi_definitions": rois,
        "included_harmonics_hz": harmonics,
        "selection_fingerprint": freshness.built_from_selection_fingerprint,
        "processing_fingerprint": plan.processing_fingerprint,
        "final_release_fingerprint": receipt.fingerprint,
        "counts": counts,
        "electrode_exclusions": electrode_exclusions,
    }
    return manifest, results_csv
