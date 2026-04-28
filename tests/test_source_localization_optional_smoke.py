from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication


_RELOAD_PREFIXES = (
    "Main_App.Legacy_App.eloreta_launcher",
    "Main_App.Legacy_App.processing_utils",
    "Main_App.PySide6_App.GUI.main_window",
    "Main_App.PySide6_App.GUI.menu_bar",
    "Main_App.Shared.source_localization_optional",
)


def _clear_optional_source_localization_modules() -> None:
    for name in list(sys.modules):
        if name == "quarantine" or name.startswith("quarantine."):
            sys.modules.pop(name, None)
            continue
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _RELOAD_PREFIXES):
            sys.modules.pop(name, None)


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


def _build_window(tmp_path: Path, monkeypatch):
    runtime_home = tmp_path / "runtime_home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    os.environ["USERPROFILE"] = str(runtime_home)
    os.environ["HOME"] = str(runtime_home)
    os.environ["APPDATA"] = str(runtime_home)
    os.environ["LOCALAPPDATA"] = str(runtime_home)

    _clear_optional_source_localization_modules()

    from Main_App.PySide6_App.GUI import main_window as main_window_module
    import Main_App.PySide6_App.GUI.update_manager as update_manager

    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    window = main_window_module.MainWindow()
    window.show()
    QApplication.processEvents()
    return window


def _find_tools_action(window, text: str):
    menu_bar = window.menuBar()
    tools_menu = None
    for top_level_action in menu_bar.actions():
        menu = top_level_action.menu()
        if menu and menu.title() == "Tools":
            tools_menu = menu
            break
    assert tools_menu is not None
    for action in tools_menu.actions():
        if action.text() == text:
            return action
    raise AssertionError(f"Action not found: {text}")


def test_main_window_disables_quarantined_source_localization(app, tmp_path: Path, monkeypatch) -> None:
    window = _build_window(tmp_path, monkeypatch)

    action = _find_tools_action(window, "Source Localization (eLORETA/sLORETA)")

    assert window.isVisible()
    assert getattr(window, "actionSourceLocalization", None) is action
    assert not action.isEnabled()
    assert "quarantined dead code" in action.statusTip()
    window.close()
    app.processEvents()


def test_open_eloreta_tool_surfaces_quarantined_source_localization(
    app,
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    window = _build_window(tmp_path, monkeypatch)

    from Main_App.Legacy_App.eloreta_launcher import open_eloreta_tool

    with caplog.at_level(logging.WARNING):
        open_eloreta_tool(window)

    app.processEvents()

    notice = getattr(window, "_source_localization_notice", None)
    assert notice is not None
    assert notice.isVisible()
    assert "quarantined dead code" in notice.text()
    assert "quarantined dead code" in window.statusBar().currentMessage()
    assert "quarantined dead code" in window.text_log.toPlainText()

    matching_records = [
        record
        for record in caplog.records
        if getattr(record, "operation", None) == "open_eloreta_tool"
    ]
    assert matching_records
    record = matching_records[-1]
    assert record.attempted_import == "quarantine.Tools.LORETA.SourceLocalization"
    assert record.optional_dependency_present is False
    assert record.exception_text == ""
    window.close()
    app.processEvents()
