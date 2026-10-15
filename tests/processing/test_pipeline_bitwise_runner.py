"""Diagnostic observer checks without Qt or project EEG computation."""

from concurrent.futures import ThreadPoolExecutor
import cProfile
import hashlib
import io
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import pstats
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


RUNNER_PATH = Path(__file__).parents[2] / "scripts/manual_diagnostics/pipeline_bitwise_runner.py"


@pytest.fixture
def runner(monkeypatch):
    name = "pipeline_bitwise_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def comparator(monkeypatch):
    spec = importlib.util.spec_from_file_location("pipeline_bitwise_observer_comparator", RUNNER_PATH.with_name("pipeline_bitwise_compare.py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _native_history_fixture(tmp_path):
    from copy import deepcopy

    root = tmp_path / "history_archive"
    evidence = root / "benchmark_evidence"
    evidence.mkdir(parents=True)
    record = {"schema_version": 2, "harmonic_selection_profile": "fixed_preregistered_domain",
              "harmonic_selection_profile_version": "1.0", "input_fingerprint": "b" * 64,
              "selection_fingerprint": "c" * 64, "saved_at": "2026-10-01T00:00:00+00:00",
              "selection_metadata": {"value": -0.0, "condition_companion": {
                  "path": "old_metrics.npz", "sha256": "a" * 64, "size_bytes": 123}}}
    section = {"schema_version": 2, "active": record, "history": []}
    initial = {"tools": {"processing": {"harmonic_selection": section}}}
    before = evidence / "project_before_runner.bin"
    before.write_text(json.dumps(initial))
    final = deepcopy(initial)
    final["tools"]["processing"]["harmonic_selection"]["history"] = [deepcopy(record)]
    owner = root / "project.json"
    owner.write_text(json.dumps(final))
    digest = hashlib.sha256(before.read_bytes()).hexdigest()
    receipt = {"version": "pipeline_bitwise_backend_runner_v1", "status": "pipeline_complete",
               "initial_project_sha256": digest, "initial_project_manifest_preimage": {
                   "path": str(before), "size_bytes": before.stat().st_size, "sha256": digest}}
    (evidence / "run_receipt.json").write_text(json.dumps(receipt))
    return root, owner, record, final, before, receipt


def test_harmonic_history_is_literal_whole_bound_input_and_never_current_authority(comparator, tmp_path):
    root, owner, record, _, _, _ = _native_history_fixture(tmp_path)
    archive = comparator.Archive(root)
    pointer = ("tools", "processing", "harmonic_selection", "history", "0")
    comparator._verify_bindings(record, owner, archive, pointer)
    assert archive.proofs[-1]["kind"] == "literal_native_harmonic_input_history"
    assert archive.proofs[-1]["current_output_authority"] is False
    assert not archive.identity_recipes
    for location in (("tools", "processing", "harmonic_selection", "active"), ("unrelated", "history", "0")):
        assert not comparator._verify_native_harmonic_input_history(record, owner, archive, location)
        descriptor = record["selection_metadata"]["condition_companion"]
        with pytest.raises(comparator.ParityError, match="Missing hash-bound artifact"):
            comparator._verify_bindings(descriptor, owner, comparator.Archive(root), (*location, "condition_companion"))


@pytest.mark.parametrize("mutation", ["source_path", "hash", "size", "timestamp", "float_sign", "type", "frequency", "fingerprint", "order", "schema"])
def test_harmonic_history_rejects_any_typed_input_change(comparator, tmp_path, mutation):
    from copy import deepcopy

    root, owner, record, final, _, _ = _native_history_fixture(tmp_path)
    changed = deepcopy(record)
    if mutation in {"source_path", "hash", "size"}:
        field = {"source_path": "path", "hash": "sha256", "size": "size_bytes"}[mutation]
        changed["selection_metadata"]["condition_companion"][field] = {"path": "other.npz", "sha256": "d" * 64, "size_bytes": 124}[field]
    elif mutation == "timestamp":
        changed["saved_at"] = "2026-10-02T00:00:00+00:00"
    elif mutation == "float_sign":
        changed["selection_metadata"]["value"] = 0.0
    elif mutation == "type":
        changed["selection_metadata"]["value"] = 0
    elif mutation == "frequency":
        changed["selection_metadata"]["included_frequencies"] = [1.2]
    elif mutation == "fingerprint":
        changed["selection_fingerprint"] = "f" * 64
    elif mutation == "order":
        changed = dict(reversed(list(changed.items())))
    else:
        changed["schema_version"] = 3
    final["tools"]["processing"]["harmonic_selection"]["history"][0] = changed
    owner.write_text(json.dumps(final))
    with pytest.raises(comparator.ParityError, match="entire actual input snapshot"):
        comparator._verify_native_harmonic_input_history(changed, owner, comparator.Archive(root),
                                                        ("tools", "processing", "harmonic_selection", "history", "0"))


@pytest.mark.parametrize("defect", ["missing_preimage", "preimage_bytes", "preimage_hash", "receipt_version", "wrong_owner", "bad_index"])
def test_harmonic_history_requires_actual_owner_and_initial_witness(comparator, tmp_path, defect):
    root, owner, record, _, before, receipt = _native_history_fixture(tmp_path)
    pointer = ("tools", "processing", "harmonic_selection", "history", "0")
    if defect == "missing_preimage":
        before.unlink()
    elif defect == "preimage_bytes":
        before.write_bytes(before.read_bytes() + b" ")
    elif defect == "preimage_hash":
        receipt["initial_project_sha256"] = "e" * 64
    elif defect == "receipt_version":
        receipt["version"] = "unsupported"
    elif defect == "wrong_owner":
        assert not comparator._verify_native_harmonic_input_history(record, root / "unrelated.json", comparator.Archive(root), pointer)
        return
    else:
        pointer = (*pointer[:-1], "00")
    (root / "benchmark_evidence/run_receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(comparator.ParityError):
        comparator._verify_native_harmonic_input_history(record, owner, comparator.Archive(root), pointer)


@pytest.mark.parametrize("version", [1, 1.0, True, None, "2.0"])
def test_harmonic_history_rejects_unsupported_native_profile_version_even_when_literal(comparator, tmp_path, version):
    root, owner, record, final, before, receipt = _native_history_fixture(tmp_path)
    record["harmonic_selection_profile_version"] = version
    initial = json.loads(before.read_text())
    initial["tools"]["processing"]["harmonic_selection"]["active"] = record
    final["tools"]["processing"]["harmonic_selection"]["history"] = [record]
    before.write_text(json.dumps(initial))
    owner.write_text(json.dumps(final))
    receipt["initial_project_sha256"] = hashlib.sha256(before.read_bytes()).hexdigest()
    receipt["initial_project_manifest_preimage"].update(sha256=receipt["initial_project_sha256"], size_bytes=before.stat().st_size)
    (root / "benchmark_evidence/run_receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(comparator.ParityError, match="entire actual input snapshot"):
        comparator._verify_native_harmonic_input_history(record, owner, comparator.Archive(root),
                                                        ("tools", "processing", "harmonic_selection", "history", "0"))


def _ram12_trace(populations=(12,)):
    return ("kurtosis_review_process_started files=58 max_workers=12 memory_budget_bytes=90000000000 dynamic_memory=True emergency_reserve_bytes=9000000000\n"
            + "".join(f"kurtosis_review_pool_started max_workers={population} worker_ceiling=12\n" for population in populations)
            + f"kurtosis_review_process_finished files=58 completed=58 max_workers=12 elapsed_seconds=2.000 cancelled=False memory_budget_bytes=90000000000 peak_reserved_bytes=60000000000 peak_in_flight={max(populations)} oversize_fallbacks=0 peak_pool_workers={max(populations)} pool_starts={len(populations)}\n")


@pytest.mark.parametrize("populations", [(12,), (1,), (12, 1, 4)])
def test_ram12_trace_accepts_bounded_dynamic_populations(comparator, tmp_path, populations):
    path = tmp_path / "backend.log"
    path.write_text(_ram12_trace(populations))
    result = comparator._verify_ram12_review_trace(path)
    assert result["pool_populations"] == list(populations)
    assert result["every_admission_snapshot_recorded"] is False


@pytest.mark.parametrize("before,after", [("completed=58", "completed=57"), ("cancelled=False", "cancelled=True"),
    ("dynamic_memory=True", "dynamic_memory=False"), ("pool_starts=1", "pool_starts=2"),
    ("max_workers=12 worker_ceiling", "max_workers=13 worker_ceiling"), ("worker_ceiling=12", "worker_ceiling=11"),
    ("peak_in_flight=12", "peak_in_flight=13"), ("peak_pool_workers=12", "peak_pool_workers=11"),
    ("peak_reserved_bytes=60000000000", "peak_reserved_bytes=-1"), ("dynamic_memory=True", "dynamic_memory=1")])
def test_ram12_trace_rejects_malformed_or_unbounded_facts(comparator, tmp_path, before, after):
    path = tmp_path / "backend.log"
    path.write_text(_ram12_trace().replace(before, after))
    with pytest.raises(comparator.ParityError):
        comparator._verify_ram12_review_trace(path)


@pytest.mark.parametrize("field", ["emergency_reserve_bytes=9000000000", "worker_ceiling=12", "pool_starts=1", "credit_bytes=1"])
@pytest.mark.parametrize("suffix", [".5", "x", " extra=1"])
def test_ram12_trace_rejects_fractional_or_suffixed_terminal_fields(comparator, tmp_path, field, suffix):
    content = _ram12_trace().replace("kurtosis_review_process_finished", "review_scoring_emergency_granted index=0 credit_bytes=1\nkurtosis_review_process_finished")
    path = tmp_path / "backend.log"
    path.write_text(content.replace(field + "\n", field + suffix + "\n"))
    with pytest.raises(comparator.ParityError, match="Malformed RAM12"):
        comparator._verify_ram12_review_trace(path)


def test_cheap_context_predicates_skip_only_nonclaiming_owner_lookups(comparator, tmp_path, monkeypatch):
    owner = tmp_path / "notes.json"
    archive = comparator.Archive(tmp_path)
    original = type(owner).resolve
    calls = []
    def observed(path, *args, **kwargs):
        if path == owner:
            calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(type(owner), "resolve", observed)
    comparator._verify_bindings({"nested": {"value": 1}}, owner, archive, ("ordinary",))
    assert calls == []
    def denied(path, *args, **kwargs):
        if path == owner:
            raise OSError("claimed owner resolution failed")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(type(owner), "resolve", denied)
    with pytest.raises(OSError, match="claimed owner"):
        comparator._verify_bindings({}, owner, archive, ("tools", "condition_electrode_interpolation", "completed", "P1", "outputs", "0"))
    (tmp_path / "project.json").write_text(json.dumps({"recordings": {}}))
    with pytest.raises(OSError, match="claimed owner"):
        comparator._repair_recording_context(archive, owner, (), ("processing_result", "results", "bad", "audit", "condition_electrode_interpolation"))


def test_unprofiled_hooks_leave_environment_and_owners_untouched(runner, tmp_path, monkeypatch):
    monkeypatch.setenv(runner.PROFILE_DIRECTORY_ENV, "unchanged")
    with runner.diagnostic_profile_hooks(False, tmp_path / "profiles"):
        assert os.environ[runner.PROFILE_DIRECTORY_ENV] == "unchanged"
    assert not (tmp_path / "profiles").exists()


def test_array_proof_preserves_native_layout_even_when_values_match(runner):
    import numpy as np

    c_array = np.arange(12, dtype=np.float64).reshape(3, 4)
    f_array = np.asfortranarray(c_array)
    c_proof, f_proof = runner.serialize(c_array), runner.serialize(f_array)
    assert c_proof["array_sha256"] == f_proof["array_sha256"]
    assert c_proof["array_strides"] == [32, 8]
    assert f_proof["array_strides"] == [8, 24]
    assert c_proof["array_c_contiguous"] and not c_proof["array_f_contiguous"]
    assert f_proof["array_f_contiguous"] and not f_proof["array_c_contiguous"]


def test_array_proof_preserves_zero_dimensional_shape(runner):
    import numpy as np

    scalar = np.array(-0.0, dtype=np.float64)
    vector = scalar.reshape(1)
    scalar_proof, vector_proof = runner.serialize(scalar), runner.serialize(vector)
    assert scalar_proof["array_shape"] == []
    assert scalar_proof["array_strides"] == []
    assert vector_proof["array_shape"] == [1]
    assert scalar_proof["array_sha256"] == vector_proof["array_sha256"]


def test_generated_storage_census_excludes_observer_evidence(runner, tmp_path):
    root = tmp_path / "project"
    cache = root / ".fpvs_processing"
    cache.mkdir(parents=True)
    (cache / "prepared.npy").write_bytes(b"12345")
    evidence = root / "benchmark_evidence"
    evidence.mkdir()
    (evidence / "observer.json").write_bytes(b"excluded")
    output = runner.storage_footprint(root, evidence)
    assert output["size_bytes"] == 5
    assert output["file_count"] == 1
    assert output["by_project_top_level"] == {".fpvs_processing": {"file_count": 1, "size_bytes": 5}}


def test_native_proofs_are_deferred_until_the_post_native_observer_phase(runner, tmp_path, monkeypatch):
    calls = []
    native = {"evidence": [-0.0, 1.0]}
    original = runner.serialize
    monkeypatch.setattr(runner, "serialize", lambda value: calls.append(value) or original(value))
    receipt = {}
    runner.defer_native_proof(receipt, "kurtosis_review", native)
    assert not calls
    assert receipt["_deferred_native_proofs"]["kurtosis_review"] is native
    assert "kurtosis_review" not in receipt
    events = tmp_path / "events.jsonl"
    target, compact = tmp_path / "run_receipt.json", tmp_path / "telemetry_core_receipt.json"
    proof = runner.write_native_receipt(receipt, events, target, compact)
    assert "_deferred_native_proofs" not in receipt
    assert "kurtosis_review" not in receipt  # No duplicate serialized proof tree is retained.
    assert json.loads(target.read_text())["kurtosis_review"]["evidence"][0]["float64_bits"] == "8000000000000000"
    assert json.loads(compact.read_text())["observer_full_receipt_proof"] == proof
    assert proof["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert proof["size_bytes"] == target.stat().st_size
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["start", "finish"]
    assert all("excluded_from_processing_time" in row["phase"] for row in rows)


def test_streamed_native_proof_matches_existing_scalar_and_array_recipe(runner):
    from fractions import Fraction
    import numpy as np

    @dataclass
    class Evidence:
        samples: object
        annotation: str

    values = {"recordings": [Evidence(np.asfortranarray(np.arange(12.).reshape(3, 4)), "\u00e9\n\"\\"),
                              np.array(-0.0), np.float32(1.5), float("nan")],
              "fraction": Fraction(1, 6), "unordered": frozenset({"Z", "A"}), "path": Path("a/b")}
    assert json.loads("".join(runner.json_proof_parts(values, native=True))) == runner.serialize(values)


def test_stream_writer_bounds_encoded_chunks_as_proof_size_grows(runner):
    target = io.BytesIO()
    writer = runner.JsonProofWriter(target, buffer_bytes=64)
    writer.value({"evidence": [float(index) for index in range(1000)]}, native=True)
    writer.flush()
    assert writer.size_bytes > 500 * 64
    assert writer.maximum_write_bytes <= 128
    assert not writer.pending
    assert writer.sha256.hexdigest() == hashlib.sha256(target.getvalue()).hexdigest()
    assert len(json.loads(target.getvalue())["evidence"]) == 1000


def test_compact_observer_oracle_validates_every_fact_and_full_proof_before_binding(runner, comparator, tmp_path):
    roots, sources = [], []
    origin = tmp_path / "original_active_root"
    for side, elapsed in (("baseline", 1.0), ("candidate", 20.0)):
        root = tmp_path / side
        evidence = root / "benchmark_evidence"
        evidence.mkdir(parents=True)
        source = tmp_path / (side + "_source")
        source.mkdir()
        roots.append(root)
        sources.append(source)
        (root / "project.json").write_text("{}\n")
        (root / "generated.json").write_text(json.dumps({"elapsed_ms": int(elapsed)}))
        receipt = {"version": "pipeline_bitwise_backend_runner_v1", "source_root": str(source),
                   "project_root": str(origin), "status": "pipeline_complete", "recordings": ["P1"],
                   "normal_pool_max_workers": 2, "requested_worker_policy": "2", "stage_seconds": {"setup": elapsed},
                   "validated_params": {"rejection_z": runner.serialize(3.0)},
                   "final_project_sha256": runner.file_hash(root / "project.json"),
                   "processing_plan": {"fingerprint": "a" * 64},
                   "expected_plan": {"processing_fingerprint": "a" * 64}, "generated_artifact_proof": {},
                   "native_runner_returned_utc": f"2026-01-01T00:00:{int(elapsed):02d}Z"}
        receipt["generated_storage_footprint"] = runner.storage_footprint(root, evidence)
        runner.defer_native_proof(receipt, "kurtosis_review", {"scientific_evidence": [-0.0, 1.5]})
        runner.defer_native_proof(receipt, "processing_result", {"results": [
            {"file": "one-shared-recording.bdf", "timings_ms": {"native_filter": int(elapsed * 1000)},
             "export_timing_records": [{"source": "native", "stage": "fif", "elapsed_ms": int(elapsed * 1000)}]}]})
        runner.write_native_receipt(receipt, evidence / "events.jsonl", evidence / "run_receipt.json",
                                    evidence / "telemetry_core_receipt.json")
    policy = {"baseline_origin_root": str(origin), "candidate_origin_root": str(origin),
              "baseline_source_root": str(sources[0]), "candidate_source_root": str(sources[1])}
    identity = comparator.compare_identity_archives(*roots, policy)
    assert identity["status"] == "passed"
    result = comparator.compare_runtime_metadata(*roots, policy, identity)
    assert result["status"] == "passed"
    assert not result["scientific_fingerprint_fields_dropped"]
    assert any(row["kind"] == "verified_complete_native_receipt_reference" for row in result["runtime_field_inventory"])
    target = roots[1] / "benchmark_evidence/telemetry_core_receipt.json"
    compact = json.loads(target.read_text())
    changed = {**compact, "normal_pool_max_workers": 3}
    with pytest.raises(comparator.ParityError, match="copied fact differs"):
        comparator._verify_compact_observer_receipt(changed, target, comparator.Archive(roots[1], origin))
    with pytest.raises(comparator.ParityError, match="missing or contain"):
        comparator._verify_compact_observer_receipt({**compact, "invented_fact": True}, target, comparator.Archive(roots[1], origin))
    changed = {**compact, "observer_full_receipt_proof": {**compact["observer_full_receipt_proof"], "sha256": "0" * 64}}
    with pytest.raises(comparator.ParityError, match="checksum/size mismatch"):
        comparator._verify_compact_observer_receipt(changed, target, comparator.Archive(roots[1], origin))
    changed_storage = {**compact["generated_storage_footprint"], "size_bytes": 1}
    with pytest.raises(comparator.ParityError, match="differs from its actual files"):
        comparator._verify_generated_storage_census(changed_storage, comparator.Archive(roots[1], origin))


def test_optional_raw_diagnostic_cache_is_bound_to_native_values_not_just_own_hashes(runner, comparator, tmp_path):
    from copy import deepcopy
    import mne
    from Main_App.processing.preflight_qc_cache import PREFLIGHT_QC_CACHE_METHOD_DIRECTORY, save_preflight_qc_cache
    from Main_App.processing.preflight_qc_reuse import encode_evidence
    from Main_App.processing.qc_review_diagnostics import QC_REVIEW_DIAGNOSTICS_VERSION
    from Main_App.processing.qc_review_diagnostics_cache import _mapping_order

    source = tmp_path / "immutable.bdf"
    source.write_bytes(b"tiny source identity; no EEG read")
    identity = {"path": str(source.resolve()), "size_bytes": source.stat().st_size, "sha256": runner.file_hash(source)}
    report = {"version": QC_REVIEW_DIAGNOSTICS_VERSION, "mne_version": mne.__version__, "authority": "review_only",
              "evaluation_scope": "all_analyzed_occurrences", "signal_stage": "loaded_raw_before_reference",
              "settings": {"threshold": 1.5, "keep_zero": -0.0}, "channels": ["O2"], "sfreq": 2048.0,
              "source_first_samp": 0, "occurrence_count": 1, "localized_events": [{"value": -0.0}]}

    def fingerprint(value):
        core = {key: item for key, item in value.items() if key != "fingerprint"}
        value["fingerprint"] = hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()

    fingerprint(report)
    occurrence = {"start_sample": 16, "stop_sample": 128, "condition_label": "Faces", "occurrence": 0, "occurrence_key": "14:0"}
    inputs = {"file_identity": {"resolved_path": str(source.resolve()), "size": source.stat().st_size,
                                "content_sha256": runner.file_hash(source), "recording_id": "P1__visit"},
              "settings": {"diagnostics": report["settings"], "recording_scope": {"participant_id": "P1", "recording_id": "P1__visit"}},
              "method": {"name": "condition_aware_preflight_qc", "version": PREFLIGHT_QC_CACHE_METHOD_DIRECTORY,
                         "evidence_codec": "typed_float64_v1"},
              "event_plan": {"diagnostic_channels": ["O2"], "sfreq": 2048.0, "first_samp": 0, "occurrences": [occurrence]}}
    native = {"kurtosis_review": {"results": [{"recording_id": "P1__visit", "participant_id": "P1", "path": str(source.resolve()),
                                              "source_identity": identity, "review_diagnostics": {**report, "source_identity": identity}}]},
              "preflight": {"results": [{"recording_id": "P1__visit", "path": str(source.resolve()), "condition_qc": {
                  "scored_source_analysis_span_plan": {"spans": [{"source_coordinates": {"start_relative_sample": 16, "stop_relative_sample": 128},
                                                                "condition_label": "Faces", "repetition_index": 0, "occurrence_key": "14:0"}]}}}]}}
    root = tmp_path / "project"
    root.mkdir()
    path = save_preflight_qc_cache(root, namespace="raw_diagnostics", **inputs,
                                  result={"report": encode_evidence(report), "mapping_order": _mapping_order(report)})
    archive = comparator.Archive(root, root)
    verified = comparator._verify_raw_diagnostics_namespace(native, archive)
    assert set(verified) == {item for item in path.parent.rglob("*") if item.is_file()}
    assert any(row["kind"] == "raw_diagnostic_cache_exact_native_payload" for row in archive.proofs)
    comparator._verify_generated_storage_census(runner.storage_footprint(root, root / "benchmark_evidence"), archive)

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    origin = tmp_path / "original_active_root"
    for side in (baseline, root):
        (side / "project.json").write_text("{}\n")
        (side / ".fpvs_processing").mkdir(exist_ok=True)
        (side / ".fpvs_processing" / "prepared.json").write_text("{}\n")
        evidence = side / "benchmark_evidence"
        evidence.mkdir()
        full = {"version": "pipeline_bitwise_backend_runner_v1", "source_root": str(tmp_path), "project_root": str(origin),
                "status": "pipeline_complete", "recordings": ["P1__visit"], "processing_plan": {"fingerprint": "a" * 64},
                "expected_plan": {"processing_fingerprint": "a" * 64}, "generated_artifact_proof": {},
                "final_project_sha256": runner.file_hash(side / "project.json"),
                "generated_storage_footprint": runner.storage_footprint(side, evidence)}
        for key, value in native.items():
            runner.defer_native_proof(full, key, value)
        runner.write_native_receipt(full, evidence / "events.jsonl", evidence / "run_receipt.json", evidence / "telemetry_core_receipt.json")
    policy = {"baseline_origin_root": str(origin), "candidate_origin_root": str(origin),
              "baseline_source_root": str(tmp_path), "candidate_source_root": str(tmp_path)}
    identity_proof = comparator.compare_identity_archives(baseline, root, policy)
    assert identity_proof["status"] == "passed"
    result = comparator.compare_runtime_metadata(baseline, root, policy, identity_proof)
    assert result["status"] == "passed"
    permitted_counts = [row for row in result["runtime_field_inventory"] if row["kind"] == "exact_native_payload_bound_optional_cache_file_count"]
    assert {row["original"][1][0][1][1] for row in permitted_counts} == {0, len(verified)}

    # Republish a self-consistent native cache envelope with changed scientific
    # data: all its own report/key/result hashes remain valid, but the bridge fails.
    changed = deepcopy(report)
    changed["localized_events"][0]["value"] = 0.0
    fingerprint(changed)
    save_preflight_qc_cache(root, namespace="raw_diagnostics", **inputs,
                           result={"report": encode_evidence(changed), "mapping_order": _mapping_order(changed)})
    with pytest.raises(comparator.ParityError, match="typed payload differs"):
        comparator._verify_raw_diagnostics_namespace(native, comparator.Archive(root, root))

    for label, mutate, expected in (
        ("occurrence", lambda key: key["event_plan"]["occurrences"][0].update(start_sample=17), "occurrences differ"),
        ("grid", lambda key: key["event_plan"].update(sfreq=1024.0), "signal context"),
        ("scope", lambda key: key["settings"]["recording_scope"].update(participant_id="P2"), "recording scope"),
        ("source", lambda key: key["file_identity"].update(content_sha256="0" * 64), "source identity"),
    ):
        altered = deepcopy(inputs)
        mutate(altered)
        other = tmp_path / label
        other.mkdir()
        save_preflight_qc_cache(other, namespace="raw_diagnostics", **altered,
                               result={"report": encode_evidence(report), "mapping_order": _mapping_order(report)})
        with pytest.raises(comparator.ParityError, match=expected):
            comparator._verify_raw_diagnostics_namespace(native, comparator.Archive(other, other))

    save_preflight_qc_cache(root, namespace="raw_diagnostics", **inputs,
                           result={"report": encode_evidence(report), "mapping_order": _mapping_order(report)})
    (path.parent / ".slots" / ("0" * 64 + ".json")).write_text("{}")
    with pytest.raises(comparator.ParityError, match="Unexplained raw diagnostic namespace artifact"):
        comparator._verify_raw_diagnostics_namespace(native, comparator.Archive(root, root))


def test_completed_repair_manifest_in_fresh_clone_keeps_requests_without_reusing_outputs(tmp_path):
    from Main_App.processing import condition_interpolation_state as state
    from Main_App.processing.processing_ledger import raw_file_metadata
    from Main_App.workers import process_runner

    source = tmp_path / "immutable.bdf"
    source.write_bytes(b"same immutable source")
    root = tmp_path / "fresh_project"
    root.mkdir()
    requests = {"Faces": ["O2"]}
    payload = state._empty_state()
    payload["requests"] = {"P1__visit": requests}
    payload["source_identities"] = {"P1__visit": raw_file_metadata(source)}
    payload["completed"] = {"P1__visit": {"request_fingerprint": state.request_fingerprint(requests),
                                           "processing_fingerprint": "previous-native-processing", "outputs": [{"artifact": {"path": "missing.fpvs"}}]}}
    (root / "project.json").write_text(json.dumps({"tools": {state.STATE_KEY: payload}}))
    before = (root / "project.json").read_bytes()
    assert state.active_condition_interpolation_requests(root, current_sources={"P1__visit": str(source)}) == {"P1__visit": requests}
    assert not state.completion_is_current(root, "P1__visit", payload)
    current = process_runner._with_current_condition_repairs({"condition_electrode_interpolation_enabled": False}, root,
                                                           current_sources={"P1__visit": str(source)})
    assert current["condition_electrode_interpolation_requests"] == {"P1__visit": requests}
    assert (root / "project.json").read_bytes() == before
    assert sorted(path.name for path in root.iterdir()) == ["project.json"]


def test_condition_repair_oracle_binds_compact_export_to_full_native_recipe(comparator, tmp_path):
    from copy import deepcopy
    from Main_App.processing.condition_electrode_interpolation import _fingerprint, condition_interpolation_export_provenance
    from Main_App.processing import condition_interpolation_state as state
    from Main_App.io.eeg_geometry import biosemi64_geometry_identity
    from Main_App.processing.analysis_spans import read_source_analysis_span_plan, realize_target_analysis_span_plan
    from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
    from Main_App.projects import FrequencyProtocol, EXPECTED_CYCLES_SOURCE_MANUAL
    import numpy as np

    root = tmp_path / "archive"
    root.mkdir()
    source = tmp_path / "same_recording.bdf"
    source.write_bytes(b"source binding only")
    repair_state = state._empty_state()
    repair_state["requests"] = {"P1__visit": {"Faces": ["O2"]}}
    manifest = {"preprocessing": {"high_pass": 0.1, "experimental_ram_preload": False},
                "recordings": {"P1__visit": {"raw_file": str(source)}}, "tools": {state.STATE_KEY: repair_state}}
    owner = root / "project.json"
    owner.write_text(json.dumps(manifest))
    geometry = biosemi64_geometry_identity(retained_channels=["O1", "O2"])
    protocol = FrequencyProtocol.from_recurrence(10, 5, expected_analyzed_oddball_cycles=10,
                                               expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL)
    events = np.array([[0, 0, 14], *[[100 + n * 50, 0, 55] for n in range(11)]])
    event_plan = plan_preflight_qc_events(events=events, event_map={"Faces": 14}, sfreq=100, n_times=800,
                                        first_samp=0, frequency_protocol=protocol).to_payload()
    source_plan = read_source_analysis_span_plan(event_plan)
    plan = realize_target_analysis_span_plan(source_plan, target_sfreq_hz=100, target_n_times=800, target_first_samp=0)
    span = plan["spans"][0]
    full = {"version": "condition_electrode_interpolation_v1", "status": "completed", "requests": {"Faces": ["O2"]},
            "recording_wide_interpolated_channels": ["O1"], "analysis_span_fingerprint": plan["fingerprint"],
            "geometry_fingerprint": geometry["coordinate_fingerprint"], "retained_scalp_set_fingerprint": geometry["retained_scalp_set_fingerprint"],
            "spans": [{"condition_label": "Faces", "occurrence_key": span["occurrence_key"], "requested_channels": ["O2"],
                       "interpolated_channels": ["O1", "O2"], "target_coordinates": span["target_coordinates"],
                       "source_coordinates": span["source_coordinates"], "span_fingerprint": span["fingerprint"]}]}
    full["fingerprint"] = _fingerprint(full)
    compact = condition_interpolation_export_provenance({"_fpvs_condition_interpolation_provenance": full}, "Faces")

    def native_document(provenance=full, export=compact, condition="Faces"):
        return {"result": {"file": str(source), "interpolated_channels": ["O1"], "geometry": geometry,
                           "condition_electrode_interpolation": provenance,
                           "audit": {"geometry": geometry, "realized_analysis_span_plan": plan, "source_analysis_span_plan": source_plan,
                                     "interpolated_channels": ["O1"],
                                     "condition_electrode_interpolation": provenance}},
                "export_receipt": {"recording_id": "P1__visit", "condition_label": condition, "condition_electrode_interpolation": export}}

    archive = comparator.Archive(root, root)
    ledger_owner = root / ".fpvs_processing" / "processing_ledger.json"
    ledger_owner.parent.mkdir()
    ledger = {"entries": {"P1__visit": {"recording_id": "P1__visit", "raw_file": str(source), "geometry": geometry,
                                        "interpolated_channels": ["O1"], "condition_electrode_interpolation": full}}}
    persisted_ledger = json.loads(json.dumps(ledger, sort_keys=True))
    ledger_owner.write_text(json.dumps(persisted_ledger, sort_keys=True))
    comparator._verify_bindings(persisted_ledger, ledger_owner, archive)
    native = native_document()
    native["result"]["audit"]["geometry"] = json.loads(json.dumps(geometry, sort_keys=True))
    comparator._verify_bindings(native, root / "native.json", archive)
    comparator._verify_span_plan_references(archive)
    assert any(row["kind"] == "condition_repair_compact_full_preimage_binding" for row in archive.proofs)
    assert any(row["kind"] == "persisted_condition_repair_native_full_context_binding" for row in archive.proofs)

    def native_run_document():
        result = deepcopy(native_document()["result"])
        result["audit"]["file"] = source.name
        return {"version": "pipeline_bitwise_backend_runner_v1", "processing_result": {"results": [result]}}

    run_owner = root / "benchmark_evidence" / "run_receipt.json"
    def verify_native_audit(document, archive, owner=run_owner):
        result = document["processing_result"]["results"][0]
        comparator._verify_bindings(result["audit"], owner, archive, ("processing_result", "results", "0", "audit"),
                                    (document, document["processing_result"], result))

    native_run = native_run_document()
    archive = comparator.Archive(root, root)
    verify_native_audit(native_run, archive)
    comparator._verify_span_plan_references(archive)
    assert any(row["kind"] == "native_preproc_audit_basename_context"
               and row["parent_source"] == str(source) and row["recording_id"] == "P1__visit"
               for row in archive.proofs)
    for mutate in (
        lambda value: value["processing_result"]["results"][0]["audit"].update(file="wrong.bdf"),
        lambda value: value["processing_result"]["results"][0]["audit"].update(file="../" + source.name),
        lambda value: value["processing_result"]["results"][0]["audit"].update(file=str(source)),
        lambda value: value["processing_result"]["results"][0].update(file=str(tmp_path / "undeclared" / source.name)),
        lambda value: value["processing_result"]["results"][0].pop("file"),
    ):
        changed_run = native_run_document()
        mutate(changed_run)
        with pytest.raises(comparator.ParityError, match="audit basename"):
            verify_native_audit(changed_run, comparator.Archive(root, root))
    with pytest.raises(comparator.ParityError, match="source path is not declared"):
        verify_native_audit(native_run_document(), comparator.Archive(root, root), root / "native.json")
    changed_run = native_run_document()
    changed_run["processing_result"]["results"][0]["audit"]["source_path"] = source.name
    with pytest.raises(comparator.ParityError, match="source path is not declared"):
        verify_native_audit(changed_run, comparator.Archive(root, root))
    changed_run = native_run_document()
    audit = changed_run["processing_result"]["results"][0]["audit"]
    audit["injected"] = {"file": source.name, "condition_electrode_interpolation": deepcopy(full)}
    with pytest.raises(comparator.ParityError, match="source path is not declared"):
        verify_native_audit(changed_run, comparator.Archive(root, root))
    changed_run = native_run_document()
    changed_run["processing_result"]["results"][0]["audit"]["injected"] = {"condition_electrode_interpolation": deepcopy(full)}
    with pytest.raises(comparator.ParityError, match="source path is not declared"):
        verify_native_audit(changed_run, comparator.Archive(root, root))
    before = state.project_processing_identity(root)
    manifest["preprocessing"]["experimental_ram_preload"] = True
    owner.write_text(json.dumps(manifest))
    assert state.project_processing_identity(root) == before  # Native runtime config is excluded by production.
    manifest["preprocessing"]["high_pass"] = 0.2
    owner.write_text(json.dumps(manifest))
    assert state.project_processing_identity(root) != before

    changed = deepcopy(compact)
    changed["interpolated_channels"] = ["O2"]
    archive = comparator.Archive(root, root)
    comparator._verify_bindings(native_document(export=changed), root / "native.json", archive)
    with pytest.raises(comparator.ParityError, match="exact validated full native provenance"):
        comparator._verify_span_plan_references(archive)
    archive = comparator.Archive(root, root)
    comparator._verify_bindings(native_document(condition="Happy"), root / "native.json", archive)
    with pytest.raises(comparator.ParityError, match="exact validated full native provenance"):
        comparator._verify_span_plan_references(archive)
    changed = deepcopy(full)
    changed["spans"][0]["target_coordinates"]["start_relative_sample"] += 1
    with pytest.raises(comparator.ParityError, match="full provenance fingerprint mismatch"):
        comparator._verify_bindings(native_document(provenance=changed), root / "native.json", comparator.Archive(root, root))
    for label, mutate in (("geometry", lambda value: value.update(geometry_fingerprint="e" * 64)),
                          ("coordinates", lambda value: value["spans"][0]["target_coordinates"].update(start_relative_sample=17)),
                          ("global_bads", lambda value: value["recording_wide_interpolated_channels"].append("O2"))):
        changed = deepcopy(full)
        mutate(changed)
        changed["fingerprint"] = _fingerprint({key: item for key, item in changed.items() if key != "fingerprint"})
        with pytest.raises(comparator.ParityError, match="native context validation failed|global bads differ"):
            comparator._verify_bindings(native_document(provenance=changed), root / "native.json", comparator.Archive(root, root))
    changed_ledger = deepcopy(ledger)
    changed_full = changed_ledger["entries"]["P1__visit"]["condition_electrode_interpolation"]
    changed_full["spans"][0]["target_coordinates"]["start_relative_sample"] += 1
    changed_full["fingerprint"] = _fingerprint({key: item for key, item in changed_full.items() if key != "fingerprint"})
    archive = comparator.Archive(root, root)
    comparator._verify_bindings(changed_ledger, ledger_owner, archive)
    comparator._verify_bindings(native_document(), root / "native.json", archive)
    with pytest.raises(comparator.ParityError, match="exact same-recording native full context"):
        comparator._verify_span_plan_references(archive)
    second_source = tmp_path / "second_recording.bdf"
    second_source.write_bytes(b"second source")
    manifest["recordings"]["P2__visit"] = {"raw_file": str(second_source)}
    owner.write_text(json.dumps(manifest))
    changed = native_document()
    changed["result"]["recording_id"] = "P2__visit"
    with pytest.raises(comparator.ParityError, match="enclosing recording/source identities disagree"):
        comparator._verify_bindings(changed, root / "native.json", comparator.Archive(root, root))
    same_name_source = tmp_path / "other" / source.name
    same_name_source.parent.mkdir()
    same_name_source.write_bytes(b"different source with same basename")
    manifest["recordings"]["P2__visit"]["raw_file"] = str(same_name_source)
    owner.write_text(json.dumps(manifest))
    changed_run = native_run_document()
    changed_run["processing_result"]["results"][0].update(file=str(same_name_source), recording_id="P1__visit")
    with pytest.raises(comparator.ParityError, match="enclosing recording/source identities disagree"):
        verify_native_audit(changed_run, comparator.Archive(root, root))
    manifest["recordings"]["P2__visit"]["raw_file"] = str(source)
    owner.write_text(json.dumps(manifest))
    with pytest.raises(comparator.ParityError, match="Ambiguous declared condition-repair source mapping"):
        verify_native_audit(native_run_document(), comparator.Archive(root, root))
    manifest["recordings"]["P2__visit"]["raw_file"] = str(second_source)
    manifest["tools"][state.STATE_KEY] = state._empty_state()
    owner.write_text(json.dumps(manifest))
    archive = comparator.Archive(root, root)
    comparator._verify_bindings(manifest, owner, archive)
    assert any(row["recipe"] == "condition_repair_project_processing_recipe"
               for rows in archive.identity_recipes.values() for row in rows)


def test_completion_coverage_rejects_valid_unrelated_artifact_and_missing_requested_output(comparator, tmp_path):
    from copy import deepcopy
    import pandas as pd
    from Main_App.io.condition_data import write_condition_companion, condition_companion_identity
    from Main_App.io.spectral_data import write_spectral_companion, spectral_companion_identity
    from Main_App.io.result_manifest import write_result_manifest
    from Main_App.processing import condition_interpolation_state as state
    from Main_App.processing.processing_ledger import raw_file_metadata, save_ledger

    root = tmp_path / "archive"
    root.mkdir()
    source = tmp_path / "source.bdf"
    source.write_bytes(b"immutable source")
    outputs = {}
    for label in ("Faces", "Objects", "Unrelated"):
        path = root / '1 - Excel Data Files' / label / 'Group' / (label + ".fpvs")
        path.parent.mkdir(parents=True)
        frames = {"BCA (uV)": pd.DataFrame({"Electrode": ["O1"], "1.2000_Hz": [-0.0]})}
        descriptor = write_condition_companion(path, frames)
        spectra = {"FullFFT Amplitude (uV)": pd.DataFrame({"Electrode": ["O1"], "0.0000_Hz": [0.0], "1.2000_Hz": [-0.0]})}
        spectral_descriptor = write_spectral_companion(path, spectra)
        write_result_manifest(path, sheet_names=[*frames, *spectra], spectral_companion=spectral_descriptor, condition_companion=descriptor)
        outputs[label] = {"artifact": state.artifact_identity(path, project_root=root),
                          "condition_companion": condition_companion_identity(path), "spectral_companion": spectral_companion_identity(path)}
    requests = {"Faces": ["O2"], "Objects": ["O2"]}
    repair_state = state._empty_state()
    repair_state["requests"] = {"P1": requests}
    repair_state["source_identities"] = {"P1": raw_file_metadata(source)}
    manifest = {"recordings": {"P1": {"raw_file": str(source)}}, "tools": {state.STATE_KEY: repair_state}}
    owner = root / "project.json"
    owner.write_text(json.dumps(manifest))
    completion = {"request_fingerprint": state.request_fingerprint(requests), "processing_fingerprint": "a" * 64,
                  "project_processing_identity": state.project_processing_identity(root), "raw_file_identity": raw_file_metadata(source),
                  "excluded_conditions": [], "outputs": [outputs["Objects"], outputs["Faces"]]}
    repair_state["completed"] = {"P1": completion}
    owner.write_text(json.dumps(manifest))
    cells = [{"processing_id": "P1", "condition_label": label, "export_receipt": {
        "condition_label": label, "path": str(root / outputs[label]["artifact"]["path"]), "status": "written"}}
        for label in ("Faces", "Objects")]
    ledger = {"entries": {"P1": {"processing_fingerprint": "a" * 64}}, "recording_condition_outcomes": {"cells": cells}}
    save_ledger(root, ledger)
    assert state.completion_is_current(root, "P1", repair_state)
    comparator._verify_bindings(manifest, owner, comparator.Archive(root, root))
    sorted_manifest = json.loads(json.dumps(manifest, sort_keys=True))
    owner.write_text(json.dumps(sorted_manifest, sort_keys=True))
    assert state.completion_is_current(root, "P1", sorted_manifest["tools"][state.STATE_KEY])
    comparator._verify_bindings(sorted_manifest, owner, comparator.Archive(root, root))
    changed_output = deepcopy(outputs["Faces"])
    changed_output["spectral_companion"] = outputs["Objects"]["spectral_companion"]
    with pytest.raises(comparator.ParityError, match="native artifact/companion identities"):
        comparator._verify_bindings(changed_output, owner, comparator.Archive(root, root),
                                    ("tools", state.STATE_KEY, "completed", "P1", "outputs", "0"))

    for replacement in ([outputs["Faces"]], [outputs["Faces"], outputs["Unrelated"]]):
        changed = deepcopy(manifest)
        changed["tools"][state.STATE_KEY]["completed"]["P1"]["outputs"] = replacement
        owner.write_text(json.dumps(changed))
        assert state.completion_is_current(root, "P1", changed["tools"][state.STATE_KEY])
        with pytest.raises(comparator.ParityError, match="outputs differ from their same-recording reconciled receipts"):
            comparator._verify_bindings(changed, owner, comparator.Archive(root, root))
    owner.write_text(json.dumps(manifest))
    ledger["recording_condition_outcomes"]["cells"] = cells[:1]
    save_ledger(root, ledger)
    with pytest.raises(comparator.ParityError, match="cover exactly its active native requested cells"):
        comparator._verify_bindings(manifest, owner, comparator.Archive(root, root))


def test_ram_oracle_permits_only_matched_native_storage_leaves_with_bound_input_history(runner, comparator, tmp_path):
    origin, frozen_source = tmp_path / "active", tmp_path / "frozen_source"
    frozen_source.mkdir()
    roots = (tmp_path / "off", tmp_path / "on")
    for flag, root in zip((False, True), roots):
        evidence = root / "benchmark_evidence"
        evidence.mkdir(parents=True)
        manifest = {"recordings": {"P1": {}}, "preprocessing": {"experimental_ram_preload": flag}}
        (root / "project.json").write_text(json.dumps(manifest))
        # Input history may reference prior GUI artifacts; it is not current
        # output authority, and every original field remains in the typed proof.
        history = {**manifest, "prior_completion": {"path": "old_gui_output.fpvs", "sha256": "f" * 64}}
        initial = evidence / "project_before_runner.bin"
        initial.write_bytes(json.dumps(history).encode())
        before = evidence / "project_before_downstream.json"
        before.write_bytes(initial.read_bytes())
        downstream = {"schema": "pipeline_downstream_probe_v1", "status": "complete",
                      "project_manifest_before_sha256": runner.file_hash(before), "project_manifest_after_sha256": runner.file_hash(root / "project.json")}
        (evidence / "downstream_receipt.json").write_text(json.dumps(downstream))
        (evidence / "backend.log").write_text("kurtosis_review_process_started files=1 max_workers=2\n")
        full = {"version": "pipeline_bitwise_backend_runner_v1", "source_root": str(frozen_source), "project_root": str(origin),
                "status": "pipeline_complete", "recordings": ["P1"], "requested_worker_policy": "2", "normal_pool_max_workers": 2,
                "validated_params": {"experimental_ram_preload": flag, "high_pass": runner.serialize(.1)},
                "processing_plan": {"fingerprint": "a" * 64}, "expected_plan": {"processing_fingerprint": "a" * 64},
                "generated_artifact_proof": {}, "final_project_sha256": runner.file_hash(root / "project.json"),
                "initial_project_sha256": runner.file_hash(initial),
                "initial_project_manifest_preimage": {"path": str(origin / "benchmark_evidence" / initial.name),
                                                       "size_bytes": initial.stat().st_size, "sha256": runner.file_hash(initial)}}
        full["generated_storage_footprint"] = runner.storage_footprint(root, evidence)
        runner.write_native_receipt(full, evidence / "events.jsonl", evidence / "run_receipt.json", evidence / "telemetry_core_receipt.json")
    policy = {"baseline_origin_root": str(origin), "candidate_origin_root": str(origin),
              "baseline_source_root": str(frozen_source), "candidate_source_root": str(frozen_source), "comparison_purpose": "ram_preload"}
    identity = comparator.compare_identity_archives(*roots, policy)
    result = comparator.compare_runtime_metadata(*roots, policy, identity)
    assert result["status"] == "passed"
    assert sum(row["kind"] == "matched_native_ram_storage_boolean" for row in result["runtime_field_inventory"]) >= 8
    assert any(row.get("role") == "historical_native_input" for row in result["proofs"])
    for root, flag in zip(roots, (False, True)):
        (root / "unexpected.json").write_text(json.dumps({"nested": {"experimental_ram_preload": flag}}))
        evidence = root / "benchmark_evidence"
        target, compact_path = evidence / "run_receipt.json", evidence / "telemetry_core_receipt.json"
        full = json.loads(target.read_text())
        full["generated_storage_footprint"] = runner.storage_footprint(root, evidence)
        target.write_text(json.dumps(full) + "\n")
        compact = json.loads(compact_path.read_text())
        compact["generated_storage_footprint"] = full["generated_storage_footprint"]
        compact["observer_full_receipt_proof"] = {"path": str(target), "size_bytes": target.stat().st_size, "sha256": runner.file_hash(target)}
        compact_path.write_text(json.dumps(compact) + "\n")
    identity = comparator.compare_identity_archives(*roots, policy)
    with pytest.raises(comparator.ParityError, match="Uncharacterized or contradictory persisted RAM"):
        comparator.compare_runtime_metadata(*roots, policy, identity)
    for root in roots:
        (root / "unexpected.json").unlink()
    (roots[1] / "benchmark_evidence" / "backend.log").write_text("kurtosis_review_process_started files=1 max_workers=3\n")
    with pytest.raises(comparator.ParityError, match="actual fixed-two-worker"):
        comparator._verify_ram_config_scope(roots, (frozen_source, frozen_source))


def test_downstream_observer_captures_existing_native_transition_once_with_exact_timer_gap(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("pipeline_downstream_capture_test", RUNNER_PATH.with_name("pipeline_downstream_probe.py"))
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, probe)
    spec.loader.exec_module(probe)
    workspace, source, scratch = (tmp_path / name for name in ("workspace", "source", "scratch"))
    workspace.mkdir()
    source.mkdir()
    scratch.mkdir()
    root = workspace / "project"
    root.mkdir()
    manifest = {"tools": {"condition_electrode_interpolation": {"requests": {"P1": {"Faces": ["O2"]}}}}}
    (root / "project.json").write_text(json.dumps(manifest))
    config = workspace / "config"
    (config / "settings").mkdir(parents=True)
    (config / "settings/settings.ini").write_text("[frozen]\nvalue=1\n")
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(config))
    for name in ("TEMP", "TMP", "TMPDIR", "MPLCONFIGDIR"):
        monkeypatch.setenv(name, os.environ.get(name, str(tmp_path)))
    monkeypatch.setattr(probe.tempfile, "tempdir", probe.tempfile.tempdir)
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "addaudithook", lambda _hook: None)
    worker_path = source / probe.WORKER_RELATIVE
    worker_path.parent.mkdir(parents=True)
    worker_path.write_bytes(b"transport-only unit fixture\n")
    calls = []

    class Signal:
        def __init__(self):
            self.listeners = []

        def connect(self, callback):
            self.listeners.append(callback)

        def emit(self, *payload):
            for callback in self.listeners:
                callback(*payload)

    class NativeWorker:
        def __init__(self, _project):
            for name in ("progress", "phase_progress", "log_message", "finished"):
                setattr(self, name, Signal())

        def run(self):
            calls.append("existing native run")
            (root / "project.json").write_text(json.dumps({**manifest, "native_stage": "after_repair_guard"}))
            self.phase_progress.emit("frequency_domain_qc", 0, 7, "checking")
            self.phase_progress.emit("frequency_domain_qc", 0, 7, "duplicate transport")
            (root / "project.json").write_text(json.dumps({**manifest, "native_stage": "after_frequency_qc"}))
            self.finished.emit({"ok": True, "steps": []})

    monkeypatch.setattr(probe, "bind_worker", lambda *_args, **_kwargs: (
        NativeWorker, None, {"worker_source_sha256": probe.sha256_bytes(worker_path.read_bytes())}))
    monkeypatch.setattr(probe, "source_inventory", lambda _source: [])
    from Main_App.projects import Project
    monkeypatch.setattr(Project, "load", lambda _root: SimpleNamespace(project_root=root))
    target = workspace / "evidence/downstream_receipt.json"
    args = SimpleNamespace(source_root=source, workspace_root=workspace, project_root=root, scratch_root=scratch,
                           output=target, events=target.with_suffix(".events.jsonl"), benchmark_review_policy=None, expected_worker_sha256=None)
    assert probe.run_probe(args) == 0
    receipt = json.loads(target.read_text())
    assert calls == ["existing native run"]
    assert len(receipt["condition_repair_manifest_preimages"]) == len(receipt["observer_manifest_capture_windows_excluded_from_worker_time"]) == 1
    proof = receipt["condition_repair_manifest_preimages"][0]
    captured = Path(proof["path"])
    assert json.loads(captured.read_bytes())["native_stage"] == "after_repair_guard"
    assert json.loads((root / "project.json").read_bytes())["native_stage"] == "after_frequency_qc"
    assert proof["sha256"] == hashlib.sha256(captured.read_bytes()).hexdigest()
    assert proof["size_bytes"] == captured.stat().st_size
    gap = receipt["observer_manifest_capture_windows_excluded_from_worker_time"][0]
    attempt = receipt["worker_run_attempts"][0]
    assert attempt["observer_manifest_capture_elapsed_seconds_excluded_from_worker_time"] == gap["finish_elapsed_seconds"] - gap["start_elapsed_seconds"]
    assert attempt["worker_run_elapsed_seconds"] == attempt["worker_run_gross_elapsed_seconds"] - attempt["observer_manifest_capture_elapsed_seconds_excluded_from_worker_time"]


def test_marker_replay_keeps_actual_human_receipt_and_rejects_changed_evidence(runner, tmp_path, monkeypatch):
    from Main_App.gui import marker_occurrence_review as markers
    from Main_App.processing import preflight_qc

    @dataclass(frozen=True)
    class Scan:
        results: tuple
        cancelled: bool = False
        project_grid_observations: tuple = ()

    path = tmp_path / "copied.bdf"
    item = SimpleNamespace(path=path, participant_id="P1", recording_id="P1__visit", session_id="visit",
                           session_label="Visit", condition_label="Condition", condition_code=14, repetition_index=0,
                           occurrence_key="14:0", marker_plan_fingerprint="a" * 64, occurrence_fingerprint="b" * 64)
    original = markers.build_marker_review_decision(item, "exclude_occurrence", reason="Existing human reason",
                                                   reviewed_at_utc="2026-01-01T00:00:00Z")
    original["source_file_path"] = str(tmp_path / "original.bdf")
    proof = tmp_path / "evidence" / "actual.json"
    proof.parent.mkdir()
    proof.write_text(json.dumps({"key": {"event_plan": {"approved_occurrences": [{"decision_payload": original}]}}}))
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({"schema": "pipeline_marker_review_replay_v1", "original_decisions": [original],
                                  "source_evidence": [{"frozen_evidence_path": str(proof), "sha256": runner.file_hash(proof)}]}))
    before = Scan((SimpleNamespace(path=path),))
    replaced = Scan((SimpleNamespace(path=path),), project_grid_observations=("native updated grid",))
    monkeypatch.setattr(markers, "collect_marker_occurrence_reviews", lambda _scan: (item,))
    def rescan(infos, params, **kwargs):
        rebound = params["_fpvs_marker_review_decisions_by_file"][str(path.resolve())]["14:0"]
        assert rebound["reviewed_at_utc"] == original["reviewed_at_utc"]
        assert rebound["reason"] == original["reason"]
        assert rebound["source_file_path"] == str(path.resolve())
        return replaced
    monkeypatch.setattr(preflight_qc, "scan_preprocessing_qc", rescan)
    receipt = {}
    output = runner.replay_marker_review(before, [SimpleNamespace(path=path)], {}, tmp_path, {"Condition": 14}, 2, None, replay, receipt)
    assert output.project_grid_observations == replaced.project_grid_observations
    assert receipt["marker_review_replay"]["receipts"][0]["original_receipt"] == original
    assert receipt["marker_review_replay"]["new_human_review"] is False
    item.occurrence_fingerprint = "c" * 64
    with pytest.raises(runner.ReviewRequired, match="evidence changed"):
        runner.replay_marker_review(before, [SimpleNamespace(path=path)], {}, tmp_path, {"Condition": 14}, 2, None, replay, {})
    proof.write_text("corrupted")
    with pytest.raises(ValueError, match="checksum changed"):
        runner.replay_marker_review(before, [SimpleNamespace(path=path)], {}, tmp_path, {"Condition": 14}, 2, None, replay, {})


def test_profile_threads_capture_native_tasks_and_restore_on_error(runner, tmp_path, monkeypatch):
    barrier = threading.Barrier(3)

    def native_task(info):
        barrier.wait(timeout=10)
        return info.value + 1

    native_normal, native_review = lambda: None, lambda _event, _queue: None
    preflight = ModuleType("Main_App.processing.preflight_qc")
    preflight._scan_one_preflight_file = native_task
    normal = ModuleType("Main_App.workers.process_runner")
    normal._worker_init = native_normal
    review = ModuleType("Main_App.workers.kurtosis_review_process")
    review._review_worker_init = native_review
    processing, workers = ModuleType("Main_App.processing"), ModuleType("Main_App.workers")
    processing.preflight_qc = preflight
    workers.process_runner, workers.kurtosis_review_process = normal, review
    monkeypatch.setitem(sys.modules, "Main_App.processing", processing)
    monkeypatch.setitem(sys.modules, "Main_App.workers", workers)
    monkeypatch.setenv(runner.PROFILE_DIRECTORY_ENV, "previous")
    directory = tmp_path / "profiles"
    parent_profiler = cProfile.Profile()
    parent_profiler.enable()
    try:
        with pytest.raises(RuntimeError, match="observer failure"):
            with runner.diagnostic_profile_hooks(True, directory, parent_profiler):
                assert normal._worker_init is runner._profile_normal_worker_init
                assert review._review_worker_init is runner._profile_review_worker_init
                with runner.pause_parent_for_preflight_profile(), ThreadPoolExecutor(max_workers=3) as executor:
                    values = list(executor.map(preflight._scan_one_preflight_file,
                                              [SimpleNamespace(value=index, processing_id=f"P{index}") for index in range(3)]))
                assert values == [1, 2, 3]
                raise RuntimeError("observer failure")
    finally:
        parent_profiler.disable()
    assert preflight._scan_one_preflight_file is native_task
    assert normal._worker_init is native_normal
    assert review._review_worker_init is native_review
    assert os.environ[runner.PROFILE_DIRECTORY_ENV] == "previous"
    profiles = list(directory.glob("preflight_thread-*.pstats"))
    assert len(profiles) == 1
    for path in profiles:
        native_stats = [value for key, value in pstats.Stats(str(path)).stats.items() if key[2] == "native_task"]
        assert len(native_stats) == 1
        # Python3.13's global monitoring-tool owner observes other threads in
        # this bounded window too. Earlier Python versions profile this thread.
        assert native_stats[0][1] >= (3 if sys.version_info >= (3, 13) else 1)
    assert {json.loads(path.read_text())["recording_id"] for path in directory.glob("*.json")} <= {"P0", "P1", "P2"}


def test_spawned_worker_profiles_flush_through_multiprocessing_finalizers(tmp_path):
    """Real spawn/shutdown, with tiny native-owner stubs instead of EEG work."""
    helper = tmp_path / "spawn_profile_smoke.py"
    helper.write_text('''
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import sys
from types import ModuleType

sys.path.insert(0, RUNNER_DIRECTORY)
import pipeline_bitwise_runner as runner

def normal_init():
    os.environ["NATIVE_OWNER_CALLED"] = "normal"

def review_init(event, queue):
    assert event is not None and queue is not None
    os.environ["NATIVE_OWNER_CALLED"] = "review"

main_app, workers = ModuleType("Main_App"), ModuleType("Main_App.workers")
normal, review = ModuleType("Main_App.workers.process_runner"), ModuleType("Main_App.workers.kurtosis_review_process")
normal._worker_init, review._review_worker_init = normal_init, review_init
workers.process_runner, workers.kurtosis_review_process = normal, review
main_app.workers = workers
sys.modules.update({"Main_App": main_app, "Main_App.workers": workers,
                    "Main_App.workers.process_runner": normal,
                    "Main_App.workers.kurtosis_review_process": review})

def tiny_native_work():
    return sum(range(1000)), os.environ["NATIVE_OWNER_CALLED"], os.environ["OMP_NUM_THREADS"]

if __name__ == "__main__":
    directory = Path(sys.argv[1])
    directory.mkdir()
    os.environ[runner.PROFILE_DIRECTORY_ENV] = str(directory)
    os.environ["OMP_NUM_THREADS"] = "23"
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context, initializer=runner._profile_normal_worker_init) as pool:
        assert pool.submit(tiny_native_work).result() == (499500, "normal", "23")
    event, queue = context.Event(), context.Queue()
    with ProcessPoolExecutor(max_workers=1, mp_context=context, initializer=runner._profile_review_worker_init, initargs=(event, queue)) as pool:
        assert pool.submit(tiny_native_work).result() == (499500, "review", "23")
    queue.close()
    queue.join_thread()
'''.replace("RUNNER_DIRECTORY", repr(str(RUNNER_PATH.parent))), encoding="utf-8")
    directory = tmp_path / "profiles"
    subprocess.run([sys.executable, str(helper), str(directory)], check=True, timeout=30,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
    profiles = list(directory.glob("*.pstats"))
    assert len(profiles) == 2
    for path in profiles:
        metadata = json.loads(path.with_suffix(".json").read_text())
        assert metadata["role"] in {"normal_worker", "review_worker"}
        assert metadata["pid"] != os.getpid()
        assert any(key[2] == "tiny_native_work" for key in pstats.Stats(str(path)).stats)
