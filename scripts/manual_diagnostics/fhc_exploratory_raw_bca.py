"""Source-immutable exploratory raw-BCA companion to a completed GUI FHC plan.

This manual diagnostic does not change the Toolbox or its Hermann-compatible
profile. It reads stored native Toolbox BCA at the exact primary harmonics,
reusing the primary cohort and assignment schedule without L2 normalization.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.dont_write_bytecode = True
LOG = logging.getLogger("exploratory_raw_bca")
METHOD_ID = "exploratory_native_bca_primary_fhc_domain_v2"
PAPER_URL = "https://onlinelibrary.wiley.com/doi/full/10.1111/psyp.70361"
SOURCE_SHEET = "FullFFT Amplitude (uV)"
BCA_SHEET = "BCA (uV)"


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def json_write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def csv_read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def csv_write(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    columns = fields or list(rows[0] if rows else {"status": None})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def load_primary(project_root: Path, primary_path: Path, wait_seconds: float) -> tuple[Path, dict]:
    if not primary_path.is_absolute():
        raise ValueError("Primary run path must be absolute.")
    primary = contained(primary_path, project_root)
    manifest_path = primary if primary.suffix.casefold() == ".json" else primary / "manifest.json"
    deadline = time.monotonic() + wait_seconds
    while not manifest_path.is_file():
        if time.monotonic() >= deadline:
            raise FileNotFoundError(f"No completed primary manifest: {manifest_path}")
        time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    manifest["_input_primary_manifest_sha256"] = sha256(manifest_bytes).hexdigest()
    if manifest.get("status") != "complete" or manifest.get("plan", {}).get("version") != "fhc_analysis_families_v2":
        raise ValueError("A completed native fhc_analysis_families_v2 primary GUI bundle is required.")
    primary_dir = manifest_path.parent
    for item in manifest["artifacts"]:
        path = contained(project_root / item["path"], project_root)
        if not path.is_relative_to(primary_dir):
            raise ValueError("Primary artifact resolves outside its immutable run bundle.")
        if path.stat().st_size != int(item["size_bytes"]) or digest(path) != item["sha256"]:
            raise ValueError(f"Primary artifact changed: {path}")
    plan = json.loads((primary_dir / "analysis_plan.json").read_text(encoding="utf-8"))
    fingerprint = plan.pop("plan_fingerprint")
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if (
        sha256(encoded).hexdigest() != fingerprint
        or fingerprint != manifest["plan_fingerprint"]
        or plan != manifest["plan"]
    ):
        raise ValueError("Primary plan fingerprint does not match its manifest.")
    expected = [row["comparison_id"] for row in plan["comparisons"]]
    if expected != [row["comparison_id"] for row in manifest["comparisons"]]:
        raise ValueError("The completed primary comparison list differs from its frozen plan.")
    return primary_dir, manifest


def primary_snr(matrix, frequency_plan: dict, selected_orders: list[int]):
    """Reconstruct the primary SNR only; it is never the secondary BCA metric."""
    import numpy as np

    values = np.asarray(matrix, dtype=np.float64)
    targets = np.asarray(frequency_plan["target_selected_indices"], dtype=np.intp)
    noise = np.asarray(frequency_plan["noise_selected_indices"], dtype=np.intp)
    candidate_orders = list(frequency_plan["candidate_orders"])
    selected = np.asarray([candidate_orders.index(order) for order in selected_orders], dtype=np.intp)
    if values.ndim != 2 or values.shape[1] != len(frequency_plan["selected_frequency_columns"]):
        raise ValueError("FullFFT matrix does not match the frozen primary selected-column plan.")
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("FullFFT amplitude maps must be complete, finite and nonnegative.")
    target = np.take(values, targets, axis=-1)
    noise_mean = np.mean(np.take(values, noise, axis=-1), axis=-1)
    if not np.isfinite(noise_mean).all() or (noise_mean <= 0).any():
        raise ValueError("The frozen primary noise mean must be finite and positive.")
    return np.ascontiguousarray((target / noise_mean)[:, selected])


def read_native_bca(
    path: Path, sensors: list[str], orders: list[int], harmonics: list[float], protocol, frequency_plan
):
    """Read exact stored per-target BCA and validate every required native cell."""
    import numpy as np
    from Main_App.io import read_condition_sheet, read_condition_sheet_selected_columns
    from Main_App.processing.spectral_eligibility import spectral_eligibility_from_rows

    eligibility = spectral_eligibility_from_rows(
        read_condition_sheet(path, sheet_name="Spectral Eligibility").to_dict(orient="records"),
        protocol=protocol,
    )
    if not np.isclose(float(eligibility.bin_width_hz), frequency_plan["frequency_resolution_hz"], rtol=0, atol=1e-12):
        raise ValueError(f"Native BCA grid differs from the frozen primary FullFFT grid: {path}")
    available = {row.target.oddball_harmonic_order: row for row in eligibility.targets}
    columns = [f"{float(hz):.4f}_Hz" for hz in harmonics]
    if len(orders) != len(harmonics) or len(set(columns)) != len(columns):
        raise ValueError("Primary harmonic identities collide in the native BCA column format.")
    for order, hz in zip(orders, harmonics, strict=True):
        target = available.get(order)
        if (
            target is None
            or not np.isclose(float(target.target.frequency_hz), float(hz), rtol=0, atol=1e-12)
            or not target.bca_available
        ):
            raise ValueError(f"Native BCA is unavailable at primary H{order} ({hz:g} Hz): {path}")
    frame = read_condition_sheet_selected_columns(
        path,
        sheet_name=BCA_SHEET,
        required_columns=["Electrode", *columns],
        require_all=True,
    )
    values = np.ascontiguousarray(ordered_amplitude_matrix(frame, sensors, columns, str(path)))
    if not np.isfinite(values).all():
        raise ValueError(f"Stored native BCA has nonfinite required cells: {path}")
    audit_columns = [
        "Electrode",
        "FFT Input Index",
        "Oddball Harmonic Order",
        "Target Frequency Exact (Hz)",
        "Target FFT Bin",
        "Eligibility Fingerprint",
        "BCA Status",
        "Noise Candidate FFT Bins",
        "Noise Retained FFT Bins",
        "Noise Mean (uV)",
    ]
    metric = read_condition_sheet_selected_columns(
        path,
        sheet_name="Spectral Metric QC",
        required_columns=audit_columns,
        require_all=True,
    )
    rows = metric.to_dict(orient="records")
    input_ids = set()
    cells = {}
    selected_audit = []
    requested_sensors = {str(sensor).strip().upper() for sensor in sensors}
    for row in rows:
        input_id = int(row["FFT Input Index"])
        if input_id <= 0 or input_id != float(row["FFT Input Index"]):
            raise ValueError(f"Native BCA has invalid FFT input identity: {path}")
        input_ids.add(input_id)
        order = int(row["Oddball Harmonic Order"])
        sensor = str(row["Electrode"]).strip().upper()
        if order not in orders or sensor not in requested_sensors:
            continue
        target = available[order]
        candidates = tuple(int(value) for value in str(row["Noise Candidate FFT Bins"]).split(","))
        retained = tuple(int(value) for value in str(row["Noise Retained FFT Bins"]).split(","))
        if (
            str(row["BCA Status"]).strip().casefold() != "available"
            or str(row["Eligibility Fingerprint"]) != eligibility.fingerprint
            or Fraction(str(row["Target Frequency Exact (Hz)"])) != target.target.frequency_hz
            or int(row["Target FFT Bin"]) != target.target_bin_index
            or candidates != target.noise_candidate_bin_indices
            or len(retained) != 16
            or len(set(retained)) != 16
            or retained != tuple(sorted(retained))
            or not set(retained).issubset(candidates)
            or not np.isfinite(float(row["Noise Mean (uV)"]))
        ):
            raise ValueError(f"Native BCA cell evidence is unavailable or inconsistent: {path}/{sensor}/H{order}")
        key = (input_id, sensor, order)
        if key in cells:
            raise ValueError(f"Native BCA repeats required cell evidence: {path}/{key}")
        cells[key] = row
        selected_audit.append({**row, "Electrode": sensor})
    required = {(number, sensor, order) for number in input_ids for sensor in requested_sensors for order in orders}
    if not input_ids or input_ids != set(range(1, max(input_ids) + 1)) or set(cells) != required:
        raise ValueError(f"Native BCA lacks complete per-input/sensor/harmonic evidence: {path}")
    selected_audit.sort(
        key=lambda row: (int(row["FFT Input Index"]), row["Electrode"], int(row["Oddball Harmonic Order"]))
    )
    encoded_audit = json.dumps(selected_audit, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return values, {
        "native_bca_columns_json": json.dumps(columns),
        "native_bca_eligibility_fingerprint": eligibility.fingerprint,
        "native_bca_fft_input_count": len(input_ids),
        "native_bca_validated_cell_count": len(cells),
        "native_bca_selected_cell_evidence_sha256": sha256(encoded_audit.encode("utf-8")).hexdigest(),
        "native_bca_status": "every required per-input BCA cell available",
    }


def ordered_amplitude_matrix(frame, sensors: list[str], columns: list[str], source: str):
    """Match labels case-insensitively, retaining the primary sensor order."""
    import numpy as np

    requested = [str(sensor).strip().upper() for sensor in sensors]
    labels = frame["Electrode"].astype(str).str.strip().str.upper()
    if len(set(requested)) != len(requested):
        raise ValueError("Primary sensor names collide after case normalization.")
    if labels.duplicated().any() or set(labels) != set(requested):
        raise ValueError(f"Source sensor set differs from primary or has duplicate labels: {source}")
    return frame.assign(Electrode=labels).set_index("Electrode").loc[requested, columns].to_numpy(dtype=np.float64)


def assemble_arm(
    comparison: dict, participant_ids: list[str], arm: str, sources: list[dict], cache: dict, sessions: list[str]
):
    import numpy as np
    from Tools.Free_Harmonic_Clustering.preparation import l2_normalize_snr

    raw, reconstructed = [], []
    for participant in participant_ids:
        rows = [
            row for row in sources if row["arm"].casefold() == arm.casefold() and row["participant_id"] == participant
        ]
        if len({row["session_id"] for row in rows}) != len(rows):
            raise ValueError(f"Ambiguous primary source identity for {participant}, arm {arm}.")
        by_session = {row["session_id"]: cache[row["project_relative_path"]] for row in rows}
        kind = comparison["kind"]
        if sessions and kind in {"between_groups", "between_conditions", "group_visit_change"}:
            if set(by_session) != set(sessions) or len(sessions) != 2:
                raise ValueError(f"Primary complete visit pair is unavailable for {participant}.")
            first, second = (by_session[session] for session in sessions)
            if kind == "group_visit_change":
                raw.append(first[0] - second[0])
                reconstructed.append(l2_normalize_snr(first[1][None])[0] - l2_normalize_snr(second[1][None])[0])
            else:
                raw.append((first[0] + second[0]) / 2)
                reconstructed.append(l2_normalize_snr(((first[1] + second[1]) / 2)[None])[0])
        else:
            if len(rows) != 1:
                raise ValueError(f"Exactly one frozen primary source is required for {participant}, arm {arm}.")
            values = cache[rows[0]["project_relative_path"]]
            raw.append(values[0])
            reconstructed.append(l2_normalize_snr(values[1][None])[0])
    return np.ascontiguousarray(raw), np.ascontiguousarray(reconstructed)


def prepare(project_root: Path, primary_dir: Path, manifest: dict):
    import numpy as np
    from Main_App.io import (
        condition_companion_identity,
        read_spectral_sheet_selected_columns,
        spectral_companion_identity,
    )
    from Main_App.processing.full_fft_provenance import validate_project_full_fft_provenance
    from Main_App.projects import load_project_dataset_index, normalize_frequency_protocol
    from Tools.Free_Harmonic_Clustering.analysis import biosemi64_adjacency_manifest
    from Tools.Free_Harmonic_Clustering.analysis_plan import build_analysis_plan
    from Tools.Free_Harmonic_Clustering.models import RecordingExclusionRequest

    method = manifest["method"]
    frozen = manifest["plan"]
    canonical_plan = build_analysis_plan(
        project_root,
        group_ids=frozen["group_ids"],
        conditions=frozen["conditions"],
        session_ids=frozen["session_ids"],
        families=frozen["families"],
        condition_pairs=[tuple(pair) for pair in frozen["condition_pairs"]],
        recording_exclusions=tuple(RecordingExclusionRequest(**row) for row in frozen["recording_exclusions"]),
    )
    if canonical_plan.to_dict() != frozen or canonical_plan.fingerprint != manifest["plan_fingerprint"]:
        raise ValueError("Primary plan differs from canonical native project metadata.")
    index = load_project_dataset_index(project_root)
    protocol = normalize_frequency_protocol(index.manifest["frequency_protocol"])
    neutral = validate_project_full_fft_provenance(
        project_root,
        base_frequency_hz=method["base_frequency_hz"],
        oddball_frequency_hz=method["oddball_frequency_hz"],
        dataset_index=index,
    )
    for primary_name, current_name in {
        "full_fft_provenance_method_version": "method_version",
        "full_fft_source_fingerprint": "source_fingerprint",
        "full_fft_cohort_fingerprint": "cohort_fingerprint",
        "full_fft_frequency_qc_fingerprint": "frequency_qc_fingerprint",
        "full_fft_processing_export_fingerprint": "processing_export_fingerprint",
    }.items():
        if manifest["preparation"][primary_name] != getattr(neutral, current_name):
            raise ValueError(f"Current project differs from the primary run: {primary_name}")
    adjacency = biosemi64_adjacency_manifest()
    if (
        manifest["adjacency"]["fingerprint"] != adjacency["fingerprint_sha256"]
        or manifest["adjacency"]["edges"] != adjacency["edges"]
    ):
        raise ValueError("Installed inference adjacency differs from the primary run.")
    source_rows = csv_read(primary_dir / "source_workbooks.csv")
    frequency_plan = manifest["frequency_plan"]
    if frequency_plan["grid_fingerprint"] != neutral.grid_fingerprint:
        raise ValueError("The primary FullFFT grid differs from current project provenance.")
    columns = frequency_plan["selected_frequency_columns"]
    cache, audits, prepared = {}, [], []
    for comparison, identity in zip(manifest["plan"]["comparisons"], manifest["comparisons"], strict=True):
        directory = contained(primary_dir / identity["directory"], primary_dir)
        with np.load(directory / "arrays.npz", allow_pickle=False) as data:
            sensors = data["sensor_names"].tolist()
            orders = data["harmonic_orders"].tolist()
            if (
                orders != manifest["selected_harmonic_orders"]
                or data["harmonics_hz"].tolist() != manifest["selected_harmonics_hz"]
            ):
                raise ValueError("Primary stored arrays differ from the shared harmonic domain.")
            sources = [row for row in source_rows if row["comparison_id"] == comparison["comparison_id"]]
            for row in sources:
                relative = row["project_relative_path"]
                path = contained(project_root / relative, project_root)
                stat = path.stat()
                if stat.st_size != int(row["source_size_bytes"]) or stat.st_mtime_ns != int(row["source_mtime_ns"]):
                    raise ValueError(f"Primary FullFFT workbook changed: {relative}")
                if relative not in cache:
                    before = digest(path)
                    companion_identity = spectral_companion_identity(path)
                    companion_path = None
                    companion_digest = ""
                    if companion_identity is not None:
                        companion_path = contained(path.parent / companion_identity["path"], project_root)
                        companion_digest = digest(companion_path)
                        if companion_digest != companion_identity["sha256"]:
                            raise ValueError(f"Spectral companion checksum differs from its declaration: {relative}")
                    condition_identity = condition_companion_identity(path)
                    condition_path = None
                    condition_digest = ""
                    if condition_identity is not None:
                        condition_path = contained(path.parent / condition_identity["path"], project_root)
                        condition_digest = digest(condition_path)
                        if condition_digest != condition_identity["sha256"]:
                            raise ValueError(f"Condition companion checksum differs from its declaration: {relative}")
                    frame = read_spectral_sheet_selected_columns(
                        path, sheet_name=SOURCE_SHEET, required_columns=["Electrode", *columns], require_all=True
                    )
                    matrix = ordered_amplitude_matrix(frame, sensors, columns, relative)
                    native_bca, bca_evidence = read_native_bca(
                        path,
                        sensors,
                        orders,
                        manifest["selected_harmonics_hz"],
                        protocol,
                        frequency_plan,
                    )
                    cache[relative] = (native_bca, primary_snr(matrix, frequency_plan, orders))
                    if digest(path) != before:
                        raise ValueError(f"Source workbook changed during preparation: {relative}")
                    if spectral_companion_identity(path) != companion_identity or (
                        companion_path is not None and digest(companion_path) != companion_digest
                    ):
                        raise ValueError(f"Spectral companion changed during preparation: {relative}")
                    if condition_companion_identity(path) != condition_identity or (
                        condition_path is not None and digest(condition_path) != condition_digest
                    ):
                        raise ValueError(f"Condition companion changed during preparation: {relative}")
                    audits.append(
                        {
                            "project_relative_path": relative,
                            "source_sha256": before,
                            "source_size_bytes": stat.st_size,
                            "source_mtime_ns": stat.st_mtime_ns,
                            "spectral_companion_identity_json": json.dumps(
                                companion_identity, sort_keys=True, allow_nan=False
                            ),
                            "spectral_companion_path": "" if companion_identity is None else companion_identity["path"],
                            "spectral_companion_sha256": companion_digest,
                            "condition_companion_identity_json": json.dumps(
                                condition_identity, sort_keys=True, allow_nan=False
                            ),
                            "condition_companion_path": ""
                            if condition_identity is None
                            else condition_identity["path"],
                            "condition_companion_sha256": condition_digest,
                            **bca_evidence,
                        }
                    )
            arms = []
            for arm in ("a", "b"):
                ids = data[f"participant_ids_{arm}"].tolist()
                if ids != identity[f"participant_ids_{arm}"]:
                    raise ValueError("Primary participant order differs between arrays and manifest.")
                raw, snr_check = assemble_arm(comparison, ids, arm, sources, cache, manifest["plan"]["session_ids"])
                np.testing.assert_allclose(
                    snr_check,
                    data[f"analyzed_values_{arm}"],
                    rtol=1e-10,
                    atol=1e-12,
                    err_msg="Reconstructed SNR fails to reproduce primary analyzed tensors; stop rather than change cohort or recipe.",
                )
                arms.append(raw)
            prepared.append((comparison, identity, tuple(sensors), arms[0], arms[1]))
    return prepared, audits, source_rows


def run(
    project_root: Path,
    primary_dir: Path,
    manifest: dict,
    prepared,
    audits,
    source_rows,
    output_root: Path,
    run_id: str,
    prepare_only: bool,
) -> Path:
    import numpy as np
    from Tools.Free_Harmonic_Clustering.analysis import (
        global_cluster_two_sided_p_value,
        holm_adjust_p_values,
        run_cluster_permutation,
    )
    from Tools.Free_Harmonic_Clustering.models import FreeHarmonicMethodSpec

    output_root = contained(output_root, project_root)
    validate_run_id(run_id)
    final = contained(output_root / "runs" / run_id, output_root)
    if final.exists():
        raise FileExistsError(f"Completed output already exists: {final}")
    staging = contained(output_root / "runs" / f".{run_id}.staging-{uuid4().hex}", output_root)
    staging.mkdir(parents=True, exist_ok=False)
    try:
        results, summary, cluster_rows, membership, participant_rows = [], [], [], [], []
        for number, (comparison, identity, sensors, arm_a, arm_b) in enumerate(prepared, 1):
            LOG.info(
                "%s %d/%d: %s", "Preparing" if prepare_only else "Analyzing", number, len(prepared), comparison["label"]
            )
            config = {**manifest["method"], "method_version": METHOD_ID, "seed": int(identity["seed"])}
            spec = FreeHarmonicMethodSpec(**config)
            if int(identity.get("permutations_evaluated", spec.n_permutations)) != spec.n_permutations:
                raise ValueError("Primary assignment count differs from its method specification.")
            result = (
                None
                if prepare_only
                else run_cluster_permutation(
                    arm_a, arm_b, design=comparison["design"], method=spec, sensor_names=sensors
                )
            )
            if result is not None and result.permutation_assignment_hash != identity["permutation_assignment_hash"]:
                raise ValueError("Raw-BCA permutation assignments differ from the frozen primary schedule.")
            results.append(result)
            entry = {
                "comparison_id": comparison["comparison_id"],
                "family_id": comparison["family_id"],
                "comparison": comparison["label"],
                "condition": comparison["condition_a"],
                "n_a": len(arm_a),
                "n_b": len(arm_b),
                "seed": spec.seed,
                "metric": METHOD_ID,
                "units": "uV",
                "status": "prepared" if result is None else "complete",
            }
            if result is not None:
                entry.update(
                    global_two_sided_cluster_p=global_cluster_two_sided_p_value(result),
                    permutation_assignment_hash=result.permutation_assignment_hash,
                    permutations=result.permutations_evaluated,
                    cluster_count=len(result.clusters),
                    degrees_of_freedom=result.degrees_of_freedom,
                    cluster_forming_t_threshold=result.cluster_forming_threshold,
                )
            summary.append(entry)
            folder = staging / "comparisons" / f"{number:04d}"
            folder.mkdir(parents=True)
            metadata = {
                **entry,
                "comparison_recipe": comparison,
                "normalization": "none",
                "tensor_semantics": "Raw BCA participant tensors; repeated arms average both visits or subtract ordered visits, with no L2 normalization",
                "arm_a_label": identity["arm_a_label"],
                "arm_b_label": identity["arm_b_label"],
            }
            arrays = {
                "raw_bca_values_a_uv": arm_a,
                "raw_bca_values_b_uv": arm_b,
                "sensor_names": np.asarray(sensors),
                "harmonic_orders": np.asarray(manifest["selected_harmonic_orders"]),
                "harmonics_hz": np.asarray(manifest["selected_harmonics_hz"]),
                "participant_ids_a": np.asarray(identity["participant_ids_a"]),
                "participant_ids_b": np.asarray(identity["participant_ids_b"]),
                "metadata_json": np.asarray(json.dumps(metadata, allow_nan=False)),
            }
            for arm in ("a", "b"):
                participant_rows.extend(
                    {
                        "comparison_id": comparison["comparison_id"],
                        "arm": arm,
                        "participant_id": pid,
                        "arm_label": identity[f"arm_{arm}_label"],
                    }
                    for pid in identity[f"participant_ids_{arm}"]
                )
            if result is not None:
                arrays.update(
                    observed_t=result.observed_t,
                    cluster_labels=result.cluster_labels,
                    null_positive_max_mass=result.null_positive_max_mass,
                    null_negative_min_mass=result.null_negative_min_mass,
                )
                for cluster in result.clusters:
                    nodes = list(cluster.node_indices)
                    mean_a = arm_a.reshape(len(arm_a), -1)[:, nodes].mean(axis=1)
                    mean_b = arm_b.reshape(len(arm_b), -1)[:, nodes].mean(axis=1)
                    row = {
                        "comparison_id": comparison["comparison_id"],
                        "family_id": comparison["family_id"],
                        **asdict(cluster),
                        "arm_a_cluster_mean_uv": float(mean_a.mean()),
                        "arm_b_cluster_mean_uv": float(mean_b.mean()),
                        "a_minus_b_cluster_mean_uv": float(mean_a.mean() - mean_b.mean()),
                        "effect_label": "Descriptive post-selection cluster-node effect; no pointwise inference",
                    }
                    for name in ("node_indices", "sensor_indices", "harmonic_indices"):
                        row[name] = json.dumps(row[name])
                    cluster_rows.append(row)
                    membership.extend(
                        {
                            "comparison_id": comparison["comparison_id"],
                            "cluster_id": cluster.cluster_id,
                            "sign": cluster.sign,
                            "sensor": sensors[node // arm_a.shape[2]],
                            "harmonic_order": manifest["selected_harmonic_orders"][node % arm_a.shape[2]],
                            "harmonic_hz": manifest["selected_harmonics_hz"][node % arm_a.shape[2]],
                            "raw_sign_specific_cluster_p": cluster.p_value,
                        }
                        for node in nodes
                    )
                json_write(
                    folder / "engine_result.json",
                    {
                        "configuration": config,
                        "permutation_assignment_hash": result.permutation_assignment_hash,
                        "timing_seconds": dict(result.timing_seconds),
                        "warnings": list(result.warnings),
                    },
                )
                csv_write(
                    folder / "node_statistics.csv",
                    [
                        {
                            "sensor": sensor,
                            "harmonic_order": order,
                            "harmonic_hz": hz,
                            "observed_t": float(result.observed_t[si, hi]),
                            "cluster_id": int(result.cluster_labels[si, hi]),
                            "mean_a_raw_bca_uv": float(arm_a[:, si, hi].mean()),
                            "mean_b_raw_bca_uv": float(arm_b[:, si, hi].mean()),
                        }
                        for si, sensor in enumerate(sensors)
                        for hi, (order, hz) in enumerate(
                            zip(manifest["selected_harmonic_orders"], manifest["selected_harmonics_hz"], strict=True)
                        )
                    ],
                )
            np.savez_compressed(folder / "arrays.npz", **arrays)
        if not prepare_only:
            global_values = [row["global_two_sided_cluster_p"] for row in summary]
            full = holm_adjust_p_values(global_values)
            for index, row in enumerate(summary):
                members = [i for i, other in enumerate(summary) if other["family_id"] == row["family_id"]]
                adjusted = holm_adjust_p_values([global_values[i] for i in members])
                row.update(
                    holm_within_family_p=adjusted[members.index(index)],
                    holm_full_plan_p=full[index],
                    family_size=len(members),
                    passes_family_holm=adjusted[members.index(index)] <= 0.05,
                )
        csv_write(staging / "comparisons.csv", summary)
        csv_write(
            staging / "all_clusters.csv",
            cluster_rows,
            None if cluster_rows else ["comparison_id", "cluster_id", "p_value", "status"],
        )
        csv_write(
            staging / "cluster_membership.csv",
            membership,
            None if membership else ["comparison_id", "cluster_id", "sensor", "harmonic_order", "harmonic_hz"],
        )
        csv_write(staging / "participants.csv", participant_rows)
        csv_write(staging / "source_workbooks.csv", source_rows)
        csv_write(staging / "source_hashes.csv", audits)
        for name in ("analysis_plan.json", "cohort_audit.csv", "exclusions.csv", "harmonic_selection.csv"):
            (staging / f"primary_{name}").write_bytes((primary_dir / name).read_bytes())
        methods = {
            "method_id": METHOD_ID,
            "label": "Exploratory stored native Toolbox BCA on the primary FHC domain",
            "metric": "Exact stored native BCA (uV) cells at the primary FHC harmonic columns; no BCA recalculation or harmonic summation",
            "units": "microvolts",
            "normalization": "none",
            "saved_toolbox_BCA_used": True,
            "native_bca_method_version": "qc14_fixed_bin_metrics_v1",
            "noise_definition_note": "Processing-owned native BCA uses exact -10..-2,+2..+10 FFT bins; one finite minimum and one maximum are removed even when tied, retaining 16 original-order bins. BCA is target amplitude minus that mean. Negative finite values are retained.",
            "native_aggregation_note": "Processing computes trimmed BCA separately for every FFT input and then averages the already-calculated BCA values. Trimming is nonlinear; recomputing BCA from the averaged FullFFT spectrum can differ and is never done here.",
            "availability_policy": "Every primary harmonic must have exact stored finite BCA and current native spectral eligibility/per-input cell availability evidence. An unavailable cell fails the complete secondary plan; no domain shrinking, fallback metric, omission or zero-fill.",
            "source_immutability": "No project manifest, workbook, settings, ledger, or QC record is modified.",
            "plan_and_cohort": "Every primary comparison, participant order, required visit pair, direction, shared harmonic domain and exclusion is frozen unchanged.",
            "tensor_recipes": "Repeated between-group/condition arms average raw BCA across both visits; within-group arms use individual raw visits; group-change arms subtract raw visit profiles in the primary plan order. No L2 normalization is applied to any BCA tensor.",
            "inference": "Existing Toolbox whole-participant permutation engine, fixed primary sensor/free-harmonic adjacency, same assignments/seeds/counts, .01 two-sided node-entry alpha and .025 sign-specific cluster alpha.",
            "multiplicity": "Holm of run-global two-sided cluster p values within each full primary family; full-plan Holm also reported. Separate metric families; this does not jointly correct primary SNR and secondary BCA.",
            "interpretation": "Exploratory cluster-level amplitude evidence conditional on the SNR-selected domain and valid participant exchangeability; no pointwise significance and no unconditional calibration claim.",
            "validation_limit": "Unnormalized BCA inference and the repeated-plan extension are not the published Hermann-compatible normalized profile and are not validated by the legacy powered-null receipt.",
            "paper_reference": PAPER_URL,
            "primary_plan_fingerprint": manifest["plan_fingerprint"],
            "shared_domain_fingerprint": manifest["preparation"]["shared_domain_fingerprint"],
            "primary_frequency_plan_for_snr_reconstruction_only": manifest["frequency_plan"],
            "primary_adjacency": manifest["adjacency"],
            "primary_preparation": manifest["preparation"],
            "primary_method": manifest["method"],
            "primary_tensor_reconstruction_check": "Every reconstructed normalized SNR arm matches primary stored arrays at rtol=1e-10, atol=1e-12 before inference.",
        }
        json_write(staging / "methods.json", methods)
        verify_input_snapshots(project_root, primary_dir, manifest, audits)
        json_write(
            staging / "manifest.json",
            {
                "schema_version": 1,
                "status": "prepared" if prepare_only else "complete",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "method_id": METHOD_ID,
                "primary_run": primary_dir.relative_to(project_root).as_posix(),
                "primary_manifest_sha256": manifest.get("_input_primary_manifest_sha256")
                or digest(primary_dir / "manifest.json"),
                "adapter_sha256": digest(Path(__file__)),
                "plan_fingerprint": manifest["plan_fingerprint"],
                "results": summary,
                "methods": methods,
                "software": {
                    "python": sys.version,
                    "numpy": np.__version__,
                    "primary_software": manifest.get("software", {}),
                },
                "artifacts": [
                    {
                        "path": path.relative_to(staging).as_posix(),
                        "sha256": digest(path),
                        "size_bytes": path.stat().st_size,
                    }
                    for path in sorted(staging.rglob("*"))
                    if path.is_file()
                ],
            },
        )
        if final.exists():
            raise FileExistsError(f"Output appeared during the analysis: {final}")
        os.replace(staging, final)
    except BaseException as exc:
        json_write(staging / "FAILED.json", {"status": "failed", "error": str(exc), "complete_bundle_published": False})
        raise
    return final


def validate_run_id(run_id: str) -> None:
    if (
        not run_id
        or run_id in {".", ".."}
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in run_id)
    ):
        raise ValueError("Run ID must use only letters, digits, underscores and hyphens.")


def verify_input_snapshots(project_root: Path, primary_dir: Path, manifest: dict, audits: list[dict]) -> None:
    """Reject input changes before publishing a completed or prepared bundle."""
    expected_manifest = manifest.get("_input_project_manifest_sha256")
    if expected_manifest and digest(project_root / "project.json") != expected_manifest:
        raise ValueError("Project manifest changed during secondary preparation or inference.")
    expected_primary = manifest.get("_input_primary_manifest_sha256")
    if expected_primary and digest(primary_dir / "manifest.json") != expected_primary:
        raise ValueError("Primary manifest changed during secondary preparation or inference.")
    if expected_primary:
        for artifact in manifest["artifacts"]:
            path = contained(project_root / artifact["path"], primary_dir)
            if path.stat().st_size != int(artifact["size_bytes"]) or digest(path) != artifact["sha256"]:
                raise ValueError(f"Primary artifact changed before publication: {path}")
    for audit in audits:
        path = contained(project_root / audit["project_relative_path"], project_root)
        if digest(path) != audit["source_sha256"]:
            raise ValueError(f"Source workbook changed before publication: {path}")
        for kind in ("spectral", "condition"):
            if audit.get(f"{kind}_companion_sha256"):
                companion = contained(path.parent / audit[f"{kind}_companion_path"], project_root)
                if digest(companion) != audit[f"{kind}_companion_sha256"]:
                    raise ValueError(f"{kind.title()} companion changed before publication: {companion}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        required=True,
        help="Explicit source checkout containing src/Tools/Free_Harmonic_Clustering.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        required=True,
        help="Explicit managed project root containing project.json; inputs remain read-only.",
    )
    parser.add_argument(
        "--primary-run",
        type=Path,
        required=True,
        help="Absolute completed native primary run directory or manifest.json beneath the same project.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Absolute additive results parent beneath the project; default Secondary Raw BCA.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="Wait only for that exact completed primary manifest; never infer a harmonic domain.",
    )
    parser.add_argument("--run-id", help="Unique additive secondary directory name.")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Validate primary inputs and export raw tensors without permutations; can still read large source archives.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.repo_root.is_absolute() or not args.project_root.is_absolute():
        parser.error("--repo-root and --project-root must be absolute.")
    repo_root = args.repo_root.resolve(strict=True)
    project_root = args.project_root.resolve(strict=True)
    src = repo_root / "src"
    if (
        not (src / "Tools" / "Free_Harmonic_Clustering" / "analysis.py").is_file()
        or not (project_root / "project.json").is_file()
    ):
        parser.error("An existing source checkout and managed project are required.")
    if args.wait_seconds < 0:
        parser.error("--wait-seconds must be nonnegative.")
    output_root = args.output_root or project_root / "Secondary Raw BCA"
    if not output_root.is_absolute():
        parser.error("--output-root must be absolute.")
    output_root = contained(output_root, project_root)
    if output_root == project_root:
        parser.error("--output-root must be a separate project-local results parent.")
    sys.path.insert(0, str(src))
    run_id = args.run_id or datetime.now(timezone.utc).strftime("raw-bca-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    validate_run_id(run_id)
    project_snapshot = digest(project_root / "project.json")
    primary_dir, manifest = load_primary(project_root, args.primary_run, args.wait_seconds)
    manifest["_input_project_manifest_sha256"] = project_snapshot
    prepared, audits, source_rows = prepare(project_root, primary_dir, manifest)
    destination = run(
        project_root, primary_dir, manifest, prepared, audits, source_rows, output_root, run_id, args.prepare_only
    )
    LOG.info("%s bundle: %s", "Prepared" if args.prepare_only else "Completed exploratory raw-BCA", destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
