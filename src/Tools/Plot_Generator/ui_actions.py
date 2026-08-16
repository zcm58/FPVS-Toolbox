"""Bottom action-row assembly for the Plot Generator page."""
from __future__ import annotations

from PySide6.QtCore import Qt

from Main_App.gui.components import ActionRow, make_action_button


def build_generation_action_row(owner, root_layout) -> None:
    """Create generation controls and add them to ``root_layout``."""

    owner.save_defaults_btn = make_action_button("Save Defaults")
    owner.save_defaults_btn.setToolTip("Save current folders as defaults")
    owner.save_defaults_btn.clicked.connect(owner._save_defaults)
    owner.load_defaults_btn = make_action_button("Reset to Default settings")
    owner.load_defaults_btn.setToolTip("Reset all values to defaults")
    owner.load_defaults_btn.clicked.connect(owner._load_defaults)
    owner.gen_btn = make_action_button("Generate", variant="primary")
    owner.gen_btn.setToolTip("Start plot generation")
    owner.gen_btn.clicked.connect(owner._generate)
    owner.gen_btn.setEnabled(False)
    owner.cancel_btn = make_action_button("Cancel", variant="danger")
    owner.cancel_btn.setToolTip("Cancel generation")
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
    actions_widget.row_layout.addSpacing(8)
    actions_widget.row_layout.addWidget(owner.progress_bar, 1)
    actions_widget.row_layout.addSpacing(12)
    actions_widget.add_button(owner.gen_btn)
    actions_widget.add_button(owner.cancel_btn)

    root_layout.addWidget(actions_widget, alignment=Qt.AlignHCenter)
