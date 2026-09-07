"""Execute the exclusions dialog's selection and worker logic without Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
DIALOG = ROOT / "src/Main_App/gui/dataset_exclusions_dialog.py"
WORKER = ROOT / "src/Main_App/workers/dataset_exclusions.py"


def _load(path, name, namespace=None, owner=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body if owner is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner
    )
    method = next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), method], type_ignores=[])
    result = {} if namespace is None else namespace
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), result)
    return result[name]


def _rows():
    return (
        SimpleNamespace(identity="participant:P1", scope="both", reason="Existing reason", has_processed_data=True),
        SimpleNamespace(identity="recording:P2-v1", scope="exclude_analysis", reason="Review", has_processed_data=True),
        SimpleNamespace(identity="participant:P3", scope="skip_processing", reason="", has_processed_data=False),
    )


def test_submission_preserves_unedited_scopes_and_reason_only_changes():
    changed = _load(DIALOG, "changed_exclusion_inputs")
    rows = _rows()
    assert changed(rows, {}, {}) == ({}, {})
    changes, reasons = changed(rows, {rows[1].identity: "include"}, {rows[0].identity: "Updated reason"})
    assert changes == {rows[0].identity: "both", rows[1].identity: "include"}
    assert reasons == {rows[0].identity: "Updated reason", rows[1].identity: ""}


def test_bulk_analysis_requires_processed_data_before_changing_any_row():
    apply = _load(DIALOG, "apply_scope_to_rows")
    rows = _rows()
    initial = {row.identity: row.scope for row in rows}
    with pytest.raises(ValueError, match="existing processed data"):
        apply(rows, initial, [row.identity for row in rows], "exclude_analysis")
    assert initial == {row.identity: row.scope for row in rows}
    result = apply(rows, initial, [rows[1].identity], "skip_processing")
    assert result[rows[1].identity] == "skip_processing"
    assert result[rows[0].identity] == "both"
    assert result[rows[2].identity] == "skip_processing"


def test_include_all_uses_every_snapshot_identity_regardless_of_filters():
    restore = _load(DIALOG, "_include_all", owner="DatasetExclusionsDialog")
    panel = SimpleNamespace(snapshot=SimpleNamespace(rows=_rows()), _apply_bulk=Mock())
    restore(panel)
    panel._apply_bulk.assert_called_once_with([row.identity for row in _rows()], "include")


@pytest.mark.parametrize("scope", ["both", "unknown"])
def test_bulk_cannot_create_an_ambiguous_scope(scope):
    apply = _load(DIALOG, "apply_scope_to_rows")
    with pytest.raises(ValueError, match="Choose Included"):
        apply(_rows(), {}, [_rows()[0].identity], scope)


def test_pending_parent_scope_updates_recording_display_without_overwriting_direct_choice():
    effective = _load(DIALOG, "effective_exclusion_scope")
    parent = SimpleNamespace(identity="p1", participant_id="P1", recording_id="", scope="skip_processing")
    child = SimpleNamespace(identity="p1-v1", participant_id="P1", recording_id="v1", scope="exclude_analysis")
    rows = (parent, child)
    assert effective(child, rows, {}) == "both"
    assert effective(child, rows, {parent.identity: "include"}) == "exclude_analysis"
    assert child.scope == "exclude_analysis"
    assert effective(child, rows, {parent.identity: "skip_processing", child.identity: "include"}) == "skip_processing"


@pytest.mark.parametrize("saving", [False, True])
def test_worker_loads_or_saves_the_exact_snapshot_and_changed_rows(saving):
    expected = object()
    namespace = {
        "load_dataset_exclusions": Mock(return_value=expected),
        "save_dataset_exclusions": Mock(return_value=expected), "logger": Mock(),
    }
    run = _load(WORKER, "run", namespace, "DatasetExclusionsWorker")
    worker = SimpleNamespace(
        project_root=Path("fixture"), snapshot=object() if saving else None,
        changes={"participant:P1": "include"}, reasons={"participant:P1": ""},
        result_ready=Mock(), failed=Mock(),
    )
    run(worker)
    worker.result_ready.emit.assert_called_once_with(expected)
    worker.failed.emit.assert_not_called()
    if saving:
        namespace["save_dataset_exclusions"].assert_called_once_with(
            worker.project_root, worker.snapshot, worker.changes, reasons=worker.reasons,
        )
        namespace["load_dataset_exclusions"].assert_not_called()
    else:
        namespace["load_dataset_exclusions"].assert_called_once_with(worker.project_root)
        namespace["save_dataset_exclusions"].assert_not_called()


def test_worker_failure_reports_the_cause_without_a_success_result():
    namespace = {"load_dataset_exclusions": Mock(side_effect=ValueError("Project changed; reload")),
                 "logger": Mock()}
    run = _load(WORKER, "run", namespace, "DatasetExclusionsWorker")
    worker = SimpleNamespace(project_root=Path("fixture"), snapshot=None, result_ready=Mock(), failed=Mock())
    run(worker)
    worker.result_ready.emit.assert_not_called()
    worker.failed.emit.assert_called_once_with("Project changed; reload")


@pytest.mark.parametrize("error,saving", [("", False), ("", True), ("Project changed; reload", True)])
def test_dialog_emits_only_after_successful_finished_save(error, saving):
    finished = _load(DIALOG, "_worker_finished", owner="DatasetExclusionsDialog")
    events = []
    snapshot = object()
    panel = SimpleNamespace(
        _error=error, _result=snapshot, _saving=saving, _worker=object(), status=Mock(),
        _populate=lambda: events.append("populate"),
        _set_busy=lambda value: events.append(("busy", value)),
        exclusions_changed=SimpleNamespace(emit=lambda value: events.append(("changed", value))),
        accept=lambda: events.append("accept"),
    )
    finished(panel)
    assert panel._worker is None
    if error:
        assert events == [("busy", False)]
        panel.status.set_text.assert_called_once_with(error)
    elif saving:
        assert events == ["populate", ("busy", False), ("changed", snapshot), "accept"]
    else:
        assert events == ["populate", ("busy", False)]


def test_project_io_is_owned_by_worker_and_dialog_does_not_wait_for_threads():
    source = DIALOG.read_text(encoding="utf-8")
    assert "load_dataset_exclusions(" not in source
    assert "save_dataset_exclusions(" not in source
    assert ".wait(" not in source
    worker = WORKER.read_text(encoding="utf-8")
    assert "super().__init__()" in worker
    assert "_RUNNING_WORKERS.add(self)" in worker
    assert "self.finished.connect(self._release)" in worker
