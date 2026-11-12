"""Shared commands for the main window's navigation controls."""
from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices


_DOCUMENTATION_URL = "https://zcm58.github.io/FPVS-Toolbox/"

_DEFAULT_TOOL_SPECS = (
    ("btn_free_harmonic_clustering", "Free Harmonic Clustering Analysis", "open_free_harmonic_clustering"),
    ("btn_graphs", "SNR Plots", "open_plot_generator"),
)

BETA_TOOL_SPECS = (
    ("btn_publication_maps", "Scalp Maps", "open_publication_maps"),
    ("btn_data", "Standard FPVS Screening", "open_stats_analyzer"),
    ("btn_sensitivity_analysis", "Sensitivity Analysis", "open_sensitivity_analysis"),
    ("btn_loreta_visualizer", "LORETA Visualizer", "open_loreta_visualizer"),
    ("btn_sequence_figure", "Sequence Figure", "open_sequence_figure"),
    ("btn_individual_detectability", "Individual Detectability", "open_individual_detectability"),
)


class ShellActions(QActionGroup):
    """One action per command, with a group lock for background work."""

    def __init__(self, host) -> None:
        super().__init__(host)
        self.setExclusive(False)
        self.home = self._add("btn_home", "Home", host.show_home_page)
        self.settings = self._add("btn_settings", "Settings", host.open_settings_window)
        self.about = self._add("btn_help", "About…", host.show_about_dialog)
        self.documentation = self._add("btn_info", "Information", self._open_documentation)
        self.default_tools = tuple(
            self._add(role, title, getattr(host, opener))
            for role, title, opener in _DEFAULT_TOOL_SPECS
        )
        self.beta_tools: tuple[QAction, ...] = ()
        if host.settings.beta_tools_enabled():
            self.beta_tools = tuple(
                self._add(role, title, partial(host._open_beta_tool, role, getattr(host, opener)))
                for role, title, opener in BETA_TOOL_SPECS
            )

    def _add(self, role: str, title: str, callback: Callable[[], None]) -> QAction:
        action = self.addAction(title)
        action.setObjectName(role)
        action.triggered.connect(callback)
        return action

    @staticmethod
    def _open_documentation() -> None:
        QDesktopServices.openUrl(QUrl(_DOCUMENTATION_URL))
