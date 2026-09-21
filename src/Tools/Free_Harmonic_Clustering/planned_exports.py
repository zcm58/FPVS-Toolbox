"""Additive, atomic exports of a frozen FHC analysis-family plan."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import os
import json
from pathlib import Path
import platform
import shutil
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

import numpy as np
from openpyxl import Workbook

from config import FPVS_TOOLBOX_VERSION
from .analysis import global_cluster_two_sided_p_value, holm_adjust_p_values
from .exports import (
    _batch_artifact_manifest_row,
    _check_export_cancelled,
    _cluster_membership_rows,
    _cluster_summary_rows,
    _dependency_version,
    _export_cluster_maps,
    _frequency_plan_manifest,
    _node_statistic_rows,
    _relative_to,
    _resolve_project_root,
    _sha256_file,
    _source_workbook_rows,
    _validate_result,
    _write_csv,
    _write_manifest,
    _write_table_sheet,
    resolve_run_destination,
)
from .models import ExportArtifact, ExportReceipt
from .planned_reporting import build_analysis_plan_report, build_planned_cluster_map_data, outcome_status

if TYPE_CHECKING:
    from .planned_analysis import PlannedAnalysisResult


PLANNED_WORKBOOK_FILENAME = "Free_Harmonic_Clustering_Analysis_Families.xlsx"
PLANNED_EXPORT_SCHEMA_VERSION = 1


def _tensor_semantics(comparison: object) -> str:
    if comparison.kind.value == "group_visit_change":
        return "Difference of separately L2-normalized visit SNR profiles; no renormalization of the change"
    if comparison.session_ids and comparison.kind.value in {"between_groups", "between_conditions"}:
        return "Participant candidate SNR averaged across both visits, then L2-normalized once per arm"
    return "Participant-arm L2-normalized SNR across the retained sensor x harmonic tensor"


def _write_plan_arrays(path: Path, outcome: object) -> None:
    contrast, raw = outcome.contrast, outcome.result
    metadata = {
        "comparison_id": outcome.comparison.comparison_id,
        "family_id": outcome.comparison.family_id,
        "arm_a_label": contrast.arm_a_label,
        "arm_b_label": contrast.arm_b_label,
        "tensor_semantics": _tensor_semantics(outcome.comparison),
        "global_p": outcome.global_p,
        "family_holm_p": outcome.family_adjusted_p,
        "full_plan_holm_p": outcome.batch_adjusted_p,
    }
    with path.open("wb") as stream:
        np.savez_compressed(
            stream,
            analyzed_values_a=contrast.values_a,
            analyzed_values_b=contrast.values_b,
            observed_t=raw.observed_t,
            cluster_labels=raw.cluster_labels,
            null_positive_max_mass=raw.null_positive_max_mass,
            null_negative_min_mass=raw.null_negative_min_mass,
            participant_ids_a=np.asarray(contrast.participant_ids_a, dtype=np.str_),
            participant_ids_b=np.asarray(contrast.participant_ids_b, dtype=np.str_),
            sensor_names=np.asarray(contrast.sensor_names, dtype=np.str_),
            harmonic_orders=contrast.harmonic_orders,
            harmonics_hz=contrast.harmonics_hz,
            metadata_json=np.asarray(json.dumps(metadata, sort_keys=True, allow_nan=False), dtype=np.str_),
        )
        stream.flush()
        os.fsync(stream.fileno())


def _validate_complete_result(result: PlannedAnalysisResult) -> None:
    from .planned_analysis import derive_planned_comparison_seed

    expected = result.plan.comparisons
    if not expected or tuple(row.comparison for row in result.outcomes) != expected:
        raise ValueError("Export requires every planned comparison exactly once and in plan order.")
    global_p = tuple(global_cluster_two_sided_p_value(row.result) for row in result.outcomes)
    full_p = holm_adjust_p_values(global_p)
    families: dict[str, list[int]] = {}
    for index, comparison in enumerate(expected):
        families.setdefault(comparison.family_id, []).append(index)
    family_p = [0.0] * len(expected)
    for indices in families.values():
        adjusted = holm_adjust_p_values(tuple(global_p[index] for index in indices))
        for index, value in zip(indices, adjusted, strict=True):
            family_p[index] = value
    for index, outcome in enumerate(result.outcomes):
        _validate_result(outcome.contrast, outcome.result)
        if outcome.result.seed != outcome.derived_seed or outcome.derived_seed != derive_planned_comparison_seed(
            result.prepared.method.seed, outcome.comparison.comparison_id
        ):
            raise ValueError("Export seed differs from the planned comparison seed.")
        if (outcome.global_p, outcome.family_adjusted_p, outcome.batch_adjusted_p) != (
            global_p[index],
            family_p[index],
            full_p[index],
        ):
            raise ValueError("Stored p-values do not match correction across the complete analysis plan.")


def _summary_rows(result: PlannedAnalysisResult) -> list[dict[str, object]]:
    sizes: dict[str, int] = {}
    for comparison in result.plan.comparisons:
        sizes[comparison.family_id] = sizes.get(comparison.family_id, 0) + 1
    return [
        {
            "comparison_id": row.comparison.comparison_id,
            "family_id": row.comparison.family_id,
            "family": row.comparison.family_label,
            "comparison": row.comparison.label,
            "condition": row.comparison.condition,
            "family_comparison_count": sizes[row.comparison.family_id],
            "n_a": len(row.contrast.participant_ids_a),
            "n_b": len(row.contrast.participant_ids_b),
            "global_p": row.global_p,
            "holm_within_family_p_value": row.family_adjusted_p,
            "holm_all_batch_p_value": row.batch_adjusted_p,
            "passes_family_holm": row.family_adjusted_p <= 0.05,
            "interpretation": outcome_status(row),
            "within_comparison_significant_clusters": sum(c.significant for c in row.result.clusters),
        }
        for row in result.outcomes
    ]


def export_analysis_plan_result(
    result: PlannedAnalysisResult,
    *,
    run_id: str | None = None,
    destination: str | Path | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ExportReceipt:
    """Publish the entire plan or nothing; historical run bundles are immutable."""
    _check_export_cancelled(cancel_check)
    _validate_complete_result(result)
    first = result.outcomes[0].contrast
    root = _resolve_project_root(first)
    if Path(result.plan.project_root).resolve(strict=True) != root:
        raise ValueError("Plan and prepared data belong to different managed projects.")
    for row in result.outcomes:
        if _resolve_project_root(row.contrast) != root:
            raise ValueError("All comparisons must belong to the same managed project.")
    resolved_id, final_directory = resolve_run_destination(first, run_id=run_id, destination=destination)
    if final_directory.exists():
        raise FileExistsError(f"Free-harmonic run already exists: {final_directory}")
    parent = final_directory.parent
    _relative_to(parent.resolve(strict=False), root, label="Output parent")
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{resolved_id}.staging-{uuid4().hex}"
    _relative_to(staging.resolve(strict=False), root, label="Staging directory")
    staging.mkdir(exist_ok=False)
    artifacts: list[dict[str, object]] = []

    def record(path: Path, role: str) -> None:
        artifacts.append(
            _batch_artifact_manifest_row(
                role=role,
                staging_path=path,
                staging_root=staging,
                destination=final_directory,
                project_root=root,
            )
        )

    summary = _summary_rows(result)
    clusters: list[dict[str, object]] = []
    membership: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    participants: list[dict[str, object]] = []
    analyses: list[dict[str, object]] = []
    report = build_analysis_plan_report(result)
    try:
        plan_path = staging / "analysis_plan.json"
        _write_manifest(plan_path, {**result.plan.to_dict(), "plan_fingerprint": result.plan.fingerprint})
        record(plan_path, "analysis_plan")
        for index, outcome in enumerate(result.outcomes):
            _check_export_cancelled(cancel_check)
            comparison, prepared, raw = outcome.comparison, outcome.contrast, outcome.result
            identity = {"comparison_id": comparison.comparison_id, "family_id": comparison.family_id}
            for row in _cluster_summary_rows(prepared, raw):
                row["arm_a_analyzed_cluster_node_mean"] = row.pop("arm_a_normalized_cluster_node_mean")
                row["arm_b_analyzed_cluster_node_mean"] = row.pop("arm_b_normalized_cluster_node_mean")
                row["arm_a_minus_b_analyzed_difference"] = row.pop("arm_a_minus_b_normalized_difference")
                row.pop("arm_a_minus_b_raw_difference")
                row["effect_value_scale"] = _tensor_semantics(comparison)
                row["descriptive_effect_label"] = "Post-selection cluster-node effect in the analyzed tensors"
                clusters.append({**identity, **row})
            membership.extend({**identity, **row} for row in _cluster_membership_rows(prepared, raw))
            sources.extend(
                {
                    **identity,
                    **row,
                    "recording_id": source.recording_id,
                    "session_id": source.session_id,
                    "session_label": source.session_label,
                    "visit_index": source.visit_index,
                }
                for row, source in zip(_source_workbook_rows(prepared, root), prepared.source_workbooks, strict=True)
            )
            for arm, label, ids in (
                ("A", prepared.arm_a_label, prepared.participant_ids_a),
                ("B", prepared.arm_b_label, prepared.participant_ids_b),
            ):
                participants.extend(
                    {**identity, "arm": arm, "arm_label": label, "participant_id": participant} for participant in ids
                )
            detail_directory = staging / "comparisons" / f"{index + 1:04d}"
            detail_directory.mkdir(parents=True)
            array_path = detail_directory / "arrays.npz"
            _write_plan_arrays(array_path, outcome)
            record(array_path, "comparison_arrays")
            node_path = detail_directory / "node_statistics.csv"
            nodes = _node_statistic_rows(prepared, raw)
            _write_csv(node_path, tuple(nodes[0]), nodes)
            record(node_path, "node_statistics")
            for map_path in _export_cluster_maps(
                build_planned_cluster_map_data(outcome),
                detail_directory / "cluster_maps",
                cancel_check=cancel_check,
            ):
                record(map_path, "cluster_map_data" if map_path.suffix == ".json" else "cluster_map_figure")
            analyses.append(
                {
                    **identity,
                    "directory": detail_directory.relative_to(staging).as_posix(),
                    "design": comparison.design.value,
                    "comparison": comparison.label,
                    "tensor_semantics": _tensor_semantics(comparison),
                    "arm_a_label": prepared.arm_a_label,
                    "arm_b_label": prepared.arm_b_label,
                    "participant_ids_a": list(prepared.participant_ids_a),
                    "participant_ids_b": list(prepared.participant_ids_b),
                    "seed": outcome.derived_seed,
                    "rng_algorithm": raw.rng_algorithm,
                    "permutations_evaluated": raw.permutations_evaluated,
                    "permutation_assignment_hash": raw.permutation_assignment_hash,
                    "degrees_of_freedom": raw.degrees_of_freedom,
                    "cluster_forming_threshold": raw.cluster_forming_threshold,
                    "warnings": list(raw.warnings),
                    "timing_seconds": dict(raw.timing_seconds),
                }
            )

        family_rows = []
        for family in dict.fromkeys(row["family_id"] for row in summary):
            rows = [row for row in summary if row["family_id"] == family]
            family_rows.append(
                {
                    "family_id": family,
                    "family": rows[0]["family"],
                    "planned_comparisons": len(rows),
                    "passes_family_holm": sum(bool(row["passes_family_holm"]) for row in rows),
                }
            )
        audit_rows = [asdict(row) for row in result.prepared.cohort_audit]
        exclusion_rows = [
            {
                "scope": "FHC recording",
                "identity": row.recording_id,
                "condition": "All conditions in recording",
                "reason": row.reason,
            }
            for row in result.plan.recording_exclusions
        ]
        exclusion_rows.extend(
            {
                "scope": "Participant condition",
                "identity": row.participant_id,
                "condition": row.condition,
                "reason": row.reason,
            }
            for row in result.prepared.provenance.participant_condition_exclusions
        )
        selector = result.prepared.shared_selection_audit
        selection = result.prepared.shared_selection
        selector_rows = []
        for index, label in enumerate(selector.cell_labels):
            for harmonic, order in enumerate(selection.candidate_orders):
                selector_rows.append(
                    {
                        "cell": label,
                        "group_id": selector.cell_group_ids[index],
                        "session_id": selector.cell_session_ids[index],
                        "condition": selector.cell_conditions[index],
                        "participants": selector.cell_participant_counts[index],
                        "harmonic_order": int(order),
                        "z": float(selector.z_scores[index, harmonic]),
                        "detected": bool(selector.detected[index, harmonic]),
                        "retained": int(order) in selection.selected_orders,
                    }
                )
        methods = [
            {
                "item": "Plan version",
                "value": result.plan.version,
                "notes": "Frozen before inference; source files are not modified.",
            },
            {"item": "Plan fingerprint", "value": result.plan.fingerprint, "notes": "See analysis_plan.json."},
            {
                "item": "Primary correction",
                "value": "Holm across all comparisons in each declared family",
                "notes": "Within-group visit comparisons across all groups belong to one family. "
                "A failed planned comparison prevents publication of the entire plan.",
            },
            {
                "item": "Additional summary",
                "value": "Holm across the full plan",
                "notes": "Calculated from the original global p-values, not from the family-adjusted p-values.",
            },
            {
                "item": "Exploratory reporting",
                "value": "Global p < .05 and family Holm p > .05",
                "notes": "A descriptive filter; it never changes the correction denominator.",
            },
            {
                "item": "Cluster inference",
                "value": "Whole-participant permutations; sign-specific maximum clusters",
                "notes": "Global two-sided p accounts for both signs. Holm applies to comparisons, not nodes.",
            },
            {
                "item": "Response scale",
                "value": "Normalized sensor-by-harmonic response pattern",
                "notes": "FHC does not test overall response amplitude. Selected cluster effects are descriptive.",
            },
            {
                "item": "Cohort audit",
                "value": "Visit coverage by participant and condition",
                "notes": "Complete visit coverage alone does not imply inclusion in every comparison. "
                "The Participants sheet records actual inclusion separately for each comparison and arm.",
            },
            {
                "item": "Repeated visit recipes",
                "value": "Ordered visit A minus visit B",
                "notes": "Visit-averaged contrasts average candidate SNR then normalize once. Visit changes "
                "subtract separately normalized visits; differences are not normalized again.",
            },
            {
                "item": "Validation",
                "value": "Toolbox analysis-family extension",
                "notes": "Legacy single-contrast calibration does not validate this shared-selector, "
                "composite-tensor, multiple-comparison extension.",
            },
        ]
        tables = [
            (
                "Families",
                "families.csv",
                family_rows,
                ("family_id", "family", "planned_comparisons", "passes_family_holm"),
            ),
            ("Comparisons", "comparisons.csv", summary, tuple(summary[0])),
            (
                "All Clusters",
                "cluster_summary.csv",
                clusters,
                tuple(clusters[0]) if clusters else ("comparison_id", "family_id", "cluster_id"),
            ),
            (
                "Cluster Membership",
                "cluster_membership.csv",
                membership,
                tuple(membership[0])
                if membership
                else ("comparison_id", "family_id", "cluster_id", "sensor", "harmonic_order"),
            ),
            ("Participants", "participants.csv", participants, tuple(participants[0])),
            (
                "Cohort Audit",
                "cohort_audit.csv",
                audit_rows,
                tuple(audit_rows[0]) if audit_rows else ("participant_id", "condition", "reason"),
            ),
            ("Exclusions", "exclusions.csv", exclusion_rows, ("scope", "identity", "condition", "reason")),
            (
                "Source Workbooks",
                "source_workbooks.csv",
                sources,
                tuple(sources[0]) if sources else ("comparison_id", "project_relative_path"),
            ),
            ("Harmonic Selection", "harmonic_selection.csv", selector_rows, tuple(selector_rows[0])),
            ("Methods and Provenance", "methods.csv", methods, ("item", "value", "notes")),
        ]
        workbook = Workbook()
        workbook.remove(workbook.active)
        try:
            for title, filename, rows, fields in tables:
                _check_export_cancelled(cancel_check)
                csv_path = staging / filename
                _write_csv(csv_path, fields, rows)
                record(csv_path, filename.removesuffix(".csv"))
                _write_table_sheet(
                    workbook.create_sheet(title),
                    title=title,
                    description="Frozen FHC analysis families. See Methods and Provenance for interpretation.",
                    fields=fields,
                    rows=rows,
                    significant_field="passes_family_holm" if title == "Comparisons" else None,
                )
            workbook_path = staging / PLANNED_WORKBOOK_FILENAME
            workbook.save(workbook_path)
        finally:
            workbook.close()
        record(workbook_path, "human_workbook")
        exploratory_path = staging / "exploratory_findings.md"
        exploratory = [row.detail_text for row in report.rows if row.is_exploratory]
        exploratory_path.write_text(
            "# Exploratory FHC findings\n\nGlobal p < .05, but does not pass family Holm correction.\n\n"
            + ("\n\n---\n\n".join(exploratory) if exploratory else "No comparisons meet this criterion.")
            + "\n",
            encoding="utf-8",
        )
        record(exploratory_path, "exploratory_report")
        first_result = result.outcomes[0].result
        payload = {
            "schema_version": PLANNED_EXPORT_SCHEMA_VERSION,
            "status": "complete",
            "run_id": resolved_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "plan": result.plan.to_dict(),
            "plan_fingerprint": result.plan.fingerprint,
            "method": asdict(result.prepared.method),
            "software": {
                "fpvs_toolbox_version": FPVS_TOOLBOX_VERSION,
                "python_version": platform.python_version(),
                "numpy_version": np.__version__,
                "scipy_version": _dependency_version("scipy"),
            },
            "multiplicity": {
                "primary": "Holm within each declared analysis family",
                "secondary": "Holm across all planned comparisons",
                "global_p": "Minimum sign-specific maximum-cluster p, multiplied by two and capped at one",
                "pointwise_significance_claimed": False,
            },
            "validation": "Toolbox extension; legacy single-contrast calibration does not validate this plan pipeline",
            "frequency_plan": _frequency_plan_manifest(first),
            "selected_harmonic_orders": selection.selected_orders.tolist(),
            "selected_harmonics_hz": selection.selected_harmonics_hz.tolist(),
            "preparation": asdict(result.prepared.provenance),
            "adjacency": {
                "version": first_result.sensor_adjacency_version,
                "fingerprint": first_result.sensor_adjacency_fingerprint,
                "edges": first_result.sensor_adjacency_edges,
                "harmonic_adjacency": "complete at each sensor",
            },
            "comparisons": analyses,
            "results": summary,
            "artifacts": artifacts,
        }
        _write_manifest(staging / "manifest.json", payload)
        _check_export_cancelled(cancel_check)
        if final_directory.exists():
            raise FileExistsError(f"Free-harmonic run appeared during export: {final_directory}")
        os.replace(staging, final_directory)
    except BaseException:
        if staging.exists():
            # Staging was explicitly resolved and checked inside the project above.
            shutil.rmtree(staging)
        raise
    receipt_rows = [
        ExportArtifact(
            role=str(row["role"]),
            path=root / str(row["path"]),
            sha256=str(row["sha256"]),
            size_bytes=int(row["size_bytes"]),
        )
        for row in artifacts
    ]
    manifest_path = final_directory / "manifest.json"
    digest, size = _sha256_file(manifest_path)
    receipt_rows.append(ExportArtifact(role="manifest", path=manifest_path, sha256=digest, size_bytes=size))
    return ExportReceipt(output_directory=final_directory, manifest_path=manifest_path, artifacts=tuple(receipt_rows))
