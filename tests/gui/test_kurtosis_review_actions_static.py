"""Execute the real bulk-review methods without importing or running Qt."""

from __future__ import annotations

import ast
from copy import deepcopy
import math
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest


DIALOG_PATH = Path(__file__).resolve().parents[2] / "src/Main_App/gui/kurtosis_review_dialog.py"
METHODS = (
    "_selected_automatic_rows", "_pending_manual_rows", "_selected_pending_rows",
    "_mark_all_flagged", "_apply_selected_pending", "_apply_bulk_decision",
    "_discard_bulk_undo", "_undo_bulk_edit", "_next_undecided", "_refresh_action_scope",
    "_repair_context",
)


class Control:
    def __init__(self, index=0, text="", checked=False):
        self.index, self.value, self.checked = index, text, checked
        self.enabled = True

    def currentIndex(self):
        return self.index

    def currentData(self):
        return ("", "approve", "reject", "experimental_auto")[self.index]

    def findData(self, value):
        return ("", "approve", "reject", "experimental_auto").index(value)

    def setCurrentIndex(self, index):
        self.index = index

    def isChecked(self):
        return self.checked

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value

    def setEnabled(self, enabled):
        self.enabled = enabled


class Table:
    def __init__(self):
        self.hidden = {4, 9}
        self.selected = set()
        self.current = 0
        self.scrolled = []

    def isRowHidden(self, row):
        return row in self.hidden

    def currentRow(self):
        return self.current

    def selectionModel(self):
        return SimpleNamespace(selectedRows=lambda: [
            SimpleNamespace(row=lambda value=value: value) for value in self.selected
        ])

    def setCurrentCell(self, row, _column):
        self.current = row

    def item(self, row, column):
        return (row, column)

    def scrollToItem(self, item):
        self.scrolled.append(item)


@pytest.fixture
def state():
    tree = ast.parse(DIALOG_PATH.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "KurtosisReviewDialog")
    nodes = [node for node in owner.body if isinstance(node, ast.FunctionDef)
             and node.name in METHODS]
    assert {node.name for node in nodes} == set(METHODS)
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {"math": math, "KURTOSIS_DECISION_APPROVE": "approve", "KurtosisReviewItem": object}
    exec(compile(ast.fix_missing_locations(module), str(DIALOG_PATH), "exec"), namespace)
    # Pending, decided, automatic, invalid, boundary, negative and hidden cases.
    identities = (
        ("P1", "Cz", 6.0), ("P1", "Pz", 7.0), ("P2", "T7", 8.0),
        ("P2", "Oz", 9.0), ("P3", "Fz", 15.0), ("P3", "C3", None),
        ("P3", "C4", math.nan), ("P4", "O1", 5.0), ("P4", "O2", -6.0),
        ("P5", "Fp1", 8.0),
    )
    items = tuple(SimpleNamespace(
        recording_id=recording, channel=channel, signed_normalized_score=score,
        threshold=5.0, analyzed_conditions=("Faces", "Objects"),
    ) for recording, channel, score in identities)
    current = SimpleNamespace(
        _items=items, table=Table(), _automatic_rows=frozenset({4}),
        _all_flag_rows=frozenset({0, 1, 2, 3, 4, 8, 9}),
        auto_checkbox=Control(checked=True), auto_all_checkbox=Control(),
        selected_decision=Control(index=1), selected_button=Control(),
        mark_all_button=Control(), undo_button=Control(), inspect_button=Control(),
        support_button=Control(), scope_label=Control(), _project_root=Path("project"),
        _manual_indices={4: 2}, _bulk_undo=(),
        _current_receipts={"old": {"Cz": {"decision": "reject", "reason": "retained"}}},
    )
    current._decision_controls = {
        (item.recording_id.casefold(), item.channel.casefold()): Control(index=index)
        for item, index in zip(items, (0, 0, 2, 1, 3, 0, 0, 0, 0, 0), strict=True)
    }
    current._reason_controls = {
        (item.recording_id.casefold(), item.channel.casefold()): Control(text=f"Evidence note {row}")
        for row, item in enumerate(items)
    }
    for name in METHODS:
        setattr(current, name, MethodType(namespace[name], current))
    return current


def _indices(state):
    return tuple(control.currentIndex() for control in state._decision_controls.values())


def _reasons(state):
    return tuple(control.text() for control in state._reason_controls.values())


def test_interpolate_all_changes_only_visible_undecided_valid_flags(state):
    before_reasons = _reasons(state)
    before_receipts = deepcopy(state._current_receipts)
    assert state._pending_manual_rows() == (0, 1, 8)
    state._mark_all_flagged()
    assert _indices(state) == (1, 1, 2, 1, 3, 0, 0, 0, 1, 0)
    assert _reasons(state) == before_reasons
    assert state._current_receipts == before_receipts
    assert state._manual_indices == {4: 2}
    assert state.auto_checkbox.isChecked()
    assert not state.auto_all_checkbox.isChecked()


@pytest.mark.parametrize("decision_index", [1, 2])
def test_selected_action_never_changes_unselected_decided_hidden_or_invalid_rows(state, decision_index):
    state.table.selected = {0, 2, 4, 5, 8, 9}
    state.selected_decision.setCurrentIndex(decision_index)
    reasons = _reasons(state)
    assert state._selected_pending_rows() == (0, 8)
    state._apply_selected_pending()
    assert _indices(state) == (decision_index, 0, 2, 1, 3, 0, 0, 0, decision_index, 0)
    assert _reasons(state) == reasons
    assert tuple(row for row, _index, _reason in state._bulk_undo) == (0, 8)


def test_automatic_rows_remain_excluded_when_made_visible(state):
    state.table.hidden.remove(4)
    state.table.selected = {4}
    state._apply_selected_pending()
    assert state._bulk_undo == ()
    assert _indices(state)[4] == 3
    assert state._pending_manual_rows() == (0, 1, 8)


def test_auto_all_policy_is_never_replaced_by_bulk_manual_decisions(state):
    state.auto_all_checkbox.checked = True
    state.table.selected = set(range(len(state._items)))
    before = _indices(state)
    state._mark_all_flagged()
    assert _indices(state) == before
    assert state._bulk_undo == ()
    assert state.auto_all_checkbox.isChecked()


def test_undo_restores_exact_draft_and_does_not_change_existing_decisions_or_receipts(state):
    before = (_indices(state), _reasons(state), deepcopy(state._current_receipts))
    state.table.selected = {0, 8}
    state._apply_selected_pending()
    assert state.undo_button.enabled
    state._undo_bulk_edit()
    assert (_indices(state), _reasons(state), state._current_receipts) == before
    assert not state.undo_button.enabled
    assert state._bulk_undo == ()
    state._undo_bulk_edit()
    assert _indices(state) == before[0]


def test_empty_action_preserves_previous_undo_and_latest_bulk_undo_is_one_level(state):
    state.table.selected = {0}
    state._apply_selected_pending()
    first = state._bulk_undo
    state._apply_selected_pending()
    assert state._bulk_undo == first
    state.table.selected = {1}
    state._apply_selected_pending()
    state._undo_bulk_edit()
    assert _indices(state)[:2] == (1, 0)


def test_manual_edit_discard_prevents_undo_overwriting_the_new_draft(state):
    state._mark_all_flagged()
    control = state._decision_controls[("p1", "cz")]
    reason = state._reason_controls[("p1", "cz")]
    control.setCurrentIndex(2)
    reason.setText("New deliberate manual choice")
    state._discard_bulk_undo()
    state._undo_bulk_edit()
    assert control.currentData() == "reject"
    assert reason.text() == "New deliberate manual choice"
    assert not state.undo_button.enabled


def test_user_edit_signals_invalidate_undo_but_programmatic_bulk_updates_do_not():
    tree = ast.parse(DIALOG_PATH.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "KurtosisReviewDialog")
    build = next(node for node in owner.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_build_ui")
    connections = {
        ast.unparse(node.func.value) for node in ast.walk(build)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect" and len(node.args) == 1
        and ast.unparse(node.args[0]) == "self._discard_bulk_undo"
    }
    assert connections == {
        "decision.activated", "reason.textEdited", "self.auto_checkbox.clicked",
        "self.auto_all_checkbox.clicked",
    }


def test_next_undecided_visits_invalid_statistics_and_wraps_past_automatic_rows(state):
    state._mark_all_flagged()
    state.table.current = 3
    state._next_undecided()
    assert state.table.current == 5
    state._next_undecided()
    assert state.table.current == 6
    state.table.current = 9
    state._next_undecided()
    assert state.table.current == 5
    assert state.table.scrolled[-1] == (5, 0)


def test_next_undecided_no_pending_rows_is_a_noop(state):
    for control in state._decision_controls.values():
        control.setCurrentIndex(1)
    state.table.current = 2
    state._next_undecided()
    assert state.table.current == 2
    assert state.table.scrolled == []


def test_action_consequences_count_unique_recordings_and_exclude_hidden_rows(state):
    state.table.selected = {0, 1, 2, 4, 5, 8, 9}
    state._refresh_action_scope()
    text = state.scope_label.text()
    assert "3 undecided electrode(s) across 2 recording(s)" in text
    assert "All undecided: 3 electrode(s) across 2 recording(s)" in text
    assert "0 hidden rows" in text
    assert "every analyzed condition" in text
    assert state.selected_button.enabled and state.mark_all_button.enabled
    state.table.selected = {2, 4, 5, 9}
    state._refresh_action_scope()
    assert not state.selected_button.enabled
    assert state.mark_all_button.enabled


def test_inspection_actions_require_current_row_and_source_context(state):
    state._refresh_action_scope()
    assert state.inspect_button.enabled and state.support_button.enabled
    state._project_root = None
    state._refresh_action_scope()
    assert not state.inspect_button.enabled
    assert state.support_button.enabled
    state.table.current = -1
    state._refresh_action_scope()
    assert not state.inspect_button.enabled and not state.support_button.enabled


@pytest.fixture
def repair_state(state):
    retained = ("Cz", "Pz", "T7", "Oz", "Fz", "C3", "Fp1", "AF7")
    state._items = tuple(SimpleNamespace(
        recording_id=recording, channel=channel,
        evidence={"geometry_identity": {"retained_scalp_channels": list(retained)}},
        signal_view={"upstream_bad_channels": ["Fp1"]},
    ) for recording, channel in (
        ("P1", "Cz"), ("P1", "Pz"), ("P1", "T7"), ("P1", "Oz"),
        ("P1", "Fz"), ("P1", "C3"), ("P2", "C4"),
    ))
    state._decision_controls = {
        (item.recording_id.casefold(), item.channel.casefold()): Control(index=index)
        for item, index in zip(state._items, (0, 0, 2, 1, 3, 0, 1), strict=True)
    }
    state._current_receipts = {
        "P1": {"AF7": {"decision": "approve"}, "T7": {"decision": "reject"}},
        "P2": {"C4": {"decision": "approve"}},
    }
    return state


def test_repair_context_excludes_upstream_current_automatic_and_unresolved_same_recording_donors(repair_state):
    from Main_App.processing.qc_review_diagnostics import review_repair_topology

    state = repair_state
    before = (_indices(state), deepcopy(state._current_receipts))
    channels, repairs, unavailable = state._repair_context(state._items[0])
    assert channels == ("Cz", "Pz", "T7", "Oz", "Fz", "C3", "Fp1", "AF7")
    assert set(repairs) == {"Cz", "Oz", "Fz", "Fp1", "AF7"}
    assert set(unavailable) == set(repairs) | {"Pz", "C3"}
    assert "C4" not in repairs and "C4" not in unavailable
    coordinates = {name: (index * .01, .01, .08) for index, name in enumerate(channels)}
    report = review_repair_topology(
        channels, coordinates, repair_channels=repairs, unusable_channels=unavailable,
    )
    assert report["status"] == "available"
    for row in report["channels"]:
        assert [donor["channel"] for donor in row["usable_donors"]] == ["T7"]
        assert row["available_donor_count"] == 1
    assert (_indices(state), state._current_receipts) == before


def test_repair_context_does_not_propose_a_current_electrode_explicitly_kept(repair_state):
    repair_state._decision_controls[("p1", "cz")].setCurrentIndex(2)
    _channels, repairs, unavailable = repair_state._repair_context(repair_state._items[0])
    assert "Cz" not in repairs and "Cz" not in unavailable
    assert "Pz" in unavailable and "C3" in unavailable


def test_repair_context_keeps_unknown_provenance_explicit_without_full_cap_fallback(repair_state):
    from Main_App.processing.qc_review_diagnostics import review_repair_topology

    item = repair_state._items[0]
    item.signal_view["upstream_bad_channels"].append("EXG1")
    channels, repairs, unavailable = repair_state._repair_context(item)
    assert "EXG1" in repairs and "EXG1" in unavailable
    assert "EXG1" not in channels
    report = review_repair_topology(
        channels, {name: (index * .01, .01, .08) for index, name in enumerate(channels)},
        repair_channels=repairs, unusable_channels=unavailable,
    )
    assert report["status"] == "unavailable"
    assert report["unknown_channels"] == ["EXG1"]
    item.evidence.clear()
    assert repair_state._repair_context(item)[0] == ()


def test_partial_repair_geometry_names_every_unknown_and_missing_location_in_details():
    from Main_App.processing.qc_review_diagnostics import review_repair_topology

    path = DIALOG_PATH.with_name("qc_repair_support.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and node.name == "_show_channel")
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                 str(path), "exec"), namespace)
    report = review_repair_topology(
        ("Cz", "Pz", "Oz", "Fz"),
        {"Cz": (0, .01, .08), "Pz": (.01, .01, .08), "Oz": (.02, .01, .08)},
        repair_channels=("Oz", "Fz", "EXG1"),
    )
    selections = []
    state = SimpleNamespace(
        _report=report, map=SimpleNamespace(select_channel=lambda *args: selections.append(args)),
        details=SimpleNamespace(setPlainText=lambda value: setattr(state, "detail_text", value)),
    )
    namespace["_show_channel"](state, "Oz")
    assert "unavailable or incomplete" in state.detail_text
    assert "Outside the retained scalp set: EXG1" in state.detail_text
    assert "Missing location evidence: Fz" in state.detail_text
    assert "Oz: 2 usable donor(s)" in state.detail_text
    assert selections == [("Oz", ["Pz", "Cz"])]


@pytest.mark.parametrize("upstream_bad", [False, True])
def test_current_keep_overrides_old_saved_approve_but_preserves_upstream_bad_exclusion(repair_state, upstream_bad):
    state = repair_state
    state._current_receipts["P1"]["Cz"] = {"decision": "approve", "reason": "Old approval"}
    state._decision_controls[("p1", "cz")].setCurrentIndex(2)
    if upstream_bad:
        state._items[0].signal_view["upstream_bad_channels"].append("Cz")
    before = deepcopy(state._current_receipts)
    _channels, repairs, unavailable = state._repair_context(state._items[0])
    assert ("Cz" in repairs) is upstream_bad
    assert ("Cz" in unavailable) is upstream_bad
    assert state._current_receipts == before
