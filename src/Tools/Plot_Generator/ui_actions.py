"""Workflow footer assembly for the SNR Plots page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressBar

from Main_App.gui.components import ActionRow, StatusBanner, make_action_button


def build_generation_action_row(owner, root_layout) -> None:
    """Create inline status, progress, and generation controls."""

    owner.workflow_status = StatusBanner(
        "Choose the processed Excel folder, plot output folder, and a condition.",
        owner,
        variant="info",
    )
    owner.workflow_status.setObjectName("snr_plot_workflow_status")
    owner.workflow_status.setAccessibleName("SNR plot generation status")
    root_layout.addWidget(owner.workflow_status)

    owner.progress_bar = QProgressBar(owner)
    owner.progress_bar.setObjectName("snr_plot_progress")
    owner.progress_bar.setRange(0, 100)
    owner.progress_bar.setValue(0)
    owner.progress_bar.setTextVisible(True)
    owner.progress_bar.setFixedHeight(18)
    owner.progress_bar.setAccessibleName("SNR plot generation progress")
    root_layout.addWidget(owner.progress_bar)

    owner.save_defaults_btn = make_action_button("Save Folder Defaults")
    owner.save_defaults_btn.setObjectName("snr_save_folder_defaults")
    owner.save_defaults_btn.setToolTip("Save the current input and output folders")
    owner.save_defaults_btn.clicked.connect(owner._save_defaults)
    owner.load_defaults_btn = make_action_button("Restore Plot Defaults")
    owner.load_defaults_btn.setObjectName("snr_restore_plot_defaults")
    owner.load_defaults_btn.setToolTip("Restore the saved plot settings")
    owner.load_defaults_btn.clicked.connect(owner._load_defaults)
    owner.open_output_btn = make_action_button("Open Plot Folder")
    owner.open_output_btn.setObjectName("snr_open_plot_folder")
    owner.open_output_btn.setToolTip("Open the selected plot output folder")
    owner.open_output_btn.clicked.connect(owner._open_output_folder)
    owner.gen_btn = make_action_button("Generate SNR Plots", variant="primary")
    owner.gen_btn.setObjectName("snr_generate_plots")
    owner.gen_btn.setToolTip("Generate matching PNG and PDF SNR plots")
    owner.gen_btn.clicked.connect(owner._generate)
    owner.gen_btn.setEnabled(False)
    owner.cancel_btn = make_action_button("Cancel", variant="danger")
    owner.cancel_btn.setObjectName("snr_cancel_generation")
    owner.cancel_btn.setToolTip("Stop SNR plot generation after the current operation")
    owner.cancel_btn.setEnabled(False)
    owner.cancel_btn.clicked.connect(owner._cancel_generation)
    owner.gen_btn.setDefault(True)
    owner.gen_btn.setAutoDefault(True)
    owner.gen_btn.setMinimumWidth(110)

    actions_widget = ActionRow(owner, alignment=Qt.AlignLeft, spacing=12)
    actions_widget.setObjectName("plot_generator_bottom_actions")
    actions_widget.row_layout.setContentsMargins(8, 8, 8, 8)
    actions_widget.add_button(owner.save_defaults_btn)
    actions_widget.add_button(owner.load_defaults_btn)
    actions_widget.add_button(owner.open_output_btn)
    actions_widget.row_layout.addStretch(1)
    actions_widget.add_button(owner.gen_btn)
    actions_widget.add_button(owner.cancel_btn)

    root_layout.addWidget(actions_widget)
