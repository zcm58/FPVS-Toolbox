"""Central typography roles for PySide6 GUI surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

APP_FONT_FAMILY = "Segoe UI"
APP_FONT_FAMILIES = (APP_FONT_FAMILY, "Arial")
APP_FONT_FAMILY_CSS = '"Segoe UI", Arial, sans-serif'

FontRole = Literal[
    "body",
    "caption",
    "subsection_header",
    "sidebar_item",
    "sidebar_section",
    "landing_title",
    "landing_action",
    "project_title",
    "update_title",
    "busy_status",
    "button_strong",
    "table_header",
    "tab",
    "tab_selected",
    "icon_glyph",
]


@dataclass(frozen=True)
class FontRoleSpec:
    point_size: int
    css_size_px: int
    qfont_weight: QFont.Weight
    css_weight: int


FONT_ROLES: dict[FontRole, FontRoleSpec] = {
    "body": FontRoleSpec(10, 13, QFont.Normal, 400),
    "caption": FontRoleSpec(10, 13, QFont.DemiBold, 600),
    "subsection_header": FontRoleSpec(10, 13, QFont.Bold, 700),
    "sidebar_item": FontRoleSpec(11, 15, QFont.Medium, 500),
    "sidebar_section": FontRoleSpec(11, 13, QFont.DemiBold, 650),
    "landing_title": FontRoleSpec(44, 60, QFont.Bold, 700),
    "landing_action": FontRoleSpec(15, 20, QFont.DemiBold, 600),
    "project_title": FontRoleSpec(16, 22, QFont.DemiBold, 600),
    "update_title": FontRoleSpec(12, 16, QFont.Bold, 700),
    "busy_status": FontRoleSpec(14, 19, QFont.Normal, 400),
    "button_strong": FontRoleSpec(10, 13, QFont.Bold, 700),
    "table_header": FontRoleSpec(10, 13, QFont.Normal, 400),
    "tab": FontRoleSpec(10, 13, QFont.Normal, 400),
    "tab_selected": FontRoleSpec(10, 13, QFont.DemiBold, 600),
    "icon_glyph": FontRoleSpec(10, 13, QFont.Bold, 700),
}


def _set_font_families(font: QFont) -> None:
    try:
        font.setFamilies(list(APP_FONT_FAMILIES))
    except AttributeError:  # pragma: no cover - older Qt bindings
        font.setFamily(APP_FONT_FAMILY)


def font_for_role(role: FontRole, base: QFont | None = None) -> QFont:
    spec = FONT_ROLES[role]
    font = QFont(base) if base is not None else QFont()
    _set_font_families(font)
    font.setPointSize(spec.point_size)
    font.setWeight(spec.qfont_weight)
    return font


def apply_font_role(widget: QWidget, role: FontRole) -> None:
    widget.setFont(font_for_role(role, widget.font()))


def app_font() -> QFont:
    return font_for_role("body")


def apply_app_font(app: QApplication) -> None:
    app.setFont(app_font())


def fixed_width_font(base: QFont | None = None) -> QFont:
    return font_for_role("body", base)


def css_font_family() -> str:
    return APP_FONT_FAMILY_CSS


def css_font_size(role: FontRole) -> str:
    return f"{FONT_ROLES[role].css_size_px}px"


def css_font_weight(role: FontRole) -> int:
    return FONT_ROLES[role].css_weight


def css_font_declaration(role: FontRole, *, include_family: bool = False) -> str:
    family_line = f'font-family: {css_font_family()};\n' if include_family else ""
    return (
        f"{family_line}"
        f"font-size: {css_font_size(role)};\n"
        f"font-weight: {css_font_weight(role)};"
    )
