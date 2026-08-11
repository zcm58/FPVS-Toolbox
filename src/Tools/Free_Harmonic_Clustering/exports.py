"""Atomic project-local exports for Free Harmonic Clustering Analysis."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import os
import platform
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

import numpy as np

from config import FPVS_TOOLBOX_VERSION

from .models import (
    ClusterPermutationResult,
    ClusterRecord,
    CohortWorkbook,
    ExportArtifact,
    ExportReceipt,
    FreeHarmonicInputError,
    PreparedContrast,
)


TOOL_TITLE = "Free Harmonic Clustering Analysis"
EXPORT_SCHEMA_VERSION = 1
DEFAULT_RESULTS_SUBFOLDER = Path(
    "3 - Statistical Analysis Results",
    TOOL_TITLE,
)
MANIFEST_FILENAME = "manifest.json"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_run_id(value: object) -> str:
    run_id = str(value or "").strip()
    if run_id in {".", ".."} or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError(
            "run_id must start with an ASCII letter or digit and contain only letters, digits, '.', '_', or '-'."
        )
    return run_id


def _default_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _relative_to(path: Path, root: Path, *, label: str) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise FreeHarmonicInputError(f"{label} must remain beneath the managed project root: {root}") from exc


def _resolve_project_root(prepared: PreparedContrast) -> Path:
    root = Path(prepared.project_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise FreeHarmonicInputError(f"Managed project root is not a directory: {root}")
    request_root = Path(prepared.request.project_root).expanduser().resolve(strict=True)
    if request_root != root:
        raise FreeHarmonicInputError("Prepared contrast and request refer to different managed project roots.")
    return root


def resolve_run_destination(
    prepared: PreparedContrast,
    *,
    run_id: str | None = None,
    destination: str | Path | None = None,
) -> tuple[str, Path]:
    """Resolve one never-overwritten run directory beneath the managed project."""

    root = _resolve_project_root(prepared)
    if destination is None:
        resolved_run_id = _validate_run_id(run_id or _default_run_id())
        target = root / DEFAULT_RESULTS_SUBFOLDER / resolved_run_id
    else:
        raw_target = Path(destination).expanduser()
        if not raw_target.is_absolute():
            raw_target = root / raw_target
        target = raw_target.resolve(strict=False)
        resolved_run_id = _validate_run_id(run_id or target.name)
        if target.name != resolved_run_id:
            raise ValueError("destination directory name must equal run_id.")

    target = target.resolve(strict=False)
    relative = _relative_to(target, root, label="Run destination")
    if not relative.parts:
        raise FreeHarmonicInputError("Run destination cannot be the project root itself.")
    return resolved_run_id, target


def _validate_source_workbook(record: CohortWorkbook, project_root: Path) -> str:
    source = Path(record.source_path).expanduser().resolve(strict=False)
    actual = _relative_to(source, project_root, label="Source workbook").as_posix()
    provided_text = str(record.project_relative_path).strip().replace("\\", "/")
    provided_posix = PurePosixPath(provided_text)
    provided_windows = PureWindowsPath(provided_text)
    if (
        not provided_text
        or provided_posix.is_absolute()
        or provided_windows.is_absolute()
        or bool(provided_windows.drive)
        or ".." in provided_posix.parts
    ):
        raise FreeHarmonicInputError("Source workbook provenance must use a project-relative path.")
    normalized = provided_posix.as_posix()
    if normalized.casefold() != actual.casefold():
        raise FreeHarmonicInputError(
            "Source workbook path and project-relative provenance do not match: "
            f"{record.participant_id} / {record.condition}."
        )
    return actual


def _validate_result(prepared: PreparedContrast, result: ClusterPermutationResult) -> None:
    if result.design is not prepared.request.design:
        raise ValueError("Prepared contrast and cluster result designs do not match.")
    expected_shape = (len(prepared.sensor_names), len(prepared.harmonics_hz))
    if result.observed_t.shape != expected_shape:
        raise ValueError(f"Cluster result shape must be {expected_shape}; got {result.observed_t.shape}.")
    labels = np.asarray(result.cluster_labels, dtype=np.int64)
    records = {cluster.cluster_id: cluster for cluster in result.clusters}
    if len(records) != len(result.clusters):
        raise ValueError("Cluster IDs must be unique.")
    observed_ids = {int(value) for value in np.unique(labels) if int(value) != 0}
    if observed_ids != set(records):
        raise ValueError("Cluster labels and cluster records contain different IDs.")
    flat_labels = labels.reshape(-1)
    occupied: set[int] = set()
    sensor_count, harmonic_count = expected_shape
    for cluster in result.clusters:
        _validate_cluster_record(
            cluster,
            flat_labels=flat_labels,
            sensor_count=sensor_count,
            harmonic_count=harmonic_count,
            occupied=occupied,
        )


def _validate_cluster_record(
    cluster: ClusterRecord,
    *,
    flat_labels: np.ndarray,
    sensor_count: int,
    harmonic_count: int,
    occupied: set[int],
) -> None:
    nodes = tuple(cluster.node_indices)
    sensors = tuple(cluster.sensor_indices)
    harmonics = tuple(cluster.harmonic_indices)
    if not (len(nodes) == len(sensors) == len(harmonics)):
        raise ValueError("Cluster node, sensor, and harmonic indices must align.")
    if len(set(nodes)) != len(nodes) or occupied.intersection(nodes):
        raise ValueError("Cluster node membership must be unique across clusters.")
    node_count = sensor_count * harmonic_count
    for node, sensor, harmonic in zip(nodes, sensors, harmonics, strict=True):
        if node >= node_count or sensor >= sensor_count or harmonic >= harmonic_count:
            raise ValueError("Cluster membership index exceeds the result tensor.")
        expected_node = sensor * harmonic_count + harmonic
        if node != expected_node or int(flat_labels[node]) != cluster.cluster_id:
            raise ValueError("Cluster membership does not match sensor-major labels.")
    occupied.update(nodes)


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())


def _write_npz(path: Path, prepared: PreparedContrast, result: ClusterPermutationResult) -> None:
    plan = prepared.frequency_plan
    target_bin_frequencies = plan.selected_frequencies_hz[plan.target_selected_indices]
    target_frequency_errors = target_bin_frequencies - plan.candidate_harmonics_hz
    with path.open("wb") as stream:
        np.savez_compressed(
            stream,
            observed_t=np.asarray(result.observed_t),
            cluster_labels=np.asarray(result.cluster_labels),
            null_positive_max_mass=np.asarray(result.null_positive_max_mass),
            null_negative_min_mass=np.asarray(result.null_negative_min_mass),
            normalized_values_a=np.asarray(prepared.values_a),
            normalized_values_b=np.asarray(prepared.values_b),
            selected_snr_a=np.asarray(prepared.snr_a),
            selected_snr_b=np.asarray(prepared.snr_b),
            sensor_names=np.asarray(prepared.sensor_names, dtype=np.str_),
            harmonic_orders=np.asarray(prepared.harmonic_orders),
            harmonics_hz=np.asarray(prepared.harmonics_hz),
            participant_ids_a=np.asarray(prepared.participant_ids_a, dtype=np.str_),
            participant_ids_b=np.asarray(prepared.participant_ids_b, dtype=np.str_),
            full_frequency_columns=np.asarray(
                plan.full_frequency_columns,
                dtype=np.str_,
            ),
            full_frequencies_hz=np.asarray(plan.full_frequencies_hz),
            selected_frequency_columns=np.asarray(
                plan.selected_frequency_columns,
                dtype=np.str_,
            ),
            selected_frequencies_hz=np.asarray(plan.selected_frequencies_hz),
            candidate_orders=np.asarray(plan.candidate_orders),
            candidate_harmonics_hz=np.asarray(plan.candidate_harmonics_hz),
            excluded_base_orders=np.asarray(plan.excluded_base_orders),
            excluded_base_harmonics_hz=np.asarray(plan.excluded_base_harmonics_hz),
            target_selected_indices=np.asarray(plan.target_selected_indices),
            noise_selected_indices=np.asarray(plan.noise_selected_indices),
            target_bin_frequencies_hz=np.asarray(target_bin_frequencies),
            target_frequency_errors_hz=np.asarray(target_frequency_errors),
        )
        stream.flush()
        os.fsync(stream.fileno())


def _write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    with path.open("wb") as stream:
        stream.write(encoded)
        stream.write(b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _cluster_summary_rows(
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cluster in sorted(result.clusters, key=lambda item: item.cluster_id):
        effect_audit = _cluster_effect_audit(prepared, cluster)
        sensors = tuple(dict.fromkeys(prepared.sensor_names[index] for index in cluster.sensor_indices))
        orders = tuple(dict.fromkeys(int(prepared.harmonic_orders[index]) for index in cluster.harmonic_indices))
        frequencies = tuple(dict.fromkeys(float(prepared.harmonics_hz[index]) for index in cluster.harmonic_indices))
        rows.append(
            {
                "cluster_id": cluster.cluster_id,
                "sign": cluster.sign,
                "mass": cluster.mass,
                "p_value": cluster.p_value,
                "conservative_p_value": cluster.conservative_p_value,
                "adjusted_two_sided_p_value": cluster.adjusted_two_sided_p_value,
                "tie_count": cluster.tie_count,
                "p_ci_low": cluster.p_ci_low,
                "p_ci_high": cluster.p_ci_high,
                "confidence_interval_straddles_alpha": (cluster.confidence_interval_straddles_alpha),
                "significant_cluster_level": cluster.significant,
                "node_count": len(cluster.node_indices),
                "n_a": len(prepared.participant_ids_a),
                "n_b": len(prepared.participant_ids_b),
                "arm_a_normalized_cluster_node_mean": effect_audit["arm_a_mean"],
                "arm_b_normalized_cluster_node_mean": effect_audit["arm_b_mean"],
                "arm_a_minus_b_raw_difference": effect_audit["difference"],
                "arm_a_minus_b_normalized_difference": effect_audit["difference"],
                "effect_denominator_sd": effect_audit["denominator_sd"],
                "effect_denominator_kind": effect_audit["denominator_kind"],
                "effect_direction": effect_audit["direction"],
                "effect_size_direction": effect_audit["direction"],
                "descriptive_effect_label": ("post-selection/shape-dependent normalized cluster-node mean"),
                "effect_value_scale": ("participant-arm L2-normalized sensor x retained-harmonic tensor"),
                "sensor_count": len(sensors),
                "harmonic_count": len(orders),
                "sensors": "|".join(sensors),
                "harmonic_orders": "|".join(str(value) for value in orders),
                "harmonics_hz": "|".join(f"{value:g}" for value in frequencies),
                "effect_size": "" if cluster.effect_size is None else cluster.effect_size,
                "effect_size_kind": cluster.effect_size_kind or "",
            }
        )
    return rows


def _cluster_effect_audit(
    prepared: PreparedContrast,
    cluster: ClusterRecord,
) -> dict[str, object]:
    nodes = np.asarray(cluster.node_indices, dtype=np.int64)
    arm_a = np.asarray(prepared.values_a).reshape(len(prepared.values_a), -1)[:, nodes]
    arm_b = np.asarray(prepared.values_b).reshape(len(prepared.values_b), -1)[:, nodes]
    participant_means_a = np.mean(arm_a, axis=1)
    participant_means_b = np.mean(arm_b, axis=1)
    mean_a = float(np.mean(participant_means_a))
    mean_b = float(np.mean(participant_means_b))
    difference = mean_a - mean_b
    if prepared.request.design.value == "paired_conditions":
        denominator_kind = "paired_difference_sd"
        denominator = float(np.std(participant_means_a - participant_means_b, ddof=1))
    else:
        denominator_kind = "pooled_within_arm_sd"
        n_a = participant_means_a.size
        n_b = participant_means_b.size
        variance_a = float(np.var(participant_means_a, ddof=1))
        variance_b = float(np.var(participant_means_b, ddof=1))
        denominator = float(np.sqrt(((n_a - 1) * variance_a + (n_b - 1) * variance_b) / (n_a + n_b - 2)))
    if not np.isfinite(denominator):
        raise ValueError("Cluster descriptive effect denominator must be finite.")
    if difference > 0.0:
        direction = "arm_a_greater"
    elif difference < 0.0:
        direction = "arm_b_greater"
    else:
        direction = "no_direction"
    return {
        "arm_a_mean": mean_a,
        "arm_b_mean": mean_b,
        "difference": difference,
        "denominator_sd": denominator,
        "denominator_kind": denominator_kind,
        "direction": direction,
    }


def _cluster_membership_rows(
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cluster in sorted(result.clusters, key=lambda item: item.cluster_id):
        for node, sensor, harmonic in zip(
            cluster.node_indices,
            cluster.sensor_indices,
            cluster.harmonic_indices,
            strict=True,
        ):
            rows.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "sign": cluster.sign,
                    "node_index": node,
                    "sensor_index": sensor,
                    "sensor": prepared.sensor_names[sensor],
                    "harmonic_index": harmonic,
                    "harmonic_order": int(prepared.harmonic_orders[harmonic]),
                    "harmonic_hz": float(prepared.harmonics_hz[harmonic]),
                    "observed_t": float(result.observed_t[sensor, harmonic]),
                    "cluster_mass": cluster.mass,
                    "cluster_p_value": cluster.p_value,
                    "cluster_significant": cluster.significant,
                }
            )
    return rows


def _node_statistic_rows(
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
) -> list[dict[str, object]]:
    cluster_by_id = {cluster.cluster_id: cluster for cluster in result.clusters}
    rows: list[dict[str, object]] = []
    harmonic_count = len(prepared.harmonics_hz)
    for sensor_index, sensor in enumerate(prepared.sensor_names):
        for harmonic_index, harmonic_hz in enumerate(prepared.harmonics_hz):
            cluster_id = int(result.cluster_labels[sensor_index, harmonic_index])
            cluster = cluster_by_id.get(cluster_id)
            rows.append(
                {
                    "node_index": sensor_index * harmonic_count + harmonic_index,
                    "sensor_index": sensor_index,
                    "sensor": sensor,
                    "harmonic_index": harmonic_index,
                    "harmonic_order": int(prepared.harmonic_orders[harmonic_index]),
                    "harmonic_hz": float(harmonic_hz),
                    "observed_t": float(result.observed_t[sensor_index, harmonic_index]),
                    "cluster_id": cluster_id,
                    "cluster_sign": "" if cluster is None else cluster.sign,
                    "cluster_p_value": "" if cluster is None else cluster.p_value,
                    "cluster_significant": "" if cluster is None else cluster.significant,
                    "pointwise_significance_claimed": False,
                }
            )
    return rows


def _harmonic_selection_rows(prepared: PreparedContrast) -> list[dict[str, object]]:
    selection = prepared.selection
    selected = {int(index) for index in selection.selected_candidate_indices}
    rows: list[dict[str, object]] = []
    for index, (order, harmonic_hz) in enumerate(
        zip(selection.candidate_orders, selection.candidate_harmonics_hz, strict=True)
    ):
        rows.append(
            {
                "harmonic_order": int(order),
                "harmonic_hz": float(harmonic_hz),
                "eligible_nonbase": True,
                "arm_a_z": float(selection.arm_a_z[index]),
                "arm_b_z": float(selection.arm_b_z[index]),
                "detected_arm_a": bool(selection.detected_arm_a[index]),
                "detected_arm_b": bool(selection.detected_arm_b[index]),
                "retained_fill_through": index in selected,
                "exclusion_reason": "" if index in selected else "above_highest_detected",
            }
        )
    for order, harmonic_hz in zip(
        selection.excluded_base_orders,
        selection.excluded_base_harmonics_hz,
        strict=True,
    ):
        rows.append(
            {
                "harmonic_order": int(order),
                "harmonic_hz": float(harmonic_hz),
                "eligible_nonbase": False,
                "arm_a_z": "",
                "arm_b_z": "",
                "detected_arm_a": False,
                "detected_arm_b": False,
                "retained_fill_through": False,
                "exclusion_reason": "base_rate_overlap",
            }
        )
    return sorted(rows, key=lambda row: int(row["harmonic_order"]))


def _participant_rows(prepared: PreparedContrast) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for arm, label, participant_ids in (
        ("a", prepared.arm_a_label, prepared.participant_ids_a),
        ("b", prepared.arm_b_label, prepared.participant_ids_b),
    ):
        for index, participant_id in enumerate(participant_ids):
            rows.append(
                {
                    "arm": arm,
                    "arm_label": label,
                    "participant_index": index,
                    "participant_id": participant_id,
                }
            )
    return rows


def _source_workbook_rows(
    prepared: PreparedContrast,
    project_root: Path,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in prepared.source_workbooks:
        project_relative_path = _validate_source_workbook(record, project_root)
        source_stat = Path(record.source_path).stat()
        rows.append(
            {
                "arm": record.arm,
                "arm_label": record.arm_label,
                "participant_id": record.participant_id,
                "condition": record.condition,
                "group_id": record.group_id or "",
                "group_label": record.group_label or "",
                "project_relative_path": project_relative_path,
                "source_size_bytes": int(source_stat.st_size),
                "source_mtime_ns": int(source_stat.st_mtime_ns),
                "header_read_seconds": record.header_read_seconds,
                "amplitude_read_seconds": record.amplitude_read_seconds,
            }
        )
    return rows


def _null_extrema_rows(result: ClusterPermutationResult) -> list[dict[str, object]]:
    return [
        {
            "permutation_index": index,
            "positive_max_mass": float(positive),
            "negative_min_mass": float(negative),
        }
        for index, (positive, negative) in enumerate(
            zip(
                result.null_positive_max_mass,
                result.null_negative_min_mass,
                strict=True,
            )
        )
    ]


def _finite_array_summary(values: np.ndarray) -> dict[str, object]:
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    return {
        "count": int(array.size),
        "finite_count": int(finite.size),
        "nonfinite_count": int(array.size - finite.size),
        "minimum": None if not finite.size else float(np.min(finite)),
        "maximum": None if not finite.size else float(np.max(finite)),
    }


def _dependency_version(distribution: str) -> str | None:
    try:
        return package_version(distribution)
    except PackageNotFoundError:
        return None


def _frequency_plan_manifest(prepared: PreparedContrast) -> dict[str, object]:
    plan = prepared.frequency_plan
    target_frequencies = plan.selected_frequencies_hz[plan.target_selected_indices]
    target_errors = target_frequencies - plan.candidate_harmonics_hz
    return {
        "electrode_column": plan.electrode_column,
        "selected_index_basis": "zero-based selected_frequency_columns",
        "noise_window_rule": ("physical +/- half-width inclusive; target and immediate adjacent FFT bins excluded"),
        "frequency_resolution_hz": plan.frequency_resolution_hz,
        "grid_fingerprint": plan.grid_fingerprint,
        "selected_columns_fingerprint": plan.selected_columns_fingerprint,
        "full_frequency_column_count": len(plan.full_frequency_columns),
        "selected_frequency_column_count": len(plan.selected_frequency_columns),
        "selected_frequency_columns": list(plan.selected_frequency_columns),
        "selected_frequencies_hz": [float(value) for value in plan.selected_frequencies_hz],
        "candidate_orders": [int(value) for value in plan.candidate_orders],
        "candidate_harmonics_hz": [float(value) for value in plan.candidate_harmonics_hz],
        "excluded_base_orders": [int(value) for value in plan.excluded_base_orders],
        "excluded_base_harmonics_hz": [float(value) for value in plan.excluded_base_harmonics_hz],
        "target_selected_indices": [int(value) for value in plan.target_selected_indices],
        "noise_selected_indices": [[int(value) for value in row] for row in plan.noise_selected_indices],
        "target_bin_frequencies_hz": [float(value) for value in target_frequencies],
        "target_frequency_errors_hz": [float(value) for value in target_errors],
    }


def _manifest_payload(
    *,
    run_id: str,
    project_root: Path,
    destination: Path,
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
    source_rows: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    selection = prepared.selection
    provenance = prepared.provenance
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "status": "complete",
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "tool": {
            "title": TOOL_TITLE,
            "method_version": prepared.method.method_version,
            "export_schema_version": EXPORT_SCHEMA_VERSION,
            "validation_label": "paper-faithful-not-author-validated",
        },
        "software": {
            "fpvs_toolbox_version": FPVS_TOOLBOX_VERSION,
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "scipy_version": _dependency_version("scipy"),
        },
        "references": {
            "article_doi_url": "https://doi.org/10.1111/psyp.70361",
            "article_full_text_url": ("https://pmc.ncbi.nlm.nih.gov/articles/PMC13379596/"),
            "article_pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/42469955/",
            "article_declared_code_data_url": ("https://github.com/users/oliver-hermann1/projects/1"),
            "clean_room_license_boundary": (
                "The referenced authors' code uses restrictive academic/"
                "non-commercial/share-alike terms; this MIT-licensed Toolbox "
                "implementation is independent and copies no author code."
            ),
        },
        "claims": {
            "familywise_error_control": "weak-FWER",
            "familywise_error_scope": "one-declared-contrast-complete-null",
            "cluster_level_inference_only": True,
            "pointwise_sensor_harmonic_significance": False,
            "cross_contrast_family_corrected": False,
            "adaptive_harmonic_selection_uses_analysis_data": True,
            "adaptive_selection_confirmatory_caveat": (
                "The paper-faithful harmonic domain is selected from the "
                "observed analysis arms before permutation and remains fixed; "
                "confirmatory work should prefer a preregistered or independent "
                "domain."
            ),
            "exchangeability_assumption": (
                "Within-participant whole-tensor swaps are exchangeable under "
                "the paired null."
                if prepared.request.design.value == "paired_conditions"
                else "Unrestricted whole-participant group labels are "
                "exchangeable under the independent-groups global null; "
                "unmodeled strata, matching, or family structure invalidate "
                "this permutation scheme."
            ),
            "method_fidelity": "paper-faithful",
            "author_validation": "not-author-validated",
        },
        "project": {
            "project_root": ".",
            "output_directory": _relative_to(
                destination,
                project_root,
                label="Output directory",
            ).as_posix(),
        },
        "contrast": {
            "design": prepared.request.design.value,
            "condition_a": prepared.request.condition_a,
            "condition_b": prepared.request.condition_b,
            "group_ids": list(prepared.request.group_ids),
            "arm_a_label": prepared.arm_a_label,
            "arm_b_label": prepared.arm_b_label,
            "participant_ids_a": list(prepared.participant_ids_a),
            "participant_ids_b": list(prepared.participant_ids_b),
            "participant_count_a": len(prepared.participant_ids_a),
            "participant_count_b": len(prepared.participant_ids_b),
        },
        "method": asdict(prepared.method),
        "normalization": {
            "method": ("participant-arm global L2 across sensor x retained harmonic tensor"),
            "estimand": "relative sensor/harmonic response distribution",
            "descriptive_cluster_effects": ("post-selection/shape-dependent normalized cluster-node means"),
        },
        "frequency_plan": _frequency_plan_manifest(prepared),
        "preparation": {
            "source_sheet": provenance.source_sheet,
            "grid_fingerprint": provenance.grid_fingerprint,
            "selected_columns_fingerprint": provenance.selected_columns_fingerprint,
            "frequency_resolution_hz": provenance.frequency_resolution_hz,
            "full_frequency_column_count": provenance.full_frequency_column_count,
            "selected_frequency_column_count": (provenance.selected_frequency_column_count),
            "workbook_count": provenance.workbook_count,
            "timing_seconds": {
                "header_read": provenance.header_read_seconds,
                "amplitude_read": provenance.amplitude_read_seconds,
                "numeric_preparation": provenance.numeric_preparation_seconds,
                "total": provenance.total_seconds,
                "reader_phases": dict(provenance.reader_phase_seconds),
            },
            "cohort_filters": {
                "ledger_filter_applied": provenance.ledger_filter_applied,
                "completed_participants": list(provenance.completed_participants),
                "ledger_excluded_participants": list(provenance.ledger_excluded_participants),
                "manual_excluded_participants": list(provenance.manual_excluded_participants),
                "frequency_qc_excluded_participants": list(provenance.frequency_qc_excluded_participants),
                "incomplete_pair_participants": list(provenance.incomplete_pair_participants),
                "dataset_diagnostics": list(provenance.dataset_diagnostics),
            },
        },
        "harmonic_selection": {
            "z_threshold": selection.z_threshold,
            "z_ddof": selection.z_ddof,
            "highest_detected_order": selection.highest_detected_order,
            "selected_orders": [int(value) for value in selection.selected_orders],
            "selected_harmonics_hz": [float(value) for value in selection.selected_harmonics_hz],
            "candidate_count": int(selection.candidate_orders.size),
            "selected_count": int(selection.selected_orders.size),
        },
        "analysis": {
            "permutations_evaluated": result.permutations_evaluated,
            "degrees_of_freedom": result.degrees_of_freedom,
            "cluster_forming_threshold": result.cluster_forming_threshold,
            "cluster_entry_alpha": result.cluster_entry_alpha,
            "cluster_alpha_per_tail": result.cluster_alpha_per_tail,
            "cluster_count": len(result.clusters),
            "significant_cluster_count": sum(cluster.significant for cluster in result.clusters),
            "rng_algorithm": result.rng_algorithm,
            "seed": result.seed,
            "permutation_assignment_hash": result.permutation_assignment_hash,
            "warnings": list(result.warnings),
            "timing_seconds": dict(result.timing_seconds),
            "null_positive_max_mass": _finite_array_summary(result.null_positive_max_mass),
            "null_negative_min_mass": _finite_array_summary(result.null_negative_min_mass),
        },
        "adjacency": {
            "version": result.sensor_adjacency_version,
            "fingerprint_sha256": result.sensor_adjacency_fingerprint,
            "sensor_edges": [list(edge) for edge in result.sensor_adjacency_edges],
            "harmonic_adjacency": "complete-within-sensor",
            "flattening_order": "sensor-major",
        },
        "source_workbooks": [dict(row) for row in source_rows],
        "artifacts": [dict(artifact) for artifact in artifacts],
    }


def _artifact_manifest_row(
    *,
    role: str,
    staging_path: Path,
    destination: Path,
    project_root: Path,
) -> dict[str, object]:
    digest, size = _sha256_file(staging_path)
    final_path = destination / staging_path.name
    return {
        "role": role,
        "path": _relative_to(final_path, project_root, label="Artifact").as_posix(),
        "sha256": digest,
        "size_bytes": size,
    }


def export_free_harmonic_run(
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
    *,
    run_id: str | None = None,
    destination: str | Path | None = None,
) -> ExportReceipt:
    """Publish one complete result bundle using a manifest-last directory commit."""

    if not isinstance(prepared, PreparedContrast):
        raise TypeError("prepared must be a PreparedContrast.")
    if not isinstance(result, ClusterPermutationResult):
        raise TypeError("result must be a ClusterPermutationResult.")
    project_root = _resolve_project_root(prepared)
    resolved_run_id, final_directory = resolve_run_destination(
        prepared,
        run_id=run_id,
        destination=destination,
    )
    _validate_result(prepared, result)
    source_rows = _source_workbook_rows(prepared, project_root)
    if final_directory.exists():
        raise FileExistsError(f"Free-harmonic run already exists: {final_directory}")

    parent = final_directory.parent
    _relative_to(parent.resolve(strict=False), project_root, label="Output parent")
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{resolved_run_id}.staging-{uuid4().hex}"
    _relative_to(staging.resolve(strict=False), project_root, label="Staging directory")
    staging.mkdir(exist_ok=False)

    csv_specs: tuple[tuple[str, str, Sequence[str], Sequence[Mapping[str, object]]], ...] = (
        (
            "cluster_summary",
            "cluster_summary.csv",
            (
                "cluster_id",
                "sign",
                "mass",
                "p_value",
                "conservative_p_value",
                "adjusted_two_sided_p_value",
                "tie_count",
                "p_ci_low",
                "p_ci_high",
                "confidence_interval_straddles_alpha",
                "significant_cluster_level",
                "node_count",
                "n_a",
                "n_b",
                "arm_a_normalized_cluster_node_mean",
                "arm_b_normalized_cluster_node_mean",
                "arm_a_minus_b_raw_difference",
                "arm_a_minus_b_normalized_difference",
                "effect_denominator_sd",
                "effect_denominator_kind",
                "effect_direction",
                "effect_size_direction",
                "descriptive_effect_label",
                "effect_value_scale",
                "sensor_count",
                "harmonic_count",
                "sensors",
                "harmonic_orders",
                "harmonics_hz",
                "effect_size",
                "effect_size_kind",
            ),
            _cluster_summary_rows(prepared, result),
        ),
        (
            "cluster_membership",
            "cluster_membership.csv",
            (
                "cluster_id",
                "sign",
                "node_index",
                "sensor_index",
                "sensor",
                "harmonic_index",
                "harmonic_order",
                "harmonic_hz",
                "observed_t",
                "cluster_mass",
                "cluster_p_value",
                "cluster_significant",
            ),
            _cluster_membership_rows(prepared, result),
        ),
        (
            "node_statistics",
            "node_statistics.csv",
            (
                "node_index",
                "sensor_index",
                "sensor",
                "harmonic_index",
                "harmonic_order",
                "harmonic_hz",
                "observed_t",
                "cluster_id",
                "cluster_sign",
                "cluster_p_value",
                "cluster_significant",
                "pointwise_significance_claimed",
            ),
            _node_statistic_rows(prepared, result),
        ),
        (
            "harmonic_selection",
            "harmonic_selection.csv",
            (
                "harmonic_order",
                "harmonic_hz",
                "eligible_nonbase",
                "arm_a_z",
                "arm_b_z",
                "detected_arm_a",
                "detected_arm_b",
                "retained_fill_through",
                "exclusion_reason",
            ),
            _harmonic_selection_rows(prepared),
        ),
        (
            "participants",
            "participants.csv",
            ("arm", "arm_label", "participant_index", "participant_id"),
            _participant_rows(prepared),
        ),
        (
            "source_workbooks",
            "source_workbooks.csv",
            (
                "arm",
                "arm_label",
                "participant_id",
                "condition",
                "group_id",
                "group_label",
                "project_relative_path",
                "source_size_bytes",
                "source_mtime_ns",
                "header_read_seconds",
                "amplitude_read_seconds",
            ),
            source_rows,
        ),
        (
            "null_extrema",
            "null_extrema.csv",
            ("permutation_index", "positive_max_mass", "negative_min_mass"),
            _null_extrema_rows(result),
        ),
    )

    artifact_rows: list[dict[str, object]] = []
    try:
        for role, filename, fieldnames, rows in csv_specs:
            path = staging / filename
            _write_csv(path, fieldnames, rows)
            artifact_rows.append(
                _artifact_manifest_row(
                    role=role,
                    staging_path=path,
                    destination=final_directory,
                    project_root=project_root,
                )
            )

        arrays_path = staging / "arrays.npz"
        _write_npz(arrays_path, prepared, result)
        artifact_rows.append(
            _artifact_manifest_row(
                role="compressed_arrays",
                staging_path=arrays_path,
                destination=final_directory,
                project_root=project_root,
            )
        )

        manifest_payload = _manifest_payload(
            run_id=resolved_run_id,
            project_root=project_root,
            destination=final_directory,
            prepared=prepared,
            result=result,
            source_rows=source_rows,
            artifacts=artifact_rows,
        )
        manifest_staging_path = staging / MANIFEST_FILENAME
        _write_manifest(manifest_staging_path, manifest_payload)

        if final_directory.exists():
            raise FileExistsError(f"Free-harmonic run appeared during export: {final_directory}")
        os.replace(staging, final_directory)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    receipt_artifacts: list[ExportArtifact] = []
    for artifact in artifact_rows:
        receipt_artifacts.append(
            ExportArtifact(
                role=str(artifact["role"]),
                path=project_root / str(artifact["path"]),
                sha256=str(artifact["sha256"]),
                size_bytes=int(artifact["size_bytes"]),
            )
        )
    manifest_path = final_directory / MANIFEST_FILENAME
    manifest_sha256, manifest_size = _sha256_file(manifest_path)
    receipt_artifacts.append(
        ExportArtifact(
            role="manifest",
            path=manifest_path,
            sha256=manifest_sha256,
            size_bytes=manifest_size,
        )
    )
    return ExportReceipt(
        output_directory=final_directory,
        manifest_path=manifest_path,
        artifacts=tuple(receipt_artifacts),
    )


__all__ = [
    "DEFAULT_RESULTS_SUBFOLDER",
    "EXPORT_SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "TOOL_TITLE",
    "export_free_harmonic_run",
    "resolve_run_destination",
]
