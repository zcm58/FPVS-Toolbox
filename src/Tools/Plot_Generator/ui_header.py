"""Compact page header for the embedded SNR Plots tool."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from Main_App.gui.components import apply_font_role, make_info_button, show_tool_info
from Tools.Plot_Generator.tool_info import SNR_PLOTS_TOOL_INFO


def build_snr_tool_header(owner, root_layout) -> None:
    """Add the compact tool title and shared About action."""

    header = QWidget(owner)
    header.setObjectName("snr_plots_header")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(12, 2, 12, 2)
    header_layout.setSpacing(8)

    title = QLabel("SNR Plots", header)
    title.setObjectName("snr_plots_title")
    title.setProperty("toolTitle", True)
    apply_font_role(title, "tool_title")
    header_layout.addWidget(title, 1)

    owner.snr_plots_info_btn = make_info_button(
        parent=header,
        tooltip="About SNR Plots",
        object_name="snr_plots_tool_info_btn",
        size=22,
    )
    owner.snr_plots_info_btn.clicked.connect(
        lambda: show_tool_info(owner, SNR_PLOTS_TOOL_INFO)
    )
    header_layout.addWidget(owner.snr_plots_info_btn, 0, Qt.AlignVCenter)
    root_layout.addWidget(header)


__all__ = ["build_snr_tool_header"]
