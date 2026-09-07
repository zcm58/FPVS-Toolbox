from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
DIALOG_PATH = ROOT / "src" / "Main_App" / "gui" / "kurtosis_review_dialog.py"
SCANNER_PATH = ROOT / "src" / "Main_App" / "processing" / "kurtosis_review_scan.py"
WORKFLOW_PATH = ROOT / "src" / "Main_App" / "gui" / "preprocessing_qc_workflow.py"
SETTINGS_PATH = ROOT / "src" / "Main_App" / "gui" / "settings_panel.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_kurtosis_review_dialog_uses_pyside6_and_shared_components() -> None:
    source = _source(DIALOG_PATH)
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert "PySide6.QtCore" in imports
    assert "PySide6.QtGui" in imports
    assert "PySide6.QtWidgets" in imports
    assert "Main_App.gui.components" in imports
    assert "class KurtosisReviewDialog(AppDialog):" in source
    assert "Tkinter" not in source
    assert "CustomTkinter" not in source
    application_constructor = "Q" + "Application("
    assert application_constructor not in source
    assert ".exec(" not in source


def test_dialog_has_no_default_manual_decision_and_optional_reason() -> None:
    source = _source(DIALOG_PATH)
    placeholder = source.index('decision.addItem("Choose…", "")')
    approve = source.index("KURTOSIS_DECISION_APPROVE", placeholder)
    reject = source.index("KURTOSIS_DECISION_REJECT", approve)

    assert placeholder < approve < reject
    assert "decision.setCurrentIndex(0)" in source
    assert "reason = reason_control.text().strip()" in source
    assert "if not decision:" in source
    assert 'reason.setPlaceholderText("Reason (optional)")' in source
    assert "if not reason:" not in source
    assert "build_kurtosis_review_decision(" in source


def test_dialog_exposes_required_scientific_evidence_and_fixed_scope() -> None:
    source = _source(DIALOG_PATH)

    for label in ("Recording", "Electrode", "|Score|", "Raw kurtosis", "Conditions", "Decision", "Reason"):
        assert f'"{label}"' in source
    assert "Signed normalized score:" in source
    assert "review threshold |z| >" in source
    assert "Analyzed occurrences:" in source
    assert "Approved corroborator:" in source
    assert "whole processed recording" in source
    assert '", ".join(item.analyzed_conditions)' in source
    assert '"Whole processed recording → {conditions}"' in source
    assert '"Changed evidence — review again"' in source
    assert "QPlainTextEdit(self)" in source
    assert "self.table.currentCellChanged.connect(self._show_selected_evidence)" in source
    assert "setWordWrap(False)" in source
    assert "ResizeToContents" not in source
    assert "seen_scopes" not in source
    assert "display_only_channel_health_summary" in source
    assert "review-only; not an approved corroborator" in _source(SCANNER_PATH)


def test_compact_signal_view_is_bounded_and_presentation_only() -> None:
    source = _source(DIALOG_PATH)

    assert "class KurtosisSignalPreviewWidget(QWidget):" in source
    assert "def paintEvent(" in source
    assert "QPainter(self)" in source
    assert "QPolygonF" in source
    assert "drawPolyline" in source
    assert "setMaximumHeight(62)" in source
    assert source.count("= KurtosisSignalPreviewWidget(") == 1
    assert "self.preview.set_signal(" in source
    assert "prepare_kurtosis_review_evidence" not in source
    assert "load_eeg_file" not in source


def test_cancel_and_close_cannot_expose_review_receipts() -> None:
    source = _source(DIALOG_PATH)

    assert "self.cancel_button.clicked.connect(self.reject)" in source
    assert "def reject(self)" in source
    assert "def closeEvent(self, event: QCloseEvent)" in source
    assert "self._accepted_receipts = None" in source
    assert "self.result() != QDialog.DialogCode.Accepted" in source
    assert "downstream processing remains blocked" in source


def test_dialog_merges_fingerprint_current_receipts_with_new_decisions() -> None:
    source = _source(DIALOG_PATH)

    assert "KurtosisReviewDecisionReconciliation" in source
    assert "review.processing_decisions_by_recording" in source
    assert "self._current_receipts = deepcopy(current_receipts)" in source
    assert "receipts = deepcopy(self._current_receipts)" in source


def test_scanner_remains_gui_neutral_and_callback_driven() -> None:
    source = _source(SCANNER_PATH)
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert all(not module.startswith("PySide6") for module in imports)
    assert "QWidget" not in source
    assert "QMessageBox" not in source
    assert "ProgressCallback = Callable[[str, int, int], None]" in source
    assert "CancelCallback = Callable[[], bool]" in source
    assert "should_cancel" in source
    assert "prepare_kurtosis_review_evidence(" in source
    assert "validate_source_analysis_span_plan(" in source
    assert "validate_raw_biosemi64_geometry(" in source
    assert "BIOSEMI64_MONTAGE_ID" in source


def test_preprocessing_workflow_runs_and_persists_the_fail_closed_review() -> None:
    source = _source(WORKFLOW_PATH)

    assert "class _KurtosisReviewWorker(QObject):" in source
    assert "scan_kurtosis_review(" in source
    assert "worker.moveToThread(thread)" in source
    assert "scan, existing, kurtosis_auto_interpolate_all=auto_all" in source
    assert "reconciliation, parent=host, auto_interpolate_all=auto_all" in source
    assert "dialog.exec() != QDialog.DialogCode.Accepted" in source
    assert "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY" in source
    assert "project.update_preprocessing(updated_preprocessing)" in source

    event_plan_index = source.index(
        'params["_fpvs_preflight_event_plans_by_file"] = existing_event_plans'
    )
    scan_index = source.index(
        "_run_kurtosis_review_scan_embedded(",
        event_plan_index,
    )
    remainder_index = source.index("_show_suspicious_remainder(", scan_index)
    assert event_plan_index < scan_index < remainder_index


def test_experimental_selection_is_visible_optional_and_auditable() -> None:
    source = _source(DIALOG_PATH)
    assert "Experimental: auto-interpolate |normalized score| >" in source
    assert "self.auto_checkbox.setChecked(True)" in source
    assert "qualifies_for_experimental_kurtosis_auto(channel)" in source
    assert "self.auto_all_checkbox.setChecked(self._auto_interpolate_all)" in source
    assert "experimental_auto=automatic and not automatic_all" in source
    assert "experimental_auto_all=automatic_all" in source
    assert "self.table.setRowHidden(row, enabled and not show_auto)" in source
    assert "self._manual_indices.pop(row)" in source


def _function_node(path: Path, name: str) -> ast.FunctionDef:
    return next(
        node for node in ast.walk(ast.parse(_source(path)))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _load_functions(path: Path, names: tuple[str, ...], namespace: dict) -> dict:
    """Execute the actual widget-neutral method bodies with lightweight controls."""
    nodes = [deepcopy(_function_node(path, name)) for name in names]
    for node in nodes:
        node.decorator_list = []
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace


class _Control:
    def __init__(self, checked=False, index=0, text=""):
        self.checked, self.index, self.value = checked, index, text
        self.enabled = True

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = checked

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        self.index = index

    def currentData(self):
        return ("", "approve", "reject", "approve")[self.index]

    def text(self):
        return self.value

    def setEnabled(self, enabled):
        self.enabled = enabled


def _dialog_state():
    build_calls = []

    def build_receipt(evidence, **kwargs):
        build_calls.append(kwargs)
        return SimpleNamespace(to_payload=lambda: dict(kwargs))

    namespace = _load_functions(
        DIALOG_PATH,
        ("_selected_automatic_rows", "_refresh_automatic_rows", "_build_receipts", "auto_interpolate_all"),
        {
            "deepcopy": deepcopy,
            "KURTOSIS_DECISION_APPROVE": "approve",
            "KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD": 10.0,
            "KurtosisReviewDialogError": ValueError,
            "KurtosisQCError": RuntimeError,
            "build_kurtosis_review_decision": build_receipt,
            "QDialog": SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        },
    )
    state = SimpleNamespace(
        auto_all_checkbox=_Control(), auto_checkbox=_Control(checked=True),
        show_auto_checkbox=_Control(), _all_flag_rows=frozenset({0, 1}),
        _automatic_rows=frozenset({1}), _manual_indices={}, _current_receipts={},
        _reviewer_identity=None, _clear_error=lambda: None,
        _show_selected_evidence=lambda *_args: None,
        _items=tuple(SimpleNamespace(
            recording_id="P01", participant_id="P01", channel=channel,
            evidence={"channel": channel}, review_scope={},
        ) for channel in ("Cz", "Pz")),
    )
    keys = [("p01", "cz"), ("p01", "pz")]
    state._decision_controls = {key: _Control(index=i + 1) for i, key in enumerate(keys)}
    state._reason_controls = {key: _Control() for key in keys}
    hidden = {}
    state.table = SimpleNamespace(
        setUpdatesEnabled=lambda *_args: None,
        setRowHidden=lambda row, value: hidden.update({row: value}),
        currentRow=lambda: 0, isRowHidden=lambda row: hidden.get(row, False),
        setCurrentCell=lambda *_args: None, scrollToItem=lambda *_args: None,
        item=lambda *_args: None,
    )
    state.banner = SimpleNamespace(set_text=lambda *_args: None)
    state.details = SimpleNamespace(setPlainText=lambda *_args: None)
    state.preview = SimpleNamespace(hide=lambda: None)
    for name in ("_selected_automatic_rows", "_refresh_automatic_rows", "_build_receipts", "auto_interpolate_all"):
        setattr(state, name, MethodType(namespace[name], state))
    return state, build_calls, hidden


def test_auto_all_takes_precedence_and_toggling_off_restores_manual_choices():
    state, calls, hidden = _dialog_state()
    state._refresh_automatic_rows()
    assert state._selected_automatic_rows() == {1}
    state._build_receipts()
    assert [call["experimental_auto"] for call in calls] == [False, True]
    assert not any(call["experimental_auto_all"] for call in calls)
    calls.clear()
    state.auto_all_checkbox.setChecked(True)
    state._refresh_automatic_rows()
    assert state._selected_automatic_rows() == {0, 1}
    assert not state.auto_checkbox.enabled
    state._build_receipts()
    assert len(calls) == 2
    assert all(call["experimental_auto_all"] and not call["experimental_auto"] for call in calls)
    assert all(call["decision"] == "approve" for call in calls)

    state.auto_all_checkbox.setChecked(False)
    state._refresh_automatic_rows()
    assert state._selected_automatic_rows() == {1}
    assert state._decision_controls[("p01", "cz")].currentIndex() == 1
    state.auto_checkbox.setChecked(False)
    state._refresh_automatic_rows()
    assert state._selected_automatic_rows() == set()
    assert [control.currentIndex() for control in state._decision_controls.values()] == [1, 2]
    assert not state._manual_indices
    assert not any(hidden.values())
    assert all(control.enabled for control in state._reason_controls.values())


def test_manual_blank_reason_reaches_receipt_builder_but_missing_decision_blocks():
    state, calls, _hidden = _dialog_state()
    state.auto_checkbox.setChecked(False)
    receipts = state._build_receipts()
    assert set(receipts["P01"]) == {"Cz", "Pz"}
    assert [call["decision"] for call in calls] == ["approve", "reject"]
    assert all(call["reason"] == "" for call in calls)
    assert all(not call["experimental_auto"] and not call["experimental_auto_all"] for call in calls)
    state._decision_controls[("p01", "cz")].setCurrentIndex(0)
    with pytest.raises(ValueError, match="choose Interpolate or Keep channel"):
        state._build_receipts()


def test_experimental_preference_accessor_requires_acceptance():
    state, _calls, _hidden = _dialog_state()
    state.auto_all_checkbox.setChecked(True)
    state.result = lambda: 0
    with pytest.raises(ValueError, match="not completed"):
        state.auto_interpolate_all()
    state.result = lambda: 1
    assert state.auto_interpolate_all() is True


@pytest.mark.parametrize("accepted", [False, True])
def test_workflow_only_reads_and_saves_new_preference_after_acceptance(accepted):
    calls = []
    preference = "kurtosis_auto_interpolate_all"
    decisions_key = "decisions"
    project = SimpleNamespace(preprocessing={preference: False}, project_root=ROOT)

    def update(values):
        calls.append(("update", deepcopy(values)))
        project.preprocessing = deepcopy(values)
        return project.preprocessing

    project.update_preprocessing = update
    project.save = lambda: calls.append(("save",))
    host = SimpleNamespace(currentProject=project)

    class Dialog:
        def __init__(self, reconciliation, *, parent, auto_interpolate_all):
            calls.append(("dialog", auto_interpolate_all))

        def exec(self):
            return int(accepted)

        def review_decisions_by_recording(self):
            assert accepted
            calls.append(("receipts",))
            return {"P01": {"Cz": {"decision": "approve"}}}

        def auto_interpolate_all(self):
            assert accepted
            calls.append(("preference",))
            return True

    def reconcile(scan, existing, **kwargs):
        calls.append(("reconcile", kwargs[preference]))
        return SimpleNamespace(pending_items=(object(),), processing_decisions_by_recording={})

    namespace = _load_functions(
        WORKFLOW_PATH, ("_save_kurtosis_review_receipts", "_review_kurtosis_findings"),
        {
            "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY": decisions_key,
            "KurtosisReviewDialog": Dialog, "KurtosisReviewDialogError": ValueError,
            "QDialog": SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
            "reconcile_kurtosis_review_decisions": reconcile,
            "_merge_kurtosis_review_receipts": lambda existing, **kwargs: kwargs["current_scanned_receipts"],
            "mark_frequency_domain_outputs_stale": lambda *_args, **_kwargs: calls.append(("stale",)),
        },
    )
    scan = SimpleNamespace(cancelled=False, errors=(), results=(SimpleNamespace(recording_id="P01"),))
    params = {preference: False}
    assert namespace["_review_kurtosis_findings"](host, params, scan) is accepted
    assert calls[:2] == [("reconcile", False), ("dialog", False)]
    if accepted:
        assert params[preference] is True
        assert project.preprocessing[preference] is True
        assert [call[0] for call in calls] == ["reconcile", "dialog", "receipts", "preference", "update", "save", "stale"]
    else:
        assert len(calls) == 2
        assert project.preprocessing == {preference: False}
        assert params == {preference: False}


@pytest.mark.parametrize("saved", [{}, {"kurtosis_auto_interpolate_all": False}, {"kurtosis_auto_interpolate_all": True}])
def test_experimental_settings_checkbox_roundtrips_project_preference(saved):
    init = _function_node(SETTINGS_PATH, "_init_experimental_tab")
    collect = _function_node(SETTINGS_PATH, "_collect_project_preprocessing_inputs")
    checkbox_name = "self.kurtosis_auto_interpolate_all_check"
    load_node = next(
        node for node in ast.walk(init)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == f"{checkbox_name}.setChecked"
    )
    save_node = next(
        node for node in ast.walk(collect)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "values['kurtosis_auto_interpolate_all']"
    )
    namespace = {"self": SimpleNamespace(kurtosis_auto_interpolate_all_check=_Control()), "qc_preproc": saved, "values": {}}
    for node in (load_node, save_node):
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(SETTINGS_PATH), "exec"), namespace)
    assert namespace["values"] == {"kurtosis_auto_interpolate_all": saved.get("kurtosis_auto_interpolate_all", False)}


@pytest.mark.parametrize(
    ("initial_mode", "chosen_mode", "second_review_accepted", "expected_scans", "expected_success"),
    [
        (True, False, True, [True, False], True),
        (True, False, False, [True, False], False),
        (True, True, True, [True], True),
        (False, False, True, [False], True),
        (False, True, True, [False], True),
    ],
)
def test_turning_off_auto_all_collects_omitted_manual_findings_before_continuing(
    initial_mode, chosen_mode, second_review_accepted, expected_scans, expected_success,
):
    workflow = _function_node(WORKFLOW_PATH, "run_preprocessing_qc_workflow")
    loop = next(
        node for node in ast.walk(workflow)
        if isinstance(node, ast.While)
        and any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            and child.func.id == "_run_kurtosis_review_scan_embedded"
            for child in ast.walk(node)
        )
    )
    wrapper = ast.parse("def run_loop():\n    pass\n")
    wrapper.body[0].body = [deepcopy(loop), ast.Return(value=ast.Constant(True))]
    params = {"kurtosis_auto_interpolate_all": initial_mode}
    scans, reviews = [], []

    def scan(_host, _infos, current_params, **_kwargs):
        mode = current_params["kurtosis_auto_interpolate_all"]
        scans.append(mode)
        return SimpleNamespace(scanned_mode=mode)

    def review(_host, current_params, result):
        reviews.append(result.scanned_mode)
        current_params["kurtosis_auto_interpolate_all"] = chosen_mode
        return len(reviews) == 1 or second_review_accepted

    namespace = {
        "host": object(), "active_infos": (), "params": params,
        "current_event_plans": {}, "display_only_raw_qc": {},
        "prefetch": None,
        "_run_kurtosis_review_scan_embedded": scan,
        "_review_kurtosis_findings": review,
    }
    exec(compile(ast.fix_missing_locations(wrapper), str(WORKFLOW_PATH), "exec"), namespace)
    assert namespace["run_loop"]() is expected_success
    assert scans == expected_scans
    assert reviews == expected_scans
