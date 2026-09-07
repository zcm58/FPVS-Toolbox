"""Execute the dialog's real bulk actions using in-memory control doubles."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui.frequency_domain_qc_review_model import (
    electrode_group_key,
    electrode_groups,
)
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_RETAIN,
    validate_frequency_domain_qc_review_decisions,
)


DIALOG_PATH = Path(__file__).resolve().parents[2] / "src/Main_App/gui/frequency_domain_qc_dialog.py"
DECISIONS = ("", DECISION_RETAIN, DECISION_EXCLUDE_CONDITION_ELECTRODE,
             DECISION_EXCLUDE_CONDITION, DECISION_EXCLUDE_RECORDING, DECISION_EXCLUDE_PARTICIPANT)


class _Control:
    def __init__(self, values=(), value=""):
        self.values = list(values)
        self.value = value
        self.blocked = False
        self.enabled = True
        self.changed = lambda _value: None

    def currentData(self):
        return self.value

    def findData(self, value):
        return self.values.index(value) if value in self.values else -1

    def setCurrentIndex(self, index):
        value = self.values[index] if 0 <= index < len(self.values) else None
        if self.value != value:
            self.value = value
            if not self.blocked:
                self.changed(index)

    def text(self):
        return self.value

    def setText(self, value):
        if self.value != value:
            self.value = value
            if not self.blocked:
                self.changed(value)

    def setEnabled(self, value):
        self.enabled = value

    def setToolTip(self, value):
        self.tooltip = value


class _SignalBlocker:
    def __init__(self, control):
        self.control = control

    def __enter__(self):
        self.previous = self.control.blocked
        self.control.blocked = True

    def __exit__(self, *unused):
        self.control.blocked = self.previous


class _Table:
    def __init__(self, display_order, *, hidden=()):
        self.display_order = display_order
        self.hidden = set(hidden)
        self.current_row = 0
        self.cells = [_Control(value="Undecided") for _ in display_order]

    def rowCount(self):
        return len(self.display_order)

    def currentRow(self):
        return self.current_row

    def isRowHidden(self, row):
        return row in self.hidden

    def item(self, row, column):
        if row < 0:
            return None
        if column == 0:
            return SimpleNamespace(data=lambda _role: self.display_order[row])
        return self.cells[row]


class _AcceptSink:
    def accept(self):
        self.accepted = True


def _dialog_methods():
    """Load production method bodies without importing the native GUI module."""
    tree = ast.parse(DIALOG_PATH.read_text(encoding="utf-8"))
    dialog = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == "FrequencyDomainQcReviewDialog")
    names = {
        "_current_section", "_selected_electrode_group", "_electrode_group_label",
        "_apply_electrode_group_decision", "_undo_electrode_group_decision",
        "_invalidate_bulk_undo", "_decision_changed", "_refresh_decision_cell",
        "_refresh_decision_view", "_finding_index", "_table_row", "accept", "review_decisions",
    }
    dialog.body = [node for node in dialog.body if isinstance(node, ast.FunctionDef) and node.name in names]
    dialog.bases = [ast.Name(id="_AcceptSink", ctx=ast.Load())]
    namespace = {
        **{name: value for name, value in globals().items() if name.startswith("DECISION_")},
        "_AcceptSink": _AcceptSink,
        "_CHOOSE_DECISION": "",
        "_DECISION_LABELS": dict.fromkeys(DECISIONS, "Decision label"),
        "QSignalBlocker": _SignalBlocker,
        "Qt": SimpleNamespace(UserRole=256),
        "_natural_sort_key": lambda value: (value,),
        "electrode_group_key": electrode_group_key,
        "validate_frequency_domain_qc_review_decisions": validate_frequency_domain_qc_review_decisions,
        "QMessageBox": SimpleNamespace(warning=lambda *_args: pytest.fail("Unexpected review validation failure")),
    }
    module = ast.fix_missing_locations(ast.Module(body=[dialog], type_ignores=[]))
    exec(compile(module, str(DIALOG_PATH), "exec"), namespace)
    return namespace["FrequencyDomainQcReviewDialog"]


def _findings():
    base = {"participant_id": "P26", "recording_id": "P26-VISIT1", "condition": "Happy",
            "electrode": "O2", "finding_type": "absolute_electrode_summed_bca"}
    return [
        {**base, "finding_fingerprint": "happy"},
        {**base, "condition": "Sad", "finding_fingerprint": "sad"},
        {**base, "condition": "Angry", "finding_fingerprint": "angry"},
        {**base, "electrode": "", "roi": "O2", "finding_fingerprint": "roi"},
        {**base, "participant_id": "P47", "recording_id": "P47-VISIT1", "finding_fingerprint": "p47"},
        {**base, "recording_id": "P26-VISIT2", "finding_fingerprint": "visit2"},
        {**base, "electrode": "CP4", "finding_fingerprint": "cp4"},
    ]


def _harness():
    dialog = _dialog_methods()()
    dialog._findings = _findings()
    dialog._identity_scope = "recording"
    dialog._electrode_groups = electrode_groups(dialog._findings, dialog._identity_scope)
    key = ("P26", "P26-VISIT1", "O2")
    dialog.electrode_group_combo = _Control(values=(None, key), value=key)
    dialog.finding_sections = SimpleNamespace(currentIndex=lambda: 0, tabData=lambda _index: "electrode")
    # Display order differs from source order, with two affected flags hidden.
    dialog.details_table = _Table([2, 5, 1, 4, 0, 6, 3], hidden=(2, 4))
    dialog._row_controls = [(_Control(DECISIONS, DECISION_RETAIN), _Control(value=f"Reason {index}"))
                            for index in range(len(dialog._findings))]
    dialog._decision_controls = {item["finding_fingerprint"]: controls
                                 for item, controls in zip(dialog._findings, dialog._row_controls)}
    dialog.bulk_undo_button = _Control()
    dialog._bulk_snapshot = {}
    dialog._sort_column = None
    dialog._submitted_decisions = ()
    dialog._report = {"identity_scope": "recording", "analysis_fingerprint": "analysis",
                      "review_findings": dialog._findings}
    dialog.accepted = False
    dialog.refresh_count = 0

    def refresh():
        dialog.refresh_count += 1
        dialog.bulk_undo_button.setEnabled(bool(dialog._bulk_snapshot))

    dialog._filter_findings = refresh
    for index, (combo, reason) in enumerate(dialog._row_controls):
        combo.changed = lambda _value, index=index: dialog._decision_changed(index)
        reason.changed = dialog._invalidate_bulk_undo
    return dialog


def _state(dialog):
    return [(combo.currentData(), reason.text()) for combo, reason in dialog._row_controls]


@pytest.mark.parametrize("decision", [DECISION_RETAIN, DECISION_EXCLUDE_CONDITION_ELECTRODE])
def test_bulk_choices_update_exact_original_members_and_submit_canonical_receipts(decision):
    dialog = _harness()
    for index in (0, 1, 2):
        dialog._row_controls[index][0].value = DECISION_EXCLUDE_CONDITION_ELECTRODE
    before = _state(dialog)
    original_findings = deepcopy(dialog._findings)

    dialog._apply_electrode_group_decision(decision)
    dialog.accept()

    assert dialog.accepted
    assert _state(dialog) == [(decision if index < 3 else old, reason)
                             for index, (old, reason) in enumerate(before)]
    assert dialog._findings == original_findings
    assert dialog._bulk_snapshot == dict(enumerate(before[:3]))
    assert dialog.refresh_count == 1
    receipts = {row["finding_fingerprint"]: row for row in dialog.review_decisions()}
    assert set(receipts) == {item["finding_fingerprint"] for item in original_findings}
    for index, finding in enumerate(original_findings):
        row = receipts[finding["finding_fingerprint"]]
        expected = decision if index < 3 else DECISION_RETAIN
        assert row["decision"] == expected
        assert row["reason"] == (f"Reason {index}" if expected != DECISION_RETAIN else "No reason provided")
        assert row["recording_id"] == finding["recording_id"]
        assert row["condition"] == finding["condition"]
        assert row["decision_fingerprint"]
    assert {receipts[name]["decision_scope"] for name in ("happy", "sad", "angry")} == {
        "recording_condition_electrode",
    }


def test_undo_restores_mixed_decisions_and_reasons_with_sorted_hidden_rows():
    dialog = _harness()
    for index, decision in enumerate(("", DECISION_RETAIN, DECISION_EXCLUDE_CONDITION)):
        dialog._row_controls[index][0].value = decision
    before = _state(dialog)

    dialog._apply_electrode_group_decision(DECISION_EXCLUDE_CONDITION_ELECTRODE)
    dialog._undo_electrode_group_decision()

    assert _state(dialog) == before
    assert not dialog._bulk_snapshot
    assert not dialog.bulk_undo_button.enabled
    assert [dialog._row_controls[index][1].enabled for index in range(3)] == [False, False, True]
    assert [cell.text() for cell in dialog.details_table.cells] == [
        "Excl. condition", "Undecided", "Retain", "Undecided", "Undecided", "Undecided", "Undecided",
    ]


@pytest.mark.parametrize("action", ["decision", "reason"])
def test_manual_edit_invalidates_bulk_undo_and_later_undo_cannot_overwrite_it(action):
    dialog = _harness()
    dialog._apply_electrode_group_decision(DECISION_EXCLUDE_CONDITION_ELECTRODE)
    combo, reason = dialog._row_controls[1]
    if action == "decision":
        combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    else:
        reason.setText("Rechecked individual evidence")
    edited = _state(dialog)

    dialog._undo_electrode_group_decision()

    assert _state(dialog) == edited
    assert not dialog._bulk_snapshot
    assert not dialog.bulk_undo_button.enabled


def test_invalid_bulk_action_is_refused_before_any_state_changes():
    dialog = _harness()
    before = _state(dialog)

    with pytest.raises(ValueError, match="condition-electrode"):
        dialog._apply_electrode_group_decision(DECISION_EXCLUDE_PARTICIPANT)

    assert _state(dialog) == before
    assert not dialog._bulk_snapshot
    assert dialog.refresh_count == 0


@pytest.mark.parametrize("selection", ["missing_group", "hidden_row", "roi"])
def test_unavailable_group_cannot_apply_a_bulk_decision(selection):
    dialog = _harness()
    if selection == "missing_group":
        dialog.electrode_group_combo.value = ("missing", "missing", "O2")
    elif selection == "hidden_row":
        dialog.electrode_group_combo.value = None
        dialog.details_table.current_row = 2
    else:
        dialog.finding_sections.tabData = lambda _index: "roi"
    before = _state(dialog)

    dialog._apply_electrode_group_decision(DECISION_EXCLUDE_CONDITION_ELECTRODE)

    assert _state(dialog) == before
    assert not dialog._bulk_snapshot
    assert dialog.refresh_count == 0
