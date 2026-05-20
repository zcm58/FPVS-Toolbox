from __future__ import annotations

from Main_App.gui.typography import (
    APP_FONT_FAMILY,
    FONT_ROLES,
    css_font_family,
    css_font_size,
    css_font_weight,
    fixed_width_font,
    font_for_role,
)


def test_typography_roles_define_single_font_family_and_role_sizes() -> None:
    body_font = font_for_role("body")
    sidebar_font = font_for_role("sidebar_section")
    landing_title_font = font_for_role("landing_title")
    landing_action_font = font_for_role("landing_action")

    assert APP_FONT_FAMILY in body_font.families()
    assert APP_FONT_FAMILY in sidebar_font.families()
    assert APP_FONT_FAMILY in landing_title_font.families()
    assert APP_FONT_FAMILY in landing_action_font.families()
    assert FONT_ROLES["body"].point_size == 10
    assert FONT_ROLES["sidebar_item"].point_size == 11
    assert css_font_size("sidebar_item") == "15px"
    assert FONT_ROLES["sidebar_section"].point_size == FONT_ROLES["sidebar_item"].point_size
    assert FONT_ROLES["project_title"].point_size > FONT_ROLES["caption"].point_size
    assert FONT_ROLES["landing_title"].point_size == 44
    assert FONT_ROLES["landing_action"].point_size == 15
    assert css_font_family().startswith('"Segoe UI"')
    assert css_font_size("landing_title") == "60px"
    assert css_font_size("landing_action") == "20px"
    assert css_font_size("tab") == "13px"
    assert css_font_weight("sidebar_section") == 650


def test_fixed_width_font_uses_central_app_family_and_role_size() -> None:
    font = fixed_width_font()

    assert font.pointSize() == FONT_ROLES["body"].point_size
    assert APP_FONT_FAMILY in font.families()
