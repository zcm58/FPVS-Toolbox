"""Compact page header for the embedded SNR Plots tool."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from Main_App.gui.components import apply_font_role, make_info_button, show_tool_info
from Tools.Plot_Generator.tool_info import SNR_PLOTS_TOOL_INFO


def build_snr_tool_header(owner, root_layout) -> None:
    """Add the shared-tool-style title, description, and About action."""

    header = QWidget(owner)
    header.setObjectName("snr_plots_header")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(12, 4, 12, 2)
    header_layout.setSpacing(8)

    heading = QWidget(header)
    heading_layout = QVBoxLayout(heading)
    heading_layout.setContentsMargins(0, 0, 0, 0)
    heading_layout.setSpacing(2)

    eyebrow = QLabel("PUBLICATION FIGURE TOOL", heading)
    eyebrow.setObjectName("snr_plots_eyebrow")
    eyebrow.setProperty("eyebrow", True)
    heading_layout.addWidget(eyebrow)

    title = QLabel("SNR Plots", heading)
    title.setObjectName("snr_plots_title")
    title.setProperty("toolTitle", True)
    apply_font_role(title, "tool_title")
    heading_layout.addWidget(title)

    subtitle = QLabel(
        "Generate publication-ready ROI spectra from processed FullSNR workbooks.",
        heading,
    )
    subtitle.setObjectName("snr_plots_subtitle")
    subtitle.setWordWrap(True)
    heading_layout.addWidget(subtitle)
    header_layout.addWidget(heading, 1)

    owner.snr_plots_info_btn = make_info_button(
        parent=header,
        tooltip="About SNR Plots",
        object_name="snr_plots_tool_info_btn",
        size=22,
    )
    owner.snr_plots_info_btn.clicked.connect(
        lambda: show_tool_info(owner, SNR_PLOTS_TOOL_INFO)
    )
    header_layout.addWidget(owner.snr_plots_info_btn, 0, Qt.AlignTop)
    root_layout.addWidget(header)


__all__ = ["build_snr_tool_header"]
