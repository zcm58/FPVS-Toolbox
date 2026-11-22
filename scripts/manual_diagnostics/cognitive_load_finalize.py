"""Finalize headless processing through native QC, release, and harmonics.

Uses the same GUI-neutral service sequence as PostProcessingPipelineWorker.
Pending interpolation-burden or frequency-domain findings stop execution and
are exported for an actual decision. This script never creates review decisions
or changes scientific settings. Run the paired-analysis exporter separately
after this receipt reports ``complete``.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any


LOG = logging.getLogger(__name__)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"nonfinite_float": repr(value)}
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if type(value).__module__.startswith("numpy") and hasattr(value, "tolist"):
        return _json_value(value.tolist())
    raise TypeError(f"Unsupported receipt value: {type(value).__qualname__}")


def finalize(project_root: Path, receipt: dict[str, Any]) -> int:
    """Run production services; return 3 for a genuine pending QC review."""
    from Main_App.io import xlsx_read_cache_scope
    from Main_App.processing.artifact_freshness import (
        activate_selection_freshness,
        load_active_selection_fingerprint,
    )
    from Main_App.processing.condition_interpolation_state import (
        require_no_pending_condition_interpolation,
    )
    from Main_App.processing.frequency_domain_qc import (
        mark_frequency_domain_outputs_current,
        mark_frequency_domain_outputs_stale,
        resolve_frequency_qc_coverage_decisions,
        run_frequency_domain_qc_review,
        sync_frequency_domain_qc_automatic_state,
    )
    from Main_App.processing.full_fft_provenance import (
        require_current_project_pre_review_geometry,
        write_project_full_fft_provenance,
    )
    from Main_App.processing.harmonic_selection_qc import (
        run_processing_harmonic_selection_qc,
    )
    from Main_App.processing.interpolation_burden_review import (
        collect_interpolation_burden_review,
    )
    from Main_App.processing.post_processing_context import (
        post_processing_validation_scope,
    )
    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.processing.recording_condition_outcomes import (
        load_recording_condition_outcomes,
        require_pre_review_readiness,
    )
    from Main_App.processing.roi_coverage import (
        build_final_roi_coverage,
        build_pre_review_roi_coverage,
        record_final_release_readiness,
    )
    from Main_App.projects import (
        Project,
        load_project_dataset_index,
        normalize_frequency_protocol,
    )

    project = Project.load(project_root)
    require_no_pending_condition_interpolation(project_root)
    ledger = load_ledger(project_root)
    burden = collect_interpolation_burden_review(project, ledger=ledger)
    receipt["interpolation_burden_review"] = burden
    if burden.requires_review:
        receipt["status"] = "interpolation_burden_review_required"
        return 3

    previous_fingerprint = load_active_selection_fingerprint(project_root)
    provenance_published = False
    try:
        with xlsx_read_cache_scope(), post_processing_validation_scope():
            receipt["stage"] = "output_readiness"
            outcomes = load_recording_condition_outcomes(ledger)
            if outcomes is None:
                raise RuntimeError("Processing has no recording-condition outcome ledger.")
            require_pre_review_readiness(outcomes)
            index = load_project_dataset_index(project_root)
            require_current_project_pre_review_geometry(project_root, dataset_index=index)

            receipt["stage"] = "pre_review_coverage"
            pre_coverage = build_pre_review_roi_coverage(
                project, outcome_ledger=outcomes, processing_ledger=ledger, persist=True,
            )
            receipt["stage"] = "frequency_domain_qc"
            qc = run_frequency_domain_qc_review(
                project, log_func=LOG.info, dataset_index=index,
            )
            receipt["frequency_domain_qc"] = qc
            if qc.get("review_required"):
                receipt["status"] = "frequency_domain_qc_review_required"
                return 3
            sync_frequency_domain_qc_automatic_state(project_root, qc)

            receipt["stage"] = "final_release"
            decisions = resolve_frequency_qc_coverage_decisions(project_root)
            if not decisions.review_complete:
                raise RuntimeError("Final release requires a current completed frequency review.")
            coverage = build_final_roi_coverage(
                project, outcome_ledger=outcomes, frequency_decisions=decisions,
                pre_review_coverage=pre_coverage, persist=True,
            )
            receipt["final_release"] = record_final_release_readiness(
                project_root, outcomes, coverage,
                expected_decision_fingerprint=decisions.decision_fingerprint,
            )

            receipt["stage"] = "full_fft_provenance"
            protocol = normalize_frequency_protocol(project.frequency_protocol)
            if not protocol.is_ready:
                raise RuntimeError("Project frequency protocol is incomplete.")
            mark_frequency_domain_outputs_current(project_root)
            receipt["full_fft_provenance"] = write_project_full_fft_provenance(
                project_root,
                base_frequency_hz=float(protocol.presentation_rate_hz),
                oddball_frequency_hz=float(protocol.oddball_rate_hz),
                frequency_protocol_fingerprint=protocol.fingerprint,
                dataset_index=index,
            )
            provenance_published = True

            receipt["stage"] = "harmonic_selection"
            selection = run_processing_harmonic_selection_qc(
                project, log_func=LOG.info, dataset_index=index,
            )
            receipt["harmonic_selection"] = selection
            receipt["selection_freshness"] = activate_selection_freshness(
                project_root, selection.selection_metadata,
                previous_fingerprint=previous_fingerprint,
                selection_summary_path=selection.workbook_path,
            )
    except Exception:
        if not provenance_published:
            mark_frequency_domain_outputs_stale(
                project_root,
                reason=f"Headless finalization failed during {receipt.get('stage')}.",
            )
        raise
    receipt["status"] = "complete"
    receipt["stage"] = "complete"
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--config-home", type=Path)
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve(strict=True)
    manifest = project_root / "project.json"
    if not manifest.is_file():
        parser.error("--project-root must contain project.json")
    config_home = (
        args.config_home
        if args.config_home is not None
        else project_root / ".fpvs_processing" / "headless_config"
    ).resolve()
    config_home.mkdir(parents=True, exist_ok=True)
    os.environ["FPVS_CONFIG_HOME"] = str(config_home)
    os.environ.setdefault("MPLBACKEND", "Agg")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    started = datetime.now(UTC)
    receipt_dir = project_root / "Quality Check" / "Headless Cognitive Load"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    target = receipt_dir / f"finalize_{started.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    receipt: dict[str, Any] = {
        "schema": "cognitive_load_finalize_v1",
        "started_at": started.isoformat(),
        "project_root": str(project_root),
        "config_home": os.environ.get("FPVS_CONFIG_HOME"),
        "manifest_before_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "review_decisions_created": False,
        "status": "running",
    }
    try:
        code = finalize(project_root, receipt)
    except Exception as exc:
        LOG.exception("headless_finalization_failed")
        receipt.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        code = 1
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    receipt["manifest_after_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with target.open("x", encoding="utf-8") as stream:
        json.dump(_json_value(receipt), stream, indent=2, allow_nan=False)
        stream.write("\n")
    LOG.info("headless_finalization status=%s receipt=%s", receipt["status"], target)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
