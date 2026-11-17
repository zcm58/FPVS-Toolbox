"""Scoped style tokens for the PySide6 main shell polish pass."""

from __future__ import annotations

import re

from Main_App.gui.typography import css_font_size, css_font_weight

ACCENT_COLOR = "#00646C"
ACCENT_COLOR_HOVER = "#00535B"
ACCENT_COLOR_PRESSED = "#00484F"
ACCENT_SOFT_BG = "#DDEEF0"
ACCENT_SOFT_BORDER = "#B9D5D9"
ACCENT_TINT = "#E8F3F4"
FOCUS_COLOR = "#805C23"
SIGNAL_COLOR = "#25B8C4"
PROGRESS_FILL = "#469DA3"
DANGER_COLOR = "#B42318"
DANGER_COLOR_HOVER = "#912018"
DANGER_SOFT_BG = "#FEEDEB"
DANGER_SOFT_BORDER = "#F6C8C3"
SUCCESS_SOFT_BG = "#EAF6EE"
SUCCESS_SOFT_BORDER = "#BFE5CB"
WARNING_SOFT_BG = "#FFF5D6"
WARNING_SOFT_BORDER = "#E7D184"

PAGE_BG = "#F3F6F8"
CONTENT_BG = PAGE_BG
SURFACE_BG = "#FFFFFF"
SURFACE_ALT_BG = PAGE_BG
LOG_PANEL_BG = PAGE_BG
LOG_BG = "#EAF0F3"

BORDER_COLOR = "#CBD9DE"
BORDER_SOFT_COLOR = BORDER_COLOR
CONTROL_BORDER = "#6A7C87"
TEXT_PRIMARY = "#1D2A34"
TEXT_SECONDARY = "#4D626D"
TEXT_MUTED = TEXT_SECONDARY
ON_ACTION = "white"

HEADER_BG = "#222F3B"
INFO_BG = "#F1F6FC"
INFO_BORDER = "#D5E2F0"

CHROME_HOVER = "#2C3D49"
CHROME_ACTIVE = "#2A4350"
CHROME_TEXT = "#F1F6F8"
CHROME_MUTED_TEXT = "#A5B7C2"

# Light tokens remain the stylesheet authoring values. Translate only these
# explicit interface roles so scientific colors and authored asset URLs stay separate.
_DARK_COLORS = {
    ACCENT_COLOR: "#61D4CE",
    ACCENT_COLOR_HOVER: "#82E2DA",
    ACCENT_COLOR_PRESSED: "#46BAB6",
    ACCENT_SOFT_BG: "#28454C",
    ACCENT_SOFT_BORDER: "#557E85",
    ACCENT_TINT: "#243B43",
    FOCUS_COLOR: "#F2BF69",
    SIGNAL_COLOR: "#53CAD0",
    PROGRESS_FILL: "#267778",
    DANGER_COLOR: "#F1948D",
    DANGER_COLOR_HOVER: "#FFAAA0",
    DANGER_SOFT_BG: "#432B30",
    DANGER_SOFT_BORDER: "#86535A",
    SUCCESS_SOFT_BG: "#223B32",
    SUCCESS_SOFT_BORDER: "#587D68",
    WARNING_SOFT_BG: "#3F3525",
    WARNING_SOFT_BORDER: "#897348",
    PAGE_BG: "#18232B",
    SURFACE_BG: "#23323C",
    LOG_BG: "#141F27",
    BORDER_COLOR: "#435864",
    CONTROL_BORDER: "#7B919E",
    TEXT_PRIMARY: "#EEF3F5",
    TEXT_SECONDARY: "#B5C7D0",
    ON_ACTION: "#15252B",
    HEADER_BG: "#121B22",
    INFO_BG: "#263B49",
    INFO_BORDER: "#527186",
    CHROME_HOVER: "#24353F",
    CHROME_ACTIVE: "#28454C",
}
_DARK_COLORS = {color.lower(): dark for color, dark in _DARK_COLORS.items()}
_STYLE_COLOR = re.compile(
    r"""url\([^)]*\)|"[^"]*"|'[^']*'"""
    r"|(?P<hex>#[0-9a-f]{6}(?![0-9a-f]))"
    r"|(?P<on_action>(?<![\w-])color:\s*white(?=\s*(?:[;}]|$)))",
    re.IGNORECASE,
)


def resolve_ui_color(color: str, *, dark: bool) -> str:
    """Resolve a shared semantic color for an opt-in widget paint operation."""
    return _DARK_COLORS.get(color.lower(), color) if dark else color


def render_ui_stylesheet(stylesheet: str, *, dark: bool) -> str:
    """Resolve semantic colors in a stylesheet authored with light tokens."""
    if not dark:
        return stylesheet

    def replace_token(match: re.Match[str]) -> str:
        if match.lastgroup == "on_action":
            return f"color: {resolve_ui_color(ON_ACTION, dark=True)}"
        value = match.group()
        return resolve_ui_color(value, dark=True) if match.lastgroup == "hex" else value

    return _STYLE_COLOR.sub(replace_token, stylesheet)


PAGE_MARGIN = 22
SECTION_PADDING = 15
SECTION_HEADER_CONTENT_GAP = 8
SECTION_GAP = 12
SECTION_GRID_GAP = 8
COMPACT_SECTION_MAX_HEIGHT = 170
CORNER_RADIUS = 9

BROWSE_BUTTON_WIDTH = 156
EVENT_ID_COLUMN_WIDTH = 88
EVENT_REMOVE_BUTTON_SIZE = 30


def build_tool_label_stylesheet() -> str:
    """Return shared tool-title, result-value, and eyebrow label rules."""

    return f"""
        QLabel[toolTitle="true"] {{
            color: {TEXT_PRIMARY};
            font-size: {css_font_size("tool_title")};
            font-weight: {css_font_weight("tool_title")};
        }}

        QLabel[resultValue="true"] {{
            color: {TEXT_PRIMARY};
            font-size: {css_font_size("result_value")};
            font-weight: {css_font_weight("result_value")};
        }}

        QLabel[eyebrow="true"] {{
            color: {ACCENT_COLOR};
            font-size: {css_font_size("caption")};
            font-weight: {css_font_weight("caption")};
        }}
    """


def build_card_header_stylesheet() -> str:
    """Return shared card-header and subsection-header rules."""
    from Main_App.gui.widgets.labels import build_subsection_header_stylesheet

    return f"""
        QWidget[cardHeader="true"] {{
            background: transparent;
        }}

        {build_subsection_header_stylesheet()}
    """


def build_progress_bar_stylesheet() -> str:
    """Return shared progress-bar fill rules."""

    return f"""
        QProgressBar {{
            text-align: center;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QProgressBar::chunk {{
            background-color: {PROGRESS_FILL};
            border-radius: 7px;
        }}
    """


def build_action_button_stylesheet() -> str:
    """Return shared action-button variant rules."""

    return f"""
        QPushButton,
        QToolButton {{
            border: 1px solid {CONTROL_BORDER};
            border-radius: 8px;
            padding: 7px 12px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QPushButton:hover,
        QToolButton:hover {{
            background: {ACCENT_SOFT_BG};
            border-color: {ACCENT_COLOR};
        }}

        QPushButton:pressed,
        QToolButton:pressed {{
            background: {ACCENT_SOFT_BG};
        }}

        QPushButton:disabled,
        QToolButton:disabled {{
            background: {PAGE_BG};
            border-color: {BORDER_COLOR};
            color: {TEXT_MUTED};
        }}

        QPushButton[compact="true"],
        QToolButton[compact="true"] {{
            padding: 5px 10px;
            border-radius: 7px;
        }}

        QPushButton[iconButton="true"],
        QToolButton[iconButton="true"] {{
            min-width: {EVENT_REMOVE_BUTTON_SIZE}px;
            max-width: {EVENT_REMOVE_BUTTON_SIZE}px;
            min-height: {EVENT_REMOVE_BUTTON_SIZE}px;
            max-height: {EVENT_REMOVE_BUTTON_SIZE}px;
            padding: 0;
            text-align: center;
            font-size: 15px;
            font-weight: {css_font_weight("icon_glyph")};
        }}

        QPushButton[primary="true"],
        QPushButton[variant="primary"] {{
            background-color: {ACCENT_COLOR};
            border-color: {ACCENT_COLOR};
            color: {ON_ACTION};
            font-weight: {css_font_weight("button_strong")};
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
            background: {ACCENT_SOFT_BG};
            border-color: {ACCENT_SOFT_BORDER};
            color: {TEXT_MUTED};
        }}

        QPushButton[secondary="true"],
        QPushButton[variant="secondary"] {{
            background: {SURFACE_ALT_BG};
            border-color: {CONTROL_BORDER};
            color: {TEXT_SECONDARY};
        }}

        QPushButton[secondary="true"]:hover,
        QPushButton[variant="secondary"]:hover {{
            background: {ACCENT_TINT};
            border-color: {ACCENT_COLOR};
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
            background: {ACCENT_SOFT_BG};
        }}

        QPushButton[variant="danger"] {{
            background: {DANGER_COLOR};
            border-color: {DANGER_COLOR};
            color: {ON_ACTION};
            font-weight: {css_font_weight("button_strong")};
        }}

        QPushButton[variant="danger"]:hover {{
            background: {DANGER_COLOR_HOVER};
            border-color: {DANGER_COLOR_HOVER};
        }}

        QPushButton[variant="danger"]:disabled {{
            background: {DANGER_SOFT_BORDER};
            border-color: {DANGER_SOFT_BORDER};
            color: {DANGER_COLOR};
        }}

        QPushButton:focus:enabled,
        QToolButton:focus:enabled {{
            border-color: {FOCUS_COLOR};
        }}
    """


def build_status_banner_stylesheet() -> str:
    """Return shared status-banner variant rules."""

    return f"""
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


def build_main_page_stylesheet() -> str:
    """Return the scoped stylesheet for the polished main page."""
    return f"""
        QGroupBox {{
            border: 1px solid {BORDER_SOFT_COLOR};
            border-radius: {CORNER_RADIUS}px;
            margin-top: 0;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QGroupBox::title {{
            color: transparent;
            height: 0;
            width: 0;
            margin: 0;
            padding: 0;
        }}

        QScrollArea,
        #event_map_scroll {{
            background: transparent;
            border: none;
        }}

        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}

        QLabel {{
            color: {TEXT_PRIMARY};
        }}

        {build_tool_label_stylesheet()}

        {build_card_header_stylesheet()}

        QRadioButton {{
            color: {TEXT_PRIMARY};
            spacing: 8px;
        }}

        QLineEdit,
        QTextEdit,
        QProgressBar {{
            border: 1px solid {CONTROL_BORDER};
            border-radius: 8px;
            padding: 6px 10px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QLineEdit:focus,
        QTextEdit:focus {{
            border-color: {FOCUS_COLOR};
        }}

        QLineEdit:disabled,
        QTextEdit:disabled {{
            background: {PAGE_BG};
            color: {TEXT_MUTED};
        }}

        {build_progress_bar_stylesheet()}

        {build_action_button_stylesheet()}

        {build_status_banner_stylesheet()}

        #processing_group QLineEdit:read-only {{
            background: {SURFACE_ALT_BG};
        }}

        #processing_page {{
            background: {CONTENT_BG};
        }}

        #processing_title {{
            color: {TEXT_PRIMARY};
            font-size: {css_font_size("project_title")};
            font-weight: {css_font_weight("project_title")};
        }}

        #processing_message {{
            color: {TEXT_SECONDARY};
        }}

        #processing_checklist_label,
        #processing_current_file_label,
        #processing_summary_label {{
            color: {TEXT_SECONDARY};
        }}

        #processing_status_separator,
        #home_history_separator {{
            color: {BORDER_SOFT_COLOR};
            background: {BORDER_SOFT_COLOR};
            max-height: 1px;
        }}

        #project_processing_history,
        #home_condition_summary {{
            color: {TEXT_SECONDARY};
        }}

        #processing_progress_bar {{
            min-height: 38px;
            border: none;
            padding: 0;
        }}

        #processing_files_table {{
            background: {SURFACE_BG};
            alternate-background-color: {SURFACE_ALT_BG};
            border: none;
            border-radius: 0;
            gridline-color: {BORDER_SOFT_COLOR};
            color: {TEXT_PRIMARY};
        }}

        #processing_files_table QHeaderView::section {{
            background: {SURFACE_ALT_BG};
            border: none;
            border-bottom: 1px solid {BORDER_SOFT_COLOR};
            color: {TEXT_SECONDARY};
            font-weight: {css_font_weight("subsection_header")};
            padding: 7px 10px;
        }}

        #event_map_header QLabel {{
            color: {TEXT_SECONDARY};
            font-size: {css_font_size("subsection_header")};
            font-weight: {css_font_weight("subsection_header")};
            padding: 0 0 3px 0;
        }}

        #event_map_list {{
            background: transparent;
        }}

        #event_map_scroll {{
            border-top: 1px solid {BORDER_SOFT_COLOR};
        }}

        #event_map_scroll QScrollBar:vertical {{
            width: 12px;
            margin: 0;
            background: {PAGE_BG};
        }}

        #event_map_scroll QScrollBar::handle:vertical {{
            min-height: 28px;
            margin: 1px 2px;
            border-radius: 4px;
            background: {CONTROL_BORDER};
        }}

        #event_map_scroll QScrollBar::add-page:vertical,
        #event_map_scroll QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        #event_map_scroll QScrollBar::add-line:vertical,
        #event_map_scroll QScrollBar::sub-line:vertical {{
            height: 0;
        }}

        #event_map_row {{
            background: transparent;
            border: none;
            border-radius: 0;
        }}

        QLineEdit[event_map_role="id"] {{
            padding-left: 0;
            padding-right: 0;
        }}

        QGroupBox[diagnosticsCard="true"] {{
            background: {LOG_PANEL_BG};
            border-color: {BORDER_SOFT_COLOR};
        }}

    """


def build_workspace_chrome_stylesheet() -> str:
    """Style the main menu in Slate and Signal Teal."""
    return f"""
        QMenuBar#workspaceMenuBar {{
            background-color: {HEADER_BG};
            color: {CHROME_TEXT};
            border: none;
            padding: 2px 8px;
            spacing: 2px;
        }}

        QMenuBar#workspaceMenuBar::item {{
            background-color: {HEADER_BG};
            color: {CHROME_TEXT};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 4px 10px;
        }}

        QMenuBar#workspaceMenuBar::item:selected:enabled {{
            background-color: {CHROME_HOVER};
            border-color: {SIGNAL_COLOR};
        }}

        QMenuBar#workspaceMenuBar::item:pressed:enabled {{
            background-color: {CHROME_ACTIVE};
        }}

        QMenuBar#workspaceMenuBar::item:disabled {{
            color: {CHROME_MUTED_TEXT};
        }}

        QLabel#workspaceDebugLabel {{
            background: transparent;
            color: #F9D293;
            font-weight: {css_font_weight("caption")};
            padding: 0 10px;
        }}
    """


def build_landing_page_stylesheet() -> str:
    """Style the flat project entry page."""
    return f"""
        #LandingPage {{
            background: {PAGE_BG};
        }}

        #landing_title {{
            color: {TEXT_PRIMARY};
            font-size: {css_font_size("landing_title")};
            font-weight: {css_font_weight("landing_title")};
        }}

        #landing_subtitle {{
            color: {TEXT_SECONDARY};
        }}

        #welcome_actions_divider {{
            background: {BORDER_COLOR};
        }}
    """
