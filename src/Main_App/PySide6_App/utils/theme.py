"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

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
    """
    Apply the configured application-wide light theme.

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
    chosen: LightThemeName = theme or DEFAULT_LIGHT_THEME

    if chosen == LIGHT_THEME_MATERIAL:
        apply_material_light_theme(app, theme=material_theme)
    else:
        apply_fusion_light_palette(app)
