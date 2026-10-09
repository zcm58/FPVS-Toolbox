from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor, QPalette

from Main_App.gui import theme
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
    styles = []

    def create_style(name):
        style = SimpleNamespace(name=name, setParent=lambda owner: setattr(style, "owner", owner))
        styles.append(style)
        return style

    def apply_light_palette(current):
        current.style_name = "Fusion"
        current.colors = QPalette()
        current.colors.setColor(QPalette.Window, QColor("white"))
        current.colors.setColor(QPalette.WindowText, QColor("black"))

    monkeypatch.setattr(theme, "QStyleFactory", SimpleNamespace(create=create_style))
    monkeypatch.setattr(theme, "apply_fusion_light_palette", apply_light_palette)
    monkeypatch.setattr(theme, "apply_app_font", lambda _app: None)
    monkeypatch.setattr(theme, "build_fpvs_app_stylesheet", lambda: "light stylesheet")

    theme.apply_fpvs_theme(app)
    style, palette = theme._native_menu_appearance(app)
    theme.apply_fpvs_theme(app)

    assert len(styles) == 1
    assert styles[0].name == "platform"
    assert styles[0].owner is app
    assert theme._native_menu_appearance(app) == (style, palette)
    resolved = palette.resolve(app.colors)
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role in QPalette.ColorRole:
            if role not in (QPalette.NoRole, QPalette.NColorRoles):
                assert resolved.brush(group, role) == native_palette.brush(group, role)
    assert app.style_name == "Fusion"
    assert app.colors.color(QPalette.Window) == QColor("white")
    assert app.colors.color(QPalette.WindowText) == QColor("black")
    assert app.stylesheet == "light stylesheet"


def test_native_menu_style_creation_failure_is_explicit(monkeypatch) -> None:
    app = SimpleNamespace(style=lambda: SimpleNamespace(objectName=lambda: "unavailable"))
    monkeypatch.setattr(theme, "QStyleFactory", SimpleNamespace(create=lambda _name: None))

    with pytest.raises(RuntimeError, match="Cannot create the native menu style 'unavailable'"):
        theme._native_menu_appearance(app)
    assert not hasattr(app, "_fpvs_native_menu_appearance")
