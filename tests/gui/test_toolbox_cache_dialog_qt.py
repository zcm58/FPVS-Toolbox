"""CI-only visible Qt checks; every cache service operation is synthetic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

from Main_App.gui import toolbox_cache_workflow as workflow  # noqa: E402
from Main_App.workers import toolbox_cache_worker as worker_module  # noqa: E402


@pytest.fixture
def cache_dialog(qtbot, monkeypatch, tmp_path):
    owner = QWidget()
    qtbot.addWidget(owner)
    inventory = SimpleNamespace(
        file_count=2, total_bytes=1024, manifest_cache_entries=0,
        project_roots=(tmp_path,), warnings=(),
        targets=(SimpleNamespace(label="Prepared QC", path=tmp_path / "cache", file_count=2, total_bytes=1024),),
    )
    calls = []
    result = SimpleNamespace(
        removed_files=2, removed_bytes=1024, errors=(), warnings=(),
        cancelled=False, cleared_project_roots=(), memory_cache_names=(),
    )

    def inspect(**kwargs):
        calls.append(("inspect", kwargs))
        return inventory

    def clear(value, **kwargs):
        calls.append(("clear", value, kwargs))
        return result

    monkeypatch.setattr(worker_module, "inspect_toolbox_caches", inspect)
    monkeypatch.setattr(worker_module, "clear_toolbox_caches", clear)
    monkeypatch.setattr(workflow, "_cache_work_is_active", lambda *args, **kwargs: False)
    dialog = workflow.ToolboxCacheDialog(owner, project=None, projects_root=tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.begin()
    qtbot.waitUntil(lambda: dialog.thread is None and dialog.inventory is inventory)
    yield dialog, owner, calls, result
    if dialog.worker is not None:
        dialog.worker.cancel_requested.set()
        qtbot.waitUntil(lambda: dialog.thread is None)
    dialog.close()


def test_inventory_does_not_delete_until_explicit_confirmation(qtbot, cache_dialog):
    dialog, owner, calls, _result = cache_dialog
    assert [item[0] for item in calls] == ["inspect"]
    assert dialog.clear_button.isEnabled()
    assert "2 cache files" in dialog.status.text()
    assert "Prepared QC" in dialog.details.toPlainText()
    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.thread is None and len(calls) == 2)
    assert calls[1][1] is dialog.inventory
    assert "Cleared 2 files" in dialog.status.text()
    assert owner._project_processing_cache_thread is None
    assert not dialog.clear_button.isEnabled()


def test_new_background_work_blocks_clearing(qtbot, monkeypatch, cache_dialog):
    dialog, _owner, calls, _result = cache_dialog
    monkeypatch.setattr(workflow, "_cache_work_is_active", lambda *args, **kwargs: True)
    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
    assert [item[0] for item in calls] == ["inspect"]
    assert "Work started" in dialog.status.text()
    assert not dialog.clear_button.isEnabled()


def test_stop_waits_for_worker_and_reports_partial_result(qtbot, monkeypatch, cache_dialog):
    dialog, owner, calls, result = cache_dialog

    def clear(value, *, should_cancel):
        calls.append(("clear", value))
        should_cancel.__self__.wait(2.0)
        return SimpleNamespace(**{**vars(result), "cancelled": should_cancel(), "removed_files": 1})

    monkeypatch.setattr(worker_module, "clear_toolbox_caches", clear)
    qtbot.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(calls) == 2)
    qtbot.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    qtbot.waitUntil(lambda: dialog.thread is None)
    assert "Stopped." in dialog.status.text()
    assert "Cleared 1 files" in dialog.status.text()
    assert owner._project_processing_cache_thread is None
    assert dialog.close_button.isEnabled()


def test_inventory_warnings_are_visible_without_opening_details(qtbot, monkeypatch, tmp_path):
    owner = QWidget()
    qtbot.addWidget(owner)
    inventory = SimpleNamespace(
        file_count=0, total_bytes=0, manifest_cache_entries=0,
        project_roots=(), targets=(), warnings=("A busy cache was skipped.",),
    )
    monkeypatch.setattr(worker_module, "inspect_toolbox_caches", lambda **kwargs: inventory)
    dialog = workflow.ToolboxCacheDialog(owner, project=None, projects_root=tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.begin()
    qtbot.waitUntil(lambda: dialog.thread is None and dialog.inventory is inventory)
    assert "need attention" in dialog.status.text()
    assert dialog.details_toggle.isChecked()
    assert "busy cache" in dialog.details.toPlainText()
