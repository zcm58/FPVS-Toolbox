from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.processing.dataset_exclusions import (
    DatasetExclusionsConflictError,
    load_dataset_exclusions,
    save_dataset_exclusions,
)
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_RETAIN,
    active_frequency_domain_exclusions,
    apply_frequency_domain_qc_decision,
    resolve_frequency_qc_coverage_decisions,
    run_frequency_domain_qc_review,
    sync_frequency_domain_qc_automatic_state,
)
from Main_App.projects import Project


def _read(root):
    return json.loads((root / "project.json").read_text(encoding="utf-8"))


def _write(root, manifest):
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")


def _flat_project(tmp_path):
    root = tmp_path / "Project"
    project = Project.load(root)
    project.save()
    manifest = _read(root)
    manifest["participants"] = {"P1": {}, "P2": {}, "P3": {}}
    manifest["preprocessing"]["low_pass"] = 42
    manifest["tools"] = {
        "other_tool": {"unchanged": [1, 2, 3]},
        "stats": {
            "group_significant_harmonics_cache": {"schema_version": 3, "entries": {"old": {"frequencies": [1.2]}}},
            "other_setting": 17,
        },
        "processing": {"full_fft_provenance": {"unchanged": True}},
        "post_processing": {
            "artifact_freshness": {
                "selection_fingerprint": "old",
                "artifacts": {
                    "stats_ready_summed_bca": {
                        "status": "current",
                        "path": "report.xlsx",
                        "built_from_selection_fingerprint": "old",
                    },
                    "unrelated_future_artifact": {"status": "current"},
                },
            }
        },
    }
    _write(root, manifest)
    for pid in ("P1", "P2"):
        path = root / "1 - Excel Data Files" / "CondA" / f"{pid}_CondA_Results.xlsx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing processed result")
    (root / "Input" / "P1.bdf").write_bytes(b"raw data retained")
    return root


def _row(snapshot, participant, recording=""):
    return next(row for row in snapshot.rows if row.participant_id == participant and row.recording_id == recording)


def _manual(pid):
    return {"participant_id": pid, "reason": "Noisy spectrum", "source": "manual_qc_review", "added_at": "2026-01-01"}


def test_snapshot_includes_unprocessed_owners_both_scopes_and_condition_details(tmp_path):
    root = _flat_project(tmp_path)
    manifest = _read(root)
    manifest["preprocessing"].update(
        manual_excluded_participants=["p1"], manual_excluded_participant_conditions={"P1": ["CondA"]}
    )
    manifest["tools"]["frequency_domain_qc"] = {"manual_participant_exclusions": [_manual("P1")]}
    _write(root, manifest)
    before = (root / "project.json").read_bytes()

    snapshot = load_dataset_exclusions(root)

    assert _row(snapshot, "P1").scope == "both"
    assert _row(snapshot, "P1").has_processed_data
    assert "Noisy spectrum" in _row(snapshot, "P1").reason
    assert any("CondA" in detail for detail in _row(snapshot, "P1").details)
    assert not _row(snapshot, "P3").has_processed_data
    assert snapshot.processing_excluded_participants == ("p1",)
    assert (root / "project.json").read_bytes() == before


def test_analysis_exclusion_is_distinct_from_processing_and_invalidates_outputs(tmp_path):
    root = _flat_project(tmp_path)
    snapshot = load_dataset_exclusions(root)
    before = _read(root)
    original_files = {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file() and path.name != "project.json"
    }
    row = _row(snapshot, "P1")

    saved = save_dataset_exclusions(
        root, snapshot, {row.identity: "exclude_analysis"}, reasons={row.identity: "Preregistered removal after review"}
    )

    manifest = _read(root)
    assert _row(saved, "P1").scope == "exclude_analysis"
    assert _row(saved, "P1").reason == "Preregistered removal after review"
    assert saved.processing_excluded_participants == ()
    assert active_frequency_domain_exclusions(root).excluded_participants == frozenset({"P1"})
    assert saved.downstream_outputs_stale
    assert manifest["tools"]["stats"]["group_significant_harmonics_cache"]["entries"] == {}
    assert manifest["tools"]["stats"]["other_setting"] == 17
    assert manifest["tools"]["other_tool"] == before["tools"]["other_tool"]
    assert manifest["tools"]["processing"] == before["tools"]["processing"]
    artifacts = manifest["tools"]["post_processing"]["artifact_freshness"]["artifacts"]
    assert artifacts["stats_ready_summed_bca"]["status"] == "stale"
    assert artifacts["unrelated_future_artifact"]["status"] == "current"
    assert manifest["preprocessing"]["low_pass"] == 42
    assert all(path.read_bytes() == content for path, content in original_files.items())


def test_scope_switch_and_include_preserve_condition_exclusions_and_manual_history(tmp_path):
    root = _flat_project(tmp_path)
    manifest = _read(root)
    manifest["preprocessing"].update(
        manual_excluded_participants=["P1", "P3"], manual_excluded_participant_conditions={"P1": ["CondA"]}
    )
    manifest["tools"]["frequency_domain_qc"] = {"manual_participant_exclusions": [_manual("P1"), _manual("P3")]}
    _write(root, manifest)
    snapshot = load_dataset_exclusions(root)

    saved = save_dataset_exclusions(
        root, snapshot, {_row(snapshot, "P1").identity: "skip_processing", _row(snapshot, "P3").identity: "include"}
    )

    assert _row(saved, "P1").scope == "skip_processing"
    assert _row(saved, "P3").scope == "include"
    assert saved.processing_excluded_participants == ("P1",)
    assert active_frequency_domain_exclusions(root).excluded_participants == frozenset()
    assert _read(root)["preprocessing"]["manual_excluded_participant_conditions"] == {"P1": ["CondA"]}
    assert _read(root)["tools"]["dataset_exclusions"]["history"][0]["removed_manual_analysis_exclusions"] == [
        _manual("P1")
    ]


def test_reason_only_both_preserves_authority_and_allows_clearing_reason(tmp_path):
    root = _flat_project(tmp_path)
    manifest = _read(root)
    manifest["preprocessing"]["manual_excluded_participants"] = ["P1"]
    manifest["tools"]["frequency_domain_qc"] = {"manual_participant_exclusions": [_manual("P1")]}
    _write(root, manifest)
    snapshot = load_dataset_exclusions(root)
    row = _row(snapshot, "P1")

    saved = save_dataset_exclusions(root, snapshot, {row.identity: "both"}, reasons={row.identity: ""})

    assert _row(saved, "P1").scope == "both"
    assert _row(saved, "P1").reason == ""
    assert _read(root)["tools"]["frequency_domain_qc"] == manifest["tools"]["frequency_domain_qc"]
    assert not saved.downstream_outputs_stale


@pytest.mark.parametrize("scope", ["exclude_analysis", "both", "unknown"])
def test_invalid_new_scope_or_analysis_without_processed_data_does_not_write(tmp_path, scope):
    root = _flat_project(tmp_path)
    snapshot = load_dataset_exclusions(root)
    before = (root / "project.json").read_bytes()
    with pytest.raises(ValueError):
        save_dataset_exclusions(root, snapshot, {_row(snapshot, "P3").identity: scope})
    assert (root / "project.json").read_bytes() == before


@pytest.mark.parametrize("changed", ["manifest", "processed_file"])
def test_stale_snapshot_refuses_conflicting_write(tmp_path, changed):
    root = _flat_project(tmp_path)
    snapshot = load_dataset_exclusions(root)
    if changed == "manifest":
        manifest = _read(root)
        manifest["tools"]["other_tool"]["new_worker_data"] = 42
        _write(root, manifest)
    else:
        (root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx").unlink()
    before = (root / "project.json").read_bytes()
    with pytest.raises(DatasetExclusionsConflictError):
        save_dataset_exclusions(root, snapshot, {_row(snapshot, "P1").identity: "exclude_analysis"})
    assert (root / "project.json").read_bytes() == before


def test_atomic_replace_failure_preserves_manifest_and_cleans_temporary(tmp_path, monkeypatch):
    root = _flat_project(tmp_path)
    snapshot = load_dataset_exclusions(root)
    before = (root / "project.json").read_bytes()

    def denied(*_args, **_kwargs):
        raise PermissionError("replace denied")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError, match="replace denied"):
        save_dataset_exclusions(root, snapshot, {_row(snapshot, "P1").identity: "skip_processing"})
    assert (root / "project.json").read_bytes() == before
    assert not list(root.glob(".project.json.dataset-exclusions-*.tmp"))


def test_final_freshness_check_preserves_intervening_worker_update(tmp_path, monkeypatch):
    root = _flat_project(tmp_path)
    snapshot = load_dataset_exclusions(root)
    path = root / "project.json"
    original_read = Path.read_bytes
    worker_manifest = _read(root)
    worker_manifest["tools"]["other_tool"]["worker_completed"] = True

    def update_when_temporary_exists(target):
        if target == path and list(root.glob(".project.json.dataset-exclusions-*.tmp")):
            _write(root, worker_manifest)
        return original_read(target)

    monkeypatch.setattr(Path, "read_bytes", update_when_temporary_exists)
    with pytest.raises(DatasetExclusionsConflictError):
        save_dataset_exclusions(root, snapshot, {_row(snapshot, "P1").identity: "skip_processing"})
    assert _read(root) == worker_manifest
    assert not list(root.glob(".project.json.dataset-exclusions-*.tmp"))


def test_restore_current_review_decision_retires_authority_across_reload_and_rebuild(tmp_path, monkeypatch):
    from Main_App.processing import full_fft_provenance
    from test_frequency_domain_qc import _decisions, _make_project

    monkeypatch.setattr(full_fft_provenance, "require_current_project_workbook_geometry", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        full_fft_provenance, "require_current_project_full_fft_provenance", lambda *_args, **_kwargs: object()
    )
    project = _make_project(tmp_path)
    root = project.project_root
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(root, report, review_decisions=_decisions(report, DECISION_EXCLUDE_PARTICIPANT))
    before = _read(root)["tools"]["frequency_domain_qc"]
    assert resolve_frequency_qc_coverage_decisions(root).review_complete
    assert active_frequency_domain_exclusions(root).excluded_participants == frozenset({"P1"})
    snapshot = load_dataset_exclusions(root)

    saved = save_dataset_exclusions(root, snapshot, {_row(snapshot, "P1").identity: "include"})

    after = _read(root)["tools"]["frequency_domain_qc"]
    assert _row(saved, "P1").scope == "include"
    assert active_frequency_domain_exclusions(root).excluded_participants == frozenset()
    assert not resolve_frequency_qc_coverage_decisions(root).review_complete
    assert "last_review" not in after
    assert (
        _read(root)["tools"]["dataset_exclusions"]["retired_review_receipts"][0]["last_review"] == before["last_review"]
    )
    assert after["review_evidence"] == before["review_evidence"]
    assert after["review_history"] == before["review_history"]
    assert after["retired_review_decisions"] == before["review_decisions"]
    assert after["review_decisions"] == []
    rebuilt = run_frequency_domain_qc_review(Project.load(root))
    assert not any(
        finding.get("finding_type") == "prior_outcome_informed_exclusion_reconfirmation"
        for finding in rebuilt["review_findings"]
    )
    apply_frequency_domain_qc_decision(root, rebuilt, review_decisions=_decisions(rebuilt, DECISION_RETAIN))
    for _ in range(2):
        report = run_frequency_domain_qc_review(Project.load(root))
        sync_frequency_domain_qc_automatic_state(root, report)
        assert active_frequency_domain_exclusions(root).excluded_participants == frozenset()


def test_processing_only_change_revokes_review_authority_without_changing_analysis_choices(tmp_path, monkeypatch):
    from Main_App.processing import full_fft_provenance
    from Main_App.processing.frequency_domain_qc import (
        DECISION_EXCLUDE_CONDITION,
        load_current_frequency_qc_review_evidence,
    )
    from test_frequency_domain_qc import _decisions, _make_project

    monkeypatch.setattr(full_fft_provenance, "require_current_project_workbook_geometry", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        full_fft_provenance, "require_current_project_full_fft_provenance", lambda *_args, **_kwargs: object()
    )
    project = _make_project(tmp_path)
    root = project.project_root
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(root, report, review_decisions=_decisions(report, DECISION_EXCLUDE_CONDITION))
    before = _read(root)["tools"]["frequency_domain_qc"]
    assert resolve_frequency_qc_coverage_decisions(root).review_complete
    snapshot = load_dataset_exclusions(root)

    save_dataset_exclusions(root, snapshot, {_row(snapshot, "P2").identity: "skip_processing"})

    after = _read(root)["tools"]["frequency_domain_qc"]
    assert not resolve_frequency_qc_coverage_decisions(root).review_complete
    with pytest.raises(RuntimeError):
        load_current_frequency_qc_review_evidence(root)
    assert after["review_decisions"] == before["review_decisions"]
    assert after["review_evidence"] == before["review_evidence"]
    assert active_frequency_domain_exclusions(root).excluded_participant_conditions == frozenset({("P1", "CondA")})


def test_before_first_processing_raw_ids_are_discovered_without_registering_or_processing(tmp_path):
    root = tmp_path / "New"
    project = Project.load(root)
    project.save()
    raw = root / "Input" / "P10_eeg.bdf"
    raw.write_bytes(b"raw data")
    before = _read(root)

    snapshot = load_dataset_exclusions(root)

    row = _row(snapshot, "P10")
    assert row.scope == "include" and not row.has_processed_data
    saved = save_dataset_exclusions(root, snapshot, {row.identity: "skip_processing"})
    assert saved.processing_excluded_participants == ("P10",)
    assert _read(root).get("participants") == before.get("participants")
    assert raw.read_bytes() == b"raw data"


def test_repeated_recordings_have_separate_scopes_and_preserve_condition_maps(tmp_path):
    root = tmp_path / "Repeated"
    root.mkdir()
    manifest = {
        "groups": {
            "birth_control": {"label": "Birth Control", "folder_name": "Birth Control", "raw_input_folder": "Raw"}
        },
        "participants": {"P01": {"group_id": "birth_control"}},
        "sessions": {
            "luteal": {"label": "Luteal", "visit_index": 1},
            "follicular": {"label": "Follicular", "visit_index": 2},
        },
        "recording_sources": {
            session: {"group_id": "birth_control", "session_id": session, "raw_input_folder": f"Raw/{session}"}
            for session in ("luteal", "follicular")
        },
        "recordings": {
            f"P01__{session}": {
                "participant_id": "P01",
                "session_id": session,
                "source_id": session,
                "raw_file": f"Raw/{session}/P01.bdf",
                "visit_index": i,
            }
            for i, session in enumerate(("luteal", "follicular"), 1)
        },
    }
    manifest["preprocessing"] = {
        "manual_excluded_participants": ["P01"],
        "manual_excluded_recordings": ["P01__luteal"],
        "manual_excluded_recording_conditions": {"P01__follicular": ["CondA"]},
    }
    _write(root, manifest)
    for rid in ("P01__luteal", "P01__follicular"):
        path = root / "1 - Excel Data Files" / "CondA" / "Birth Control" / f"{rid}_CondA_Results.xlsx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing processed visit")
    snapshot = load_dataset_exclusions(root)
    first = _row(snapshot, "P01", "P01__luteal")
    second = _row(snapshot, "P01", "P01__follicular")
    assert first.scope == "skip_processing"
    assert first.group_label == "Birth Control"
    assert first.has_processed_data and second.has_processed_data
    assert any("Whole-participant" in text for text in first.details)

    saved = save_dataset_exclusions(root, snapshot, {first.identity: "include", second.identity: "exclude_analysis"})

    assert _row(saved, "P01").scope == "skip_processing"
    assert _row(saved, "P01", "P01__luteal").scope == "include"
    assert _row(saved, "P01", "P01__follicular").scope == "exclude_analysis"
    assert active_frequency_domain_exclusions(root).excluded_recordings == frozenset({"P01__FOLLICULAR"})
    assert _read(root)["preprocessing"]["manual_excluded_recording_conditions"] == {"P01__follicular": ["CondA"]}
