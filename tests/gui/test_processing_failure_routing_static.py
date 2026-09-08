"""Exercise real orchestration functions with lightweight doubles, without Qt."""

from __future__ import annotations

import ast
from datetime import datetime
import gc
import json
import logging
from pathlib import Path
from queue import Empty, Queue
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_function(relative_path, name, namespace, *, class_name=None, outer_function=None):
    path = REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = tree if class_name is None else next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    if outer_function is not None:
        owner = next(
            node for node in owner.body
            if isinstance(node, ast.FunctionDef) and node.name == outer_function
        )
    function = next(
        node for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    function.decorator_list = []
    # Postpone production annotations; no PySide6 import or event loop is needed.
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def _build_params_for_project(project):
    from Main_App.projects import FrequencyProtocol, FrequencyProtocolError
    from Main_App.projects.preprocessing_settings import (
        KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
        MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
        RemovedElectrodeDetectionConfirmationRequired,
        normalize_preprocessing_settings,
    )

    protocol = FrequencyProtocol.from_recurrence(
        6.0, 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    messages = Mock()
    build = _load_function(
        "src/Main_App/gui/processing_inputs.py", "build_validated_params",
        {
            "processing_protocol_snapshot": lambda _project: protocol,
            "normalize_preprocessing_settings": normalize_preprocessing_settings,
            "require_removed_electrode_detection_choice_ready": lambda _settings: None,
            "RemovedElectrodeDetectionConfirmationRequired": RemovedElectrodeDetectionConfirmationRequired,
            "validate_protocol_condition_codes": lambda *_args: None,
            "FrequencyProtocolError": FrequencyProtocolError,
            "logger": logging.getLogger(__name__),
            "QLineEdit": object, "QMessageBox": messages,
            "_illegal_condition_chars": lambda _label: (),
            "config": SimpleNamespace(DEFAULT_STIM_CHANNEL="Status"),
            "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY": KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
            "MANUAL_REMOVED_ELECTRODES_ENABLED_KEY": MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
        },
    )
    row = SimpleNamespace(findChildren=lambda _kind: [
        SimpleNamespace(text=lambda: "Faces"), SimpleNamespace(text=lambda: "1"),
    ])
    params = build(SimpleNamespace(currentProject=project, event_rows=[row]))
    return params, messages


@pytest.mark.parametrize("mapping", ["anatomical_labels", "biosemi64_1020_ab_v1"])
def test_processing_params_preserve_project_geometry_in_run_plan(mapping):
    from Main_App.processing.processing_ledger import _configured_geometry_identity

    settings = {"electrode_montage": "biosemi64", "electrode_mapping_profile": mapping}
    project = SimpleNamespace(
        preprocessing=settings,
        experimental_qc_settings=SimpleNamespace(
            raw_spectral_screening=SimpleNamespace(to_manifest=lambda: {}),
        ),
    )
    params, messages = _build_params_for_project(project)

    assert params is not None
    assert _configured_geometry_identity(params) == _configured_geometry_identity(settings)
    assert params["electrode_montage"] == "biosemi64"
    assert params["electrode_mapping_profile"] == mapping
    messages.warning.assert_not_called()


@pytest.mark.parametrize("explicit_local_change", [False, True])
def test_processing_refreshes_external_geometry_without_overwriting_local_choice(
    tmp_path, explicit_local_change,
):
    from Main_App.processing.preflight_qc import preflight_file_settings_identity
    from Main_App.projects import Project

    initial_mapping = (
        "anatomical_labels" if explicit_local_change else "biosemi64_1020_ab_v1"
    )
    manifest = {"preprocessing": {
        "electrode_montage": "biosemi64",
        "electrode_mapping_profile": initial_mapping,
        "high_pass": 0.1,
    }}
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(tmp_path, manifest)
    if explicit_local_change:
        project.update_preprocessing({
            **project.preprocessing,
            "electrode_mapping_profile": "biosemi64_1020_ab_v1",
        })
    previous_params, _ = _build_params_for_project(project)
    assert previous_params["electrode_mapping_profile"] == "biosemi64_1020_ab_v1"

    # Reproduce an external repair while the same Project remains open. An
    # unrelated disk edit must not refresh the whole live preprocessing state.
    repaired = json.loads(manifest_path.read_text(encoding="utf-8"))
    repaired["preprocessing"]["electrode_mapping_profile"] = "anatomical_labels"
    repaired["preprocessing"]["high_pass"] = 0.5
    manifest_path.write_text(json.dumps(repaired), encoding="utf-8")
    repaired_bytes = manifest_path.read_bytes()

    params, messages = _build_params_for_project(project)
    expected = "biosemi64_1020_ab_v1" if explicit_local_change else "anatomical_labels"
    assert params["electrode_mapping_profile"] == expected
    assert params["electrode_montage"] == "biosemi64"
    assert params["high_pass"] == 0.1
    assert manifest_path.read_bytes() == repaired_bytes
    before = preflight_file_settings_identity(previous_params, participant_id="P1")
    after = preflight_file_settings_identity(params, participant_id="P1")
    assert (before == after) is explicit_local_change
    messages.warning.assert_not_called()


def test_processing_blocks_stale_geometry_when_current_manifest_is_invalid(tmp_path):
    from Main_App.projects import Project

    manifest = {"preprocessing": {
        "electrode_montage": "biosemi64",
        "electrode_mapping_profile": "biosemi64_1020_ab_v1",
    }}
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(tmp_path, manifest)
    manifest_path.write_text("{invalid project metadata", encoding="utf-8")

    params, messages = _build_params_for_project(project)

    assert params is None
    messages.warning.assert_called_once()
    assert messages.warning.call_args.args[1] == "Project Settings Unavailable"
    assert manifest_path.read_text(encoding="utf-8") == "{invalid project metadata"


def test_many_file_errors_keep_batch_running_until_one_finished_payload():
    poll = _load_function(
        "src/Main_App/workers/mp_runner_bridge.py", "_poll",
        {"Empty": Empty, "Path": Path, "logger": logging.getLogger(__name__)},
        class_name="MpRunnerBridge",
    )
    bridge = SimpleNamespace(
        _q=Queue(), _total=12, _running=True, _results=[], _error_results=[],
        _excluded_results=[], _timer=Mock(), _cancel_event=object(),
        _worker_thread=object(), error=Mock(), file_status=Mock(),
        progress=Mock(), finished=Mock(),
    )
    failures = [
        {"file": f"p{index}.bdf", "status": "error", "stage": "preprocess", "error": "Bad receipt"}
        for index in range(12)
    ]
    for index, failure in enumerate(failures, start=1):
        bridge._q.put({"type": "progress", "completed": index, "result": failure})
    poll(bridge)

    assert bridge._running
    bridge.error.emit.assert_not_called()
    bridge.finished.emit.assert_not_called()
    bridge._timer.stop.assert_not_called()
    assert bridge.file_status.emit.call_count == 12

    bridge._q.put({"type": "done"})
    poll(bridge)
    bridge.finished.emit.assert_called_once()
    assert bridge.finished.emit.call_args.args[0]["errors"] == failures
    assert not bridge._running


def test_completion_preserves_failure_details_and_shows_one_summary(tmp_path):
    error = {"file": str(tmp_path / "p1.bdf"), "status": "error", "stage": "preprocess", "error": "Bad receipt"}
    ledger_error = {"file": error["file"], "status": "failed", "reason": "incomplete"}
    summary = Mock()
    record = Mock()
    report = Mock(return_value=tmp_path / "qc.xlsx")
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "record_processing_results": record, "export_processing_qc_summary": report,
        "_run_failed_results_from_ledger": lambda *_: [ledger_error],
        "_run_condition_warning_results_from_ledger": lambda *_: [],
        "_format_exclusion_reason": lambda result: result.get("error", "incomplete"),
        "_show_exclusion_summary_popup": summary,
        "_show_condition_warning_popup": Mock(),
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    finalized = []
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _processing_plan=object(), currentProject=object(), _busy_stop=Mock(),
    )
    host._finalize_processing = lambda *args, **kwargs: finalized.append(host._processing_summary_reported)
    finished(host, {"results": [], "errors": [error], "cancelled": False})

    assert record.call_args.args[2] == [error]
    assert report.call_args.args[2] == [error]
    summary.assert_called_once_with(host, [error])
    assert finalized == [True]
    assert not host._processing_summary_reported


def test_reported_failures_do_not_open_second_completion_dialog():
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    host = SimpleNamespace(
        _processing_summary_reported=True, log=Mock(), _set_controls_enabled=Mock(),
        progress_bar=Mock(),
    )
    finalize(host, True)
    assert not messages.mock_calls
    host._set_controls_enabled.assert_called_once_with(True)
    assert not host.busy


@pytest.mark.parametrize(
    "case, expected_success",
    [
        ("all_worker_errors", False),
        ("ledger_only_failure", False),
        ("partial_success", True),
        ("intentional_exclusions", True),
    ],
)
def test_completion_does_not_report_an_entirely_failed_batch_as_success(
    tmp_path, case, expected_success,
):
    failed = {"file": str(tmp_path / "P01.bdf"), "status": "error", "error": "Load failed"}
    errors = [failed] if case in {"all_worker_errors", "partial_success"} else []
    ledger_failures = [failed] if case == "ledger_only_failure" else []
    results = [{"file": str(tmp_path / "P02.bdf"), "status": "ok"}] if case == "partial_success" else []
    excluded = (
        [{"file": failed["file"], "status": "excluded", "reason": "Manual exclusion"}]
        if case == "intentional_exclusions" else []
    )

    def start_pipeline(host, *, on_finished):
        on_finished()
        return True

    starter = Mock(side_effect=start_pipeline)
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "record_processing_results": Mock(),
        "export_processing_qc_summary": Mock(return_value=tmp_path / "qc.xlsx"),
        "_run_failed_results_from_ledger": lambda *_: ledger_failures,
        "_run_condition_warning_results_from_ledger": lambda *_: [],
        "_format_exclusion_reason": lambda result: result.get("error", result.get("reason", "")),
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_review_interpolation_burden_before_post_processing": lambda *_: True,
        "_start_post_processing_pipeline_after_processing": starter,
        "BDF_RECORDING_NOT_STARTED_REASON": "bdf_recording_not_started",
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _processing_plan=object(), currentProject=object(),
        _busy_stop=Mock(), _finalize_processing=Mock(),
    )
    finished(host, {"results": results, "errors": errors, "excluded": excluded})

    host._finalize_processing.assert_called_once_with(expected_success, cancelled=False)
    assert starter.call_count == int(case == "partial_success")
    host._busy_stop.assert_called_once()
    namespace["_show_exclusion_summary_popup"].assert_called_once()
    assert host._post_processing_failure_reason == ""


def _post_processing_namespace():
    path = "src/Main_App/gui/processing_workflows.py"
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id.startswith("_POST_PROCESSING_")
            for target in node.targets
        )
    ]
    namespace = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), path, "exec"), namespace)
    _load_function(path, "_post_processing_frequency_domain_outputs_ready", namespace)
    _load_function(path, "_post_processing_failure_reason", namespace)
    return namespace


def test_post_processing_fatal_prerequisite_keeps_exact_reason():
    namespace = _post_processing_namespace()
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    result = {
        "ok": False,
        "steps": [{"name": "post_processing_pipeline", "ok": False, "message": reason}],
    }

    assert namespace["_post_processing_failure_reason"](result) == reason


def test_post_processing_optional_failure_keeps_core_outputs_usable():
    namespace = _post_processing_namespace()
    result = {
        "ok": False,
        "steps": [
            {"name": name, "ok": True}
            for name in namespace["_POST_PROCESSING_FREQUENCY_DOMAIN_STEP_NAMES"]
        ] + [{"name": "eloreta_volume_source_psd", "ok": False, "message": "Source export failed"}],
    }

    assert namespace["_post_processing_failure_reason"](result) == ""


@pytest.mark.parametrize("reported_summary", [False, True])
def test_post_processing_incomplete_dialog_survives_preprocessing_summary(reported_summary):
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    host = SimpleNamespace(
        _processing_summary_reported=reported_summary,
        _post_processing_failure_reason=reason,
        log=Mock(), _set_controls_enabled=Mock(), progress_bar=Mock(),
    )
    finalize(host, False)

    messages.show_info.assert_not_called()
    messages.show_error.assert_called_once()
    title, message, parent = messages.show_error.call_args.args
    assert title == "Post-processing Incomplete"
    assert reason in message
    assert "not ready" in message
    assert parent is host
    assert not host.busy


@pytest.mark.parametrize("cancelled", [False, True])
def test_processing_completion_propagates_post_processing_failure(tmp_path, cancelled):
    reason = "P9 / Neutral Angry: no condition occurrence was planned."

    def start_pipeline(host, *, on_finished):
        host._post_processing_failure_reason = reason
        on_finished()
        return True

    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "_review_interpolation_burden_before_post_processing": lambda *_: True,
        "_start_post_processing_pipeline_after_processing": start_pipeline,
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _busy_stop=Mock(), _finalize_processing=Mock(),
    )
    result = {"file": str(tmp_path / "p9.bdf"), "status": "ok"}
    finished(host, {"results": [result], "cancelled": cancelled})

    host._finalize_processing.assert_called_once_with(False, cancelled=cancelled)
    assert host._post_processing_failure_reason == ("" if cancelled else reason)


def test_ledger_save_failure_does_not_claim_processing_success(tmp_path):
    namespace = {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "format_audit_summary": lambda *_: ("Preprocessed", False),
        "_format_timing_summary": lambda *_: None,
        "_show_exclusion_summary_popup": Mock(), "_show_condition_warning_popup": Mock(),
        "record_processing_results": Mock(side_effect=OSError("Project folder is read-only")),
        "_start_post_processing_pipeline_after_processing": Mock(),
    }
    finished = _load_function(
        "src/Main_App/gui/processing_workflows.py", "on_processing_finished", namespace,
    )
    host = SimpleNamespace(
        settings=SimpleNamespace(debug_enabled=lambda: False), validated_params={},
        log=Mock(), _busy_stop=Mock(), _finalize_processing=Mock(),
        _processing_plan=object(), currentProject=object(),
    )
    finished(host, {"results": [{"file": str(tmp_path / "p9.bdf"), "status": "ok"}]})

    host._finalize_processing.assert_called_once_with(False, cancelled=False)
    namespace["_start_post_processing_pipeline_after_processing"].assert_not_called()
    assert "Project folder is read-only" in host._post_processing_failure_reason


def test_successful_rebuild_skip_is_not_a_post_processing_failure():
    reason = _post_processing_namespace()["_post_processing_failure_reason"]
    assert reason({"ok": True, "rebuild_skipped": True, "steps": []}) == ""


def test_paused_frequency_qc_requires_review_without_claiming_success():
    reason = _post_processing_namespace()["_post_processing_failure_reason"]
    assert "QC review must be completed" in reason({
        "ok": False, "requires_frequency_domain_qc_review": True, "steps": [],
    })


@pytest.mark.parametrize("failure_stage", ["group", "identity", "dialog"])
@pytest.mark.parametrize("has_cache", [False, True])
def test_frequency_qc_review_start_preserves_actual_failure_stage_and_reason(
    monkeypatch, tmp_path, failure_stage, has_cache,
):
    from Main_App.processing.frequency_qc_identity import FrequencyQcReviewIdentityError

    errors = {
        "group": ValueError("Participant P09 has no canonical group membership."),
        "identity": FrequencyQcReviewIdentityError(
            "Recording-scoped review finding for P09 is missing recording_id."
        ),
        "dialog": RuntimeError("Could not initialize the review controls."),
    }
    error = errors[failure_stage]
    dialog_factory = Mock(side_effect=error if failure_stage != "group" else None)
    save_review = Mock()
    events = []
    mark_stale = Mock(side_effect=lambda *_args, **_kwargs: events.append("stale"))
    for name, attributes in (
        ("Main_App.gui.frequency_domain_qc_dialog", {"FrequencyDomainQcReviewDialog": dialog_factory}),
        ("Main_App.gui.frequency_domain_qc_handoff", {"save_frequency_domain_qc_review": save_review}),
        ("Main_App.processing.frequency_domain_qc", {"mark_frequency_domain_outputs_stale": mark_stale}),
    ):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    messages = SimpleNamespace(critical=Mock(side_effect=lambda *_args: events.append("critical")))
    group_resolver = Mock(
        return_value={"P09": "Control"},
        side_effect=error if failure_stage == "group" else None,
    )
    log = Mock()
    resume = Mock(side_effect=lambda *_args: events.append("resume"))
    review = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_handle_frequency_domain_qc_review",
        {
            "_frequency_domain_qc_participant_groups": group_resolver,
            "logger": log, "QMessageBox": messages,
            "_set_resume_post_processing_pending": resume,
        },
    )
    project = SimpleNamespace(project_root=tmp_path)
    host = SimpleNamespace(_post_processing_failure_reason="")
    cache = Mock() if has_cache else None
    if cache is not None:
        cache.clear.side_effect = lambda: events.append("clear")
    finished_reasons = []

    def on_finished():
        events.append("finished")
        finished_reasons.append(host._post_processing_failure_reason)

    report = {"findings": [{"participant_id": "P09"}]}
    review(host, project, report, on_finished=on_finished, provisional_cache=cache)

    expected_context = "resolve canonical group membership" if failure_stage == "group" else "build the review dialog"
    expected_reason = f"Frequency-domain QC could not {expected_context}: {error}"
    expected_event = "frequency_domain_qc_group_membership_failed" if failure_stage == "group" else "frequency_domain_qc_review_build_failed"
    assert host._post_processing_failure_reason == expected_reason
    log.exception.assert_called_once_with(expected_event)
    messages.critical.assert_called_once_with(host, "Frequency-Domain QC Error", str(error))
    mark_stale.assert_called_once_with(tmp_path, reason=expected_reason)
    assert finished_reasons == [expected_reason]
    resume.assert_called_once_with(host, True)
    assert events == (["clear"] if has_cache else []) + ["critical", "stale", "finished", "resume"]
    if cache is not None:
        cache.clear.assert_called_once()
    if failure_stage == "group":
        dialog_factory.assert_not_called()
    else:
        dialog_factory.assert_called_once_with(report, host, participant_groups={"P09": "Control"})
    save_review.assert_not_called()


def test_worker_finished_delivers_explicit_failure_to_completion_callback():
    reason = "P9 / Neutral Angry: no condition occurrence was planned."
    host = SimpleNamespace(log=Mock())
    finalized_reasons = []
    namespace = _post_processing_namespace()
    cache = Mock()
    action_button = Mock()
    namespace.update({
        "host": host, "project": object(), "logging": logging,
        "provisional_cache": cache,
        "action_button": action_button, "previous_action_tooltip": "Original action",
        "_post_processing_source_map_outcome": lambda _: (False, False),
        "on_finished": lambda: finalized_reasons.append(host._post_processing_failure_reason),
        "QTimer": SimpleNamespace(singleShot=lambda _delay, callback: callback()),
    })
    handler = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_handle_finished", namespace,
        outer_function="_start_post_processing_pipeline_after_processing",
    )
    handler({
        "ok": False, "failure_reason": reason,
        "steps": [{"name": "post_processing_pipeline", "ok": False, "message": reason}],
    })

    assert finalized_reasons == [reason]
    cache.clear.assert_called_once()
    action_button.setToolTip.assert_called_once_with("Original action")
    assert host._post_processing_pipeline_thread is None
    assert any("not ready" in call.args[0] for call in host.log.call_args_list)


def test_failed_post_processing_phase_does_not_say_complete():
    namespace = _post_processing_namespace()
    display = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_post_processing_phase_display_state",
        namespace,
    )
    title, message, phase = display("post_processing_failed", "P9 needs a condition decision.")

    assert title == "Post-processing Incomplete"
    assert message == "P9 needs a condition decision."
    assert phase == 5


def test_canceled_processing_does_not_show_post_processing_error_dialog():
    messages = Mock()
    finalize = _load_function(
        "src/Main_App/gui/processing_completion.py", "finalize_processing_host_state",
        {"user_messages": messages, "gc": gc, "datetime": datetime},
    )
    finalize(SimpleNamespace(
        _suppress_completion_dialogs=True, _post_processing_failure_reason="Previous failure",
        log=Mock(),
    ), False)

    assert not messages.mock_calls


def _registered_open_project(tmp_path):
    """Canonical, deliberately uneven registered visits with one extra raw file."""
    groups = {}
    sources = {}
    for group in ("control", "treatment"):
        group_root = tmp_path / "raw" / group
        groups[group] = {"label": group.title(), "folder_name": group.title(),
                         "raw_input_folder": str(group_root)}
        for session in ("visit1", "visit2"):
            source_root = group_root / session
            source_root.mkdir(parents=True)
            sources[f"{group}_{session}"] = {
                "group_id": group, "session_id": session, "raw_input_folder": str(source_root),
            }
    recordings = {}
    participants = {}
    for participant, group, session in (
        ("P1", "control", "visit1"), ("P1", "control", "visit2"),
        ("P2", "control", "visit1"), ("P3", "treatment", "visit1"),
    ):
        source_id = f"{group}_{session}"
        raw_file = Path(sources[source_id]["raw_input_folder"]) / f"{participant}.bdf"
        raw_file.write_bytes(b"Synthetic raw path only; never loaded as EEG")
        participants[participant] = {"group_id": group}
        recordings[f"{participant}_{session}"] = {
            "participant_id": participant, "source_id": source_id,
            "session_id": session, "raw_file": str(raw_file),
        }
    extra = Path(sources["control_visit1"]["raw_input_folder"]) / "P99.bdf"
    extra.write_bytes(b"Unregistered source that must not be discovered on open")
    manifest = {
        "groups_locked": True, "groups": groups, "participants": participants,
        "sessions": {"visit1": {"label": "Baseline", "visit_index": 1},
                     "visit2": {"label": "Follow-up", "visit_index": 2}},
        "recording_sources": sources, "recordings": recordings,
        "input_folder": str(tmp_path / "raw"), "preprocessing": {},
        "subfolders": {"excel": "excel"},
    }
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return SimpleNamespace(project_root=tmp_path, **manifest), manifest_path, extra


@pytest.mark.parametrize("missing_registered", [False, True])
def test_locked_project_open_uses_only_existing_registered_uneven_visits(tmp_path, monkeypatch, missing_registered):
    from Main_App.projects import project_recording_context

    project, manifest_path, extra = _registered_open_project(tmp_path)
    registered = [recording.raw_file for recording in project_recording_context(project).recordings]
    if missing_registered:
        registered[-1].unlink()
    existing = [path for path in registered if path.is_file()]
    before = manifest_path.read_bytes()
    discover = Mock(side_effect=AssertionError("Project opening must not run processing discovery"))
    paths_for_open = _load_function(
        "src/Main_App/gui/project_workflows.py", "_raw_paths_for_project_open",
        {"project_recording_context": project_recording_context, "prepare_batch_files": discover},
    )
    monkeypatch.setattr(Path, "glob", Mock(side_effect=AssertionError("Do not scan raw folders on open")))
    monkeypatch.setattr(Path, "rglob", Mock(side_effect=AssertionError("Do not recurse raw folders on open")))

    assert paths_for_open(project) == existing
    discover.assert_not_called()
    assert extra not in existing
    assert manifest_path.read_bytes() == before
    assert set(project.recordings) == {"P1_visit1", "P1_visit2", "P2_visit1", "P3_visit1"}


@pytest.mark.parametrize("repeated, locked", [(False, False), (False, True), (True, False)])
def test_project_open_keeps_existing_strict_discovery_for_other_projects(tmp_path, repeated, locked):
    from Main_App.projects import project_recording_context

    project, manifest_path, _extra = _registered_open_project(tmp_path)
    project.groups_locked = locked
    if not repeated:
        project.sessions = {}
        project.recording_sources = {}
        project.recordings = {}
    before = manifest_path.read_bytes()
    expected = [tmp_path / "existing.bdf"]
    discover = Mock(return_value=expected)
    paths_for_open = _load_function(
        "src/Main_App/gui/project_workflows.py", "_raw_paths_for_project_open",
        {"project_recording_context": project_recording_context, "prepare_batch_files": discover},
    )

    assert paths_for_open(project) == expected
    discover.assert_called_once_with(project)
    discover.side_effect = ValueError("Strict source discovery failed")
    with pytest.raises(ValueError, match="Strict source discovery failed"):
        paths_for_open(project)
    assert manifest_path.read_bytes() == before


def test_project_open_discovery_failure_keeps_context_and_reports_actual_cause(tmp_path):
    project, manifest_path, _extra = _registered_open_project(tmp_path)
    project.input_folder = Path(project.input_folder)
    before = manifest_path.read_bytes()
    messages = Mock()
    loaded = Mock(side_effect=lambda host, current: setattr(host, "currentProject", current))
    error = "Processed project recording assignments are locked; P99.bdf is not registered"
    namespace = {
        "_load_project": loaded,
        "_raw_paths_for_project_open": Mock(side_effect=ValueError(error)),
        "logger": logging.getLogger(__name__), "logging": logging,
        "QMessageBox": messages, "SimpleNamespace": SimpleNamespace,
        "project_group_context": lambda _project: SimpleNamespace(has_group_metadata=False, groups=()),
        "sync_input_folder_display": Mock(),
        "normalize_preprocessing_settings": lambda settings: settings,
        "QLineEdit": lambda value: SimpleNamespace(text=lambda: value),
    }
    load = _load_function("src/Main_App/gui/project_workflows.py", "load_project", namespace)
    host = SimpleNamespace(log=Mock(), data_paths=["stale_previous_project.bdf"])

    load(host, project, lambda edit: edit)

    loaded.assert_called_once_with(host, project)
    assert host.currentProject is project
    assert host.data_paths == []
    messages.critical.assert_not_called()
    messages.warning.assert_not_called()
    logged = [str(call.args[0]) for call in host.log.call_args_list]
    assert any(error in message for message in logged)
    assert not any("no .bdf files found" in message.lower() for message in logged)
    assert host.save_folder_path.get() == str(tmp_path / "excel")
    assert hasattr(host, "max_bad_channels_alert_entry")
    namespace["sync_input_folder_display"].assert_called_once_with(host)
    assert manifest_path.read_bytes() == before


def _registration_validation_harness(tmp_path, *, mode="Batch", additions=True):
    """Drive the real GUI orchestration without widgets or EEG processing."""
    project = SimpleNamespace(
        project_root=tmp_path, groups_locked=True, subfolders={"excel": "excel"},
        preprocessing={}, recordings={"P1_visit1": {"participant_id": "P1"}},
    )
    manifest = tmp_path / "project.json"
    manifest.write_text(json.dumps({"recordings": project.recordings}), encoding="utf-8")
    old = SimpleNamespace(path=tmp_path / "P1.bdf", processing_id="P1_visit1")
    new = SimpleNamespace(path=tmp_path / "P2.bdf", processing_id="P2_visit2")
    new_row = SimpleNamespace(participant_id="P2", group_id="control", group_label="Control",
                              session_id="visit2", session_label="Follow-up", raw_file=new.path,
                              recording_id="P2_visit2", status="New participant and recording")
    selected = (new,) if mode == "Single" else (old, new)
    proposal = SimpleNamespace(files=selected, source_files=(old, new),
                               review_rows=(new_row,) if additions else (), manifest_sha256="frozen")
    timeline = []
    messages = Mock()
    host = SimpleNamespace(
        currentProject=project, data_paths=[str(new.path if mode == "Single" else old.path)],
        file_mode=SimpleNamespace(get=lambda: mode), log=Mock(),
        _build_validated_params=Mock(side_effect=lambda: timeline.append("params") or {"event_id_map": {"Faces": 1}}),
        review_recording_additions_for_processing=Mock(side_effect=lambda *_: timeline.append("confirm") or True),
        run_preprocessing_qc_workflow=Mock(),
    )
    namespace = {
        "_ensure_removed_electrode_detection_choice_ready": lambda _: True,
        "Path": Path, "SimpleNamespace": SimpleNamespace, "logging": logging,
        "logger": logging.getLogger(__name__), "QMessageBox": messages,
        "prepare_raw_registration_review": Mock(return_value=proposal),
        "commit_raw_registration_review": Mock(side_effect=lambda *_: timeline.append("commit") or list(selected)),
        "prepare_batch_file_infos": Mock(side_effect=AssertionError("Strict discovery must not run before addition review")),
        "raw_file_info_for_path": Mock(side_effect=AssertionError("Locked selection must use staged discovery")),
        "project_recording_context": lambda _: SimpleNamespace(is_repeated_session=True),
        "validate_repeated_recording_sources_for_processing": Mock(side_effect=lambda *_: timeline.append("preflight")),
        "review_recording_additions_for_processing": Mock(),
        "participant_review_rows": Mock(), "register_participants": Mock(),
        "review_participants_for_processing": Mock(),
        "_planning_settings_from_params": lambda params: (params, params["event_id_map"]),
        "classify_processing_inputs": Mock(side_effect=lambda *_: timeline.append("plan") or SimpleNamespace(states=[])),
        "PREPROCESSING_CANONICAL_KEYS": (), "FFT_MULTINOTCH_METHOD_VERSION": "unchanged",
        "FFT_MULTINOTCH_HALF_WIDTH_HZ": 1, "FFT_MULTINOTCH_COMPONENT_COUNT": 1,
    }
    validate = _load_function("src/Main_App/gui/processing_inputs.py", "validate_inputs", namespace)
    return validate, host, proposal, namespace, timeline, manifest


@pytest.mark.parametrize("mode", ["Batch", "Single"])
def test_processing_confirms_additions_once_before_planning_exact_selected_files(tmp_path, mode):
    validate, host, proposal, namespace, timeline, _manifest = _registration_validation_harness(tmp_path, mode=mode)

    assert validate(host) is True

    assert timeline == ["preflight", "params", "confirm", "commit", "plan"]
    host.review_recording_additions_for_processing.assert_called_once_with(host, proposal.review_rows)
    namespace["commit_raw_registration_review"].assert_called_once_with(host.currentProject, proposal)
    assert namespace["validate_repeated_recording_sources_for_processing"].call_args.args[1] == proposal.source_files
    assert namespace["classify_processing_inputs"].call_args.args[1] == list(proposal.files)
    assert host.data_paths == [str(info.path) for info in proposal.files]
    assert host._processing_raw_file_infos == list(proposal.files)
    namespace["participant_review_rows"].assert_not_called()
    namespace["register_participants"].assert_not_called()
    host.run_preprocessing_qc_workflow.assert_not_called()
    namespace["QMessageBox"].critical.assert_not_called()


@pytest.mark.parametrize("outcome", ["cancel", "stale_manifest", "save_failure", "project_changed"])
def test_addition_review_cancel_or_failure_never_plans_or_saves_through_generic_registration(tmp_path, outcome):
    validate, host, _proposal, namespace, timeline, manifest = _registration_validation_harness(tmp_path)
    before = manifest.read_bytes()
    initial_paths = list(host.data_paths)
    if outcome == "cancel":
        host.review_recording_additions_for_processing.side_effect = lambda *_: False
    elif outcome == "project_changed":
        host.review_recording_additions_for_processing.side_effect = lambda *_: setattr(host, "currentProject", object()) or True
    else:
        exception = ValueError("Project changed after the review opened") if outcome == "stale_manifest" else OSError("Project folder is read-only")
        namespace["commit_raw_registration_review"].side_effect = exception

    assert validate(host) is False

    assert "plan" not in timeline
    namespace["classify_processing_inputs"].assert_not_called()
    namespace["register_participants"].assert_not_called()
    namespace["participant_review_rows"].assert_not_called()
    host.run_preprocessing_qc_workflow.assert_not_called()
    assert host.data_paths == initial_paths
    assert manifest.read_bytes() == before
    if outcome in {"cancel", "project_changed"}:
        namespace["commit_raw_registration_review"].assert_not_called()
    if outcome == "cancel":
        namespace["QMessageBox"].critical.assert_not_called()
    else:
        namespace["QMessageBox"].critical.assert_called_once()
        message = namespace["QMessageBox"].critical.call_args.args[2]
        expected = {"stale_manifest": "Project changed", "save_failure": "read-only",
                    "project_changed": "active project changed"}[outcome]
        assert expected in message


def test_addition_source_conflict_stops_before_confirmation_or_registration(tmp_path):
    validate, host, _proposal, namespace, _timeline, manifest = _registration_validation_harness(tmp_path)
    before = manifest.read_bytes()
    namespace["prepare_raw_registration_review"].side_effect = ValueError("Stable group assignment conflict")

    assert validate(host) is False

    host.review_recording_additions_for_processing.assert_not_called()
    namespace["commit_raw_registration_review"].assert_not_called()
    namespace["classify_processing_inputs"].assert_not_called()
    assert "Stable group assignment conflict" in namespace["QMessageBox"].critical.call_args.args[2]
    assert manifest.read_bytes() == before


def test_no_new_recordings_continues_without_a_redundant_confirmation(tmp_path):
    validate, host, _proposal, _namespace, timeline, _manifest = _registration_validation_harness(tmp_path, additions=False)

    assert validate(host) is True

    host.review_recording_additions_for_processing.assert_not_called()
    assert timeline == ["preflight", "params", "commit", "plan"]


def test_single_file_picker_stages_extra_file_without_confirming_or_saving(tmp_path):
    chosen = tmp_path / "P2.bdf"
    project = SimpleNamespace(groups_locked=True)
    stage = Mock(return_value=SimpleNamespace(files=(SimpleNamespace(path=chosen),)))
    namespace = {
        "Path": Path, "raw_selection_start_folder": lambda _: tmp_path,
        "QFileDialog": SimpleNamespace(getOpenFileName=lambda *_: (str(chosen), "")),
        "QMessageBox": Mock(), "prepare_raw_registration_review": stage,
        "raw_file_info_for_path": Mock(side_effect=AssertionError("Do not require registration just to select")),
    }
    select = _load_function("src/Main_App/gui/processing_inputs.py", "select_single_file", namespace)
    host = SimpleNamespace(currentProject=project, le_input_file=Mock(), log=Mock(), _update_start_enabled=Mock())

    select(host)

    stage.assert_called_once_with(project, selected_path=chosen)
    assert host.data_paths == [str(chosen)]
    assert host._selected_bdf == str(chosen)
    host.le_input_file.setText.assert_called_once_with(str(chosen))
    assert not namespace["QMessageBox"].mock_calls
