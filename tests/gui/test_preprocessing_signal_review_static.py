"""Execute the actual review-row adapter without importing or starting Qt."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Main_App.gui.signal_review_model import SignalReviewItem, episode_view_context, review_time_scope
from Main_App.processing.preflight_qc import PreflightQcFileResult, PreflightQcScan
from Main_App.processing.kurtosis_qc import (
    CHANNEL_DECISION_DIRECT, KURTOSIS_DECISION_APPROVE, KURTOSIS_DECISION_REJECT,
)
from Main_App.projects.preprocessing_settings import KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY


def _adapter():
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/preprocessing_qc_workflow.py"
    function = next(node for node in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_remaining_review_rows")
    namespace = {
        "Mapping": Mapping, "Sequence": Sequence, "Any": Any,
        "PreflightQcFileResult": PreflightQcFileResult, "PreflightQcScan": PreflightQcScan,
        "SignalReviewItem": SignalReviewItem, "review_time_scope": review_time_scope,
        "_recording_aware": lambda _results: False,
        "_payload_list": lambda payload, key: list(payload.get(key, ())),
        "_result_group_display_name": lambda result, labels: labels.get(result.group_id, "Group"),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_remaining_review_rows"]


def test_new_raw_pattern_reaches_review_even_when_original_qc_is_clear(tmp_path):
    path = tmp_path / "P01.bdf"
    raw_qc = {"experimental_removed_electrode_detector": {"evaluation_status": "evaluated"}}
    result = PreflightQcFileResult(
        path, "P01", None, raw_qc, {"evaluation_status": "evaluated"},
        condition_qc={"event_plan": {"sfreq": 100, "first_samp": 1000, "n_times": 1000}},
    )
    scan = PreflightQcScan((result,))
    assert not scan.suspicious_results
    event = {"channel": "Cz", "kind": "abrupt_jump", "condition_label": "Faces",
             "occurrence": 0, "start_sample": 1100, "stop_sample": 1102,
             "start_s": 1.0, "stop_s": 1.02, "interpretation": "Transition support only."}
    report = {"localized_events": [event]}
    items = []
    rows = _adapter()(scan, set(), review_items=items, review_diagnostics_by_file={str(path): report})
    assert len(rows) == len(items) == 1
    assert items[0].time_spans_s == ((1.0, 1.02),)
    assert items[0].source_path == str(path)
    assert items[0].evidence["start_sample"] == 1100
    assert "does not authorize interpolation or exclusion" in rows[0][-1]
    assert report == {"localized_events": [event]}
    assert result.raw_channel_qc == {
        "experimental_removed_electrode_detector": {"evaluation_status": "evaluated"},
    }


def test_excluded_recording_does_not_return_as_new_diagnostic_cue(tmp_path):
    path = tmp_path / "P01.bdf"
    result = PreflightQcFileResult(path, "P01", None, None, None)
    report = {str(path): {"localized_events": [{"kind": "exact_flatline"}]}}
    assert _adapter()(PreflightQcScan((result,)), {"p01"}, review_diagnostics_by_file=report) == []


def test_missing_timebase_keeps_diagnostic_evidence_unlocalized(tmp_path):
    path = tmp_path / "P01.bdf"
    result = PreflightQcFileResult(path, "P01", None, None, None)
    report = {str(path): {"localized_events": [{"kind": "exact_flatline", "channel": "Cz",
                                               "start_sample": 1, "stop_sample": 10}]}}
    items = []
    _adapter()(PreflightQcScan((result,)), set(), review_items=items, review_diagnostics_by_file=report)
    assert items[0].time_scope == "unlocalized"
    assert items[0].time_spans_s == ()


def _inspection_callback(*, scan, kurtosis_scan, params, items, project_root):
    """Execute the actual closure; only the modal widget boundary is replaced."""
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/preprocessing_qc_workflow.py"
    owner = next(node for node in ast.parse(path.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_show_suspicious_remainder")
    callback = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                    and node.name == "inspect_episode")
    callback.body = [node for node in callback.body if not (
        isinstance(node, ast.ImportFrom) and node.module == "Main_App.gui.qc_signal_viewer"
    )]
    opened = []
    panel = object()

    class Viewer:
        def __init__(self, request, parent):
            assert parent is panel
            opened.append(request)

        def exec(self):
            return None

    namespace = {
        "QcSignalViewer": Viewer, "replace": replace,
        "episode_view_context": episode_view_context,
        "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY": KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
        "host": SimpleNamespace(currentProject=SimpleNamespace(project_root=project_root)),
        "scan": scan, "kurtosis_scan": kurtosis_scan, "signal_params": params,
        "review_items": items, "panel": panel,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[callback], type_ignores=[])),
                 str(path), "exec"), namespace)
    return namespace["inspect_episode"], opened


@pytest.fixture
def inspection(tmp_path):
    path = tmp_path / "visit_2" / "P01.bdf"
    sibling = tmp_path / "visit_1" / "P01.bdf"
    plan = {
        "sfreq": 100.0, "first_samp": 1000, "n_times": 10000,
        "spans": [{"condition_label": "Faces", "repetition_index": 1,
                   "time_start_sample": 2000, "time_stop_sample": 6000}],
    }
    source = PreflightQcFileResult(
        path, "P01", None, None, None, condition_qc={"event_plan": plan},
        recording_id="P01__visit_2",
    )
    sibling_source = replace(source, path=sibling, recording_id="P01__visit_1", condition_qc={
        "event_plan": {**plan, "spans": [{"condition_label": "Faces", "repetition_index": 0,
                                          "time_start_sample": 1000, "time_stop_sample": 1500}]},
    })
    identity = {"path": str(path), "size_bytes": 12000, "sha256": "a" * 64}
    diagnostics = {"source_identity": identity, "localized_events": [{
        "channel": "Cz", "kind": "abrupt_jump", "start_sample": 4000, "stop_sample": 4002,
    }]}
    scanned = SimpleNamespace(
        path=path, recording_id="P01__visit_2", source_identity=identity,
        review_diagnostics=diagnostics,
        decision_plan={"channel_decisions": [
            {"channel": "Cz", "interpolation_authorized": True},
            {"channel": "Pz", "interpolation_authorized": False},
            {"channel": "Oz", "interpolation_authorized": True},
            {"channel": "T7", "interpolation_authorized": False},
        ]},
    )
    sibling_scan = SimpleNamespace(
        path=sibling, recording_id="P01__visit_1",
        source_identity={"path": str(sibling), "size_bytes": 999, "sha256": "b" * 64},
        review_diagnostics={"different_recording": True}, decision_plan={},
    )
    item = SignalReviewItem(
        ("P01", "P01__visit_2", "Follow-up", "2", "Group", "P01.bdf", "Twenty millisecond cue."),
        "Signal patterns", "Abrupt jump", "Faces", "2", "Cz, Pz", source_path=str(path),
        time_spans_s=((30.0, 30.02),), time_scope="diagnostic_windows",
    )
    episode = SimpleNamespace(
        source_path=str(path), condition="Faces", occurrence="2", item_indices=(0,),
        time_spans_s=item.time_spans_s,
    )
    params = {
        "ref_channel1": "EXG1", "ref_channel2": "EXG2",
        KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY: {"p01__VISIT_2": {
            "Cz": {"decision": KURTOSIS_DECISION_REJECT, "reason": "Keep after review"},
            "Pz": {"decision": KURTOSIS_DECISION_APPROVE, "reason": "Repair after review"},
        }},
    }
    return SimpleNamespace(
        path=path, project_root=tmp_path, scan=PreflightQcScan((sibling_source, source)),
        kurtosis_scan=SimpleNamespace(results=(sibling_scan, scanned)),
        params=params, items=[item], episode=episode, scanned=scanned,
    )


def _open_inspection(context):
    callback, opened = _inspection_callback(
        scan=context.scan, kurtosis_scan=context.kurtosis_scan, params=context.params,
        items=context.items, project_root=context.project_root,
    )
    callback(context.episode)
    assert len(opened) == 1
    return opened[0]


def test_twenty_millisecond_cue_opens_matching_full_occurrence_with_bounded_context(inspection):
    request = _open_inspection(inspection)
    assert request.spans == ((10.0, 50.0),)
    assert request.span_labels == ("Faces · occurrence 2",)
    assert request.start_seconds == 29.0
    assert request.occurrence_index == 0
    assert inspection.episode.time_spans_s == ((30.0, 30.02),)
    assert not inspection.path.exists()  # Request creation performs no source I/O.


def test_source_identity_and_diagnostics_follow_exact_recording_path_not_same_named_sibling(inspection):
    before = deepcopy((inspection.scanned.source_identity, inspection.scanned.review_diagnostics))
    request = _open_inspection(inspection)
    assert request.path == inspection.path
    assert request.project_root == inspection.project_root
    assert request.channel == "Cz"
    assert request.params == {"ref_channel1": "EXG1", "ref_channel2": "EXG2"}
    assert request.source_identity == inspection.scanned.source_identity
    assert request.diagnostics == inspection.scanned.review_diagnostics
    assert (inspection.scanned.source_identity, inspection.scanned.review_diagnostics) == before
    assert "different_recording" not in request.diagnostics


def test_current_keep_receipt_overrides_old_authorization_and_new_approval_excludes_donor(inspection):
    before = deepcopy((inspection.params, inspection.scanned.decision_plan))
    request = _open_inspection(inspection)
    assert request.unusable_channels == ("Oz", "Pz")
    assert "Cz" not in request.unusable_channels
    assert (inspection.params, inspection.scanned.decision_plan) == before


def test_absent_current_receipts_preserve_scans_authorized_repair_exclusions(inspection):
    inspection.params.pop(KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY)
    assert _open_inspection(inspection).unusable_channels == ("Cz", "Oz")


def test_missing_matching_scan_does_not_attach_another_recordings_identity_or_donors(inspection):
    inspection.kurtosis_scan.results = inspection.kurtosis_scan.results[:1]
    request = _open_inspection(inspection)
    assert request.source_identity == {}
    assert request.diagnostics == {}
    assert request.unusable_channels == ()
    assert request.spans == ((10.0, 50.0),)


def test_unlocalized_episode_preserves_empty_intervals_without_fabricating_context(inspection):
    inspection.episode.time_spans_s = ()
    request = _open_inspection(inspection)
    assert request.spans == ()
    assert request.span_labels == ()
    assert request.start_seconds is None
    assert request.source_identity == inspection.scanned.source_identity


@pytest.mark.parametrize("missing", ["project_root", "source_path"])
def test_inspection_requires_explicit_project_and_source_context(inspection, missing):
    if missing == "project_root":
        inspection.project_root = None
    else:
        inspection.episode.source_path = ""
    callback, opened = _inspection_callback(
        scan=inspection.scan, kurtosis_scan=inspection.kurtosis_scan, params=inspection.params,
        items=inspection.items, project_root=inspection.project_root,
    )
    callback(inspection.episode)
    assert opened == []


def test_old_keep_receipt_cannot_make_direct_manual_or_physical_bad_channel_a_donor(inspection):
    inspection.scanned.decision_plan["channel_decisions"][0]["state"] = CHANNEL_DECISION_DIRECT
    assert inspection.params[KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY]["p01__VISIT_2"]["Cz"]["decision"] == KURTOSIS_DECISION_REJECT
    request = _open_inspection(inspection)
    assert request.unusable_channels == ("Cz", "Oz", "Pz")


def _clear_source(path):
    return PreflightQcFileResult(
        path, "P01", None,
        {"experimental_removed_electrode_detector": {"evaluation_status": "evaluated"}},
        {"evaluation_status": "evaluated"},
    )


def test_display_limit_emits_explicit_incomplete_assessment_without_automatic_authority(tmp_path):
    path = tmp_path / "P01.bdf"
    result = _clear_source(path)
    event = {"kind": "abrupt_jump", "channel": "Cz", "start_sample": 100, "stop_sample": 102}
    report = {"events_omitted_by_display_limit": 7, "localized_events": [event]}
    before = deepcopy(report)
    items = []
    rows = _adapter()(PreflightQcScan((result,)), set(), review_items=items,
                      review_diagnostics_by_file={str(path): report})
    assert len(rows) == 2
    status = next(item for item in items if item.kind == "Assessment status")
    assert "7 additional provisional signal cue(s)" in status.details
    assert "displayed cues are incomplete" in status.details
    assert "does not establish a clean recording or authorize interpolation or exclusion" in status.details
    assert status.evidence["events_omitted_by_display_limit"] == 7
    assert status.evidence["authority"] == "review_only"
    assert status.time_spans_s == ()
    assert status.source_path == str(path)
    assert report == before


def test_unavailable_diagnostics_is_explicit_and_missing_mapping_does_not_invent_an_assessment(tmp_path):
    path = tmp_path / "P01.bdf"
    result = _clear_source(path)
    scan = PreflightQcScan((result,))
    assert not scan.suspicious_results
    assert _adapter()(scan, set(), review_diagnostics_by_file={}) == []
    report = {"authority": "review_only", "status": "unavailable",
              "reason": "Signal diagnostics could not be computed.", "localized_events": []}
    before = deepcopy(report)
    items = []
    rows = _adapter()(scan, set(), review_items=items, review_diagnostics_by_file={str(path): report})
    assert len(rows) == len(items) == 1
    assert items[0].kind == "Assessment status"
    assert "Signal diagnostics could not be computed" in items[0].details
    assert "No clean-recording verdict or repair/exclusion decision" in items[0].details
    assert items[0].evidence == report
    assert items[0].time_scope == "unlocalized" and items[0].time_spans_s == ()
    assert items[0].source_path == str(path)
    assert report == before
