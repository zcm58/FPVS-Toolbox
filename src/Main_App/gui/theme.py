"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    ACCENT_COLOR_HOVER,
    ACCENT_COLOR_PRESSED,
    ACCENT_SOFT_BG,
    ACCENT_SOFT_BORDER,
    ACCENT_TINT,
    BORDER_COLOR,
    BORDER_SOFT_COLOR,
    CONTENT_BG,
    CORNER_RADIUS,
    DANGER_COLOR,
    DANGER_COLOR_HOVER,
    DANGER_SOFT_BG,
    DANGER_SOFT_BORDER,
    INFO_BG,
    INFO_BORDER,
    LOG_BG,
    PAGE_BG,
    SUCCESS_SOFT_BG,
    SUCCESS_SOFT_BORDER,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING_SOFT_BG,
    WARNING_SOFT_BORDER,
)

try:  # qt_material is optional; we fall back to Fusion if it's missing.
    from qt_material import apply_stylesheet as _qt_material_apply_stylesheet  # type: ignore[import]
except Exception:  # pragma: no cover - import guard
    _qt_material_apply_stylesheet = None

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
            font-weight: 400;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 4px;
            color: {TEXT_PRIMARY};
            font-weight: 600;
        }}

        QWidget[cardHeader="true"] {{
            background: transparent;
        }}

        QLabel[cardTitle="true"] {{
            color: {TEXT_PRIMARY};
            font-weight: 600;
            padding: 0;
        }}

        QLabel[caption="true"] {{
            color: {TEXT_SECONDARY};
            font-weight: 600;
        }}

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

        QProgressBar {{
            text-align: center;
            background: #EBEEF3;
        }}

        QProgressBar::chunk {{
            background-color: {ACCENT_COLOR};
            border-radius: 7px;
        }}

        QPushButton,
        QToolButton {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 8px;
            padding: 7px 12px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QPushButton:hover,
        QToolButton:hover {{
            background: {ACCENT_SOFT_BG};
            border-color: {ACCENT_SOFT_BORDER};
        }}

        QPushButton:pressed,
        QToolButton:pressed {{
            background: #DDEAF7;
        }}

        QPushButton:disabled,
        QToolButton:disabled {{
            background: #F1F3F6;
            border-color: {BORDER_COLOR};
            color: {TEXT_MUTED};
        }}

        QPushButton[compact="true"],
        QToolButton[compact="true"] {{
            padding: 5px 10px;
            border-radius: 7px;
        }}

        QPushButton[primary="true"],
        QPushButton[variant="primary"] {{
            background-color: {ACCENT_COLOR};
            border-color: {ACCENT_COLOR};
            color: white;
            font-weight: 600;
            padding: 8px 18px;
        }}

        QPushButton[primary="true"]:hover,
        QPushButton[variant="primary"]:hover {{
            background-color: {ACCENT_COLOR_HOVER};
            border-color: {ACCENT_COLOR_HOVER};
        }}

        QPushButton[primary="true"]:pressed,
        QPushButton[variant="primary"]:pressed {{
            background-color: {ACCENT_COLOR_PRESSED};
            border-color: {ACCENT_COLOR_PRESSED};
        }}

        QPushButton[primary="true"]:disabled,
        QPushButton[variant="primary"]:disabled {{
            background: #BFD5EE;
            border-color: #BFD5EE;
            color: white;
        }}

        QPushButton[secondary="true"],
        QPushButton[variant="secondary"] {{
            background: {SURFACE_ALT_BG};
            border-color: {BORDER_SOFT_COLOR};
            color: {TEXT_SECONDARY};
        }}

        QPushButton[secondary="true"]:hover,
        QPushButton[variant="secondary"]:hover {{
            background: #F2F6FA;
            border-color: {BORDER_COLOR};
            color: {TEXT_PRIMARY};
        }}

        QPushButton[tertiary="true"],
        QPushButton[variant="tertiary"] {{
            background: transparent;
            border-color: transparent;
            color: {ACCENT_COLOR};
            padding-left: 6px;
            padding-right: 6px;
        }}

        QPushButton[tertiary="true"]:hover,
        QPushButton[variant="tertiary"]:hover {{
            background: {ACCENT_TINT};
            border-color: transparent;
            color: {ACCENT_COLOR_HOVER};
        }}

        QPushButton[tertiary="true"]:pressed,
        QPushButton[variant="tertiary"]:pressed {{
            background: #D7E7F8;
        }}

        QPushButton[variant="danger"] {{
            background: {DANGER_COLOR};
            border-color: {DANGER_COLOR};
            color: white;
            font-weight: 600;
        }}

        QPushButton[variant="danger"]:hover {{
            background: {DANGER_COLOR_HOVER};
            border-color: {DANGER_COLOR_HOVER};
        }}

        QPushButton[variant="danger"]:disabled {{
            background: {DANGER_SOFT_BORDER};
            border-color: {DANGER_SOFT_BORDER};
            color: white;
        }}

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
        }}

        QTabBar::tab:selected {{
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
            font-weight: 600;
        }}

        QTextEdit[logSurface="true"],
        QPlainTextEdit[logSurface="true"] {{
            background: {LOG_BG};
        }}

        QWidget[statusVariant="info"] {{
            background: {INFO_BG};
            border: 1px solid {INFO_BORDER};
            border-radius: 8px;
        }}

        QWidget[statusVariant="warning"] {{
            background: {WARNING_SOFT_BG};
            border: 1px solid {WARNING_SOFT_BORDER};
            border-radius: 8px;
        }}

        QWidget[statusVariant="error"] {{
            background: {DANGER_SOFT_BG};
            border: 1px solid {DANGER_SOFT_BORDER};
            border-radius: 8px;
        }}

        QWidget[statusVariant="success"] {{
            background: {SUCCESS_SOFT_BG};
            border: 1px solid {SUCCESS_SOFT_BORDER};
            border-radius: 8px;
        }}
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
    if _qt_material_apply_stylesheet is None:
        # qt_material not available in this environment – fall back to Fusion.
        logger.warning(
            "qt_material is not installed or failed to import; "
            "falling back to Fusion light palette."
        )
        apply_fusion_light_palette(app)
        return

    # Qt-Material will set up its own stylesheet/palette combo.
    try:
        _qt_material_apply_stylesheet(app, theme=theme, invert_secondary=invert_secondary)
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

    This is the function used by all entry points (main app, Image Resizer,
    Plot Generator). Existing callers that just do `apply_light_palette(app)`
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

    app.setStyleSheet(build_fpvs_app_stylesheet())
