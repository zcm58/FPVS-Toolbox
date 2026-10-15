from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor, QPalette

from Main_App.gui import icons, theme
from Main_App.gui.sidebar import (
    BETA_TOOL_SPECS,
    CENTERED_TEXT_TRAILING_SPACER_PX,
    ICON_PX,
    ROW_ITEM_GAP,
    ROW_LEFT_PADDING,
    ROW_MIN_HEIGHT,
    ROW_RIGHT_PADDING,
    SELECTION_BAR_WIDTH,
    TEXT_BOX_PX,
)
from Main_App.gui.style_tokens import SIDEBAR_WIDTH, build_header_bar_stylesheet, build_sidebar_stylesheet
from Main_App.gui.typography import css_font_size, css_font_weight


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
    assert [(role, label, opener) for role, label, _icon, opener in BETA_TOOL_SPECS] == [
        ("btn_publication_maps", "Scalp Maps", "open_publication_maps"),
        ("btn_data", "Data Screening", "open_stats_analyzer"),
        ("btn_sensitivity_analysis", "Sensitivity Analysis", "open_sensitivity_analysis"),
        ("btn_loreta_visualizer", "LORETA Visualizer", "open_loreta_visualizer"),
        ("btn_sequence_figure", "Sequence Figure", "open_sequence_figure"),
        ("btn_individual_detectability", "Individual Detectability", "open_individual_detectability"),
    ]


def test_sidebar_section_headers_are_visually_distinct() -> None:
    stylesheet = build_sidebar_stylesheet()

    assert "#SidebarSectionLabel" in stylesheet
    assert '#SidebarSectionLabel[centered="true"]' in stylesheet
    assert "#sidebar_beta_tools_divider" in stylesheet
    assert '#SidebarSelectionBar[active="true"]' in stylesheet
    assert "background-color: transparent;" in stylesheet
    assert f"font-size: {css_font_size('sidebar_section')};" in stylesheet
    assert f"font-weight: {css_font_weight('sidebar_section')};" in stylesheet
    assert "rgba(255, 255, 255, 0.76)" in stylesheet


def test_header_bar_uses_project_title_typography() -> None:
    stylesheet = build_header_bar_stylesheet()

    assert "#HeaderBar QLabel" in stylesheet
    assert f"font-size: {css_font_size('project_title')};" in stylesheet
    assert f"font-weight: {css_font_weight('project_title')};" in stylesheet


def test_sidebar_icon_and_text_sizing_match_larger_sidebar_style() -> None:
    assert SIDEBAR_WIDTH == 244
    assert ICON_PX == 20
    assert ROW_MIN_HEIGHT == 46
    assert ROW_LEFT_PADDING == 6
    assert ROW_RIGHT_PADDING == 8
    assert ROW_ITEM_GAP == 7
    assert TEXT_BOX_PX == 26
    assert SELECTION_BAR_WIDTH == 3
    assert CENTERED_TEXT_TRAILING_SPACER_PX == 28


def test_native_menu_chrome_survives_application_theme_changes(monkeypatch) -> None:
    native_palette = QPalette()
    native_palette.setColor(QPalette.Window, QColor("#202124"))
    native_palette.setColor(QPalette.WindowText, QColor("white"))
    native_palette.setResolveMask(0)
    app = SimpleNamespace(style_name="platform", colors=native_palette)
    app.style = lambda: SimpleNamespace(objectName=lambda: app.style_name)
    app.palette = lambda: app.colors
    app.setStyleSheet = lambda stylesheet: setattr(app, "stylesheet", stylesheet)
    def apply_light_palette(current):
        current.style_name = "Fusion"
        current.colors = QPalette()
        current.colors.setColor(QPalette.Window, QColor("white"))
        current.colors.setColor(QPalette.WindowText, QColor("black"))

    monkeypatch.setattr(theme, "apply_fusion_light_palette", apply_light_palette)
    monkeypatch.setattr(theme, "apply_app_font", lambda _app: None)
    monkeypatch.setattr(theme, "build_fpvs_app_stylesheet", lambda: "light stylesheet")

    theme.apply_fpvs_theme(app)
    style_name, palette = theme._native_menu_appearance(app)
    theme.apply_fpvs_theme(app)

    assert style_name == "platform"
    assert theme._native_menu_appearance(app) == (style_name, palette)
    resolved = palette.resolve(app.colors)
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role in QPalette.ColorRole:
            if role not in (QPalette.NoRole, QPalette.NColorRoles):
                assert resolved.brush(group, role) == native_palette.brush(group, role)
    assert app.style_name == "Fusion"
    assert app.colors.color(QPalette.Window) == QColor("white")
    assert app.colors.color(QPalette.WindowText) == QColor("black")
    assert app.stylesheet == "light stylesheet"


@pytest.mark.parametrize("dark_native", [False, True])
def test_native_menu_text_and_painted_background_stay_paired(dark_native) -> None:
    # The app has switched to light colors, but the menu retained its original
    # platform palette. Native Windows painting need not honor that palette.
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#202124" if dark_native else "#ffffff"))
    palette.setColor(QPalette.WindowText, QColor("#ffffff" if dark_native else "#202124"))
    palette.setColor(QPalette.Highlight, QColor("#0f6cbd"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#999999" if dark_native else "#666666"))
    stylesheet = theme._native_menu_stylesheet(palette)

    # Require the painter overrides themselves to carry both colors; palette
    # equality alone passed while Windows could still paint white-on-white.
    rules = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", stylesheet):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        for selector in selectors.split(","):
            rules[selector.strip()] = declarations
    for selector in ("QMenu", "QMenuBar", "QMenu::item", "QMenuBar::item"):
        assert rules[selector]["color"] == palette.color(QPalette.Active, QPalette.WindowText).name()
        assert rules[selector]["background-color"] == palette.color(QPalette.Active, QPalette.Window).name()
    for selector in ("QMenu::item:selected:enabled", "QMenuBar::item:selected:enabled", "QMenuBar::item:pressed:enabled"):
        assert rules[selector]["color"] == palette.color(QPalette.Active, QPalette.HighlightedText).name()
        assert rules[selector]["background-color"] == palette.color(QPalette.Active, QPalette.Highlight).name()
    for selector in ("QMenu:disabled", "QMenuBar:disabled", "QMenu::item:disabled", "QMenuBar::item:disabled"):
        assert rules[selector]["color"] == palette.color(QPalette.Disabled, QPalette.WindowText).name()
