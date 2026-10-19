"""Compare a registered project's native and BIDS processing with optional QC off.

This explicit, non-GUI diagnostic reads project.json without Project.load(),
never modifies source recordings or project settings, and writes all evidence
under a new --work-dir. Each recording/route runs in a fresh subprocess, with
one numerical thread and RAM preload. No repository tests are invoked.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

from compare_bids_pipeline import _baseline, _compare, _sha256, _write_json

LOG = logging.getLogger(__name__)


def _settings(manifest: dict, project_root: Path) -> dict:
    from Main_App.projects.frequency_protocol import normalize_frequency_protocol
    from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings

    original = normalize_preprocessing_settings(manifest.get("preprocessing", {}))
    settings = {key: value for key, value in original.items() if not key.startswith("_fpvs_")}
    protocol = normalize_frequency_protocol(manifest.get("frequency_protocol"))
    if not protocol.is_ready:
        raise ValueError("The project needs a confirmed frequency protocol before comparison.")
    settings.update({
        "project_root": str(project_root),
        "frequency_protocol": protocol.to_manifest(),
        "downsample_rate": original["downsample"],
        "ref_channel1": original["ref_chan1"],
        "ref_channel2": original["ref_chan2"],
        "max_idx_keep": original["max_chan_idx_keep"],
        "stim_channel": original.get("stim_channel") or "Status",
        "kurtosis_screening_enabled": False,
        "reject_thresh": 0.0,
        "rejection_z": 0.0,
        "raw_signal_screening_enabled": False,
        "removed_electrode_detection_mode": "off",
        "auto_detect_removed_electrodes": False,
        "manual_removed_electrodes_enabled": False,
        "manual_removed_electrodes": {},
        "manual_removed_electrodes_by_recording": {},
        "manual_excluded_participants": [],
        "manual_excluded_recordings": [],
        "manual_excluded_participant_conditions": {},
        "manual_excluded_recording_conditions": {},
        "kurtosis_auto_interpolate_all": False,
        "kurtosis_review_auto_interpolate_extreme": False,
        "kurtosis_review_decisions_by_recording": {},
        "interpolation_burden_review_enabled": False,
        "interpolation_burden_review_decisions": {},
        "condition_specific_interpolation_enabled": False,
        "condition_electrode_interpolation_requests": {},
        "raw_spectral_screening_enabled": False,
        "snr_spectral_screening_enabled": False,
        "stats_dv_screening_enabled": False,
        "summed_bca_screening": {"enabled": False},
        "raw_spectral_screening": {"enabled": False},
        "enable_preprocessed_cache": False,
        "experimental_ram_preload": True,
    })
    return settings


def _capture_inputs(repo: Path, project_root: Path, limit: int | None) -> dict:
    """Resolve only registered raw sources through the read-only project API."""
    sys.path.insert(0, str(repo / "src"))
    from Main_App.projects.recordings import project_recording_context_from_manifest

    manifest_path = project_root / "project.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    context = project_recording_context_from_manifest(project_root, manifest)
    participants = {row.participant_id: row for row in context.participants}
    groups = {row.group_id: row for row in context.groups}
    rows = []
    if context.recordings:
        for row in context.recordings:
            participant = participants[row.participant_id]
            rows.append({"participant": row.participant_id, "recording_id": row.recording_id,
                         "file": str(row.raw_file.resolve()), "group_id": participant.group_id,
                         "session_id": row.session_id,
                         "session_label": context.session(row.session_id).label,
                         "visit_index": row.visit_index, "days_from_baseline": row.days_from_baseline})
    else:
        for row in context.participants:
            if row.raw_file is None:
                raise ValueError(f"Registered participant {row.participant_id} has no raw_file.")
            rows.append({"participant": row.participant_id, "recording_id": row.participant_id,
                         "file": str(row.raw_file.resolve()), "group_id": row.group_id,
                         "session_id": "", "session_label": ""})
    rows.sort(key=lambda row: (row["participant"], row["recording_id"]))
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("The project has no registered recordings to compare.")
    files = set()
    for row in rows:
        path = Path(row["file"])
        if path.suffix.casefold() != ".bdf":
            raise ValueError(f"This native BDF comparison requires .bdf files: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path in files:
            raise ValueError(f"Multiple registered recordings refer to the same raw file: {path}")
        files.add(path)
        row["size_bytes"] = path.stat().st_size
        row["mtime_ns"] = path.stat().st_mtime_ns
        row["sha256"] = _sha256(path)
        row["group_folder"] = groups[row["group_id"]].folder_name if row["group_id"] else None
    event_map = {str(label): int(code) for label, code in manifest.get("event_map", {}).items()}
    if not event_map:
        raise ValueError("The project has no configured condition event map.")
    settings = _settings(manifest, project_root)
    scientific = {key: value for key, value in settings.items() if key != "project_root"}
    fingerprint = hashlib.sha256(json.dumps(scientific, sort_keys=True).encode()).hexdigest()
    settings["_fpvs_processing_fingerprint"] = fingerprint
    settings["_fpvs_processing_fingerprint_version"] = "project-native-bids-qc-off-diagnostic-v1"
    return {"project_root": str(project_root), "project_name": manifest.get("name") or project_root.name,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "recordings": rows, "event_map": event_map, "settings": settings,
            "grouped_project": bool(context.groups), "repeated_session": bool(context.recordings),
            "qc_disabled": True, "line_noise_filter_enabled": settings["line_noise_filter_enabled"],
            "preload": "RAM", "numerical_threads": 1,
            "original_preprocessing": manifest.get("preprocessing", {})}


def _recording_settings(inputs: dict, row: dict, project_root: Path) -> dict:
    settings = dict(inputs["settings"])
    settings["project_root"] = str(project_root)
    path = row["file"]
    settings["event_id_map"] = inputs["event_map"]
    settings["_fpvs_participant_id_by_file"] = {path: row["participant"]}
    settings["_fpvs_recording_id_by_file"] = {path: row["recording_id"]}
    settings["_fpvs_output_stem_by_file"] = {path: row["recording_id"]}
    settings["_fpvs_grouped_project"] = inputs["grouped_project"]
    if row["group_id"]:
        settings["_fpvs_group_id_by_file"] = {path: row["group_id"]}
        settings["_fpvs_output_group_by_file"] = {path: row["group_folder"]}
    for key in ("session_id", "session_label", "visit_index", "days_from_baseline"):
        if row.get(key) not in (None, ""):
            settings[f"_fpvs_{key}_by_file"] = {path: row[key]}
    return settings


def _run_recording(source_root: Path, work: Path, side: str, index: int) -> None:
    sys.path.insert(0, str(source_root / "src"))
    import mne
    from Main_App.io.load_utils import open_preflight_eeg_file
    from Main_App.processing.preflight_qc import _find_preflight_events
    from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
    from Main_App.projects.frequency_protocol import normalize_frequency_protocol
    from Main_App.workers.process_runner import _run_full_pipeline_for_file
    from types import SimpleNamespace

    mne.set_log_level("ERROR")
    inputs = json.loads((work / "inputs.json").read_text(encoding="utf-8"))
    row = inputs["recordings"][index]
    path = Path(row["file"])
    project_root = work / side
    settings = _recording_settings(inputs, row, project_root)
    settings["frequency_protocol"] = normalize_frequency_protocol(settings["frequency_protocol"])
    receipt_path = work / "receipts" / f"{side}-{index:04d}.json"
    conversion = (
        json.loads((work / "receipts" / f"import-{index:04d}.json").read_text(encoding="utf-8"))
        if side == "new" else None
    )
    total_started = time.perf_counter()
    started = time.perf_counter()
    app = SimpleNamespace(log=lambda _message: None)
    with open_preflight_eeg_file(
        app, str(path), acquisition_settings=settings,
        ref_pair=(settings["ref_channel1"], settings["ref_channel2"]),
        electrode_mapping_profile=settings["electrode_mapping_profile"],
        electrode_montage=settings["electrode_montage"],
    ) as raw:
        if raw is None:
            raise RuntimeError(f"The {side} reader could not admit {row['recording_id']}.")
        events, source = _find_preflight_events(raw, stim_channel=settings["stim_channel"])
        plan = plan_preflight_qc_events(
            events=events, event_map=inputs["event_map"], sfreq=raw.info["sfreq"],
            n_times=raw.n_times, first_samp=raw.first_samp,
            frequency_protocol=settings["frequency_protocol"], recording_id=row["recording_id"],
        )
        if plan.unresolved_occurrences:
            _write_json(receipt_path, {"status": "marker_review_required", "recording": row,
                                      "unresolved_occurrences": plan.unresolved_occurrences})
            raise RuntimeError(f"{row['recording_id']}: mandatory marker plan requires review; see {receipt_path}")
        snapshot = {"events": events.tolist(), "event_source": source, "channel_names": raw.ch_names,
                    "channel_types": raw.get_channel_types(), "sfreq": raw.info["sfreq"],
                    "n_times": raw.n_times, "first_samp": raw.first_samp,
                    "event_plan": plan.to_payload()}
    preflight_seconds = time.perf_counter() - started
    settings["_fpvs_preflight_event_plans_by_file"] = {str(path): plan.to_payload()}
    started = time.perf_counter()
    result = _run_full_pipeline_for_file(
        path, settings, inputs["event_map"], project_root / "1 - Excel Data Files", project_root,
    )
    processing_seconds = time.perf_counter() - started
    total_seconds = time.perf_counter() - total_started
    item = {"participant": row["participant"], "recording_id": row["recording_id"],
            "preflight_seconds": preflight_seconds, "processing_seconds": processing_seconds,
            "total_seconds": total_seconds, "bids_conversion": conversion,
            "source_snapshot": snapshot, "result": result}
    _write_json(receipt_path, item)
    if result.get("status") != "ok" or result.get("source_derivative_status") != "complete":
        raise RuntimeError(f"{side} {row['recording_id']} failed; see {receipt_path}")
    audit = result["audit"]
    if audit.get("raw_signal_screening_enabled") is not False or audit.get("n_rejected") != 0:
        raise RuntimeError("Optional raw-signal QC or channel interpolation was unexpectedly active.")


def _prepare_imports(repo: Path, work: Path, inputs: dict, *, resume: bool) -> float:
    """Serialize initial conversion so its time is separate from both worker runs."""
    sys.path.insert(0, str(repo / "src"))
    from Main_App.io.bids_import import prepare_bids_recording

    started_phase = time.perf_counter()
    for index, row in enumerate(inputs["recordings"]):
        receipt_path = work / "receipts" / f"import-{index:04d}.json"
        if resume and receipt_path.is_file():
            continue
        LOG.info("BIDS import %d/%d %s starting", index + 1, len(inputs["recordings"]), row["recording_id"])
        settings = _recording_settings(inputs, row, work / "new")
        started = time.perf_counter()
        imported = prepare_bids_recording(Path(row["file"]), project_root=work / "new", settings=settings)
        conversion = {"wall_seconds": time.perf_counter() - started,
                      "conversion_seconds": imported.conversion_seconds,
                      "identity_seconds": imported.identity_seconds,
                      "reused": imported.reused, "dataset_root": str(imported.dataset_root),
                      "bids_path": str(imported.bids_path), "manifest_path": str(imported.manifest_path)}
        if imported.reused:
            raise RuntimeError("Cold-conversion benchmark unexpectedly reused an import without a saved timing receipt.")
        _write_json(receipt_path, conversion)
        LOG.info("BIDS import %s complete in %.3f s (conversion %.3f s)", row["recording_id"],
                 conversion["wall_seconds"], conversion["conversion_seconds"])
    return time.perf_counter() - started_phase


def _run_phase(work: Path, source: Path, side: str, inputs: dict, *, workers: int, resume: bool) -> float:
    environment = dict(os.environ, PYTHONNOUSERSITE="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", OMP_NUM_THREADS="1")

    def run_one(index: int, row: dict) -> tuple[int, dict]:
        receipt_path = work / "receipts" / f"{side}-{index:04d}.json"
        if resume and receipt_path.exists():
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing.get("result", {}).get("status") == "ok":
                return index, existing
            raise RuntimeError(f"An incomplete receipt needs inspection before resuming: {receipt_path}")
        LOG.info("%s %d/%d %s starting", side, index + 1, len(inputs["recordings"]), row["recording_id"])
        with (work / "logs" / f"{side}-{index:04d}.log").open("w", encoding="utf-8") as stream:
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--work-dir", str(work),
                 "--run-side", side, "--source-root", str(source), "--index", str(index)],
                cwd=source, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True,
            )
        return index, json.loads(receipt_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run_one, index, row) for index, row in enumerate(inputs["recordings"])]
        for future in as_completed(futures):
            index, item = future.result()
            LOG.info("%s %s complete: marker planning + worker %.3f s; worker %.3f s", side, item["recording_id"],
                     item["total_seconds"], item["processing_seconds"])
            _write_json(work / "progress.json", {"side": side, "recording_index": index,
                                                "recording_id": item["recording_id"]})
    return time.perf_counter() - started


def _finish_comparison(work: Path) -> dict:
    inputs = json.loads((work / "inputs.json").read_text(encoding="utf-8"))
    sides = {}
    for side in ("old", "new"):
        rows = [json.loads((work / "receipts" / f"{side}-{i:04d}.json").read_text(encoding="utf-8"))
                for i in range(len(inputs["recordings"]))]
        sides[side] = rows
        if side == "new":
            # Source/copy verification is outside all conversion/processing phase timers.
            for index, (row, item) in enumerate(zip(inputs["recordings"], rows, strict=True)):
                if _sha256(Path(row["file"])) != row["sha256"]:
                    raise RuntimeError(f"Original recording changed: {row['recording_id']}")
                copied = Path(item["bids_conversion"]["bids_path"])
                preserved = _sha256(copied) == row["sha256"]
                item["bids_conversion"]["native_bdf_sha256_preserved"] = preserved
                if not preserved:
                    raise RuntimeError(f"BDF bytes changed during import: {row['recording_id']}")
                _write_json(work / "receipts" / f"new-{index:04d}.json", item)
        _write_json(work / f"{side}-receipt.json", {"side": side, "participants": rows, "qc_disabled": True})
    result = _compare(work)
    result["recordings"] = len(inputs["recordings"])
    result["participants"] = len({row["participant"] for row in inputs["recordings"]})
    result["dataset"] = inputs["project_name"]
    result["native_bdf_bytes_total"] = sum(row["size_bytes"] for row in inputs["recordings"])
    result["source_manifest_unchanged"] = (
        _sha256(Path(inputs["project_root"]) / "project.json") == inputs["manifest_sha256"]
    )
    if not result["source_manifest_unchanged"]:
        result["failures"].append({"error": "Original project manifest changed during comparison."})
        result["passed"] = False
    for side, rows in sides.items():
        result[f"{side}_required_marker_planning_seconds_total"] = sum(row["preflight_seconds"] for row in rows)
        result[f"{side}_total_seconds"] = sum(row["total_seconds"] for row in rows)
    result["new_total_seconds"] += result["conversion_wall_seconds_total"]
    timings_path = work / "phase-timings.json"
    if timings_path.is_file():
        result["phase_wall_timings"] = json.loads(timings_path.read_text(encoding="utf-8"))
    result["timing_definition"] = {
        "conversion_seconds": "BIDS copy/metadata/publication, excluding source/output integrity hashing.",
        "conversion_wall_seconds": "Complete initial import including identity and integrity checks.",
        "processing_seconds": "Full per-recording worker: loading, preprocessing, epochs, FFT, exports; optional QC off.",
        "total_seconds": "Sum of recording times: initial BIDS import (new only), required marker planning, and full worker; concurrent times overlap.",
        "phase_wall_timings": "Actual elapsed conversion/old/new processing phases; worker phases include subprocess startup. New end-to-end wall adds initial import phase.",
        "excluded": "Python startup/imports, initial source hashing, post-run integrity checks, output comparison.",
    }
    result["limitations"] = [
        "One run per route; operating-system disk caches were not flushed.",
        "All optional/manual QC, interpolation and exclusions disabled; saved scientific filtering and reference settings retained.",
        "Per-recording processing and exports only; no group Stats or GUI workflows.",
        "MNE imports/process startup and diagnostic integrity/output comparison are excluded from total_seconds.",
        "BIDS cache artifacts are inventoried separately from existing scientific outputs.",
    ]
    _write_json(work / "comparison.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--baseline-ref", default="da14edaa")
    parser.add_argument("--limit", type=int, help="Optional pilot recording count; default processes every registered recording.")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent isolated recording workers, identical for each route.")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Resume completed per-recording receipts without reprocessing them.")
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument("--run-side", choices=("old", "new"), help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--index", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    work = args.work_dir.resolve()
    if args.compare_only:
        return 0 if _finish_comparison(work)["passed"] else 1
    if args.run_side:
        _run_recording(args.source_root.resolve(), work, args.run_side, args.index)
        return 0
    repo = Path(__file__).resolve().parents[2]
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.resume:
        inputs = json.loads((work / "inputs.json").read_text(encoding="utf-8"))
        baseline = work / "baseline-source"
    else:
        if args.project_root is None:
            parser.error("--project-root is required for a new comparison")
        project_root = args.project_root.resolve(strict=True)
        if work in (project_root, repo):
            parser.error("--work-dir must be a new diagnostic subdirectory")
        work.mkdir(parents=True, exist_ok=False)
        inputs = _capture_inputs(repo, project_root, args.limit)
        inputs["baseline_commit"] = subprocess.check_output(
            ["git", "rev-parse", args.baseline_ref], cwd=repo, text=True,
        ).strip()
        inputs["workers"] = args.workers
        _write_json(work / "inputs.json", inputs)
        baseline = _baseline(repo, work, inputs["baseline_commit"])
        for name in ("old", "new", "receipts", "logs"):
            (work / name).mkdir()
    if args.prepare_only:
        LOG.info("Prepared %d recordings at %s", len(inputs["recordings"]), work)
        return 0
    started = time.perf_counter()
    phases = {"workers": inputs["workers"], "resume": args.resume}
    phases["initial_bids_import_seconds"] = _prepare_imports(repo, work, inputs, resume=args.resume)
    _write_json(work / "phase-timings.json", phases)
    for side, source in (("old", baseline), ("new", repo)):
        phases[f"{side}_processing_seconds"] = _run_phase(
            work, source, side, inputs, workers=inputs["workers"], resume=args.resume,
        )
        _write_json(work / "phase-timings.json", phases)
    phases["new_end_to_end_seconds"] = phases["initial_bids_import_seconds"] + phases["new_processing_seconds"]
    _write_json(work / "phase-timings.json", phases)
    run_wall_seconds = time.perf_counter() - started
    result = _finish_comparison(work)
    result["diagnostic_subprocess_wall_seconds"] = run_wall_seconds
    _write_json(work / "comparison.json", result)
    LOG.info("Comparison passed=%s; receipt=%s", result["passed"], work / "comparison.json")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
