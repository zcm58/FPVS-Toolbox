from __future__ import annotations

from Main_App.gui.sidebar import (
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


def test_sidebar_section_headers_are_visually_distinct() -> None:
    stylesheet = build_sidebar_stylesheet()

    assert "#SidebarSectionLabel" in stylesheet
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
