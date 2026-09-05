"""Exercise the actual tool guard and preflight decisions without loading Qt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
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
