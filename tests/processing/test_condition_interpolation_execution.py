"""Headless orchestration checks; real EEG interpolation has separate numeric tests."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import json
from threading import Event
from types import SimpleNamespace

import pytest

from Main_App.processing import condition_interpolation_executor as executor
from Main_App.processing import condition_interpolation_state as state_api
from Main_App.processing.condition_electrode_interpolation import CONDITION_INTERPOLATION_VERSION
from Main_App.processing.processing_ledger import load_ledger, save_ledger, raw_file_metadata


def _project(tmp_path, identity="P01"):
    (tmp_path / "project.json").write_text('{"tools": {"other_tool": {"keep": true}}}')
    raw = tmp_path / "recording.bdf"
    raw.write_bytes(b"original source")
    source = raw_file_metadata(raw)
    save_ledger(tmp_path, {"entries": {identity: {**source, "processing_fingerprint": "processing-1"}}})
    manifest = json.loads((tmp_path / "project.json").read_text())
    decision = {"decision": state_api.REPAIR_DECISION, "recording_id": identity.upper(),
                "participant_id": "P01", "condition": "Faces", "electrode": "O2", "roi": ""}
    report = {"project_root": str(tmp_path), "analysis_fingerprint": "review-1"}
    state_api.queue_condition_interpolation_decisions(manifest, [decision], report)
    state_api.atomic_json(tmp_path / "project.json", manifest)
    return raw, source, decision, report


def test_queue_preserves_canonical_recording_identity_and_deduplicates(tmp_path):
    _raw, _source, decision, report = _project(tmp_path, "p01_visit2")
    manifest = json.loads((tmp_path / "project.json").read_text())
    state_api.queue_condition_interpolation_decisions(manifest, [decision], report)
    state = manifest["tools"][state_api.STATE_KEY]
    assert state["requests"] == {"p01_visit2": {"Faces": ["O2"]}}
    assert set(state["pending"]) == {"p01_visit2"}
    assert len(state["review_decisions"]) == 2
    assert manifest["tools"]["other_tool"] == {"keep": True}


def test_replaced_raw_retires_old_approval_without_losing_audit(tmp_path):
    raw, _source, _decision, _report = _project(tmp_path)
    raw.write_bytes(b"a different recording")
    assert state_api.active_condition_interpolation_requests(tmp_path) == {}
    requests, warnings = state_api.reconcile_condition_interpolation_sources(tmp_path)
    assert requests == {} and len(warnings) == 1
    state = state_api.load_condition_interpolation_state(tmp_path)
    assert state["pending"] == {} and len(state["review_decisions"]) == 1
    assert state["retired_requests"][0]["requests"] == {"Faces": ["O2"]}
    assert state_api.reconcile_condition_interpolation_sources(tmp_path) == ({}, [])
    state_api.require_no_pending_condition_interpolation(tmp_path)


def test_absent_manifest_default_path_does_not_load_processing_io(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "completion_is_current", lambda *_: pytest.fail("unexpected completion work"))
    assert executor.execute_pending_condition_interpolations(tmp_path) is False
    state_api.require_no_pending_condition_interpolation(tmp_path)


@pytest.mark.parametrize("root_exists", [False, True])
def test_absent_manifest_reconciliation_leaves_filesystem_untouched(tmp_path, root_exists):
    root = tmp_path / "unmanaged_project"
    if root_exists:
        root.mkdir()
    assert state_api.reconcile_condition_interpolation_sources(root) == ({}, [])
    assert root.exists() is root_exists
    if root_exists:
        assert list(root.iterdir()) == []


def test_reassigned_source_path_does_not_reuse_old_approval(tmp_path):
    raw, _source, _decision, _report = _project(tmp_path)
    replacement = tmp_path / "replacement.bdf"
    replacement.write_bytes(raw.read_bytes())
    assert state_api.active_condition_interpolation_requests(tmp_path, current_sources={"p01": replacement}) == {}
    requests, warnings = state_api.reconcile_condition_interpolation_sources(tmp_path, current_sources={"P01": replacement})
    assert requests == {} and warnings
    assert raw.exists()


def test_missing_snapshot_requires_normal_processing_and_keeps_request(tmp_path):
    _project(tmp_path)
    with pytest.raises(executor.ConditionInterpolationProcessingRequired, match="Run Processing"):
        executor.execute_pending_condition_interpolations(tmp_path)
    assert state_api.load_condition_interpolation_state(tmp_path)["pending"]


def test_snapshot_preserves_exact_review_inputs_and_rejects_changed_filter(tmp_path):
    _raw, source, _decision, _report = _project(tmp_path)
    settings = {"high_pass": 0.10000000000000003, "reviewed_marker_samples": [101, 1807]}
    executor.persist_condition_interpolation_run_snapshot(tmp_path, {
        "version": executor.SNAPSHOT_VERSION, "settings": settings,
        "event_map": {"Faces": 1}, "save_folder": str(tmp_path / "outputs"),
        "processing_fingerprint": "processing-1",
        "records": [{"processing_id": "P01", "info": {"path": source["raw_file"]}}],
    })
    restored = executor._load_snapshot(tmp_path)
    assert restored["settings"]["high_pass"].hex() == settings["high_pass"].hex()
    assert restored["settings"]["reviewed_marker_samples"] == [101, 1807]
    manifest = json.loads((tmp_path / "project.json").read_text())
    manifest["preprocessing"] = {"high_pass": 0.5}
    state_api.atomic_json(tmp_path / "project.json", manifest)
    with pytest.raises(executor.ConditionInterpolationProcessingRequired):
        executor._load_snapshot(tmp_path)


@dataclass(frozen=True)
class _Cell:
    condition_label: str
    expected_workbook: str
    planned_cell_action: str = "process_condition"


@dataclass(frozen=True)
class _Recording:
    processing_id: str
    cells: tuple


@dataclass(frozen=True)
class _Plan:
    recordings: tuple
    run_id: str = "run-1"
    processing_fingerprint: str = "processing-1"
    processing_fingerprint_version: str = "version-1"


@pytest.mark.parametrize("concurrent_review", [None, "new_recording", "same_recording"])
def test_failed_repair_retries_without_rewriting_other_condition_and_adopts_normal_receipts(
    tmp_path, monkeypatch, concurrent_review,
):
    from Main_App.processing import expected_processing_ledger as expected_api
    from Main_App.processing import recording_condition_outcomes as outcomes_api
    from Main_App.io import condition_data, spectral_data

    _raw, source, decision, report = _project(tmp_path, "p01_visit2")
    output = tmp_path / "1 - Excel Data Files"
    output.mkdir()
    faces, objects = output / "Faces.fpvs", output / "Objects.fpvs"
    faces.write_bytes(b"old Faces")
    objects.write_bytes(b"unchanged Objects exact bytes")
    untouched = (objects.read_bytes(), objects.stat().st_mtime_ns)
    plan = _Plan((_Recording("p01_visit2", (_Cell("Faces", str(faces)), _Cell("Objects", str(objects)))),))
    holder = [plan]
    monkeypatch.setattr(expected_api, "load_expected_recording_condition_plan", lambda *_: holder[0])
    monkeypatch.setattr(expected_api, "save_expected_recording_condition_plan", lambda _root, value: holder.__setitem__(0, value))
    monkeypatch.setattr(condition_data, "condition_companion_identity", lambda _path: None)
    monkeypatch.setattr(spectral_data, "spectral_companion_identity", lambda _path: None)

    def receipt(condition, path, repaired=False):
        row = {"recording_id": "P01_VISIT2", "condition_label": condition, "path": str(path),
               "status": "written", "run_id": plan.run_id, "processing_fingerprint": plan.processing_fingerprint}
        if repaired:
            row["condition_electrode_interpolation"] = {
                "version": CONDITION_INTERPOLATION_VERSION, "status": "completed",
                "requested_channels": ["O2"], "spans": [{"condition_label": condition}],
            }
        return row

    def reconcile(_plan, receipts):
        assert {row["condition_label"] for row in receipts} == {"Faces", "Objects"}
        return SimpleNamespace(to_payload=lambda: {"cells": [
            {"processing_id": "p01_visit2", "condition_label": row["condition_label"], "export_receipt": row}
            for row in receipts]})

    monkeypatch.setattr(outcomes_api, "reconcile_recording_condition_outputs", reconcile)
    monkeypatch.setattr(outcomes_api, "require_pre_review_readiness", lambda *_: None)
    ledger = load_ledger(tmp_path)
    ledger[outcomes_api.RECORDING_CONDITION_OUTCOME_LEDGER_KEY] = {
        **reconcile(plan, [receipt("Faces", faces), receipt("Objects", objects)]).to_payload(),
        "reconciliation_status": "complete",
    }
    save_ledger(tmp_path, ledger)
    executor.persist_condition_interpolation_run_snapshot(tmp_path, {
        "version": executor.SNAPSHOT_VERSION, "settings": {"reviewed_marker_samples": [101, 1807]},
        "event_map": {"Faces": 1, "Objects": 2}, "save_folder": str(output),
        "processing_fingerprint": plan.processing_fingerprint,
        "records": [{"processing_id": "p01_visit2", "info": {"path": source["raw_file"]}}],
    })
    calls = []

    def accept_new_review():
        from Main_App.projects import project_manifest_transaction

        newer = dict(decision)
        if concurrent_review == "new_recording":
            ledger = load_ledger(tmp_path)
            ledger["entries"]["P02"] = {**source, "processing_fingerprint": "processing-1"}
            save_ledger(tmp_path, ledger)
            newer.update(recording_id="P02", participant_id="P02")
        else:
            newer["electrode"] = "P9"
        path = tmp_path / "project.json"
        with project_manifest_transaction(path) as transaction:
            manifest = json.loads(path.read_bytes())
            state_api.queue_condition_interpolation_decisions(manifest, [newer], report)
            transaction.write(manifest)

    def run(_root, snapshot, _record, requests, **_kwargs):
        calls.append(deepcopy(requests))
        assert snapshot["settings"]["reviewed_marker_samples"] == [101, 1807]
        assert requests == {"p01_visit2": {"Faces": ["O2"]}}
        faces.write_bytes(b"repaired Faces")
        if len(calls) == 1:
            raise RuntimeError("simulated export interruption")
        if concurrent_review:
            # A separate writer must be free to accept QC while EEG work runs.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(accept_new_review).result(timeout=10)
        return {"export_receipts": [receipt("Faces", faces, True)]}

    monkeypatch.setattr(executor, "_run_recording", run)
    with pytest.raises(RuntimeError, match="interruption"):
        executor.execute_pending_condition_interpolations(tmp_path)
    assert state_api.load_condition_interpolation_state(tmp_path)["pending"]
    assert (objects.read_bytes(), objects.stat().st_mtime_ns) == untouched
    if concurrent_review:
        with pytest.raises(state_api.ConditionInterpolationStateConflictError, match="preserved"):
            executor.execute_pending_condition_interpolations(tmp_path)
        latest = state_api.load_condition_interpolation_state(tmp_path)
        assert "p01_visit2" in latest["pending"]
        assert "p01_visit2" not in latest["completed"]
        assert len(latest["review_decisions"]) == 2
        if concurrent_review == "new_recording":
            assert latest["requests"]["P02"] == {"Faces": ["O2"]}
            assert "P02" in latest["pending"]
        else:
            assert set(latest["requests"]["p01_visit2"]["Faces"]) == {"O2", "P9"}
        assert (objects.read_bytes(), objects.stat().st_mtime_ns) == untouched
        return
    assert executor.execute_pending_condition_interpolations(tmp_path)
    state_api.require_no_pending_condition_interpolation(tmp_path)
    assert (objects.read_bytes(), objects.stat().st_mtime_ns) == untouched
    assert len(load_ledger(tmp_path)["entries"]["p01_visit2"]["export_receipts"]) == 2
    # Emulate a completed full normal run with no feature completion receipt yet.
    state = state_api.load_condition_interpolation_state(tmp_path)
    baseline = deepcopy(state)
    state["completed"] = {}
    state["pending"]["p01_visit2"] = {}
    state_api.save_condition_interpolation_state(tmp_path, state, expected_state=baseline)
    assert executor.execute_pending_condition_interpolations(tmp_path) is True
    assert executor.execute_pending_condition_interpolations(tmp_path) is False
    assert len(calls) == 2
    state_api.require_no_pending_condition_interpolation(tmp_path)
    faces.write_bytes(b"tampered derivative")
    with pytest.raises(state_api.ConditionInterpolationPendingError):
        state_api.require_no_pending_condition_interpolation(tmp_path)


def test_explicit_exclusions_suspend_repairs_but_missing_inputs_do_not():
    plan = _Plan((_Recording("P01", (_Cell("Faces", "", "exclude_condition"), _Cell("Objects", ""))),))
    requests = {"Faces": ["O2"], "Objects": ["P9"], "Absent": ["P10"]}
    assert state_api.active_condition_requests(plan, "p01", requests) == {"Objects": ["P9"], "Absent": ["P10"]}
    reinstated = replace(plan, recordings=(_Recording("P01", (_Cell("Faces", "path"),)),))
    assert state_api.active_condition_requests(reinstated, "P01", requests) == requests


def test_stale_retirement_cannot_remove_a_newly_accepted_request(tmp_path):
    from Main_App.projects import project_manifest_transaction

    _raw, source, decision, report = _project(tmp_path)
    baseline = state_api.load_condition_interpolation_state(tmp_path)
    retired = deepcopy(baseline)
    retired["requests"].pop("P01")
    retired["pending"].pop("P01")
    ledger = load_ledger(tmp_path)
    ledger["entries"]["P02"] = source
    save_ledger(tmp_path, ledger)
    path = tmp_path / "project.json"
    with project_manifest_transaction(path) as transaction:
        manifest = json.loads(path.read_bytes())
        newer = {**decision, "recording_id": "P02", "participant_id": "P02"}
        state_api.queue_condition_interpolation_decisions(manifest, [newer], report)
        transaction.write(manifest)
    before = path.read_bytes()
    with pytest.raises(state_api.ConditionInterpolationStateConflictError):
        state_api.save_condition_interpolation_state(tmp_path, retired, expected_state=baseline)
    assert path.read_bytes() == before
    assert set(state_api.load_condition_interpolation_state(tmp_path)["requests"]) == {"P01", "P02"}


def test_source_retirement_serializes_with_a_concurrent_qc_acceptance(tmp_path, monkeypatch):
    from Main_App.projects import project_manifest_transaction

    raw, _source, decision, report = _project(tmp_path)
    raw.write_bytes(b"replaced original source")
    other_raw = tmp_path / "P02.bdf"
    other_raw.write_bytes(b"new source")
    ledger = load_ledger(tmp_path)
    ledger["entries"]["P02"] = raw_file_metadata(other_raw)
    save_ledger(tmp_path, ledger)
    checking, release, attempted, published = (Event() for _ in range(4))
    original_source_check = state_api._source_matches_active_path

    def hold_source_check(source, identity, current_sources):
        checking.set()
        assert release.wait(10)
        return original_source_check(source, identity, current_sources)

    def accept_review():
        path = tmp_path / "project.json"
        attempted.set()
        with project_manifest_transaction(path) as transaction:
            manifest = json.loads(path.read_bytes())
            newer = {**decision, "recording_id": "P02", "participant_id": "P02"}
            state_api.queue_condition_interpolation_decisions(manifest, [newer], report)
            transaction.write(manifest)
        published.set()

    monkeypatch.setattr(state_api, "_source_matches_active_path", hold_source_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        retiring = pool.submit(state_api.reconcile_condition_interpolation_sources, tmp_path)
        try:
            assert checking.wait(10)
            accepting = pool.submit(accept_review)
            assert attempted.wait(10)
            assert not published.wait(0.1)
        finally:
            release.set()
        requests, warnings = retiring.result(timeout=10)
        accepting.result(timeout=10)
    assert requests == {} and warnings
    latest = state_api.load_condition_interpolation_state(tmp_path)
    assert latest["requests"] == {"P02": {"Faces": ["O2"]}}
    assert set(latest["pending"]) == {"P02"}
    assert latest["retired_requests"][0]["processing_id"] == "P01"


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_recording_repair_respects_terminal_cleanup_after_successful_file(
    tmp_path, monkeypatch, cleanup_failed,
):
    from Main_App.workers import process_runner

    result = {"status": "ok", "file": str(tmp_path / "P01.bdf"), "export_receipts": []}

    def run(_params, *, progress_queue):
        progress_queue.put({"type": "progress", "result": result})
        return {
            "status": "error" if cleanup_failed else "success",
            "controller_error": "RuntimeError: pool cleanup failed" if cleanup_failed else "",
            "results": [result], "errors": [],
        }

    monkeypatch.setattr(process_runner, "run_project_parallel", run)
    snapshot = {"settings": {}, "event_map": {"Faces": 1}, "save_folder": str(tmp_path / "outputs")}
    record = {"processing_id": "P01", "info": {"path": result["file"], "subject_id": "P01"}}
    logs = []
    if cleanup_failed:
        with pytest.raises(state_api.ConditionInterpolationPendingError, match="P01:.*pool cleanup failed"):
            executor._run_recording(tmp_path, snapshot, record, {"P01": {"Faces": ["O2"]}}, log_func=logs.append)
        assert logs == []
    else:
        assert executor._run_recording(
            tmp_path, snapshot, record, {"P01": {"Faces": ["O2"]}}, log_func=logs.append,
        ) is result
        assert logs == ["Condition-electrode repair processed P01."]
