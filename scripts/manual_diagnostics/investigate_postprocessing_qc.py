"""Read-only postprocessing QC stage profiler; never starts Qt.

Run with the repository environment, a project root, and an isolated output
directory. Coverage persistence is explicitly disabled. An audit hook rejects
every project write, including attempted cache publication. This is a backend
stage measurement, not a measurement of the GUI or the whole pipeline.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import contextmanager, nullcontext
import cProfile
import hashlib
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
import threading
import time


def load_frozen_audit_parser(repo: Path, ref: str, qc):
    """Load only the reviewed parser/helpers/constants from an exact git commit."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=repo, text=True,
    ).strip()
    relative_path = "src/Main_App/processing/frequency_domain_qc.py"
    source = subprocess.check_output(
        ["git", "show", f"{commit}:{relative_path}"], cwd=repo, text=True,
        encoding="utf-8",
    )
    names = {
        "_read_bca_method_audit_rows", "_exact_frequency_column",
        "_optional_cell_text", "_normalize_electrode",
        "SPECTRAL_METRIC_QC_SHEET_NAME", "_BCA_AUDIT_REQUIRED_COLUMNS",
    }
    selected, found = [], set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            matches = {target.id for target in node.targets if isinstance(target, ast.Name)} & names
            if matches:
                selected.append(node)
                found.update(matches)
    if found != names:
        raise ValueError(f"Baseline {commit} lacks parser dependencies: {sorted(names - found)}")
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *selected,
    ], type_ignores=[])
    namespace = dict(vars(qc))
    exec(compile(ast.fix_missing_locations(module), f"{commit}:{relative_path}", "exec"), namespace)
    return namespace["_read_bca_method_audit_rows"], {
        "requested_ref": ref, "commit": commit,
        "module_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "selected_ast_sha256": hashlib.sha256(ast.dump(module).encode("utf-8")).hexdigest(),
        "frozen_dependencies": sorted(found),
    }


@contextmanager
def installed_audit_parser(qc, parser):
    original = qc._read_bca_method_audit_rows
    qc._read_bca_method_audit_rows = parser
    try:
        yield
    finally:
        qc._read_bca_method_audit_rows = original


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--stage", choices=("review", "exports"), default="review")
    comparison = parser.add_mutually_exclusive_group()
    comparison.add_argument("--audit-candidate", type=Path,
                            help="Isolated prototype module exposing install(); never edits runtime files")
    comparison.add_argument("--baseline-ref",
                            help="Pair the frozen audit parser at this git commit with current production")
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    root = args.project.resolve(strict=True)
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("Diagnostic output must be outside the project.")
    if (output / "results.json").exists():
        parser.error("Use a new diagnostic output directory.")
    output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "src"))
    sys.dont_write_bytecode = True
    for name in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    counts: Counter = Counter()
    blocked: list[str] = []
    root_key = os.path.normcase(str(root))

    def inside(path: object) -> bool:
        if not isinstance(path, (str, bytes, os.PathLike)):
            return False
        name = os.path.normcase(os.path.abspath(os.fsdecode(path)))
        return name == root_key or name.startswith(root_key + os.sep)

    def audit(event: str, values: tuple) -> None:
        if event == "open" and inside(values[0]):
            mode, flags = values[1:3]
            if (mode and any(c in mode for c in "wax+")) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            ):
                blocked.append(event)
                raise RuntimeError("Diagnostic blocked a project write")
            path = Path(os.fsdecode(values[0]))
            counts[f"open:{path.suffix}"] += 1
            if path.name == "project.json":
                counts["open:project.json"] += 1
        if event in {
            "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod",
            "os.utime", "os.link", "os.symlink",
        } and any(inside(v) for v in values[:2]):
            if event == "os.mkdir" and Path(values[0]).is_dir():
                return
            blocked.append(event)
            raise RuntimeError("Diagnostic blocked project mutation: " + event)

    sys.addaudithook(audit)
    import numpy as np
    import pandas as pd
    import psutil
    import scipy
    from threadpoolctl import threadpool_info
    from Main_App.io import xlsx_read_cache_scope
    from Main_App.processing import frequency_domain_qc as qc
    from Main_App.processing.full_fft_provenance import (
        require_current_project_pre_review_geometry,
    )
    from Main_App.processing.post_processing_context import post_processing_validation_scope
    from Main_App.processing.processing_ledger import load_ledger
    from Main_App.processing.provisional_harmonic_cache import ProvisionalHarmonicCache, _digest
    from Main_App.processing.recording_condition_outcomes import (
        load_recording_condition_outcomes, require_pre_review_readiness,
    )
    from Main_App.processing.roi_coverage import (
        build_pre_review_roi_coverage, require_project_final_release,
    )
    from Main_App.projects import Project, load_project_dataset_index
    from Tools.Stats.analysis.canonical_harmonics import load_project_processing_harmonics
    from Tools.Stats.io.stats_ready_export import prepare_stats_ready_export

    original_digest = hashlib.file_digest

    def counted_digest(stream, *a, **kw):
        counts["file_digest_calls"] += 1
        try:
            counts["file_digest_bytes"] += os.fstat(stream.fileno()).st_size
        except (OSError, AttributeError):
            pass
        return original_digest(stream, *a, **kw)

    hashlib.file_digest = counted_digest
    stage_logs: list[dict] = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.name.startswith("Main_App.processing"):
                if "stage_complete" in record.msg:
                    stage_logs.append({"stage": record.stage, "elapsed_s": record.elapsed_s})
                elif "provisional_cache status=" in record.msg:
                    counts[f"provisional:{record.args[0]}"] += 1

    capture = Capture()
    logging.getLogger("Main_App.processing").addHandler(capture)
    logging.getLogger("Main_App.processing").setLevel(logging.INFO)
    project = Project.load(root)
    manifest_sha = hashlib.sha256((root / "project.json").read_bytes()).hexdigest()
    timings: dict[str, float] = {}

    @contextmanager
    def timed(name):
        started = time.perf_counter()
        yield
        timings[name] = time.perf_counter() - started

    def review_operation(cache):
        with timed("readiness"):
            ledger = load_ledger(root)
            outcomes = load_recording_condition_outcomes(ledger)
            if outcomes is None:
                raise RuntimeError("No current recording-condition ledger")
            require_pre_review_readiness(outcomes)
        with timed("dataset_index"):
            index = load_project_dataset_index(root)
        with timed("geometry"):
            require_current_project_pre_review_geometry(root, dataset_index=index)
        with timed("coverage_no_persistence"):
            coverage = build_pre_review_roi_coverage(
                project, outcome_ledger=outcomes, processing_ledger=ledger, persist=False,
            )
        with timed("frequency_review"):
            report = qc.run_frequency_domain_qc_review(
                project, dataset_index=index, provisional_cache=cache,
            )
        return {
            "report": report, "coverage_fingerprint": coverage.fingerprint,
            "outcome_fingerprint": outcomes.fingerprint,
        }

    def export_operation(_cache):
        with timed("index_and_release"):
            index = load_project_dataset_index(root)
            rois = require_project_final_release(root)[1].roi_snapshot.as_mapping()
        with timed("accepted_selection"):
            canonical = load_project_processing_harmonics(project_root=root, log_func=lambda _: None)
        with timed("stats_preparation"):
            result = prepare_stats_ready_export(
                subjects=list(index.participant_ids), conditions=list(index.conditions),
                subject_data=index.subject_data(), base_freq=canonical.metadata["base_frequency_hz"],
                rois=rois, dv_policy=None,
                group_map=index.participant_group_id_map(uppercase_keys=True, include_legacy_aliases=True),
                group_label_map=index.participant_group_label_map(uppercase_keys=True, include_legacy_aliases=True),
                log_func=lambda _: None, save_path=None, max_freq=None,
                selection_conditions=list(index.conditions), project_root=str(root),
            )
        return result

    operation = review_operation if args.stage == "review" else export_operation
    candidate = None
    baseline_parser, baseline_metadata = None, None
    production_source = inspect.getsource(qc._read_bca_method_audit_rows)
    if args.baseline_ref:
        baseline_parser, baseline_metadata = load_frozen_audit_parser(repo, args.baseline_ref, qc)
    if args.audit_candidate:
        spec = importlib.util.spec_from_file_location("qc_audit_candidate", args.audit_candidate.resolve())
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
    qc._now_utc_iso = lambda: "2026-09-08T00:00:00Z"
    rows: list[dict] = []
    reference = None
    process = psutil.Process()

    def measure(label, cache, *, profiled=False):
        nonlocal reference
        counts.clear()
        stage_logs.clear()
        timings.clear()
        stop = threading.Event()
        rss = [process.memory_info().rss]

        def sample():
            while not stop.wait(0.02):
                rss.append(process.memory_info().rss)

        sampler = threading.Thread(target=sample, daemon=True)
        if not profiled:
            sampler.start()
        profiler = cProfile.Profile()
        started = time.perf_counter()
        cpu = time.process_time()
        try:
            result = profiler.runcall(operation, cache) if profiled else operation(cache)
        finally:
            elapsed = time.perf_counter() - started
            cpu_s = time.process_time() - cpu
            stop.set()
            if not profiled:
                sampler.join()
            rss.append(process.memory_info().rss)
        if args.stage == "review":
            # The frozen generated_at is the sole report field normalized.
            value = result
            digest = _digest(value)
            if reference is not None and digest != reference:
                raise AssertionError("Ordered full review payload changed")
            reference = digest
            detail = {
                "flags": len(result["report"]["flags"]),
                "review_required": result["report"]["review_required"],
                "subjects": len(result["report"]["subjects"]),
                "conditions": len(result["report"]["conditions"]),
            }
        else:
            digest_parts = []
            if reference is not None:
                assert tuple(result.frames) == tuple(reference)
            for name, frame in result.frames.items():
                if reference is not None:
                    pd.testing.assert_frame_equal(frame, reference[name], check_exact=True)
                for col in frame.columns:
                    array = frame[col].to_numpy()
                    if array.dtype.kind in "biufc":
                        if reference is not None:
                            assert array.tobytes() == reference[name][col].to_numpy().tobytes()
                        digest_parts.append((name, str(col), array.dtype.str, array.shape,
                                             hashlib.sha256(array.tobytes()).hexdigest()))
            if reference is None:
                reference = result.frames
            digest = hashlib.sha256(json.dumps(digest_parts).encode()).hexdigest()
            detail = {"rows": result.row_count}
        row = {
            "label": label, "profiled": profiled, "elapsed_s": elapsed, "cpu_s": cpu_s,
            "rss_measurement": "start_end_only" if profiled else "20ms_process_samples",
            "rss_start_mib": rss[0] / 2**20, "rss_peak_mib": max(rss) / 2**20,
            "counts": dict(counts), "stages": dict(timings), "qc_stages": list(stage_logs),
            "result_sha256": digest, **detail,
        }
        rows.append(row)
        if profiled:
            profiler.dump_stats(str(output / f"{label}.prof"))
            functions = [
                {"file": key[0], "line": key[1], "name": key[2],
                 "calls": value[1], "self_s": value[2], "cum_s": value[3]}
                for key, value in pstats.Stats(profiler).stats.items()
            ]
            (output / f"{label}-functions.json").write_text(json.dumps(
                sorted(functions, key=lambda x: x["cum_s"], reverse=True), indent=2,
            ), encoding="utf-8")
        print(json.dumps(row), flush=True)

    try:
        for trial in range(1 if args.profile else args.trials):
            variants = (
                ["baseline", "production"] if baseline_parser is not None
                else ["baseline", "candidate"] if candidate else ["baseline"]
            )
            if trial % 2:
                variants.reverse()
            for variant in variants:
                cache = ProvisionalHarmonicCache()
                parser_scope = (
                    installed_audit_parser(qc, baseline_parser)
                    if variant == "baseline" and baseline_parser is not None
                    else candidate.install() if variant == "candidate" else nullcontext()
                )
                with parser_scope:
                    if args.stage == "review":
                        # New worker scopes for both sides; only explicit evidence survives.
                        for state in ("new_evidence", "reused_evidence"):
                            with xlsx_read_cache_scope(), post_processing_validation_scope():
                                measure(f"{trial}_{variant}_{state}", cache, profiled=args.profile)
                    else:
                        with xlsx_read_cache_scope(), post_processing_validation_scope():
                            for state in ("new_scope", "same_scope"):
                                measure(f"{trial}_{variant}_{state}", cache, profiled=args.profile)
                cache.clear()
                assert not cache._entries
    finally:
        final_sha = hashlib.sha256((root / "project.json").read_bytes()).hexdigest()
        metadata = {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "audit_parser_baseline": baseline_metadata,
            "production_audit_parser_sha256": hashlib.sha256(production_source.encode("utf-8")).hexdigest(),
            "python": sys.version, "platform": platform.platform(), "processor": platform.processor(),
            "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
            "native_pools": threadpool_info(), "os_cache_flushed": False,
            "coverage_persisted": False, "blocked_mutations": blocked,
            "manifest_sha256_before": manifest_sha, "manifest_sha256_after": final_sha,
            "rows": rows,
        }
        (output / "results.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        assert manifest_sha == final_sha
        assert not blocked, "A project write was attempted; exclude this run from performance claims"


if __name__ == "__main__":
    main()
