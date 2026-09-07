"""Execute Settings callback lifetime guards without importing or starting Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"


def _source_class(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _execute(nodes, namespace):
    module = ast.Module(
        body=[ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0,
        ), *nodes],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace


def _bridge_type(events):
    class ObjectStub:
        def __init__(self, parent=None):
            self.parent = parent

        def deleteLater(self):
            events.append("delete bridge")

    bridge = _source_class("_SettingsWorkerUiBridge")
    bridge.bases = [ast.Name(id="ObjectStub", ctx=ast.Load())]
    for node in bridge.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    return _execute([bridge], {"ObjectStub": ObjectStub})[bridge.name]


def _idle_panel(*, embedded, activity, events):
    method = next(
        node for node in _source_class("SettingsDialog").body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_finish_settings_post_processing_activity_when_idle"
    )
    namespace = _execute([method], {})
    panel = SimpleNamespace(
        accept=lambda: events.append("accept"),
        _settings_post_processing_activity_is_active=lambda: activity,
        _finish_settings_post_processing_activity=(
            lambda *, return_home: events.append(("finish activity", return_home))
        ),
    )
    owner = SimpleNamespace() if embedded else panel
    if embedded:
        panel.host = owner
    panel.finish_when_idle = namespace[method.name].__get__(panel)
    return panel, owner


@pytest.mark.parametrize("handler", ["handle_result", "handle_failed"])
@pytest.mark.parametrize("raises", [False, True])
def test_nested_thread_exit_waits_for_result_or_failure_handler(handler, raises):
    events = []
    bridge_class = _bridge_type(events)

    def handle_payload(payload):
        events.append(("begin", payload))
        # A modal review dispatches thread.finished while its result callback
        # still needs Settings widgets. Repeated delivery must coalesce.
        bridge.handle_thread_finished()
        bridge.handle_thread_finished()
        assert events == [("begin", "review payload")]
        events.append("handler still has controls")
        if raises:
            raise ValueError("review failed")
        events.append("handler returned")

    bridge = bridge_class(
        result_callback=handle_payload,
        failed_callback=handle_payload,
        thread_finished_callback=lambda: events.append("release controls"),
    )
    if raises:
        with pytest.raises(ValueError, match="review failed"):
            getattr(bridge, handler)("review payload")
    else:
        getattr(bridge, handler)("review payload")

    expected = [("begin", "review payload"), "handler still has controls"]
    if not raises:
        expected.append("handler returned")
    assert events == [*expected, "release controls", "delete bridge"]


def test_bridge_releases_after_a_previously_completed_result():
    events = []
    bridge = _bridge_type(events)(
        result_callback=lambda payload: events.append(("result", payload)),
        thread_finished_callback=lambda: events.append("release controls"),
    )
    bridge.handle_result("complete")
    assert events == [("result", "complete")]

    bridge.handle_thread_finished()

    assert events == [("result", "complete"), "release controls", "delete bridge"]


def test_bridge_is_retired_even_when_cleanup_raises():
    events = []

    def release():
        events.append("release attempted")
        raise RuntimeError("release failed")

    bridge = _bridge_type(events)(
        result_callback=lambda _payload: None,
        thread_finished_callback=release,
    )
    with pytest.raises(RuntimeError, match="release failed"):
        bridge.handle_thread_finished()

    assert events == ["release attempted", "delete bridge"]


@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("activity", [False, True])
def test_home_waits_for_both_worker_cleanup_callbacks(embedded, activity):
    events = []
    panel, owner = _idle_panel(embedded=embedded, activity=activity, events=events)
    # A stopped thread can still have an undelivered cleanup callback. Keep
    # the Settings page until ownership clears, regardless of isRunning().
    owner._settings_full_fft_grid_qc_thread = SimpleNamespace(isRunning=lambda: False)
    owner._settings_harmonic_recalc_thread = SimpleNamespace(isRunning=lambda: False)

    panel.finish_when_idle(return_home=True)
    assert events == []
    owner._settings_harmonic_recalc_thread = None
    panel.finish_when_idle()
    assert events == []
    owner._settings_full_fft_grid_qc_thread = None
    panel.finish_when_idle()

    expected = [("finish activity", True)] if activity else ["accept"]
    assert events == expected
    assert not hasattr(owner, "_settings_post_processing_pending_return_home")
    before_repeat = list(events)
    panel.finish_when_idle()
    assert events == before_repeat


@pytest.mark.parametrize("activity", [False, True])
def test_failed_followup_can_replace_pending_home_decision(activity):
    events = []
    panel, owner = _idle_panel(embedded=True, activity=activity, events=events)
    owner._settings_harmonic_recalc_thread = object()
    panel.finish_when_idle(return_home=True)
    panel.finish_when_idle(return_home=False)
    assert events == []

    owner._settings_harmonic_recalc_thread = None
    panel.finish_when_idle()

    expected = [("finish activity", False)] if activity else []
    assert events == expected
    assert not hasattr(owner, "_settings_post_processing_pending_return_home")
