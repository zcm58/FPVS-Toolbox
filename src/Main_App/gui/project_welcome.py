"""Welcome screen and project creation choices."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from Main_App.gui.components import AppDialog, make_action_button
from Main_App.gui.style_tokens import build_landing_page_stylesheet
from Main_App.gui.theme import set_themed_stylesheet
from Main_App.gui.typography import apply_font_role


def build_project_welcome(host, parent: QWidget) -> QWidget:
    """Build the Welcome surface and expose its project actions to the host."""
    landing = QWidget(parent)
    landing.setObjectName("LandingPage")
    landing.setAttribute(Qt.WA_StyledBackground, True)
    set_themed_stylesheet(landing, build_landing_page_stylesheet())

    layout = QVBoxLayout(landing)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addStretch(1)

    content = QWidget(landing)
    content.setMaximumWidth(480)
    host.landing_content = content
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(0)

    identity = QHBoxLayout()
    identity.setSpacing(12)
    identity.addStretch(1)
    logo = QLabel(content)
    logo.setObjectName("welcomeAppIcon")
    logo.setPixmap(host.windowIcon().pixmap(QSize(44, 44), host.devicePixelRatioF()))
    identity.addWidget(logo)

    title = QLabel("FPVS Toolbox", content)
    title.setObjectName("landing_title")
    apply_font_role(title, "landing_title")
    identity.addWidget(title)
    identity.addStretch(1)
    content_layout.addLayout(identity)
    content_layout.addSpacing(24)

    host.btn_open_project = make_action_button(
        "Open Existing Project…", variant="primary", parent=content,
    )
    host.btn_open_project.setObjectName("welcomeOpenProject")
    host.btn_open_project.setMinimumHeight(56)
    content_layout.addWidget(host.btn_open_project)
    content_layout.addSpacing(12)

    host.btn_create_project = make_action_button(
        "Create New Project…", variant="secondary", parent=content,
    )
    host.btn_create_project.setObjectName("welcomeCreateProject")
    host.btn_create_project.setMinimumHeight(56)
    host.btn_create_project.clicked.connect(lambda: show_project_creation_choices(host))
    content_layout.addWidget(host.btn_create_project)

    centered = QHBoxLayout()
    centered.addStretch(1)
    centered.addWidget(content, 10)
    centered.addStretch(1)
    layout.addLayout(centered)
    layout.addStretch(1)
    return landing


def show_project_creation_choices(host) -> None:
    """Choose a creation route before opening its existing project workflow."""
    dialog = AppDialog("Create New Project", host)
    dialog.setObjectName("projectCreationChoices")
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)

    def choose(action: QAction) -> None:
        dialog.accept()
        action.trigger()

    import_studio = make_action_button("Import FPVS Studio Config…", parent=dialog)
    import_studio.setObjectName("welcomeImportStudio")
    import_studio.clicked.connect(lambda: choose(host.actionImportFpvsConfigProject))

    import_help = QLabel(
        "Uses the protocol and triggers saved in a .fpvsconfig file.", dialog,
    )
    import_help.setWordWrap(True)
    import_studio.setAccessibleDescription(import_help.text())

    import_layout = QVBoxLayout()
    import_layout.setSpacing(6)
    import_layout.addWidget(import_studio)
    import_layout.addWidget(import_help)
    dialog.root_layout.addLayout(import_layout)

    create_manually = make_action_button("Create Project Manually…", parent=dialog)
    create_manually.setObjectName("welcomeCreateManually")
    create_manually.clicked.connect(lambda: choose(host.actionCreateNewProject))
    import_studio.setMinimumHeight(38)
    create_manually.setMinimumHeight(38)
    dialog.root_layout.addWidget(create_manually)

    footer = QDialogButtonBox(QDialogButtonBox.Cancel, dialog)
    footer.rejected.connect(dialog.reject)
    dialog.root_layout.addWidget(footer)
    dialog.resize(388, dialog.sizeHint().height())
    dialog.open()
