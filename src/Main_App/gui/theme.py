"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    BORDER_COLOR,
    BORDER_SOFT_COLOR,
    CONTENT_BG,
    CORNER_RADIUS,
    DANGER_COLOR,
    LOG_BG,
    PAGE_BG,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    build_action_button_stylesheet,
    build_card_header_stylesheet,
    build_progress_bar_stylesheet,
    build_status_banner_stylesheet,
    build_tool_label_stylesheet,
)
from Main_App.gui.typography import apply_app_font, css_font_family, css_font_size, css_font_weight

logger = logging.getLogger(__name__)

LightThemeName = Literal["fusion", "material"]

# ---------------------------------------------------------------------------
# Default light theme for the whole app
#   - "fusion": your current deterministic Fusion + light palette
#   - "material": Qt-Material light theme via qt_material
#
# To globally switch the app to Qt-Material light:
#   1) Change DEFAULT_LIGHT_THEME to "material"
#   OR
#   2) Call apply_light_palette(app, theme="material") at each entry point.
# ---------------------------------------------------------------------------
LIGHT_THEME_FUSION: LightThemeName = "fusion"
LIGHT_THEME_MATERIAL: LightThemeName = "material"

DEFAULT_LIGHT_THEME: LightThemeName = LIGHT_THEME_FUSION


def build_fpvs_app_stylesheet() -> str:
    """Return the shared FPVS stylesheet for app and tool windows."""
    return f"""
        QWidget {{
            color: {TEXT_PRIMARY};
            font-family: {css_font_family()};
            font-size: {css_font_size("body")};
        }}

        QWidget[fpvsSurface="true"] {{
            background: {PAGE_BG};
        }}

        QGroupBox {{
            border: 1px solid {BORDER_SOFT_COLOR};
            border-radius: {CORNER_RADIUS}px;
            margin-top: 0;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
            font-weight: {css_font_weight("body")};
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 4px;
            color: {TEXT_PRIMARY};
            font-weight: {css_font_weight("caption")};
        }}

        {build_card_header_stylesheet()}

        QLabel[caption="true"] {{
            color: {TEXT_SECONDARY};
            font-size: {css_font_size("caption")};
            font-weight: {css_font_weight("caption")};
        }}

        {build_tool_label_stylesheet()}

        QLineEdit,
        QComboBox,
        QSpinBox,
        QDoubleSpinBox,
        QTextEdit,
        QPlainTextEdit,
        QProgressBar {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 8px;
            padding: 6px 10px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QLineEdit:focus,
        QComboBox:focus,
        QSpinBox:focus,
        QDoubleSpinBox:focus,
        QTextEdit:focus,
        QPlainTextEdit:focus {{
            border-color: {ACCENT_COLOR};
        }}

        QLineEdit:read-only {{
            background: {SURFACE_ALT_BG};
        }}

        QLineEdit:disabled,
        QComboBox:disabled,
        QSpinBox:disabled,
        QDoubleSpinBox:disabled,
        QTextEdit:disabled,
        QPlainTextEdit:disabled {{
            background: #F1F3F6;
            color: {TEXT_MUTED};
        }}

        QLineEdit[invalid="true"] {{
            border: 1px solid {DANGER_COLOR};
        }}

        {build_progress_bar_stylesheet()}

        {build_action_button_stylesheet()}

        QTabWidget::pane {{
            border: 1px solid {BORDER_SOFT_COLOR};
            border-radius: {CORNER_RADIUS}px;
            background: {CONTENT_BG};
        }}

        QTabBar::tab {{
            border: 1px solid {BORDER_SOFT_COLOR};
            border-bottom: none;
            border-top-left-radius: 7px;
            border-top-right-radius: 7px;
            padding: 7px 12px;
            background: {SURFACE_ALT_BG};
            color: {TEXT_SECONDARY};
            font-size: {css_font_size("tab")};
            font-weight: {css_font_weight("tab")};
        }}

        QTabBar::tab:selected {{
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
            font-weight: {css_font_weight("tab_selected")};
        }}

        QTextEdit[logSurface="true"],
        QPlainTextEdit[logSurface="true"] {{
            background: {LOG_BG};
        }}

        {build_status_banner_stylesheet()}
    """


def apply_fusion_light_palette(app: QApplication) -> None:
    """Apply a deterministic Fusion + light palette regardless of OS theme."""
    app.setStyle("Fusion")
    palette = app.palette()

    # Core surfaces
    palette.setColor(QPalette.Window, QColor("white"))
    palette.setColor(QPalette.Base, QColor("white"))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))

    # Text / foregrounds
    palette.setColor(QPalette.Text, QColor("black"))
    palette.setColor(QPalette.WindowText, QColor("black"))
    palette.setColor(QPalette.ButtonText, QColor("black"))

    # Buttons / controls
    palette.setColor(QPalette.Button, QColor(240, 240, 240))

    # Tooltips
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText, QColor("black"))

    # Selection / accents
    palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.HighlightedText, QColor("white"))

    # Disabled state readability
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(128, 128, 128))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(128, 128, 128))

    app.setPalette(palette)


def apply_material_light_theme(
    app: QApplication,
    theme: str = "light_blue.xml",
    invert_secondary: bool = True,
) -> None:
    """
    Apply a Qt-Material light theme, if qt_material is available.

    Parameters
    ----------
    app:
        The QApplication instance.
    theme:
        Qt-Material theme name, e.g. "light_blue.xml", "light_cyan_500.xml", etc.
    invert_secondary:
        Passed through to qt_material.apply_stylesheet; True is recommended for light themes.
    """
    try:
        from qt_material import apply_stylesheet as qt_material_apply_stylesheet  # type: ignore[import]
    except Exception:  # pragma: no cover - optional dependency import guard
        # qt_material not available in this environment – fall back to Fusion.
        logger.warning(
            "qt_material is not installed or failed to import; "
            "falling back to Fusion light palette."
        )
        apply_fusion_light_palette(app)
        return

    # Qt-Material will set up its own stylesheet/palette combo.
    try:
        qt_material_apply_stylesheet(app, theme=theme, invert_secondary=invert_secondary)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to apply Qt-Material theme %r: %s; falling back to Fusion.", theme, exc)
        apply_fusion_light_palette(app)


def apply_light_palette(
    app: QApplication,
    *,
    theme: Optional[LightThemeName] = None,
    material_theme: str = "light_blue.xml",
) -> None:
    """Apply the configured application-wide FPVS light theme.

    This is the function used by all entry points, including the main app and
    Plot Generator. Existing callers that just do `apply_light_palette(app)`
    will continue to get the Fusion light palette.

    Parameters
    ----------
    app:
        The QApplication instance.
    theme:
        "fusion" or "material". If None, uses DEFAULT_LIGHT_THEME.
    material_theme:
        The Qt-Material theme name when `theme="material"`.
    """
    apply_fpvs_theme(app, theme=theme, material_theme=material_theme)


def apply_fpvs_theme(
    app: QApplication,
    *,
    theme: Optional[LightThemeName] = None,
    material_theme: str = "light_blue.xml",
) -> None:
    """Apply the central FPVS palette and shared stylesheet."""
    chosen: LightThemeName = theme or DEFAULT_LIGHT_THEME
    if chosen == LIGHT_THEME_MATERIAL:
        apply_material_light_theme(app, theme=material_theme)
    else:
        apply_fusion_light_palette(app)

    apply_app_font(app)
    app.setStyleSheet(build_fpvs_app_stylesheet())
