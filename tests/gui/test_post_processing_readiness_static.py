"""Exercise the actual tool guard and preflight decisions without loading Qt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.processing import frequency_domain_qc
from Main_App.projects.preprocessing_settings import normalize_manual_excluded_participant_conditions


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_function(relative_path, name, namespace, *, class_name=None):
    path = REPO_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = tree if class_name is None else next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    function = next(node for node in owner.body if getattr(node, "name", None) == name)
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("reason", [
    "Frequency review is blocked: P9/Neutral Angry has no condition occurrence.",
    "Kurtosis review decisions changed.",
    "",
])
def test_tool_guard_displays_persisted_cause_instead_of_guessing(tmp_path, reason):
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    frequency_domain_qc.mark_frequency_domain_outputs_stale(tmp_path, reason=reason)
    guard = _load_function(
        "src/Main_App/gui/main_window.py", "_frequency_domain_outputs_ready_for_tool",
        {"logger": logging.getLogger(__name__)}, class_name="MainWindow",
    )
    host = SimpleNamespace(
        currentProject=SimpleNamespace(project_root=tmp_path),
        request_post_processing_rebuild=Mock(),
    )

    assert not guard(host, "SNR Plots")
    args = host.request_post_processing_rebuild.call_args.args
    assert args == (
        "SNR Plots",
        reason or "The project's analysis outputs need a completed post-processing run.",
        str(tmp_path),
    )

    frequency_domain_qc.mark_frequency_domain_outputs_current(tmp_path)
    host.request_post_processing_rebuild.reset_mock()
    assert guard(host, "SNR Plots")
    host.request_post_processing_rebuild.assert_not_called()


@pytest.mark.parametrize("choice", ["cancel", "skip", None])
def test_missing_condition_cannot_bypass_preflight_decision(choice):
    audit = SimpleNamespace(review_candidates=[SimpleNamespace(repetition_count=0)])
    build_audit = Mock(return_value=audit)
    await_choice = Mock(return_value=choice)
    namespace = {
        "normalize_manual_excluded_participant_conditions": lambda value: value or {},
        "normalize_manual_excluded_recording_conditions": lambda value: value or {},
        "normalize_manual_excluded_participants": lambda value: value or [],
        "normalize_manual_excluded_recordings": lambda value: value or [],
        "build_preflight_condition_crop_grid_audit": build_audit,
        "_recording_aware": lambda _: False,
        "_show_data_quality_notice": Mock(), "_begin_preflight_page": Mock(),
        "_set_label": Mock(), "_set_preflight_table": Mock(),
        "_condition_crop_review_rows": Mock(return_value=[]),
        "_await_preflight_choice": await_choice,
        "_CONFIRM_CONDITION_EXCLUSIONS_STEP": 3,
        "_CONDITION_EXCLUSION_CHECK_COLUMN": 6,
    }
    confirm = _load_function(
        "src/Main_App/gui/preprocessing_qc_workflow.py", "_confirm_condition_crop_exclusions", namespace,
    )
    params = {"event_id_map": {"Neutral Angry": 12}}
    assert not confirm(SimpleNamespace(), params, object(), {})
    assert build_audit.call_args.kwargs["expected_event_map"] == params["event_id_map"]
    actions = await_choice.call_args.args[1]
    assert ("Cancel Processing", "cancel", "secondary") in actions
    assert all(action[1] != "skip" for action in actions)


def test_missing_condition_is_not_selected_when_review_table_is_unavailable():
    candidates = [SimpleNamespace(repetition_count=0, pair_key=("p9", "neutral angry"))]
    for name, expected in [
        ("_checked_condition_crop_pairs", set()),
        ("_checked_condition_crop_scopes", (set(), set())),
    ]:
        checked = _load_function(
            "src/Main_App/gui/preprocessing_qc_workflow.py", name, {},
        )
        assert checked(SimpleNamespace(), candidates) == expected


def test_missing_condition_all_visits_choice_saves_participant_scope():
    replace_exclusions = _load_function(
        "src/Main_App/gui/preprocessing_qc_workflow.py", "_replace_reviewed_condition_exclusions",
        {"normalize_manual_excluded_participant_conditions": normalize_manual_excluded_participant_conditions},
    )
    candidates = [
        SimpleNamespace(
            participant_id="P9", condition_label="Neutral Angry",
            pair_key=("p9-v1", "neutral angry"),
            participant_pair_key=("p9", "neutral angry"),
        ),
    ]
    updated = replace_exclusions(
        {"P2": ["Faces"]}, candidates, {("p9", "neutral angry")},
    )
    assert updated == {"P2": ["Faces"], "P9": ["Neutral Angry"]}
    assert replace_exclusions(updated, candidates, set()) == {"P2": ["Faces"]}


class _ActionButton:
    def __init__(self):
        self.text = "Stop Processing"
        self.enabled = True
        self.tooltip = "Original action help"

    def setText(self, value):
        self.text = value

    def setEnabled(self, value):
        self.enabled = value

    def setToolTip(self, value):
        self.tooltip = value

    def toolTip(self):
        return self.tooltip


@pytest.mark.parametrize("outcome", [
    "complete", "optional_failure", "required_failure", "review", "start_failure",
])
def test_postprocessing_action_cannot_offer_stop_and_restores_help_before_handoff(
    monkeypatch, outcome,
):
    """Execute the orchestration closure while all Qt/runtime owners are doubles."""
    module = ModuleType("Main_App.workers.post_processing_pipeline_worker")

    def signal():
        return SimpleNamespace(connect=Mock())

    worker = SimpleNamespace(
        moveToThread=Mock(), run=Mock(), deleteLater=Mock(),
        progress=signal(), phase_progress=signal(), log_message=signal(), finished=signal(),
    )
    module.PostProcessingPipelineWorker = Mock(return_value=worker)
    module.POST_PROCESSING_PHASE_COUNT = 5
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(frequency_domain_qc, "mark_frequency_domain_outputs_current", Mock())
    button = _ActionButton()
    thread = SimpleNamespace(started=signal(), finished=signal(), quit=Mock(), deleteLater=Mock())
    observed = []

    def start_thread():
        observed.append((button.text, button.enabled, button.tooltip))
        if outcome == "start_failure":
            raise RuntimeError("Thread could not start")

    thread.start = start_thread
    bridge = SimpleNamespace(
        handle_progress=Mock(), handle_phase_progress=Mock(), handle_log_message=Mock(),
        handle_finished=Mock(), deleteLater=Mock(),
    )
    bridge_factory = Mock(return_value=bridge)
    project = SimpleNamespace(project_root=Path("project"))
    host = SimpleNamespace(currentProject=project, btn_start=button, log=Mock())
    cache, finish, review = Mock(), Mock(), Mock()
    delayed = []
    namespace = {
        "os": SimpleNamespace(getenv=lambda _: None), "QThread": lambda _: thread,
        "shell_status": SimpleNamespace(prepare_post_processing_activity=Mock()),
        "_PostProcessingPipelineBridge": bridge_factory, "logging": logging,
        "logger": logging.getLogger(__name__),
        "_post_processing_source_map_outcome": lambda _: (False, False),
        "_post_processing_frequency_domain_outputs_ready": lambda _: outcome in {"complete", "optional_failure"},
        "_post_processing_failure_reason": lambda _: "Incomplete inputs" if outcome == "required_failure" else "",
        "_sync_project_tools_metadata_from_disk": Mock(),
        "_handle_frequency_domain_qc_review": review,
        "QTimer": SimpleNamespace(singleShot=lambda _delay, callback: delayed.append(callback)),
        "_POST_PROCESSING_PROGRESS_SETTLE_MS": 1,
    }
    start = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_start_post_processing_pipeline_after_processing", namespace,
    )

    assert start(host, on_finished=finish, provisional_cache=cache) == (outcome != "start_failure")
    assert observed == [(
        "Preparing Outputs…", False,
        "Post-processing must finish before another action can start.",
    )]
    worker.run.assert_not_called()
    if outcome == "start_failure":
        assert host._post_processing_failure_reason == "Post-processing could not start: Thread could not start"
        assert button.tooltip == "Original action help"
        assert host._post_processing_pipeline_thread is None
        assert host._post_processing_pipeline_worker is None
        assert host._post_processing_pipeline_bridge is None
        assert not delayed
        cache.clear.assert_called_once()
        worker.deleteLater.assert_called_once()
        bridge.deleteLater.assert_called_once()
        thread.deleteLater.assert_called_once()
        review.assert_not_called()
        finish.assert_not_called()  # False return hands recovery back to the caller.
        return
    result = {"ok": outcome == "complete", "steps": []}
    if outcome == "review":
        result.update(requires_frequency_domain_qc_review=True, frequency_domain_qc_report={"flags": []})
    bridge_factory.call_args.kwargs["finished_callback"](result)

    assert button.tooltip == "Original action help"
    assert button.enabled is False  # Only the existing handoff/finalizer may unlock it.
    assert host._post_processing_pipeline_thread is None
    assert host._post_processing_pipeline_worker is None
    assert host._post_processing_pipeline_bridge is None
    bridge.deleteLater.assert_called_once()
    if outcome == "review":
        review.assert_called_once_with(
            host, project, result["frequency_domain_qc_report"],
            on_finished=finish, provisional_cache=cache,
        )
        assert not delayed
        cache.clear.assert_not_called()
    else:
        review.assert_not_called()
        cache.clear.assert_called_once()
        finish.assert_not_called()
        assert len(delayed) == 1
        delayed[0]()
        finish.assert_called_once()


@pytest.mark.parametrize("started", [False, True])
def test_resume_action_is_locked_before_start_and_finalizer_restores_start(started):
    button = _ActionButton()
    host = SimpleNamespace(
        currentProject=object(), btn_start=button, log=Mock(),
        _busy_start=Mock(), _busy_stop=Mock(),
        _update_start_enabled=lambda: button.setEnabled(True),
    )
    host._set_controls_enabled = lambda enabled: button.setEnabled(enabled)
    namespace = {"logging": logging, "logger": logging.getLogger(__name__)}
    pending = _load_function(
        "src/Main_App/gui/processing_workflows.py", "_set_resume_post_processing_pending", namespace,
    )
    captured = []

    def start(_host, *, on_finished):
        assert button.text == "Preparing Outputs…"
        assert button.enabled is False
        assert host._run_active and host.busy
        captured.append(on_finished)
        return started

    namespace.update(
        _set_resume_post_processing_pending=pending,
        _start_post_processing_pipeline_after_processing=start,
    )
    resume = _load_function("src/Main_App/gui/processing_workflows.py", "resume_post_processing", namespace)
    finished = Mock()
    resume(host, on_finished=finished)
    if started:
        finished.assert_not_called()
        assert button.enabled is False
        captured[0]()
    finished.assert_called_once()
    host._busy_stop.assert_called_once()
    assert button.text == "Start Processing"
    assert button.enabled is True
    assert not host._run_active and not host.busy
