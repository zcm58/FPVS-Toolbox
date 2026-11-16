from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui import icons, theme
from Main_App.gui.menu_bar import BETA_TOOL_SPECS
from Main_App.gui.style_tokens import (
    CHROME_ACTIVE,
    CHROME_MUTED_TEXT,
    CHROME_TEXT,
    CONTROL_BORDER,
    FOCUS_COLOR,
    HEADER_BG,
    SIGNAL_COLOR,
    TEXT_MUTED,
    build_workspace_chrome_stylesheet,
)


@pytest.mark.parametrize("frozen", [False, True])
def test_application_icon_loads_from_checkout_or_bundle_independent_of_cwd(tmp_path, monkeypatch, frozen) -> None:
    asset = Path(__file__).resolve().parents[2] / "assets" / "ToolBox_Icon.ico"
    runtime = SimpleNamespace(frozen=frozen)
    if frozen:
        runtime._MEIPASS = str(tmp_path / "bundle")
        bundled_asset = Path(runtime._MEIPASS) / "assets" / asset.name
        bundled_asset.parent.mkdir(parents=True)
        bundled_asset.write_bytes(asset.read_bytes())
        asset = bundled_asset

    def file_icon(filename):
        path = Path(filename)
        return SimpleNamespace(path=path, isNull=lambda: not path.is_file())

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(icons, "sys", runtime)
    monkeypatch.setattr(icons, "QIcon", file_icon)
    assert icons.application_icon().path == asset


def test_missing_bundled_application_icon_fails_explicitly(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(icons, "sys", SimpleNamespace(frozen=True, _MEIPASS=str(tmp_path)))
    monkeypatch.setattr(icons, "QIcon", lambda _filename: SimpleNamespace(isNull=lambda: True))
    with pytest.raises(RuntimeError, match="Cannot load the FPVS Toolbox application icon"):
        icons.application_icon()


def test_beta_tool_inventory_and_routes_match_supported_surfaces() -> None:
    assert BETA_TOOL_SPECS == (
        ("btn_publication_maps", "Scalp Maps", "open_publication_maps"),
        ("btn_data", "Standard FPVS Screening", "open_stats_analyzer"),
        ("btn_sensitivity_analysis", "Sensitivity Analysis", "open_sensitivity_analysis"),
        ("btn_loreta_visualizer", "LORETA Visualizer", "open_loreta_visualizer"),
        ("btn_sequence_figure", "Sequence Figure", "open_sequence_figure"),
        ("btn_individual_detectability", "Individual Detectability", "open_individual_detectability"),
    )


def _stylesheet_rules(stylesheet: str) -> dict[str, dict[str, str]]:
    rules = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", stylesheet):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        for selector in selectors.split(","):
            rules.setdefault(selector.strip(), {}).update(declarations)
    return rules


def test_menu_uses_slate_chrome_with_distinct_focus_and_disabled_states() -> None:
    rules = _stylesheet_rules(build_workspace_chrome_stylesheet())
    for selector in ("QMenuBar#workspaceMenuBar", "QMenuBar#workspaceMenuBar::item"):
        assert rules[selector]["background-color"] == HEADER_BG
        assert rules[selector]["color"] == CHROME_TEXT
    assert rules["QMenuBar#workspaceMenuBar::item:disabled"]["color"] == CHROME_MUTED_TEXT
    assert rules["QMenuBar#workspaceMenuBar::item:selected:enabled"]["border-color"] == SIGNAL_COLOR
    assert rules["QMenuBar#workspaceMenuBar::item:pressed:enabled"]["background-color"] == CHROME_ACTIVE
    assert not any(selector.startswith("QMenu::") for selector in rules)


def test_settings_navigation_uses_one_keyboard_focus_indicator() -> None:
    rules = _stylesheet_rules(theme.build_fpvs_app_stylesheet())
    assert rules["QListWidget#settings_navigation"]["outline"] == "none"
    assert rules["QListWidget#settings_navigation::item:focus"]["border-color"] == FOCUS_COLOR
    assert rules["QLineEdit"]["border"] == f"1px solid {CONTROL_BORDER}"
    assert rules["QLineEdit"]["placeholder-text-color"] == TEXT_MUTED


def test_control_chevrons_are_resolved_independently_of_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rules = _stylesheet_rules(theme.build_fpvs_app_stylesheet())
    assert rules["QComboBox::drop-down"]["border"] == "none"
    images = {
        "QComboBox::down-arrow": "chevron-down.svg",
        "QSpinBox::up-arrow": "chevron-up.svg",
        "QSpinBox::down-arrow": "chevron-down.svg",
        "QDoubleSpinBox::up-arrow": "chevron-up.svg",
        "QDoubleSpinBox::down-arrow": "chevron-down.svg",
    }
    for selector, filename in images.items():
        image = rules[selector]["image"]
        path = Path(image.removeprefix('url("').removesuffix('")'))
        assert path.is_absolute()
        assert path.name == filename
        assert path.is_file()
