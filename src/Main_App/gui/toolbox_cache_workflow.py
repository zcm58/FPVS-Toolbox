"""Settings-owned cache confirmation with background inventory and removal."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, QThreadPool, Qt, Slot
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QToolButton

from Main_App.gui.components import (
    ActionRow, AppDialog, StatusBanner, SurfaceSize, make_action_button, show_info,
)
from Main_App.gui.project_workflows import (
    _format_cache_size,
    _processing_cache_reset_is_busy,
    _set_processing_cache_reset_ui_locked,
)
from Main_App.workers.toolbox_cache_worker import ToolboxCacheWorker

logger = logging.getLogger(__name__)


def _cache_work_is_active(owner, *, include_start_guard: bool = True) -> bool:
    if include_start_guard and _processing_cache_reset_is_busy(owner):
        return True
    if bool(getattr(owner, "_run_active", False)):
        return True
    if QThreadPool.globalInstance().activeThreadCount():
        return True
    try:
        attributes = vars(owner)
        objects = [owner, *attributes.values(), *owner.findChildren(QThread)]
        for name, value in attributes.items():
            if name.endswith("_page") and value is not None:
                objects.append(value)
                objects.extend(vars(value).values())
                objects.extend(value.findChildren(QThread))
    except (AttributeError, RuntimeError, TypeError):
        return True
    for obj in objects:
        for method in ("isRunning", "activeThreadCount", "has_active_generation"):
            check = getattr(obj, method, None)
            if callable(check):
                try:
                    if check():
                        return True
                except RuntimeError:
                    # Uncertain worker ownership must not allow deletion.
                    return True
    return False


def _refresh_active_manifest_cache(project, cleared_project_roots) -> None:
    """Remove only the deleted cache entry, preserving unsaved project settings."""
    if project is None or Path(project.project_root).resolve() not in {
        Path(root).resolve() for root in cleared_project_roots
    }:
        return
    manifest = getattr(project, "manifest", None)
    tools = manifest.get("tools") if isinstance(manifest, dict) else None
    stats = tools.get("stats") if isinstance(tools, dict) else None
    if isinstance(stats, dict):
        stats.pop("group_significant_harmonics_cache", None)


class ToolboxCacheDialog(AppDialog):
    def __init__(self, owner, *, project, projects_root: Path | None) -> None:
        super().__init__(
            "Clear Toolbox Cache", owner,
            size=SurfaceSize(620, 370, min_width=520, min_height=300),
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.owner = owner
        self.project = project
        self.projects_root = projects_root
        self.inventory = None
        self.thread = None
        self.worker = None
        self._result = None
        self._error = ""
        self._clearing = False
        self.status = StatusBanner("Checking disposable caches…", self)
        self.root_layout.addWidget(self.status)
        note = QLabel(
            "Includes the current project, projects in your configured folder, "
            "and app caches. Recordings, results, settings, saved exclusions, and "
            "anatomical templates are kept. The next calculations may take longer.", self,
        )
        note.setWordWrap(True)
        self.root_layout.addWidget(note)
        self.details_toggle = QToolButton(self)
        self.details_toggle.setText("Show cache locations")
        self.details_toggle.setCheckable(True)
        self.root_layout.addWidget(self.details_toggle)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Cache locations and operation details")
        self.details.setMinimumHeight(100)
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        self.root_layout.addWidget(self.details, 1)
        actions = ActionRow(self)
        self.clear_button = make_action_button("Clear Cache", variant="primary", parent=actions)
        self.clear_button.setEnabled(False)
        self.close_button = make_action_button("Cancel", parent=actions)
        self.clear_button.clicked.connect(self._clear)
        self.close_button.clicked.connect(self.reject)
        actions.add_button(self.clear_button)
        actions.add_button(self.close_button)
        self.root_layout.addWidget(actions)

    def begin(self) -> None:
        self._start_worker()

    def _start_worker(self) -> None:
        self._result = None
        self._error = ""
        self.clear_button.setEnabled(False)
        thread = QThread(self)
        worker = ToolboxCacheWorker(
            active_project_root=(Path(self.project.project_root) if self.project is not None else None),
            projects_root=self.projects_root,
            inventory=self.inventory if self._clearing else None,
        )
        worker.moveToThread(thread)
        self.thread, self.worker = thread, worker
        # Reuse the existing main-window shutdown guard during both operations.
        self.owner._project_processing_cache_thread = thread
        thread.started.connect(worker.run)
        worker.finished.connect(self._receive_result)
        worker.failed.connect(self._receive_error)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self._release_worker)
        thread.finished.connect(thread.deleteLater)
        try:
            thread.start()
        except Exception as exc:  # noqa: BLE001 - release GUI ownership on startup failure
            logger.exception("toolbox_cache_thread_start_failed")
            self._error = str(exc)
            worker.deleteLater()
            self._release_worker()
            thread.deleteLater()

    @Slot(object)
    def _receive_result(self, result) -> None:
        self._result = result

    @Slot(str)
    def _receive_error(self, message: str) -> None:
        self._error = message

    @Slot()
    def _release_worker(self) -> None:
        cancelled = self.worker is not None and self.worker.cancel_requested.is_set()
        if getattr(self.owner, "_project_processing_cache_thread", None) is self.thread:
            self.owner._project_processing_cache_thread = None
        self.thread = self.worker = None
        self.close_button.setEnabled(True)
        self.close_button.setText("Close" if self._clearing or self._error else "Cancel")
        if cancelled and not self._clearing:
            super().reject()
            return
        if self._error:
            self.status.set_text("Cache operation could not finish. See details below.")
            self.status.set_variant("warning")
            self.details.setPlainText(self._error)
            self.details_toggle.setChecked(True)
            return
        if not self._clearing:
            self.inventory = self._result
            count = self.inventory.file_count
            entries = self.inventory.manifest_cache_entries
            self.status.set_text(
                f"Clear {count:,} cache files ({_format_cache_size(self.inventory.total_bytes)})"
                + (f" and {entries:,} saved cache entries?" if entries else "?")
                if count or entries else "No disposable disk caches were found."
            )
            locations = [f"Project: {root}" for root in self.inventory.project_roots]
            locations.extend(
                f"{target.label}: {target.path}\n"
                f"  {target.file_count:,} files · {_format_cache_size(target.total_bytes)}"
                for target in self.inventory.targets
            )
            locations.extend(self.inventory.warnings)
            self.details.setPlainText("\n".join(locations))
            if self.inventory.warnings:
                self.status.set_text(self.status.text() + " Some cache locations need attention; see details.")
                self.status.set_variant("warning")
                self.details_toggle.setChecked(True)
            self.clear_button.setEnabled(bool(count or entries))
            return
        result = self._result
        _refresh_active_manifest_cache(self.project, result.cleared_project_roots)
        issue_count = len(result.errors)
        self.status.set_text(
            f"{'Stopped. ' if result.cancelled else ''}Cleared {result.removed_files:,} files "
            f"({_format_cache_size(result.removed_bytes)})."
            + (f" Cleared saved selection caches in {len(result.cleared_project_roots)} project(s)."
               if result.cleared_project_roots else "")
            + (f" {issue_count} item(s) could not be cleared." if issue_count else "")
        )
        self.status.set_variant("warning" if issue_count or result.cancelled else "success")
        details = [*result.errors, *result.warnings]
        details.append("Open tool results remain available.")
        self.details.setPlainText("\n".join(details))
        if issue_count or result.warnings:
            self.details_toggle.setChecked(True)

    @Slot()
    def _clear(self) -> None:
        if self.thread is not None or self.inventory is None:
            return
        # The dialog owns the start guard; still recheck actual work immediately
        # before deletion in case a tool started background work meanwhile.
        if _cache_work_is_active(self.owner, include_start_guard=False):
            self.status.set_text("Work started in the background. Close this window and retry when it finishes.")
            self.status.set_variant("warning")
            self.clear_button.setEnabled(False)
            return
        self._clearing = True
        self.status.set_text("Clearing the listed caches…")
        self.close_button.setText("Stop")
        self._start_worker()

    def reject(self) -> None:
        if self.worker is not None:
            self.worker.cancel_requested.set()
            self.close_button.setEnabled(False)
            self.status.set_text("Stopping after the current cache operation…")
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)


def show_toolbox_cache_clear(settings) -> None:
    owner = getattr(settings, "host", None) or settings
    if _cache_work_is_active(owner):
        show_info(settings, "Work In Progress", "Wait for processing and tool work to finish before clearing caches.")
        return
    guard = getattr(owner, "_start_guard", None)
    if guard is None or not guard.start():
        show_info(settings, "Cache Clear Unavailable", "Open Settings from the main window when processing is idle.")
        return
    dialog = None
    try:
        configured = settings.manager.get_project_root()
        dialog = ToolboxCacheDialog(
            owner, project=settings.project,
            projects_root=Path(configured) if configured else None,
        )
        _set_processing_cache_reset_ui_locked(owner, True)
        dialog.begin()
        dialog.exec()
    finally:
        _set_processing_cache_reset_ui_locked(owner, False)
        guard.end()
        if dialog is not None:
            dialog.deleteLater()
