"""Utilities for applying consistent theming across PySide6 entry points."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import Literal, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    ACCENT_SOFT_BG,
    ACCENT_TINT,
    BORDER_SOFT_COLOR,
    CONTROL_BORDER,
    CONTENT_BG,
    CORNER_RADIUS,
    DANGER_COLOR,
    FOCUS_COLOR,
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
    build_workspace_chrome_stylesheet,
    render_ui_stylesheet,
    resolve_ui_color,
)
from Main_App.gui.typography import app_font, apply_app_font, css_font_family, css_font_size, css_font_weight

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
    chevron_down = _appearance_asset_url("chevron-down")
    chevron_up = _appearance_asset_url("chevron-up")
    checkbox_check = _appearance_asset_url("checkbox-check")
    return f"""
        QWidget {{
            color: {TEXT_PRIMARY};
            font-family: {css_font_family()};
            font-size: {css_font_size("body")};
        }}

        QWidget[fpvsSurface="true"] {{
            background: {PAGE_BG};
        }}

        QMenu {{
            background-color: {SURFACE_BG};
            border: 1px solid {BORDER_SOFT_COLOR};
        }}

        QMenu::item:disabled {{
            color: {TEXT_MUTED};
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

        QCheckBox::indicator,
        QRadioButton::indicator {{
            width: 11px;
            height: 11px;
            border: 1px solid {CONTROL_BORDER};
            background: {SURFACE_BG};
        }}

        QCheckBox::indicator {{
            border-radius: 3px;
        }}

        QRadioButton::indicator {{
            border-radius: 6px;
        }}

        QCheckBox::indicator:checked {{
            background: {ACCENT_COLOR};
            border-color: {ACCENT_COLOR};
            image: {checkbox_check};
        }}

        QCheckBox::indicator:indeterminate {{
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {SURFACE_BG}, stop: 0.38 {SURFACE_BG},
                stop: 0.39 {TEXT_SECONDARY}, stop: 0.61 {TEXT_SECONDARY},
                stop: 0.62 {SURFACE_BG}, stop: 1 {SURFACE_BG});
        }}

        QRadioButton::indicator:checked {{
            border-color: {ACCENT_COLOR};
            background: qradialgradient(cx: 0.5, cy: 0.5, fx: 0.5, fy: 0.5, radius: 0.5,
                stop: 0 {ACCENT_COLOR}, stop: 0.42 {ACCENT_COLOR},
                stop: 0.57 {SURFACE_BG}, stop: 1 {SURFACE_BG});
        }}

        QCheckBox::indicator:hover:enabled,
        QRadioButton::indicator:hover:enabled {{
            border-color: {ACCENT_COLOR};
        }}

        QCheckBox::indicator:focus:enabled,
        QRadioButton::indicator:focus:enabled {{
            border-color: {FOCUS_COLOR};
        }}

        QCheckBox:disabled,
        QRadioButton:disabled {{
            color: {TEXT_MUTED};
        }}

        QCheckBox::indicator:unchecked:disabled,
        QRadioButton::indicator:unchecked:disabled {{
            background: {PAGE_BG};
        }}

        QCheckBox::indicator:checked:disabled {{
            background: {CONTROL_BORDER};
            border-color: {CONTROL_BORDER};
        }}

        QRadioButton::indicator:checked:disabled {{
            border-color: {CONTROL_BORDER};
            background: qradialgradient(cx: 0.5, cy: 0.5, fx: 0.5, fy: 0.5, radius: 0.5,
                stop: 0 {CONTROL_BORDER}, stop: 0.42 {CONTROL_BORDER},
                stop: 0.57 {PAGE_BG}, stop: 1 {PAGE_BG});
        }}

        QLineEdit,
        QComboBox,
        QSpinBox,
        QDoubleSpinBox,
        QTextEdit,
        QPlainTextEdit,
        QProgressBar {{
            border: 1px solid {CONTROL_BORDER};
            border-radius: 8px;
            padding: 6px 10px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QLineEdit,
        QComboBox,
        QTextEdit,
        QPlainTextEdit {{
            placeholder-text-color: {TEXT_MUTED};
        }}

        QComboBox {{
            padding-right: 28px;
        }}

        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: center right;
            width: 26px;
            background: transparent;
            border: none;
        }}

        QComboBox::down-arrow {{
            image: {chevron_down};
            width: 12px;
            height: 12px;
        }}

        QSpinBox::up-button,
        QDoubleSpinBox::up-button,
        QSpinBox::down-button,
        QDoubleSpinBox::down-button {{
            subcontrol-origin: padding;
            width: 18px;
            background: transparent;
            border: none;
        }}

        QSpinBox::up-button,
        QDoubleSpinBox::up-button {{
            subcontrol-position: top right;
            border-top-right-radius: 7px;
        }}

        QSpinBox::down-button,
        QDoubleSpinBox::down-button {{
            subcontrol-position: bottom right;
            border-bottom-right-radius: 7px;
        }}

        QSpinBox::up-button:hover:enabled:on,
        QDoubleSpinBox::up-button:hover:enabled:on,
        QSpinBox::down-button:hover:enabled:on,
        QDoubleSpinBox::down-button:hover:enabled:on {{
            background: {ACCENT_TINT};
        }}

        QSpinBox::up-arrow,
        QDoubleSpinBox::up-arrow,
        QSpinBox::down-arrow,
        QDoubleSpinBox::down-arrow {{
            width: 11px;
            height: 11px;
        }}

        QSpinBox::up-arrow,
        QDoubleSpinBox::up-arrow {{
            image: {chevron_up};
        }}

        QSpinBox::down-arrow,
        QDoubleSpinBox::down-arrow {{
            image: {chevron_down};
        }}

        QLineEdit:focus,
        QComboBox:focus,
        QSpinBox:focus,
        QDoubleSpinBox:focus,
        QTextEdit:focus,
        QPlainTextEdit:focus {{
            border-color: {FOCUS_COLOR};
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
            background: {PAGE_BG};
            color: {TEXT_MUTED};
        }}

        QLineEdit[invalid="true"] {{
            border: 1px solid {DANGER_COLOR};
        }}

        {build_progress_bar_stylesheet()}

        {build_action_button_stylesheet()}

        {build_workspace_chrome_stylesheet()}

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
            background: {ACCENT_SOFT_BG};
            color: {TEXT_PRIMARY};
            font-weight: {css_font_weight("tab_selected")};
        }}

        QTabBar::tab:selected:focus {{
            border-color: {FOCUS_COLOR};
        }}

        QListWidget#settings_navigation {{
            background: {PAGE_BG};
            border: none;
            outline: none;
        }}

        QListWidget#settings_navigation::item {{
            padding: 6px 9px;
            border: 1px solid transparent;
            border-radius: 6px;
        }}

        QListWidget#settings_navigation::item:hover {{
            background: {ACCENT_TINT};
        }}

        QListWidget#settings_navigation::item:selected {{
            background: {ACCENT_SOFT_BG};
            border-color: {ACCENT_COLOR};
            color: {TEXT_PRIMARY};
        }}

        QListWidget#settings_navigation::item:focus {{
            border-color: {FOCUS_COLOR};
        }}

        QTextEdit[logSurface="true"],
        QPlainTextEdit[logSurface="true"] {{
            background: {LOG_BG};
        }}

        {build_status_banner_stylesheet()}
    """


def _appearance_asset_url(name: str, *, dark: bool = False) -> str:
    filename = f"{name}{'-dark' if dark else ''}.svg"
    return f'url("{Path(__file__).with_name(filename).as_posix()}")'


def _render_stylesheet(stylesheet: str, *, dark: bool) -> str:
    if not dark:
        return stylesheet
    result = render_ui_stylesheet(stylesheet, dark=True)
    for name in ("chevron-up", "chevron-down", "checkbox-check"):
        result = result.replace(_appearance_asset_url(name), _appearance_asset_url(name, dark=True))
    return result


def appearance_is_dark(app: QApplication | None = None) -> bool:
    """Return whether the active Toolbox theme is dark."""
    app = app if app is not None else QApplication.instance()
    if app is None:
        return False
    mode = app.property("fpvsAppearanceMode")
    return mode == "dark" or (mode == "auto" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark)


def theme_color(light_color: str) -> QColor:
    """Resolve a shared UI token for custom painting, independently of figure colors."""
    return QColor(resolve_ui_color(light_color, dark=appearance_is_dark()))


def set_themed_stylesheet(widget: QWidget, stylesheet: str) -> None:
    """Apply widget-local semantic QSS and keep its source for live theme changes."""
    if widget.property("fpvsStylesheetSource") != stylesheet:
        widget.setProperty("fpvsStylesheetSource", stylesheet)
    _apply_widget_stylesheet(widget, stylesheet, dark=appearance_is_dark())


def _apply_widget_stylesheet(widget: QWidget, source: str, *, dark: bool) -> None:
    stylesheet = _render_stylesheet(source, dark=dark)
    if widget.styleSheet() != stylesheet:
        widget.setStyleSheet(stylesheet)


def _apply_fusion_palette(app: QApplication, *, dark: bool) -> None:
    palette = app.style().standardPalette()

    for role, color in (
        (QPalette.Window, PAGE_BG),
        (QPalette.Base, SURFACE_BG),
        (QPalette.AlternateBase, SURFACE_ALT_BG),
        (QPalette.Text, TEXT_PRIMARY),
        (QPalette.WindowText, TEXT_PRIMARY),
        (QPalette.ButtonText, TEXT_PRIMARY),
        (QPalette.Button, SURFACE_BG),
        (QPalette.ToolTipBase, SURFACE_BG if dark else "#FFFFDC"),
        (QPalette.ToolTipText, TEXT_PRIMARY),
        (QPalette.PlaceholderText, TEXT_MUTED),
        (QPalette.Highlight, ACCENT_SOFT_BG),
        (QPalette.HighlightedText, TEXT_PRIMARY),
        (QPalette.Link, ACCENT_COLOR),
        (QPalette.LinkVisited, ACCENT_COLOR),
        (QPalette.Mid, BORDER_SOFT_COLOR),
    ):
        palette.setColor(role, QColor(resolve_ui_color(color, dark=dark)))

    if dark:
        palette.setColor(QPalette.Dark, QColor(resolve_ui_color(LOG_BG, dark=True)))
        palette.setColor(QPalette.Light, QColor(resolve_ui_color(CONTROL_BORDER, dark=True)))
        palette.setColor(QPalette.Midlight, QColor(resolve_ui_color(BORDER_SOFT_COLOR, dark=True)))

    disabled_color = QColor(resolve_ui_color(TEXT_MUTED, dark=dark))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, disabled_color)

    if app.palette() != palette:
        app.setPalette(palette)


def apply_fusion_light_palette(app: QApplication) -> None:
    """Apply a deterministic Fusion + light palette regardless of OS theme."""
    app.setStyle("Fusion")
    _apply_fusion_palette(app, dark=False)


def _apply_app_appearance(app: QApplication) -> None:
    # Qt wraps the base style when app QSS is active. Keep the actual
    # wrapper so we can detect a caller switching styles without resetting Fusion.
    if app.style() is not getattr(app, "_fpvs_fusion_style", None):
        app.setStyle("Fusion")
    font = app_font()
    if app.font() != font:
        app.setFont(font)

    dark = appearance_is_dark(app)
    _apply_fusion_palette(app, dark=dark)
    stylesheet = _render_stylesheet(build_fpvs_app_stylesheet(), dark=dark)
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)
    app._fpvs_fusion_style = app.style()
    for widget in app.allWidgets():
        source = widget.property("fpvsStylesheetSource")
        if source is not None:
            _apply_widget_stylesheet(widget, source, dark=dark)


def _system_appearance_changed(app: QApplication, _scheme: Qt.ColorScheme) -> None:
    if app.property("fpvsAppearanceMode") == "auto":
        _apply_app_appearance(app)


def set_appearance_mode(app: QApplication, mode: str) -> None:
    """Apply Light, Dark, or Follow system throughout the running application."""
    schemes = {
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
        "auto": Qt.ColorScheme.Unknown,
    }
    key = mode.strip().lower()
    if key not in schemes:
        raise ValueError("Appearance must be Light, Dark, or Auto.")
    hints = app.styleHints()
    if app.property("fpvsAppearanceMode") is None:
        # Qt announces colorSchemeChanged before updating the platform palette.
        hints.colorSchemeChanged.connect(partial(_system_appearance_changed, app), Qt.QueuedConnection)
    app.setProperty("fpvsAppearanceMode", key)
    hints.setColorScheme(schemes[key])
    _apply_app_appearance(app)


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
    set_appearance_mode(app, "Light")
    if chosen == LIGHT_THEME_MATERIAL:
        apply_material_light_theme(app, theme=material_theme)
        apply_app_font(app)
        app.setStyleSheet(build_fpvs_app_stylesheet())
