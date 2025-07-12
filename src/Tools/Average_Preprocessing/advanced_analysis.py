"""Aggregate Advanced Analysis components into a single class."""

from .advanced_analysis_base import AdvancedAnalysisWindow as _BaseAdvancedAnalysisWindow
from .advanced_analysis_file_ops import AdvancedAnalysisFileOpsMixin
from .advanced_analysis_group_ops import AdvancedAnalysisGroupOpsMixin
from .advanced_analysis_processing import AdvancedAnalysisProcessingMixin
from .advanced_analysis_post import AdvancedAnalysisPostMixin


class AdvancedAnalysisWindow(
    AdvancedAnalysisFileOpsMixin,
    AdvancedAnalysisGroupOpsMixin,
    AdvancedAnalysisProcessingMixin,
    AdvancedAnalysisPostMixin,
    _BaseAdvancedAnalysisWindow,
):
    """Combined window class composed from refactored mixins."""
    pass
