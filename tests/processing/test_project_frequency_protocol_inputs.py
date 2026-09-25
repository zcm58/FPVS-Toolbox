from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.gui import processing_inputs
from Main_App.gui.condition_input_model import validate_condition_rows
from Main_App.projects import FrequencyProtocol, Project
from Main_App.processing import kurtosis_review_scan, preprocess
from Main_App.processing.analysis_spans import (
    restrict_source_analysis_span_plan_by_condition,
    validate_source_analysis_span_context,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.processing_ledger import build_processing_fingerprint
from Main_App.workers import process_runner
from tests.processing.test_preprocess_kurtosis_gate import _approval, _raw


@pytest.fixture
def condition_validation(monkeypatch):
    calls = []

    def validated_rows(host, *, focus_error=False):
        calls.append((tuple(host.event_rows), focus_error))
        mapping, errors = validate_condition_rows(host.event_rows)
        return None if errors else mapping

    monkeypatch.setattr(processing_inputs, "validated_event_map", validated_rows)
    return calls


def _ready_project(root: Path, *, marker_code: int = 55) -> Project:
    project = Project.load(root)
    project.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            "3",
            10,
            expected_analyzed_oddball_cycles=144,
            expected_analyzed_oddball_cycles_source="manual",
            oddball_marker_code=marker_code,
        )
    )
    return project


def _kurtosis_worker_settings(host, params):
    """Evaluate the real worker argument without importing or starting Qt."""
    path = Path(processing_inputs.__file__).with_name("preprocessing_qc_workflow.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_run_kurtosis_review_scan_embedded")
    worker = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "_KurtosisReviewWorker")
    settings = next((keyword.value for keyword in worker.keywords if keyword.arg == "settings"), None)
    if settings is None:
        settings = worker.args[1]
    expression = ast.Expression(body=settings)
    return eval(compile(ast.fix_missing_locations(expression), str(path), "eval"),
                {"host": host, "params": params})


def test_processing_params_use_one_frozen_project_protocol_snapshot(tmp_path, condition_validation) -> None:
    project = _ready_project(tmp_path / "project")
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=object(),
        event_rows=[("Condition A", "11")],
    )

    params = processing_inputs.build_validated_params(host)

    assert params is not None
    assert condition_validation == [((("Condition A", "11"),), True)]
    assert params["event_id_map"] == {"Condition A": 11}
    assert params["frequency_protocol"] is project.frequency_protocol
    assert params["frequency_protocol"].oddball_rate_hz.numerator == 3
    assert params["frequency_protocol"].oddball_rate_hz.denominator == 10
    assert params["frequency_protocol_fingerprint"] == project.frequency_protocol.fingerprint
    assert params["base_freq"] == 3.0
    assert params["oddball_freq"] == 0.3
    assert "bca_upper_limit" not in params
    assert "bca_upper_limit" not in params["analysis"]
    assert params["analysis"]["frequency_protocol"] == (
        project.frequency_protocol.to_manifest()
    )


@pytest.mark.parametrize("stale_root", [False, True])
def test_kurtosis_worker_uses_current_project_without_changing_planning_settings(
    tmp_path, condition_validation, stale_root,
) -> None:
    first = _ready_project(tmp_path / "first")
    second = _ready_project(tmp_path / "second")
    host = SimpleNamespace(
        currentProject=first,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=SimpleNamespace(project_root=str(first.project_root)),
        event_rows=[("Condition A", "11")],
    )

    params = processing_inputs.build_validated_params(host)
    assert "project_root" not in params
    if stale_root:
        params["project_root"] = str(tmp_path / "stale")
    original = deepcopy(params)
    fingerprint = build_processing_fingerprint(first, params, params["event_id_map"])
    first_settings = _kurtosis_worker_settings(host, params)
    host.currentProject = second
    second_settings = _kurtosis_worker_settings(host, params)

    assert first_settings["project_root"] == str(first.project_root)
    assert second_settings["project_root"] == str(second.project_root)
    assert params == original
    assert build_processing_fingerprint(first, params, params["event_id_map"]) == fingerprint


def test_gui_params_allow_kurtosis_scan_to_resume_in_processing(
    tmp_path, monkeypatch, condition_validation,
) -> None:
    project = _ready_project(tmp_path / "project")
    project.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        10, 5, expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source="manual",
    ))
    project.update_preprocessing({
        **project.preprocessing,
        "high_pass": 0.5, "low_pass": 30.0, "downsample": 80,
        "max_chan_idx_keep": 20, "line_noise_filter_enabled": False,
        "kurtosis_auto_interpolate_all": False,
    })
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=object(), event_rows=[("Condition", "1")],
    )
    params = processing_inputs.build_validated_params(host)
    source = project.project_root / "P001.bdf"
    source.write_bytes(b"Synthetic source for the real GUI-to-processing handoff")
    raw = _raw()
    raw._data[-1, 1] = 1.0
    raw._data[-1, 100:601:50] = 55.0
    events = mne.find_events(raw, stim_channel="Status", shortest_event=1, verbose=False)
    event_plan = plan_preflight_qc_events(
        events=events, event_map=params["event_id_map"],
        sfreq=raw.info["sfreq"], n_times=raw.n_times, first_samp=raw.first_samp,
        frequency_protocol=params["frequency_protocol"], recording_id="P001_session-1",
    ).to_payload()
    file_key = str(source.resolve())
    params.update({
        "_fpvs_participant_id_by_file": {file_key: "P001"},
        "_fpvs_recording_id_by_file": {file_key: "P001_session-1"},
        "_fpvs_session_id_by_file": {file_key: "session-1"},
        "_fpvs_session_label_by_file": {file_key: "Visit 1"},
        "_fpvs_preflight_event_plans_by_file": {file_key: event_plan},
    })
    monkeypatch.setattr(kurtosis_review_scan.load_utils, "load_eeg_file", lambda *_a, **_k: raw.copy())
    scan = kurtosis_review_scan.scan_kurtosis_review(
        [SimpleNamespace(path=source, subject_id="P001", recording_id="P001_session-1",
                         session_id="session-1", session_label="Visit 1", visit_index=1)],
        _kurtosis_worker_settings(host, params), event_map=params["event_id_map"], max_workers=1,
    )
    assert not scan.cancelled
    assert len(scan.results) == 1 and scan.results[0].error is None
    assert scan.review_items
    evidence = scan.results[0].evidence
    receipts = {item.channel: _approval(evidence, item.channel, source) for item in scan.review_items}
    params["kurtosis_review_decisions_by_recording"] = {"P001_session-1": receipts}
    final_params = process_runner._settings_for_file(source, params)
    # The final runner already supplies its explicit active project root.
    final_params["project_root"] = str(project.project_root)
    source_plan = validate_source_analysis_span_context(
        event_plan_payload=event_plan, event_map=params["event_id_map"],
        protocol=params["frequency_protocol"], recording_id="P001_session-1",
    )
    final_params["_fpvs_source_analysis_span_plan"] = restrict_source_analysis_span_plan_by_condition(
        source_plan, excluded_condition_labels=(),
        exclusion_scope={"participant_id": "P001", "recording_id": "P001_session-1"},
    )
    final_params["_fpvs_require_analysis_spans"] = True
    reference_params = {**deepcopy(final_params), "enable_kurtosis_checkpoint_cache": False}
    reference, expected_count = preprocess.perform_preprocessing(raw.copy(), reference_params, lambda *_: None)
    assert reference is not None, reference_params.get("_fpvs_preprocessing_error")

    def must_not_repeat(*_args, **_kwargs):
        pytest.fail("Processing repeated a stage already completed by the GUI kurtosis scan")

    monkeypatch.setattr(preprocess, "filter_raw_with_prepared_fir", must_not_repeat)
    monkeypatch.setattr(mne.io.BaseRaw, "resample", must_not_repeat)
    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", must_not_repeat)
    resumed, resumed_count = preprocess.perform_preprocessing(raw.copy(), final_params, lambda *_: None)
    assert resumed is not None, final_params.get("_fpvs_preprocessing_error")
    assert final_params["_fpvs_kurtosis_checkpoint_status"] == "hit"
    assert resumed_count == expected_count == len(receipts)
    np.testing.assert_array_equal(resumed.get_data(), reference.get_data())
    assert final_params["_fpvs_kurtosis_qc_evidence"] == evidence
    for key in ("_fpvs_kurtosis_decision_plan", "_fpvs_realized_analysis_span_plan",
                "_fpvs_interpolated_channels"):
        assert final_params[key] == reference_params[key]
    assert final_params["_fpvs_kurtosis_review_decisions"] == receipts
    for current in (raw, reference, resumed):
        current.close()


def test_processing_params_block_incomplete_protocol_before_event_parsing(
    tmp_path,
    monkeypatch,
    condition_validation,
) -> None:
    project = Project.load(tmp_path / "project")
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        processing_inputs.QMessageBox,
        "warning",
        lambda _host, title, message: warnings.append((title, message)),
    )
    host = SimpleNamespace(
        currentProject=project,
        settings=object(),
        event_rows=[],
    )

    assert processing_inputs.build_validated_params(host) is None
    assert condition_validation == []
    assert warnings == [
        (
            "FPVS Protocol Required",
            "Enter the expected number of analyzed oddball cycles in Settings > "
            "Protocol and save before processing.",
        )
    ]


def test_processing_params_reject_marker_condition_code_collision(
    tmp_path,
    monkeypatch,
    condition_validation,
) -> None:
    project = _ready_project(tmp_path / "project", marker_code=55)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        processing_inputs.QMessageBox,
        "warning",
        lambda _host, title, message: warnings.append((title, message)),
    )
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=object(),
        event_rows=[("Condition A", "55")],
    )

    assert processing_inputs.build_validated_params(host) is None
    assert condition_validation == [((("Condition A", "55"),), True)]
    assert warnings[0][0] == "Invalid FPVS Protocol"
    assert "also a condition-onset code" in warnings[0][1]
