"""Exercise pre-handoff draft and active-work decisions without running Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _guard():
    path = ROOT / "src/Main_App/gui/update_install_guard.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    namespace = {
        "QWidget": object,
        "QThread": object,
        "Any": object,
        "show_warning": Mock(),
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    namespace["_confirm_project_draft_exit"] = Mock(return_value=True)
    namespace["_has_active_tool_operations"] = Mock(return_value=False)
    return namespace


def _host(**attributes):
    return SimpleNamespace(findChildren=lambda _kind: [], **attributes)


@pytest.mark.parametrize("accepted", [True, False])
def test_draft_save_discard_or_cancel_resolves_before_handoff(accepted):
    code = _guard()
    host = _host()
    code["_confirm_project_draft_exit"].return_value = accepted
    assert code["default_install_guard"](host) is accepted
    code["_confirm_project_draft_exit"].assert_called_once_with(host)
    code["show_warning"].assert_not_called()


def test_save_that_starts_background_work_prevents_handoff():
    code = _guard()
    host = _host()

    def save(_host):
        host._settings_post_processing_activity_active = True
        return True

    code["_confirm_project_draft_exit"].side_effect = save
    assert not code["default_install_guard"](host)
    code["show_warning"].assert_called_once()


@pytest.mark.parametrize("attribute", [
    "_settings_full_fft_grid_qc_thread",
    "_settings_harmonic_recalc_thread",
    "_project_processing_cache_thread",
])
def test_unparented_project_worker_blocks_installation(attribute):
    code = _guard()
    host = _host(**{attribute: SimpleNamespace(isRunning=lambda: True)})
    assert not code["default_install_guard"](host)
    code["_confirm_project_draft_exit"].assert_not_called()


@pytest.mark.parametrize("attribute", ["_plot_generator_page", "_publication_maps_page"])
def test_embedded_tool_generation_blocks_installation_without_a_child_thread(attribute):
    code = _guard()
    host = _host(**{attribute: SimpleNamespace(has_active_generation=lambda: True)})
    assert not code["default_install_guard"](host)
    code["_confirm_project_draft_exit"].assert_not_called()


def test_global_fhc_operation_blocks_installation_even_after_page_switch():
    code = _guard()
    code["_has_active_tool_operations"].return_value = True
    assert not code["default_install_guard"](_host())
    code["_confirm_project_draft_exit"].assert_not_called()


@pytest.mark.parametrize("close_result", [True, False, RuntimeError("window closed")])
def test_confirmed_update_exit_uses_normal_close_and_never_leaks_draft_consent(close_result):
    namespace = _guard()
    host = _host()

    def close():
        assert host._update_exit_confirmed
        if isinstance(close_result, Exception):
            raise close_result
        return close_result

    host.close = close
    if isinstance(close_result, Exception):
        with pytest.raises(RuntimeError, match="window closed"):
            namespace["close_after_update"](host)
    else:
        assert namespace["close_after_update"](host) is close_result
    assert host._update_exit_confirmed is False


def test_standalone_update_guard_never_loads_project_or_tool_state():
    code = _guard()
    assert code["default_install_guard"](None)
    code["_has_active_tool_operations"].assert_not_called()
    code["_confirm_project_draft_exit"].assert_not_called()
