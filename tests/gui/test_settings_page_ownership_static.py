"""Exercise Settings' retained page extension points without importing Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"
PAGE_METHODS = (
    ("_init_preproc_tab", "settings_preprocessing_page", "build_preprocessing_page"),
    ("_init_protocol_tab", "settings_protocol_page", "build_protocol_page"),
    ("_init_harmonic_tab", "settings_harmonic_page", "build_harmonic_page"),
    ("_add_harmonic_selection_section", "settings_harmonic_page", "add_harmonic_selection_section"),
    ("_init_experimental_tab", "settings_experimental_page", "build_experimental_page"),
    ("_add_experimental_info_row", "settings_experimental_page", "add_experimental_info_row"),
    ("_init_beta_tools_page", "settings_experimental_page", "build_beta_tools_page"),
    ("_add_experimental_threshold_grid", "settings_experimental_page", "add_experimental_threshold_grid"),
    ("_init_quality_control_tab", "settings_preferences_pages", "build_quality_control_page"),
    ("_add_frequency_domain_qc_settings", "settings_preferences_pages", "add_frequency_domain_qc_settings"),
)
EXPERIMENTAL_PREPROCESSING_BUILDERS = (
    ("build_signal_review", ("self", "signals_page", "signals_layout", "qc_preproc", "experimental_settings")),
    ("build_removed_electrode_review", ("self", "electrodes_page", "electrodes_layout", "qc_preproc")),
    ("build_raw_spectral_review", ("self", "raw_spectral_page", "raw_spectral_layout", "experimental_settings")),
)


def _method(name, namespace):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace[name], method


@pytest.mark.parametrize("method_name,module_name,builder_name", PAGE_METHODS)
def test_existing_page_methods_keep_the_dialog_and_arguments(method_name, module_name, builder_name):
    result = object()
    builder = Mock(return_value=result)
    method, node = _method(method_name, {
        module_name: SimpleNamespace(**{builder_name: builder}),
    })
    arguments = tuple(object() for _ in node.args.args)

    assert method(*arguments) is result
    builder.assert_called_once_with(*arguments)

    failure = RuntimeError("Page construction failed")
    builder.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        method(*arguments)
    assert caught.value is failure


def test_project_root_action_uses_the_original_patch_point_when_clicked():
    builder = Mock()
    original = Mock()
    namespace = {
        "settings_preferences_pages": SimpleNamespace(build_application_page=builder),
        "changeProjectsRoot": original,
    }
    method, _ = _method("_init_application_tab", namespace)
    dialog, tabs = object(), object()
    method(dialog, tabs)
    callback = builder.call_args.kwargs["change_projects_root"]
    assert builder.call_args.args == (dialog, tabs)
    original.assert_not_called()

    replacement = Mock()
    namespace["changeProjectsRoot"] = replacement
    callback()
    original.assert_not_called()
    replacement.assert_called_once_with(dialog)


def test_experimental_preprocessing_sections_receive_the_same_owner_and_settings():
    source = SOURCE.with_name("settings_experimental_page.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    coordinator = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "build_experimental_page")
    calls = [node for node in coordinator.body
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
             and isinstance(node.value.func, ast.Attribute)
             and isinstance(node.value.func.value, ast.Name)
             and node.value.func.value.id == "settings_experimental_preprocessing_page"]
    assert [node.value.func.attr for node in calls] == [
        name for name, _arguments in EXPERIMENTAL_PREPROCESSING_BUILDERS
    ]
    namespace = {
        name: object()
        for _builder, arguments in EXPERIMENTAL_PREPROCESSING_BUILDERS
        for name in arguments
    }
    builders = SimpleNamespace(**{
        name: Mock() for name, _arguments in EXPERIMENTAL_PREPROCESSING_BUILDERS
    })
    namespace["settings_experimental_preprocessing_page"] = builders
    exec(compile(ast.Module(body=calls, type_ignores=[]), str(source), "exec"), namespace)

    for name, arguments in EXPERIMENTAL_PREPROCESSING_BUILDERS:
        getattr(builders, name).assert_called_once_with(*(namespace[arg] for arg in arguments))
