"""Source localization tools using (s/e)LORETA."""

from .eloreta_gui import SourceLocalizationWindow
from .runner import run_source_localization
from .worker import run_localization_worker
from .stc_utils import (
    average_stc_files,
    average_stc_directory,
    average_conditions_dir,
    average_conditions_to_fsaverage,
    morph_to_fsaverage,
)
from .visualization import view_source_estimate
from .pyqt_viewer import STCViewer

__all__ = [
    "SourceLocalizationWindow",
    "run_source_localization",
    "view_source_estimate",
    "average_stc_files",
    "average_stc_directory",
    "average_conditions_dir",
    "average_conditions_to_fsaverage",
    "run_localization_worker",
    "morph_to_fsaverage",
    "STCViewer",
]
