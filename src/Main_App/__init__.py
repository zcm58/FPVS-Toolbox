
"""Top-level package for the FPVS Toolbox main application.

This package exposes the core GUI and processing modules that make up the
FPVS Toolbox application.  Importing ``Main_App`` allows external code to
access utility classes such as :class:`SettingsManager` and tools for checking
application updates.
"""

from . import Legacy_App

from .Legacy_App.settings_manager import SettingsManager
from .Legacy_App.settings_window import SettingsWindow
from .Legacy_App.relevant_publications_window import (
    RelevantPublicationsWindow,
)
from .Legacy_App.menu_bar import AppMenuBar
from .Legacy_App.ui_setup_panels import SetupPanelManager
from .Legacy_App.ui_event_map_manager import EventMapManager
from .Legacy_App.event_map_utils import EventMapMixin
from .Legacy_App.file_selection import FileSelectionMixin
from .Legacy_App.event_detection import EventDetectionMixin
from .Legacy_App.validation_mixins import ValidationMixin
from .Legacy_App.processing_utils import ProcessingMixin
from .Legacy_App.load_utils import load_eeg_file
from .Legacy_App.eeg_preprocessing import perform_preprocessing
from .Legacy_App.app_logic import preprocess_raw
from .Legacy_App.post_process import post_process
from .Legacy_App.debug_utils import install_messagebox_logger
from .PySide6_App.Backend import Project
from .Legacy_App.debug_utils      import configure_logging
from .Legacy_App.settings_manager import get_settings

__all__ = [
    "SettingsManager",
    "SettingsWindow",
    "RelevantPublicationsWindow",
    "AppMenuBar",
    "SetupPanelManager",
    "EventMapManager",
    "EventMapMixin",
    "FileSelectionMixin",
    "EventDetectionMixin",
    "ValidationMixin",
    "ProcessingMixin",
    "load_eeg_file",
    "perform_preprocessing",
    "preprocess_raw",
    "post_process",
    "configure_logging",
    "get_settings",
    "install_messagebox_logger",
    "Project",
    "Legacy_App",
]
