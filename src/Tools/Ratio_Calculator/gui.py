from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from Main_App.gui.components import SurfaceSize, configure_window_surface

from .gui_condition_selection import RatioConditionSelectionMixin
from .gui_participants import RatioParticipantsMixin
from .gui_rois import RatioRoisMixin
from .gui_run_workflow import RatioRunWorkflowMixin
from .gui_sections import RatioSectionsMixin
from .gui_settings import RatioSettingsMixin
from .roi_provider import load_ratio_rois

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtCore import QThread

    from .worker import RatioCalculatorWorker


class RatioCalculatorWindow(
    RatioRunWorkflowMixin,
    RatioConditionSelectionMixin,
    RatioSectionsMixin,
    RatioRoisMixin,
    RatioParticipantsMixin,
    RatioSettingsMixin,
    QWidget,
):
    def __init__(
        self,
        parent: QWidget | None = None,
        project_root: str | None = None,
        roi_loader: Callable[[], dict[str, list[str]]] | None = None,
    ) -> None:
        super().__init__(parent)
        configure_window_surface(
            self,
            title="Ratio Calculator",
            size=SurfaceSize(width=980, height=760),
        )

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Optional[Path] = None
        self._paired_participants: list[str] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[RatioCalculatorWorker] = None
        self._output_dir: Optional[Path] = None
        self._condition_paths: dict[str, Path] = {}
        self._label_a_dirty = False
        self._label_b_dirty = False
        self._run_label_dirty = False
        self._loading_participants = False
        self._roi_loader = roi_loader or load_ratio_rois
        self._active_roi_defs: dict[str, list[str]] = {}
        self._roi_settings_signature: tuple[tuple[str, tuple[str, ...]], ...] = ()
        self._roi_watch_timer = QTimer(self)
        self._roi_watch_timer.setInterval(1500)
        self._roi_watch_timer.timeout.connect(self._sync_rois_if_changed)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        self.tabs = QTabWidget()
        self.basic_tab = QWidget()
        self.advanced_tab = QWidget()
        self.tabs.addTab(self.basic_tab, "Basic")
        self.tabs.addTab(self.advanced_tab, "Advanced")

        self._build_basic_tab()
        self._build_advanced_tab()

        main_layout.addWidget(self.tabs)
        main_layout.addWidget(self._build_bottom_panel())

        self._apply_button_styling()
        self._apply_button_tooltips()
        self._apply_button_icons()

        self._refresh_conditions()
        self._refresh_rois()
        self._roi_watch_timer.start()
        self._set_default_output()
        self._update_run_state()
