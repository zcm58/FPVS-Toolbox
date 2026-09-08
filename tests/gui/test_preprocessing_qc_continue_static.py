"""Exercise clear QC step acknowledgements without importing or executing Qt."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / "src/Main_App/gui/preprocessing_qc_workflow.py"
)


def _review_namespace():
    names = {
        "_show_clear_preflight_step",
        "_review_marker_occurrences",
        "_confirm_condition_crop_exclusions",
        "_confirm_hard_exclusions",
        "_review_removed_electrodes",
        "_review_removed_electrodes_by_recording",
    }
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *[
                node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names
            ],
        ],
        type_ignores=[],
    )
    calls = SimpleNamespace(pages=[], labels={}, tables=[], actions=[], notices=[])
    namespace = {
        "_begin_preflight_page": lambda _host, **kwargs: calls.pages.append(kwargs),
        "_set_label": lambda _host, name, text: calls.labels.update({name: text}),
        "_set_preflight_table": lambda _host, headers, rows, **kwargs: calls.tables.append(
            (headers, rows, kwargs)
        ),
        "_await_preflight_choice": lambda _host, actions: (
            calls.actions.append(actions) or "continue"
        ),
        "_show_data_quality_notice": lambda *_args: calls.notices.append(_args),
        "_REVIEW_MARKER_OCCURRENCES_STEP": 2,
        "_CONFIRM_CONDITION_EXCLUSIONS_STEP": 3,
        "_CONFIRM_REMOVED_ELECTRODES_STEP": 4,
        "_CONFIRM_PARTICIPANT_EXCLUSIONS_STEP": 5,
        "MarkerOccurrenceReviewError": ValueError,
        "collect_marker_occurrence_reviews": lambda _scan: (),
        "_participant_group_display_map": lambda *_args: {},
        "normalize_manual_excluded_participant_conditions": lambda value: value or {},
        "normalize_manual_excluded_recording_conditions": lambda value: value or {},
        "normalize_manual_excluded_participants": lambda value: value or [],
        "normalize_manual_excluded_recordings": lambda value: value or [],
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    return namespace, calls


@pytest.mark.parametrize("step", [2, 3, 5])
def test_clear_checks_wait_for_one_continue_without_changing_decisions(step):
    namespace, calls = _review_namespace()
    scan = SimpleNamespace(results=(object(), object()), hard_exclusion_candidates=())
    params = {
        "manual_excluded_participants": ["P9"],
        "manual_excluded_participant_conditions": {"P1": ["Oddball"]},
    }
    original = deepcopy(params)
    audit = SimpleNamespace(
        review_candidates=(),
        observations=(
            SimpleNamespace(already_excluded=False),
            SimpleNamespace(already_excluded=True),
        ),
    )
    namespace["build_preflight_condition_crop_grid_audit"] = lambda *_args, **_kwargs: audit
    # No project is available: clear steps must never try to save settings.
    host = object()

    if step == 2:
        assert namespace["_review_marker_occurrences"](host, [], params, scan, {}) is scan
    elif step == 3:
        assert namespace["_confirm_condition_crop_exclusions"](host, params, scan, {}) is True
    else:
        assert namespace["_confirm_hard_exclusions"](host, params, scan, {}) == set()

    assert params == original
    assert len(calls.pages) == 1
    assert calls.pages[0]["step"] == step
    assert calls.pages[0]["busy"] is False
    assert calls.pages[0]["review_visible"] is True
    assert calls.pages[0]["progress_visible"] is False
    assert calls.actions == [(("Continue", "continue", "primary"),)]
    assert calls.notices == []
    if step == 3:
        assert dict(calls.tables[0][1]) == {
            "Condition entries in crop audit": "2",
            "Condition entries already excluded": "1",
            "Condition decisions needed": "0",
        }
    else:
        assert dict(calls.tables[0][1])["Recordings in scan"] == "2"


def test_marker_findings_keep_their_review_without_an_extra_clear_step():
    namespace, calls = _review_namespace()
    namespace["collect_marker_occurrence_reviews"] = lambda _scan: (SimpleNamespace(participant_id="P01"),)
    namespace["_show_marker_occurrence_review"] = lambda *_args, **_kwargs: "cancel"

    assert namespace["_review_marker_occurrences"](object(), [], {}, object(), {}) is None
    assert calls.pages == []
    assert calls.actions == []


@pytest.mark.parametrize("recording_mode", [False, True])
def test_no_removed_flags_keep_editable_review_without_intro_modal(recording_mode):
    namespace, calls = _review_namespace()
    namespace.update(
        _recording_aware=lambda _infos: recording_mode,
        normalize_manual_removed_electrodes_map=lambda value: value or {},
        _participant_group_display_map=lambda *_args: {},
        _filter_removed_map_for_participants=lambda values, _ids: values,
        _removed_review_row_values=lambda *_args: [],
        _removed_review_reason_map=lambda _scan: {},
        project_recording_coverage_rows=lambda *_args: (),
        _REMOVED_REVIEW_HEADERS=("Participant", "Flags", "Manual additions"),
        _REMOVED_REVIEW_AUTO_COLUMN=2,
        _REMOVED_REVIEW_MANUAL_COLUMN=4,
        _REMOVED_REVIEW_REASON_COLUMN=3,
    )

    def cancel(_host, actions):
        calls.actions.append(actions)
        return "cancel"

    namespace["_await_preflight_choice"] = cancel
    host = SimpleNamespace(currentProject=object())
    scan = SimpleNamespace(suggested_removed_electrodes={})
    assert namespace["_review_removed_electrodes"](host, [], {}, scan, {}) is False

    assert len(calls.pages) == 1
    assert calls.pages[0]["step"] == 4
    assert calls.tables[0][2]["editable_columns"] == ((6, 8) if recording_mode else (2, 4))
    assert len(calls.actions) == 1
    assert calls.actions[0][0] == ("Save / Next", "save", "primary")
    assert "No removed-electrode candidates were flagged." in calls.labels["processing_summary_label"]
    assert calls.notices == []
