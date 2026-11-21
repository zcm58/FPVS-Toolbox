"""File menu setup extracted from main_window.py."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from Main_App.gui.project_workflows import import_fpvs_config_project


def init_file_menu(self) -> None:
    """Configure the File menu with project actions."""
    menu_bar = self.menuBar()
    if not menu_bar:
        return

    file_menu = menu_bar.findChild(QMenu, "fileMenu")
    if file_menu is None:
        return

    file_menu.clear()

    action_import = QAction("Import FPVS Studio Config…", self)
    action_import.setObjectName("actionImportFpvsConfigProject")
    action_import.triggered.connect(lambda: import_fpvs_config_project(self))
    self.actionImportFpvsConfigProject = action_import
    file_menu.addAction(action_import)
    from Main_App.gui.studio_cohort_review import reopen_study_review
    review = QAction("Review Studio Cohort…", self)
    review.triggered.connect(lambda: reopen_study_review(self))
    file_menu.addAction(review)
    from Main_App.gui.reporting_dialog import open_results_sharing
    share = QAction("Share study results…", self)
    share.triggered.connect(lambda: open_results_sharing(self))
    file_menu.addAction(share)
    file_menu.aboutToShow.connect(lambda: share.setVisible(bool(
        getattr(getattr(self, "currentProject", None), "manifest", {})
        .get("tools", {}).get("studio_cohort", {}).get("website_study")
    )))
    file_menu.aboutToShow.connect(lambda: review.setVisible(
        bool(getattr(getattr(self, "currentProject", None), "manifest", {}).get("tools", {}).get("studio_cohort"))
    ))

    action_open = QAction("Open Existing Project…", self)
    action_open.triggered.connect(self.open_existing_project)
    self.actionOpenExistingProject = action_open
    file_menu.addAction(action_open)

    action_new = QAction("Create Project Manually…", self)
    action_new.triggered.connect(self.new_project)
    self.actionCreateNewProject = action_new
    file_menu.addAction(action_new)

    action_save = QAction("Save Project Settings", self)
    action_save.triggered.connect(self.saveProjectSettings)
    file_menu.addAction(action_save)

    file_menu.addSeparator()

    file_menu.addAction(self.shell_actions.settings)

    action_reset_cache = QAction("Reset Project Processing Cache...", self)
    action_reset_cache.setObjectName("actionResetProjectProcessingCache")
    action_reset_cache.setStatusTip(
        "Remove only FPVS-managed cache state so the next processing run starts cold"
    )
    action_reset_cache.triggered.connect(self.reset_project_processing_cache)
    self.actionResetProjectProcessingCache = action_reset_cache
    file_menu.addAction(action_reset_cache)

    file_menu.addSeparator()

    action_check = QAction("Check for Updates", self)
    action_check.triggered.connect(self.check_for_updates)
    file_menu.addAction(action_check)

    file_menu.addAction(self.shell_actions.about)

    file_menu.addSeparator()

    self.exit_action = QAction("Exit", self)
    self.exit_action.triggered.connect(self.quit)
    file_menu.addAction(self.exit_action)
