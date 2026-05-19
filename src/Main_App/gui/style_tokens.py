"""Scoped style tokens for the PySide6 main shell polish pass."""

from __future__ import annotations

ACCENT_COLOR = "#0F6CBD"
ACCENT_COLOR_HOVER = "#0D5F9D"
ACCENT_COLOR_PRESSED = "#0A4978"
ACCENT_SOFT_BG = "#EAF2FB"
ACCENT_SOFT_BORDER = "#C8DCF4"
ACCENT_TINT = "#E3EEF9"
DANGER_COLOR = "#B42318"
DANGER_COLOR_HOVER = "#912018"
DANGER_SOFT_BG = "#FEEDEB"
DANGER_SOFT_BORDER = "#F6C8C3"
SUCCESS_COLOR = "#1A7F37"
SUCCESS_SOFT_BG = "#EAF6EE"
SUCCESS_SOFT_BORDER = "#BFE5CB"
WARNING_COLOR = "#8A5A00"
WARNING_SOFT_BG = "#FFF5D6"
WARNING_SOFT_BORDER = "#E7D184"

PAGE_BG = "#F3F5F8"
CONTENT_BG = "#F6F8FB"
SURFACE_BG = "#FFFFFF"
SURFACE_ALT_BG = "#FCFDFE"
LOG_PANEL_BG = "#F4F7FA"
LOG_BG = "#EEF2F6"
LANDING_CARD_BG = "#FBFCFE"
LANDING_CARD_BORDER = "#D9E3EE"
LANDING_CARD_ACCENT_BG = "#F5F9FD"
LANDING_BADGE_BG = "#E7F0FA"
LANDING_BADGE_BORDER = "#C7D9EE"

BORDER_COLOR = "#D7DEE8"
BORDER_SOFT_COLOR = "#E4EAF2"
TEXT_PRIMARY = "#1F2328"
TEXT_SECONDARY = "#576171"
TEXT_MUTED = "#7A8391"

HEADER_BG = "#232A33"
INFO_BG = "#F1F6FC"
INFO_BORDER = "#D5E2F0"
INFO_ICON_BG = "#DDE7F1"
INFO_ICON_BORDER = "#BCCCDC"
INFO_ICON_FG = "#30465D"

SIDEBAR_BG = "#1F242B"
SIDEBAR_BORDER = "#2C333D"
SIDEBAR_ITEM_HOVER = "#29323A"
SIDEBAR_ITEM_ACTIVE = "#26323D"

PAGE_MARGIN = 22
SECTION_PADDING = 15
SECTION_HEADER_CONTENT_GAP = 8
SECTION_GAP = 12
SECTION_GRID_GAP = 8
COMPACT_SECTION_MAX_HEIGHT = 170
CORNER_RADIUS = 9

SIDEBAR_WIDTH = 216
BROWSE_BUTTON_WIDTH = 156
EVENT_ID_COLUMN_WIDTH = 88
EVENT_REMOVE_BUTTON_SIZE = 24


def build_main_page_stylesheet() -> str:
    """Return the scoped stylesheet for the polished main page."""
    return f"""
        #Page1 {{
            background: {PAGE_BG};
        }}

        #MainContent {{
            background: {CONTENT_BG};
        }}

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

        QWidget[cardHeader="true"] {{
            background: transparent;
        }}

        QLabel[cardTitle="true"] {{
            color: {TEXT_PRIMARY};
            font-weight: 600;
            padding: 0;
        }}

        QRadioButton {{
            color: {TEXT_PRIMARY};
            spacing: 8px;
        }}

        QLineEdit,
        QTextEdit,
        QProgressBar {{
            border: 1px solid {BORDER_COLOR};
            border-radius: 8px;
            padding: 6px 10px;
            background: {SURFACE_BG};
            color: {TEXT_PRIMARY};
        }}

        QLineEdit:focus,
        QTextEdit:focus {{
            border-color: {ACCENT_COLOR};
        }}

        QLineEdit:disabled,
        QTextEdit:disabled {{
            background: #F1F3F6;
            color: {TEXT_MUTED};
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

        #preprocessing_info_strip {{
            background: {INFO_BG};
            border: 1px solid {INFO_BORDER};
            border-radius: 8px;
        }}

        #preprocessing_info_strip QLabel {{
            color: {TEXT_SECONDARY};
        }}

        #preprocessing_info_icon {{
            min-width: 20px;
            max-width: 20px;
            min-height: 20px;
            max-height: 20px;
            border-radius: 10px;
            border: 1px solid {INFO_ICON_BORDER};
            background: {INFO_ICON_BG};
            color: {INFO_ICON_FG};
            font-weight: 700;
        }}

        #processing_group QLineEdit:read-only {{
            background: {SURFACE_ALT_BG};
        }}

        #event_map_header {{
            border-bottom: 1px solid {BORDER_SOFT_COLOR};
        }}

        #event_map_header QLabel {{
            color: {TEXT_SECONDARY};
            font-weight: 600;
            padding: 0 0 3px 0;
        }}

        #event_map_list {{
            background: transparent;
        }}

        #event_map_scroll {{
            border-top: 1px solid transparent;
        }}

        #event_map_row {{
            background: {SURFACE_ALT_BG};
            border: 1px solid {BORDER_SOFT_COLOR};
            border-radius: 7px;
        }}

        QLineEdit[event_map_role="id"] {{
            padding-left: 0;
            padding-right: 0;
        }}

        QToolButton#event_map_remove_button {{
            border: none;
            background: transparent;
            color: {TEXT_SECONDARY};
            padding: 0;
        }}

        QToolButton#event_map_remove_button:hover {{
            background: #F4E7E7;
            color: #974242;
        }}

        QToolButton#event_map_remove_button:pressed {{
            background: #EAD8D8;
        }}

        QGroupBox[diagnosticsCard="true"] {{
            background: {LOG_PANEL_BG};
            border-color: {BORDER_SOFT_COLOR};
        }}

        #log_surface {{
            background: {LOG_BG};
            border-color: transparent;
        }}

        #main_page_splitter::handle:vertical {{
            height: 8px;
            margin: 3px 0;
            background: transparent;
        }}

        #main_page_splitter::handle:vertical:hover {{
            background: {BORDER_SOFT_COLOR};
            border-radius: 3px;
        }}
    """


def build_sidebar_stylesheet() -> str:
    """Return the scoped stylesheet for the left navigation."""
    return f"""
        #sidebar {{
            background-color: {SIDEBAR_BG};
            border-right: 1px solid {SIDEBAR_BORDER};
        }}

        #SidebarSectionLabel {{
            color: rgba(255, 255, 255, 0.62);
            padding-left: 14px;
            padding-top: 4px;
            padding-bottom: 4px;
            font-size: 11px;
            font-weight: 600;
        }}

        #sidebar_primary_group,
        #sidebar_tools_group,
        #sidebar_lower_region,
        #sidebar_utilities_group {{
            background: transparent;
        }}

        #SidebarButton {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: {CORNER_RADIUS}px;
        }}

        #SidebarButton:hover {{
            background-color: {SIDEBAR_ITEM_HOVER};
            border-color: transparent;
        }}

        #SidebarButton[selected="true"] {{
            background-color: {SIDEBAR_ITEM_ACTIVE};
            border-color: transparent;
        }}

        #SidebarButton:focus {{
            border-color: rgba(255, 255, 255, 0.12);
        }}

        #SidebarButton QLabel {{
            color: rgba(255, 255, 255, 0.88);
        }}

        #SidebarButton[selected="true"] QLabel {{
            color: white;
        }}

        #SidebarSelectionBar {{
            background-color: {ACCENT_COLOR};
            border-radius: 2px;
        }}

        #sidebar_home_divider,
        #sidebar_divider {{
            background: rgba(255, 255, 255, 0.12);
        }}
    """


def build_header_bar_stylesheet() -> str:
    """Return the scoped stylesheet for the project header strip."""
    return f"""
        #HeaderBar {{
            background-color: {HEADER_BG};
            border-bottom: 1px solid {ACCENT_COLOR};
        }}

        #HeaderBar QLabel {{
            color: white;
        }}
    """


def build_landing_page_stylesheet() -> str:
    """Return the scoped stylesheet for the welcome page."""
    return f"""
        #LandingPage {{
            background: {PAGE_BG};
        }}

        #landing_content {{
            background: transparent;
        }}

        #landing_welcome_card {{
            background: {LANDING_CARD_BG};
            border: 1px solid {LANDING_CARD_BORDER};
            border-radius: 14px;
        }}

        #landing_badge {{
            color: {TEXT_SECONDARY};
        }}

        #landing_title {{
            color: {TEXT_PRIMARY};
        }}

        #landing_subtitle {{
            color: {TEXT_SECONDARY};
        }}

        QPushButton[landingAction="true"] {{
            background: {SURFACE_BG};
            border: 1px solid {BORDER_COLOR};
            border-radius: 8px;
            color: {TEXT_PRIMARY};
            font-weight: 600;
        }}

        QPushButton[landingAction="true"]:hover {{
            background: {ACCENT_SOFT_BG};
            border-color: {ACCENT_SOFT_BORDER};
        }}

        QPushButton[landingAction="true"]:pressed {{
            background: #DDEAF7;
        }}

        QPushButton[landingAction="true"]:focus {{
            border-color: {ACCENT_SOFT_BORDER};
        }}

        QPushButton[landingAction="true"][variant="primary"] {{
            background: {ACCENT_COLOR};
            border-color: {ACCENT_COLOR};
            color: white;
        }}

        QPushButton[landingAction="true"][variant="primary"]:hover {{
            background: {ACCENT_COLOR_HOVER};
            border-color: {ACCENT_COLOR_HOVER};
        }}

        QPushButton[landingAction="true"][variant="primary"]:pressed {{
            background: {ACCENT_COLOR_PRESSED};
            border-color: {ACCENT_COLOR_PRESSED};
        }}

        QPushButton[landingAction="true"][variant="secondary"] {{
            background: {SURFACE_BG};
            border-color: {BORDER_COLOR};
            color: {TEXT_PRIMARY};
        }}
    """
