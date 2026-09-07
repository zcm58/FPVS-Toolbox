"""Open project exclusion management and synchronize its saved settings."""

from __future__ import annotations

import logging
from pathlib import Path

from Main_App.gui.components import show_info
from Main_App.gui.dataset_exclusions_dialog import DatasetExclusionsDialog
from Main_App.gui.shell_status import _set_processing_navigation_locked
from Main_App.gui.toolbox_cache_workflow import _cache_work_is_active
from Tools.Stats.analysis.dv_policy_group_significant import clear_group_significant_selection_cache

logger = logging.getLogger(__name__)


def _sync_saved_exclusions(settings, snapshot) -> None:
    """Adopt only saved exclusion fields, keeping other pending Settings edits."""

    project = settings.project
    if project is None or Path(project.project_root).resolve() != Path(
        snapshot.project_root
    ).resolve():
        logger.warning("dataset_exclusions_saved_for_different_project")
        return
    values = {
        "manual_excluded_participants": list(snapshot.processing_excluded_participants),
        "manual_excluded_recordings": list(snapshot.processing_excluded_recordings),
    }
    project.preprocessing = {**project.preprocessing, **values}
    manifest = getattr(project, "manifest", None)
    if isinstance(manifest, dict):
        preprocessing = manifest.setdefault("preprocessing", {})
        preprocessing.update(values)
        tools = manifest.get("tools")
        stats = tools.get("stats") if isinstance(tools, dict) else None
        if snapshot.downstream_outputs_stale and isinstance(stats, dict):
            stats.pop("group_significant_harmonics_cache", None)
    settings._manual_excluded_participants = list(values["manual_excluded_participants"])
    settings._manual_excluded_recordings = list(values["manual_excluded_recordings"])
    settings._project_cache = {**getattr(settings, "_project_cache", {}), **values}

    if snapshot.downstream_outputs_stale:
        clear_group_significant_selection_cache()

    owner = getattr(settings, "host", None) or settings.parent()
    if (
        snapshot.downstream_outputs_stale
        and owner is not None
        and getattr(owner, "currentProject", project) is project
    ):
        from Main_App.gui.processing_workflows import _set_resume_post_processing_pending

        _set_resume_post_processing_pending(owner, True)


def show_dataset_exclusions(settings) -> None:
    """Hold the processing/navigation guard throughout the modal worker lifetime."""

    if settings.project is None:
        show_info(settings, "Dataset Exclusions", "Open a project to manage its exclusions.")
        return
    owner = getattr(settings, "host", None) or settings.parent()
    if owner is None or _cache_work_is_active(owner):
        show_info(
            settings, "Work In Progress",
            "Wait for processing and tool work to finish before changing dataset exclusions.",
        )
        return
    guard = getattr(owner, "_start_guard", None)
    if guard is None or not guard.start():
        show_info(
            settings, "Dataset Exclusions Unavailable",
            "Open Settings from the main window while processing is idle.",
        )
        return
    dialog = None
    try:
        _set_processing_navigation_locked(owner, True)
        dialog = DatasetExclusionsDialog(settings.project.project_root, settings)
        dialog.exclusions_changed.connect(lambda snapshot: _sync_saved_exclusions(settings, snapshot))
        dialog.exec()
    finally:
        _set_processing_navigation_locked(owner, False)
        guard.end()
        if dialog is not None:
            dialog.deleteLater()
