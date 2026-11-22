"""Set up and process the reviewed cognitive-load Studio project without widgets.

This task-scoped adapter accepts the observed Studio project schema 1.6.0,
not an exported .fpvsconfig. Numerical work, review gates and output ledgers
remain owned by the production Toolbox. All evidence is project-local.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
LOG = logging.getLogger(__name__)
EVIDENCE_FOLDER = Path("Quality Check") / "Headless Cognitive Load"


class ReviewRequired(RuntimeError):
    """The next numerical stage needs a real review or acquisition decision."""


def json_value(value):
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [json_value(item) for item in value]
    if isinstance(value, (Path, Decimal, Fraction)):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if hasattr(value, "to_manifest"):
        return json_value(value.to_manifest())
    return value


def write_evidence(root: Path, name: str, value) -> Path:
    destination = root / EVIDENCE_FOLDER / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(json_value(value), indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    LOG.info("Evidence saved: %s", destination)
    return destination


def studio_evidence(path: Path) -> dict:
    raw = path.read_bytes()
    source = json.loads(raw)
    if source.get("schema_version") != "1.6.0" or source.get("experiment_category") != "cognitive_load_fpvs":
        raise ValueError("This task adapter supports only the reviewed cognitive_load_fpvs Studio project schema 1.6.0.")
    settings = source["settings"]
    conditions = source["conditions"]
    event_map = {row["name"]: int(row["trigger_code"]) for row in conditions}
    if len(event_map) != len(conditions) or len(set(event_map.values())) != len(conditions):
        raise ValueError("Studio condition names and trigger codes must be unique.")
    counts = {(int(row["sequence_count"]), int(row["oddball_cycle_repeats_per_sequence"])) for row in conditions}
    if len(counts) != 1:
        raise ValueError("Mixed planned condition lengths require separate reviewed processing protocols.")
    sequence_count, repeats = counts.pop()
    if sequence_count < 1 or repeats < 1:
        raise ValueError("Studio counts must be positive.")
    return {
        "source_path": str(path.resolve()), "source_sha256": hashlib.sha256(raw).hexdigest(),
        "schema_version": source["schema_version"], "name": source["meta"]["name"],
        "base_hz": settings["protocol"]["base_hz"],
        "oddball_every_n": settings["protocol"]["oddball_every_n"],
        "oddball_trigger_code": settings["triggers"]["oddball_trigger_code"],
        "event_map": event_map, "sequence_count": sequence_count,
        "oddball_cycle_repeats_per_sequence": repeats,
        "planned_presented_oddballs": sequence_count * repeats,
        "maximum_first_to_last_cycles": sequence_count * repeats - 1,
        "session_block_count": settings["session"]["block_count"],
        "extraction": "Direct read of meta.name, settings.protocol, settings.triggers, conditions and settings.session; not a .fpvsconfig import.",
    }


def inspect_sources(args, evidence: dict) -> dict:
    import numpy as np
    from Main_App.io.bdf_format import inspect_bdf_format

    files = sorted(args.source_dir.glob("*.bdf"))
    if not files:
        raise FileNotFoundError(f"No direct-child BDF files in {args.source_dir}")
    rows = []
    onset_codes = set(evidence["event_map"].values())
    labels = {code: label for label, code in evidence["event_map"].items()}
    for path in files:
        source = inspect_bdf_format(path, optional_digital_channels=("Status",))
        signal = next(item for item in source.header.signals if item.label == "Status")
        rate = Fraction(signal.samples_per_record) / Fraction(source.header.record_duration)
        status = np.asarray(dict(source.digital_signals)["Status"], dtype=np.int64)
        low16 = status & 65535
        changed = np.flatnonzero((low16 != 0) & (low16 != np.r_[0, low16[:-1]]))
        events = [(int(sample), int(low16[sample])) for sample in changed]
        onsets = [(sample, code) for sample, code in events if code in onset_codes]
        occurrences = []
        for index, (start, code) in enumerate(onsets):
            stop = onsets[index + 1][0] if index + 1 < len(onsets) else len(status)
            markers = np.array([sample for sample, value in events if start <= sample < stop and value == evidence["oddball_trigger_code"]], dtype=np.int64)
            intervals = np.diff(markers) / float(rate)
            occurrences.append({
                "condition": labels[code], "condition_code": code, "onset_sample": start,
                "onset_seconds": start / float(rate), "boundary_sample": stop,
                "oddball_count": len(markers), "marker_samples": markers.tolist(),
                "first_to_last_seconds": float((markers[-1] - markers[0]) / float(rate)) if len(markers) else None,
                "minimum_interval_seconds": float(intervals.min()) if len(intervals) else None,
                "maximum_interval_seconds": float(intervals.max()) if len(intervals) else None,
                "median_interval_seconds": float(np.median(intervals)) if len(intervals) else None,
            })
        rows.append({
            "source_path": str(path.resolve()), "source_sha256": source.file_sha256,
            "header": source.header, "processing_blockers": source.processing_blockers,
            "sampling_rate_hz": str(rate), "duration_seconds": float(len(status) / rate),
            "event_code_counts": dict(Counter(code for _, code in events)),
            "condition_occurrence_counts": dict(Counter(labels[code] for _, code in onsets)),
            "occurrences": occurrences,
        })
        LOG.info("Inspected %s: %s condition onsets, %s oddball markers", path.name, len(onsets), sum(item["oddball_count"] for item in occurrences))
    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "studio": evidence,
        "interpretation": "Read-only low-16-bit Status transition diagnostic; this does not confirm acquisition hardware or replace canonical production preflight events.",
        "recordings": rows,
    }
    write_evidence(args.project_root, "source_timing_inspection.json", result)
    return result


def setup_project(args, evidence: dict):
    from Main_App.projects import FrequencyProtocol, Project
    from Main_App.projects.preprocessing_settings import new_project_preprocessing_settings
    from Main_App.processing.processing_controller import prepare_raw_registration_review, commit_raw_registration_review
    from Main_App.io.load_utils import read_bdf_sampling_rate_hz

    manifest_path = args.project_root / "project.json"
    if manifest_path.exists():
        project = Project.load(args.project_root)
        if project.input_folder != args.source_dir or project.event_map != evidence["event_map"]:
            raise ValueError("Existing project sources or condition map disagree; refusing to replace them.")
    else:
        rates = tuple({read_bdf_sampling_rate_hz(path) for path in args.source_dir.glob("*.bdf")})
        if not rates:
            raise FileNotFoundError("No BDF inputs found.")
        defaults = new_project_preprocessing_settings()
        protocol = FrequencyProtocol.from_recurrence(
            evidence["base_hz"], evidence["oddball_every_n"],
            oddball_marker_code=evidence["oddball_trigger_code"],
            oddball_marker_code_source="manual",
        ).with_studio_window(evidence["maximum_first_to_last_cycles"], target_sampling_rate_hz=defaults["downsample"])
        protocol = protocol.resolve_analysis_window(target_sampling_rate_hz=defaults["downsample"], source_sampling_rates_hz=rates)
        project = Project.load(args.project_root, manifest={
            "name": evidence["name"], "input_folder": str(args.source_dir),
            "event_map": evidence["event_map"], "frequency_protocol": protocol.to_manifest(),
            "preprocessing": defaults,
        })
        project.save()
        review = prepare_raw_registration_review(project)
        commit_raw_registration_review(project, review)
    if args.hardware_confirmed:
        if not args.hardware_confirmation.strip():
            raise ValueError("--hardware-confirmed requires a recorded --hardware-confirmation statement.")
        project.update_preprocessing({**project.preprocessing, "hardware_platform": "biosemi", "hardware_confirmed": True,
                                      "hardware_selection_source": "user_confirmed"})
        project.save()
        write_evidence(args.project_root, "hardware_confirmation.json", {
            "hardware_platform": "biosemi", "statement": args.hardware_confirmation,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        })
    write_evidence(args.project_root, "studio_import_evidence.json", {
        **evidence, "frequency_protocol": project.frequency_protocol.to_manifest(),
        "hardware_confirmed": project.preprocessing.get("hardware_confirmed", False),
    })
    return project


def processing_settings(project) -> dict:
    from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings, processing_metadata_snapshot, require_removed_electrode_detection_choice_ready
    from Main_App.projects.frequency_protocol import validate_protocol_condition_codes
    pp = normalize_preprocessing_settings(project.preprocessing)
    if pp.get("hardware_platform") != "biosemi" or pp.get("hardware_confirmed") is not True:
        raise ReviewRequired("Confirm BioSemi ActiveTwo64 hardware before production acquisition or processing; this task runner does not infer it from BDF labels.")
    require_removed_electrode_detection_choice_ready(pp)
    protocol = project.frequency_protocol
    if not protocol.is_ready:
        raise ReviewRequired("The project frequency protocol is incomplete.")
    validate_protocol_condition_codes(protocol, project.event_map.values())
    params = dict(pp)
    params.update({
        "project_root": str(project.project_root), "downsample_rate": pp["downsample"],
        "reject_thresh": pp["rejection_z"], "ref_channel1": pp["ref_chan1"], "ref_channel2": pp["ref_chan2"],
        "max_idx_keep": pp["max_chan_idx_keep"], "max_bad_channels_alert_thresh": pp["max_bad_chans"],
        "save_preprocessed_fif": False, "event_id_map": dict(project.event_map),
        "frequency_protocol": protocol, "frequency_protocol_fingerprint": protocol.fingerprint,
        "base_freq": float(protocol.presentation_rate_hz), "oddball_freq": float(protocol.oddball_rate_hz),
        "analysis": {"base_freq": float(protocol.presentation_rate_hz), "oddball_freq": float(protocol.oddball_rate_hz),
                     "frequency_protocol": protocol.to_manifest(), "frequency_protocol_fingerprint": protocol.fingerprint},
        "raw_signal_screening_enabled": project.experimental_qc_settings.raw_signal_screening_enabled,
        "kurtosis_screening_enabled": project.experimental_qc_settings.kurtosis_screening_enabled,
        "raw_spectral_screening": project.experimental_qc_settings.raw_spectral_screening.to_manifest(),
    })
    params.update(processing_metadata_snapshot(pp))
    return params


def preflight(project, params, infos, workers):
    from Main_App.processing.preflight_qc import scan_preprocessing_qc, build_preflight_condition_crop_grid_audit
    from Main_App.gui.marker_occurrence_review import canonical_event_plans_by_file
    scan = scan_preprocessing_qc(infos, params, project_root=project.project_root, event_map=project.event_map,
                                max_workers=workers, progress=lambda message, done, total: LOG.info("%s (%d/%d)", message, done, total))
    write_evidence(project.project_root, "preflight.json", scan)
    blocked = [row for row in scan.results if row.load_error or row.raw_qc_excluded or row.raw_qc_decision_review_required]
    if scan.cancelled or blocked:
        raise ReviewRequired("Preflight has acquisition/raw-QC findings requiring review; see preflight.json.")
    plans = canonical_event_plans_by_file(scan)
    grid = build_preflight_condition_crop_grid_audit(scan)
    write_evidence(project.project_root, "preflight_grid.json", grid)
    if grid.has_unresolved_grid_conflict:
        raise ReviewRequired("Preflight FFT grids disagree; see preflight_grid.json.")
    params["_fpvs_preflight_event_plans_by_file"] = plans
    raw_qc = {row.recording_id or row.participant_id: dict(row.raw_channel_qc)
              for row in scan.results if row.raw_channel_qc is not None}
    return plans, raw_qc


def prepare(project, params, infos, plans, raw_qc, workers):
    from Main_App.processing.kurtosis_review_scan import scan_kurtosis_review, reconcile_kurtosis_review_decisions
    scan = scan_kurtosis_review(infos, params, event_map=project.event_map, reviewed_event_plans_by_file=plans,
                                raw_channel_qc_by_recording=raw_qc, execution_backend="process", max_workers=workers,
                                progress=lambda message, done, total: LOG.info("%s (%d/%d)", message, done, total))
    write_evidence(project.project_root, "kurtosis_preparation.json", scan)
    reconciliation = reconcile_kurtosis_review_decisions(scan, project.preprocessing.get("kurtosis_review_decisions_by_recording", {}),
                                                         kurtosis_auto_interpolate_all=bool(project.preprocessing.get("kurtosis_auto_interpolate_all", False)))
    write_evidence(project.project_root, "kurtosis_pending_review.json", reconciliation)
    if scan.cancelled or scan.errors or reconciliation.pending_items:
        raise ReviewRequired("Kurtosis preparation needs current channel decisions; see kurtosis_pending_review.json. No manual approvals were synthesized.")
    return scan


def process(project, params, infos, plans, workers):
    from Main_App.processing.processing_ledger import classify_processing_inputs, with_processing_choice, PROCESSING_FINGERPRINT_VERSION, output_group_folder_by_file, record_processing_results
    from Main_App.processing.expected_processing_ledger import build_expected_recording_condition_plan, save_expected_recording_condition_plan
    from Main_App.processing.qc_summary_export import export_processing_qc_summary
    from Main_App.processing.interpolation_burden_review import collect_interpolation_burden_review
    from Main_App.processing.condition_interpolation_executor import build_condition_interpolation_run_snapshot
    from Main_App.projects import project_group_context
    from Main_App.workers import RunParams, run_project_parallel

    plan = with_processing_choice(classify_processing_inputs(project, infos, params, project.event_map), "incremental")
    expected = build_expected_recording_condition_plan(
        processing_plan=plan, event_map=project.event_map, frequency_protocol=project.frequency_protocol,
        approved_event_plans=plans, planning_settings=params,
    )
    save_expected_recording_condition_plan(project.project_root, expected)
    settings = dict(params)
    settings.update({"_fpvs_grouped_project": project_group_context(project).has_group_metadata,
                     "_fpvs_processing_fingerprint": plan.fingerprint,
                     "_fpvs_processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                     "_fpvs_expected_plan_run_id": expected.run_id, "_fpvs_expected_plan_fingerprint": expected.fingerprint})
    if settings["_fpvs_grouped_project"]:
        settings["_fpvs_output_group_by_file"] = output_group_folder_by_file(project, infos)
    for key, attribute in (("participant_id", "subject_id"), ("recording_id", "recording_id"),
                           ("session_id", "session_id"), ("session_label", "session_label"),
                           ("visit_index", "visit_index"), ("days_from_baseline", "days_from_baseline"),
                           ("output_stem", "output_stem"), ("group_id", "group")):
        settings[f"_fpvs_{key}_by_file"] = {str(info.path.resolve()): getattr(info, attribute) for info in infos if getattr(info, attribute) is not None}
    excel_root = project.subfolders["excel"]
    settings["_fpvs_condition_interpolation_run_snapshot"] = build_condition_interpolation_run_snapshot(settings, project.event_map, plan, excel_root)
    write_evidence(project.project_root, "processing_plan.json", {"plan": plan, "expected": expected})
    result = run_project_parallel(RunParams(project_root=project.project_root, data_files=list(plan.run_files),
                                           settings=settings, event_map=dict(project.event_map), save_folder=excel_root, max_workers=workers))
    rows = [*result.get("results", []), *result.get("errors", []), *result.get("excluded", [])]
    record_processing_results(project, plan, rows, run_mode="Batch", user_choice="incremental", cancelled=bool(result.get("cancelled")))
    export_processing_qc_summary(project, plan, rows)
    write_evidence(project.project_root, "processing_results.json", result)
    if result.get("status") != "success":
        raise ReviewRequired("Processing did not complete all selected inputs; see processing_results.json.")
    burden = collect_interpolation_burden_review(project)
    write_evidence(project.project_root, "interpolation_burden.json", burden)
    if burden.requires_review:
        raise ReviewRequired("Interpolation burden requires review before downstream publication.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--studio-project", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--stage", choices=("setup", "inspect", "preflight", "prepare", "process"), required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--hardware-confirmed", action="store_true", help="Record an explicitly obtained ActiveTwo64 hardware confirmation during setup.")
    parser.add_argument("--hardware-confirmation", default="", help="The actual user hardware confirmation, retained as evidence.")
    args = parser.parse_args()
    args.source_dir = args.source_dir.resolve(strict=True)
    args.studio_project = args.studio_project.resolve(strict=True)
    args.project_root = args.project_root.resolve()
    if args.project_root == args.source_dir or args.source_dir.is_relative_to(args.project_root):
        raise ValueError("Use a dedicated output project, separate from the raw source directory.")
    if args.workers < 1:
        raise ValueError("--workers must be positive.")
    os.environ["FPVS_CONFIG_HOME"] = str(args.project_root / ".fpvs_processing" / "headless_config")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    evidence = studio_evidence(args.studio_project)
    try:
        if args.stage == "inspect":
            inspect_sources(args, evidence)
            return 0
        if args.stage == "setup":
            project = setup_project(args, evidence)
            inspect_sources(args, evidence)
            LOG.info("Project ready: %s; analyzed duration=%s s", project.project_root, project.frequency_protocol.derived_analyzed_seconds)
            return 0
        from Main_App.projects import Project
        from Main_App.processing.processing_controller import prepare_batch_file_infos
        project = Project.load(args.project_root)
        params = processing_settings(project)
        infos = prepare_batch_file_infos(project)
        plans, raw_qc = preflight(project, params, infos, args.workers)
        if args.stage == "preflight":
            return 0
        prepare(project, params, infos, plans, raw_qc, args.workers)
        if args.stage == "prepare":
            return 0
        process(project, params, infos, plans, args.workers)
        return 0
    except ReviewRequired as exc:
        write_evidence(args.project_root, "review_required.json", {"stage": args.stage, "message": str(exc), "at_utc": datetime.now(timezone.utc).isoformat()})
        LOG.error("%s", exc)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
