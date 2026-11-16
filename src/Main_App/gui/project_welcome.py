"""Project entry page for FPVS Studio imports and existing projects."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from Main_App.gui.components import SubsectionHeaderLabel, make_action_button
from Main_App.gui.style_tokens import build_landing_page_stylesheet
from Main_App.gui.typography import apply_font_role


def build_project_welcome(host, parent: QWidget) -> QWidget:
    """Build the Welcome surface and expose its project actions to the host."""
    landing = QWidget(parent)
    landing.setObjectName("LandingPage")
    landing.setAttribute(Qt.WA_StyledBackground, True)
    landing.setStyleSheet(build_landing_page_stylesheet())

    layout = QVBoxLayout(landing)
    layout.setContentsMargins(36, 32, 36, 32)
    layout.addStretch(1)

    content = QWidget(landing)
    content.setMaximumWidth(690)
    content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    host.landing_card = content
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(20)

    title = QLabel("FPVS Toolbox", content)
    title.setObjectName("landing_title")
    apply_font_role(title, "landing_title")
    content_layout.addWidget(title)

    actions = QHBoxLayout()
    actions.setSpacing(24)
    studio = QVBoxLayout()
    studio.setSpacing(12)
    instructions = QLabel(
        "Choose the .fpvsconfig exported by FPVS Studio. "
        "Toolbox will then ask for your EEG recordings.",
        content,
    )
    instructions.setObjectName("landing_subtitle")
    instructions.setWordWrap(True)
    studio.addWidget(instructions)

    host.btn_import_project = make_action_button(
        "Import FPVS Studio Config…", variant="primary", parent=content,
    )
    host.btn_import_project.setObjectName("welcomeImportStudio")
    host.btn_import_project.setMinimumHeight(42)
    studio.addWidget(host.btn_import_project, 0, Qt.AlignLeft)
    studio.addStretch(1)
    actions.addLayout(studio, 3)

    divider = QFrame(content)
    divider.setObjectName("welcome_actions_divider")
    divider.setFixedWidth(1)
    divider.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    divider.setAttribute(Qt.WA_StyledBackground, True)
    actions.addWidget(divider)

    other = QVBoxLayout()
    other.setSpacing(8)
    other.addWidget(SubsectionHeaderLabel("Other project options", content))
    host.btn_open_project = make_action_button(
        "Open Existing Project…", variant="secondary", parent=content,
    )
    host.btn_open_project.setObjectName("welcomeOpenProject")
    host.btn_create_project = make_action_button(
        "Create Manually…", variant="tertiary", parent=content,
    )
    host.btn_create_project.setObjectName("welcomeCreateManually")
    other.addWidget(host.btn_open_project, 0, Qt.AlignLeft)
    other.addWidget(host.btn_create_project, 0, Qt.AlignLeft)
    other.addStretch(1)
    actions.addLayout(other, 2)
    content_layout.addLayout(actions)

    layout.addWidget(content, 0, Qt.AlignHCenter)
    layout.addStretch(1)
    return landing
