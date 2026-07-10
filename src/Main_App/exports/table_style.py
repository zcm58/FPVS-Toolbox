"""GUI-neutral style contract for publication-table exports."""

from __future__ import annotations

from typing import Literal

TABLE_FONT_FAMILY_CSS = '"Segoe UI", Arial, sans-serif'
TABLE_HEADER_FONT_SIZE_PX = 16
TABLE_BODY_FONT_SIZE_PX = 14
TABLE_HEADER_FONT_WEIGHT = 600
TABLE_BODY_FONT_WEIGHT = 400

TABLE_SURFACE_BG = "#FFFFFF"
TABLE_SURFACE_ALT_BG = "#FCFDFE"
TABLE_BORDER_COLOR = "#D7DEE8"
TABLE_BORDER_SOFT_COLOR = "#E4EAF2"
TABLE_TEXT_COLOR = "#1F2328"

TableTextRole = Literal["header", "body"]


def table_font_size_px(role: TableTextRole) -> int:
    """Return the publication-table font size for a text role."""

    if role == "header":
        return TABLE_HEADER_FONT_SIZE_PX
    return TABLE_BODY_FONT_SIZE_PX


def table_font_weight(role: TableTextRole) -> int:
    """Return the publication-table CSS font weight for a text role."""

    if role == "header":
        return TABLE_HEADER_FONT_WEIGHT
    return TABLE_BODY_FONT_WEIGHT


__all__ = [
    "TABLE_BODY_FONT_SIZE_PX",
    "TABLE_BODY_FONT_WEIGHT",
    "TABLE_BORDER_COLOR",
    "TABLE_BORDER_SOFT_COLOR",
    "TABLE_FONT_FAMILY_CSS",
    "TABLE_HEADER_FONT_SIZE_PX",
    "TABLE_HEADER_FONT_WEIGHT",
    "TABLE_SURFACE_ALT_BG",
    "TABLE_SURFACE_BG",
    "TABLE_TEXT_COLOR",
    "TableTextRole",
    "table_font_size_px",
    "table_font_weight",
]
