"""Project management utilities extracted from main_window.py."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import logging
import os
from pathlib import Path
import re
import sys
from threading import Event
from types import SimpleNamespace

from PySide6.QtCore import QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QProgressDialog,
    QWidget,
)

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.gui.op_guard import OpGuard
from Main_App.projects.fpvs_config_import import (
    CONFIG_SUFFIX,
    FPVSConfigImportError,
    create_project_from_fpvs_config,
)
from Main_App.projects.grouping import (
    GroupConfigurationError,
    make_group_id,
    normalize_project_groups,
    project_group_context,
    validate_group_folder_name,
)
from Main_App.projects.project import Project
from Main_App.projects.recordings import (
    ProjectRecordingContext,
    RecordingConfigurationError,
    normalize_project_recording_sources,
    normalize_project_sessions,
    project_recording_context,
)
from Main_App.projects.recording_preflight import (
    RecordingPreflightCancelled,
    RecordingPreflightReport,
    derive_filename_token_rules,
    preflight_repeated_recording_sources,
)
from Main_App.projects.preprocessing_settings import (
    new_project_preprocessing_settings,
)
from Main_App.projects.project_metadata import ProjectMetadata, read_project_metadata
from Main_App.projects.projects_root import ensure_projects_root

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_open_project_guard = OpGuard()
_open_selected_project_guard = OpGuard()


class _ProjectScanSignals(QObject):
    error = Signal(str)
    finished = Signal(object)
    progress = Signal(int)


class _RepeatedSourcePreflightSignals(QObject):
    cancelled = Signal()
    failed = Signal(str)
    finished = Signal(object)


CANCEL_SCAN_MESSAGE = "Project scan cancelled."
FLAT_PROJECT_STRUCTURE = "Single recording per participant (current)"
REPEATED_SESSION_PROJECT_STRUCTURE = "Repeated sessions / visits"


class RepeatedSessionProjectSetupError(ValueError):
    """Raised when a repeated-session project setup is incomplete or ambiguous."""


def make_session_id(label: object, used_ids: set[str] | None = None) -> str:
    """Return a readable stable session ID with deterministic collision suffixes."""

    text = str(label or "").strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "session"
    used = used_ids if used_ids is not None else set()
    candidate = base
    suffix = 2
    while candidate.casefold() in {item.casefold() for item in used}:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_repeated_session_project_manifest(
    *,
    project_root: str | Path,
    project_name: str,
    groups: Mapping[str, Mapping[str, object]],
    sessions: Mapping[str, Mapping[str, object]],
    source_folders: Mapping[tuple[str, str], str | Path],
    preprocessing: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a complete, validated repeated-session manifest without file I/O.

    ``source_folders`` must contain exactly one folder for every declared
    ``(group_id, session_id)`` cell. Session labels describe the session or
    phase-at-visit, while ``visit_index`` independently records visit order.
    """

    name = str(project_name).strip()
    if not name:
        raise RepeatedSessionProjectSetupError("Project name cannot be empty.")

    root = Path(project_root).resolve(strict=False)
    try:
        normalized_groups, _aliases = normalize_project_groups(root, groups)
        normalized_sessions = normalize_project_sessions(sessions)
    except (GroupConfigurationError, RecordingConfigurationError) as exc:
        raise RepeatedSessionProjectSetupError(str(exc)) from exc

    if not normalized_groups:
        raise RepeatedSessionProjectSetupError(
            "A repeated-session project requires at least one declared group."
        )
    if len(normalized_sessions) < 2:
        raise RepeatedSessionProjectSetupError(
            "A repeated-session project requires at least two declared sessions."
        )

    group_lookup = {
        group_id.casefold(): group_id for group_id in normalized_groups
    }
    session_lookup = {
        session_id.casefold(): session_id for session_id in normalized_sessions
    }
    canonical_folders: dict[tuple[str, str], str | Path] = {}
    for raw_cell, folder in source_folders.items():
        if not isinstance(raw_cell, tuple) or len(raw_cell) != 2:
            raise RepeatedSessionProjectSetupError(
                "Each source folder key must be a (group_id, session_id) pair."
            )
        raw_group_id, raw_session_id = (str(value).strip() for value in raw_cell)
        group_id = group_lookup.get(raw_group_id.casefold())
        session_id = session_lookup.get(raw_session_id.casefold())
        if group_id is None:
            raise RepeatedSessionProjectSetupError(
                f"Source folder references unknown group_id '{raw_group_id}'."
            )
        if session_id is None:
            raise RepeatedSessionProjectSetupError(
                f"Source folder references unknown session_id '{raw_session_id}'."
            )
        cell = (group_id, session_id)
        if cell in canonical_folders:
            raise RepeatedSessionProjectSetupError(
                f"More than one source folder was provided for '{group_id}/{session_id}'."
            )
        if folder is None or not str(folder).strip():
            raise RepeatedSessionProjectSetupError(
                f"Source folder for '{group_id}/{session_id}' cannot be blank."
            )
        canonical_folders[cell] = folder

    ordered_sessions = dict(
        sorted(
            normalized_sessions.items(),
            key=lambda item: (int(item[1]["visit_index"]), item[0].casefold()),
        )
    )
    required_cells = {
        (group_id, session_id)
        for group_id in normalized_groups
        for session_id in ordered_sessions
    }
    supplied_cells = set(canonical_folders)
    if supplied_cells != required_cells:
        missing = sorted(required_cells - supplied_cells)
        unexpected = sorted(supplied_cells - required_cells)
        details: list[str] = []
        if missing:
            details.append(
                "missing " + ", ".join(f"{group}/{session}" for group, session in missing)
            )
        if unexpected:
            details.append(
                "unexpected "
                + ", ".join(
                    f"{group}/{session}" for group, session in unexpected
                )
            )
        raise RepeatedSessionProjectSetupError(
            "Recording source folders must cover every declared group/session cell exactly once: "
            + "; ".join(details)
            + "."
        )

    sources_payload: dict[str, dict[str, object]] = {}
    used_source_ids: set[str] = set()
    for group_id in normalized_groups:
        for session_id in ordered_sessions:
            base_source_id = f"{group_id}__{session_id}"
            source_id = base_source_id
            suffix = 2
            while source_id.casefold() in used_source_ids:
                source_id = f"{base_source_id}_{suffix}"
                suffix += 1
            used_source_ids.add(source_id.casefold())
            sources_payload[source_id] = {
                "group_id": group_id,
                "session_id": session_id,
                "raw_input_folder": canonical_folders[(group_id, session_id)],
            }

    try:
        normalized_sources = normalize_project_recording_sources(
            root,
            sources_payload,
            normalized_groups,
            ordered_sessions,
        )
    except RecordingConfigurationError as exc:
        raise RepeatedSessionProjectSetupError(str(exc)) from exc

    preprocessing_payload = (
        deepcopy(dict(preprocessing))
        if preprocessing is not None
        else new_project_preprocessing_settings()
    )
    return {
        "name": name,
        "options": {"mode": "batch"},
        "groups": normalized_groups,
        "sessions": ordered_sessions,
        "recording_sources": normalized_sources,
        "preprocessing": preprocessing_payload,
    }


class _ProjectScanJob(QRunnable):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.signals = _ProjectScanSignals()
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            entries = list(self.root.iterdir())
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self.signals.error.emit(str(exc))
            return

        metadata: list[ProjectMetadata] = []
        total = len(entries)
        for idx, entry in enumerate(entries, start=1):
            if self._cancel_requested:
                self.signals.error.emit(CANCEL_SCAN_MESSAGE)
                return
            self.signals.progress.emit(int(idx / total * 100) if total else 100)
            if not entry.is_dir():
                continue
            manifest_path = entry / "project.json"
            if not manifest_path.exists():
                continue
            try:
                metadata.append(read_project_metadata(entry))
            except Exception as exc:
                logger.error(
                    "Failed to read project metadata at %s: %s",
                    entry,
                    exc,
                    exc_info=exc,
                    extra={"op": "open_existing_project", "path": str(entry)},
                )
                continue

        if self._cancel_requested:
            self.signals.error.emit(CANCEL_SCAN_MESSAGE)
            return
        self.signals.finished.emit(metadata)


class _RepeatedSourcePreflightJob(QRunnable):
    """Audit repeated recording-source folders without touching widgets."""

    def __init__(
        self,
        context: ProjectRecordingContext,
        *,
        group_filename_tokens: Mapping[str, tuple[str, ...]],
        session_filename_tokens: Mapping[str, tuple[str, ...]],
    ) -> None:
        super().__init__()
        self.context = context
        self.group_filename_tokens = dict(group_filename_tokens)
        self.session_filename_tokens = dict(session_filename_tokens)
        self.signals = _RepeatedSourcePreflightSignals()
        self._cancel_event = Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            report = preflight_repeated_recording_sources(
                self.context,
                group_filename_tokens=self.group_filename_tokens,
                session_filename_tokens=self.session_filename_tokens,
                require_nonempty_cells=True,
                cancel_requested=self._cancel_event.is_set,
            )
        except RecordingPreflightCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "repeated_session_source_preflight_failed",
                extra={"project_root": str(self.context.project_root)},
            )
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            if self._cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.finished.emit(report)


def select_projects_root(self) -> None:
    settings = SettingsManager()
    saved_root = settings.get_project_root()

    if saved_root and Path(saved_root).is_dir():
        self.projectsRoot = Path(saved_root)
    elif os.getenv("FPVS_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
        self.projectsRoot = Path.cwd()
    else:
        root = QFileDialog.getExistingDirectory(
            self, "Select Projects Root Folder", ""
        )
        if not root:
            QMessageBox.critical(
                self,
                "Projects Root Required",
                "You must select a Projects Root folder to continue.",
            )
            sys.exit(1)
        self.projectsRoot = Path(root)
        settings.set_project_root(str(self.projectsRoot))
        settings.save()


def _collect_repeated_session_manifest(
    self,
    *,
    project_dir: Path,
    project_name: str,
    group_count: int,
) -> dict[str, object] | None:
    session_count, ok = QInputDialog.getInt(
        self,
        "Repeated Sessions / Visits",
        (
            "How many sessions or visits does each participant have?\n\n"
            "Enter sessions in visit order. A session label (for example, a "
            "menstrual phase) describes the phase-at-visit; visit_index stores "
            "order separately. If everyone follows the same phase order, phase "
            "and visit/order effects are confounded."
        ),
        2,
        2,
        20,
        1,
    )
    if not ok:
        return None

    sessions_payload: dict[str, dict[str, object]] = {}
    used_session_ids: set[str] = set()
    for visit_index in range(1, session_count + 1):
        while True:
            session_label, ok = QInputDialog.getText(
                self,
                f"Session Label — Visit {visit_index}",
                (
                    f"Enter the session/phase-at-visit label for visit {visit_index}.\n"
                    "The label identifies the session; the visit number records "
                    "its order."
                ),
                text=f"Session {visit_index}",
            )
            if not ok:
                QMessageBox.information(
                    self,
                    "Project Creation Cancelled",
                    "Project creation cancelled.",
                )
                return None
            session_label = session_label.strip()
            if not session_label:
                QMessageBox.warning(
                    self,
                    "Session Label Required",
                    "Session labels cannot be empty.",
                )
                continue
            session_id = make_session_id(session_label, used_session_ids)
            sessions_payload[session_id] = {
                "label": session_label,
                "visit_index": visit_index,
            }
            break

    groups_payload: dict[str, dict[str, object]] = {}
    group_labels: dict[str, str] = {}
    used_group_ids: set[str] = set()
    used_group_roots: set[Path] = set()
    used_group_names: set[str] = set()
    for idx in range(group_count):
        folder = QFileDialog.getExistingDirectory(
            self,
            f"Select Common Raw-Data Folder for group #{idx + 1}",
            "",
        )
        if not folder:
            QMessageBox.information(
                self,
                "Project Creation Cancelled",
                "Project creation cancelled.",
            )
            return None
        folder_path = Path(folder).resolve(strict=False)
        if folder_path in used_group_roots:
            QMessageBox.warning(
                self,
                "Duplicate Group Folder",
                "Each group must use a unique common raw-data folder.",
            )
            return None

        default_name = folder_path.name or f"Group {idx + 1}"
        while True:
            group_name, ok = QInputDialog.getText(
                self,
                "Group Name",
                f"Enter a name for group #{idx + 1}:",
                text=default_name,
            )
            if not ok:
                QMessageBox.information(
                    self,
                    "Project Creation Cancelled",
                    "Project creation cancelled.",
                )
                return None
            group_name = group_name.strip()
            if not group_name:
                QMessageBox.warning(
                    self,
                    "Group Name Required",
                    "Group names cannot be empty.",
                )
                continue
            try:
                folder_name = validate_group_folder_name(group_name)
            except GroupConfigurationError as exc:
                QMessageBox.warning(
                    self,
                    "Invalid Group Folder Name",
                    (
                        "Group names become output folder names and must be one safe "
                        "Windows folder name.\n\n"
                        f"Group: {group_name}\n"
                        f"Problem: {exc}\n\n"
                        "Please choose another group name."
                    ),
                )
                continue
            group_name_key = group_name.casefold()
            if group_name_key in used_group_names:
                QMessageBox.warning(
                    self,
                    "Duplicate Group",
                    "Each group must have a unique name.",
                )
                continue

            group_id = make_group_id(group_name, used_group_ids)
            groups_payload[group_id] = {
                "label": group_name,
                "folder_name": folder_name,
                "raw_input_folder": folder_path,
            }
            group_labels[group_id] = group_name
            used_group_names.add(group_name_key)
            used_group_roots.add(folder_path)
            break

    source_folders: dict[tuple[str, str], Path] = {}
    used_source_folders: dict[Path, tuple[str, str]] = {}
    for group_id, group_info in groups_payload.items():
        group_label = group_labels[group_id]
        group_root = Path(group_info["raw_input_folder"])
        for session_id, session_info in sessions_payload.items():
            visit_index = int(session_info["visit_index"])
            session_label = str(session_info["label"])
            folder = QFileDialog.getExistingDirectory(
                self,
                (
                    f"Select Raw Source — {group_label}, visit {visit_index}: "
                    f"{session_label}"
                ),
                str(group_root),
            )
            if not folder:
                QMessageBox.information(
                    self,
                    "Project Creation Cancelled",
                    "Project creation cancelled.",
                )
                return None
            folder_path = Path(folder).resolve(strict=False)
            previous_cell = used_source_folders.get(folder_path)
            if previous_cell is not None:
                QMessageBox.warning(
                    self,
                    "Duplicate Recording Source",
                    (
                        "Each group/session cell must use a unique raw source folder.\n\n"
                        f"Already assigned to {previous_cell[0]}/{previous_cell[1]}."
                    ),
                )
                return None
            cell = (group_id, session_id)
            source_folders[cell] = folder_path
            used_source_folders[folder_path] = cell

    try:
        manifest = build_repeated_session_project_manifest(
            project_root=project_dir,
            project_name=project_name,
            groups=groups_payload,
            sessions=sessions_payload,
            source_folders=source_folders,
        )
    except RepeatedSessionProjectSetupError as exc:
        QMessageBox.critical(
            self,
            "Invalid Repeated-Session Setup",
            str(exc),
        )
        return None

    return manifest


def _repeated_preflight_inputs(
    project_dir: Path,
    manifest: Mapping[str, object],
) -> tuple[
    ProjectRecordingContext,
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    """Build worker inputs without scanning any source folder."""

    preview_project = SimpleNamespace(
        project_root=project_dir,
        groups=manifest["groups"],
        participants={},
        sessions=manifest["sessions"],
        recording_sources=manifest["recording_sources"],
        recordings={},
    )
    groups = manifest["groups"]
    sessions = manifest["sessions"]
    if not isinstance(groups, Mapping) or not isinstance(sessions, Mapping):
        raise RepeatedSessionProjectSetupError(
            "Repeated-session preflight requires normalized groups and sessions."
        )
    group_tokens = derive_filename_token_rules(
        {
            str(group_id): (
                group_id,
                info["label"],
                info["folder_name"],
            )
            for group_id, info in groups.items()
            if isinstance(info, Mapping)
        }
    )
    session_tokens = derive_filename_token_rules(
        {
            str(session_id): (session_id, info["label"])
            for session_id, info in sessions.items()
            if isinstance(info, Mapping)
        }
    )
    return project_recording_context(preview_project), group_tokens, session_tokens


def _empty_repeated_source_scaffold(report: RecordingPreflightReport) -> bool:
    """Return whether every declared source is present but contains no BDFs."""

    return not report.rows and all(
        issue.code == "empty_source_cell" for issue in report.issues
    )


def apply_repeated_session_preflight_report(
    manifest: Mapping[str, object],
    report: RecordingPreflightReport,
) -> dict[str, object]:
    """Return a copied manifest populated from one accepted source audit."""

    if report.is_blocked and not _empty_repeated_source_scaffold(report):
        raise RepeatedSessionProjectSetupError(report.summary_text())
    completed = deepcopy(dict(manifest))
    if _empty_repeated_source_scaffold(report):
        completed["participants"] = {}
        completed["recordings"] = {}
    else:
        completed["participants"] = report.participants_manifest()
        completed["recordings"] = report.recordings_manifest()
    return completed


def _create_repeated_session_project(
    self,
    *,
    project_dir: Path,
    project_name: str,
    manifest: Mapping[str, object],
    use_existing_project_folder: bool,
) -> Project:
    """Commit an accepted repeated manifest and activate the new project."""

    if (project_dir / "project.json").exists():
        raise RepeatedSessionProjectSetupError(
            f"A project now exists at {project_dir}; it was not overwritten."
        )
    if use_existing_project_folder:
        if not project_dir.is_dir():
            raise RepeatedSessionProjectSetupError(
                f"The selected existing project folder is no longer available: {project_dir}"
            )
    else:
        project_dir.mkdir(parents=True, exist_ok=False)

    project = Project.load(project_dir, manifest=dict(manifest))
    project.name = project_name
    project.options["mode"] = "batch"
    project.groups_locked = False
    project.groups_locked_at = None
    project.save()
    self.currentProject = project
    self.loadProject(project)
    return project


def _start_repeated_session_preflight(
    self,
    *,
    project_dir: Path,
    project_name: str,
    manifest: Mapping[str, object],
    use_existing_project_folder: bool,
) -> bool:
    """Start the cancellable source audit and continue creation on success."""

    if getattr(self, "_active_repeated_preflight_job", None) is not None:
        QMessageBox.information(
            self,
            "Repeated-Session Preflight Running",
            "A repeated-session source preflight is already running.",
        )
        return False

    try:
        context, group_tokens, session_tokens = _repeated_preflight_inputs(
            project_dir,
            manifest,
        )
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(
            self,
            "Invalid Repeated-Session Setup",
            str(exc),
        )
        return False

    progress = QProgressDialog(
        "Auditing repeated-session source folders…",
        "Cancel",
        0,
        0,
        self,
    )
    progress.setWindowTitle("Repeated-Session Source Preflight")
    progress.setWindowModality(Qt.WindowModal)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)

    job = _RepeatedSourcePreflightJob(
        context,
        group_filename_tokens=group_tokens,
        session_filename_tokens=session_tokens,
    )
    job.setAutoDelete(False)
    self._active_repeated_preflight_job = job
    self._active_repeated_preflight_progress = progress
    action = getattr(self, "actionCreateNewProject", None)
    if action is not None:
        action.setEnabled(False)
    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        progress.close()
        progress.deleteLater()
        if getattr(self, "_active_repeated_preflight_job", None) is job:
            self._active_repeated_preflight_job = None
        if getattr(self, "_active_repeated_preflight_progress", None) is progress:
            self._active_repeated_preflight_progress = None
        if action is not None:
            action.setEnabled(True)

    def handle_cancel_request() -> None:
        job.request_cancel()
        progress.setLabelText("Cancelling repeated-session source preflight…")
        progress.setCancelButton(None)

    def handle_cancelled() -> None:
        cleanup()
        QMessageBox.information(
            self,
            "Project Creation Cancelled",
            "Repeated-session source preflight was cancelled. No project was created.",
        )

    def handle_failed(message: str) -> None:
        cleanup()
        QMessageBox.critical(
            self,
            "Repeated-Session Source Preflight Failed",
            message,
        )

    def handle_finished(raw_report: object) -> None:
        cleanup()
        if not isinstance(raw_report, RecordingPreflightReport):
            QMessageBox.critical(
                self,
                "Repeated-Session Source Preflight Failed",
                "The source preflight returned an invalid result.",
            )
            return
        if raw_report.is_blocked and not _empty_repeated_source_scaffold(raw_report):
            QMessageBox.critical(
                self,
                "Repeated-Session Source Preflight Failed",
                raw_report.summary_text(),
            )
            return
        if raw_report.warnings:
            answer = QMessageBox.question(
                self,
                "Incomplete Repeated-Session Coverage",
                raw_report.summary_text()
                + "\n\nCreate the project with these explicitly audited missing sessions?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            completed_manifest = apply_repeated_session_preflight_report(
                manifest,
                raw_report,
            )
            _create_repeated_session_project(
                self,
                project_dir=project_dir,
                project_name=project_name,
                manifest=completed_manifest,
                use_existing_project_folder=use_existing_project_folder,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "repeated_session_project_creation_failed",
                extra={"project_root": str(project_dir)},
            )
            QMessageBox.critical(
                self,
                "Project Creation Failed",
                f"Could not create repeated-session project at {project_dir}: {exc}",
            )

    job.signals.cancelled.connect(handle_cancelled, Qt.QueuedConnection)
    job.signals.failed.connect(handle_failed, Qt.QueuedConnection)
    job.signals.finished.connect(handle_finished, Qt.QueuedConnection)
    progress.canceled.connect(handle_cancel_request)
    progress.show()
    try:
        QThreadPool.globalInstance().start(job)
    except Exception as exc:  # noqa: BLE001
        cleanup()
        logger.exception(
            "repeated_session_source_preflight_start_failed",
            extra={"project_root": str(project_dir)},
        )
        QMessageBox.critical(
            self,
            "Repeated-Session Source Preflight Failed",
            f"Could not start the source preflight: {exc}",
        )
        return False
    return True


def new_project(self) -> None:
    if getattr(self, "_active_repeated_preflight_job", None) is not None:
        QMessageBox.information(
            self,
            "Repeated-Session Preflight Running",
            "Finish or cancel the active repeated-session source preflight first.",
        )
        return
    name, ok = QInputDialog.getText(
        self, "Project Name", "Enter a name for this new project:"
    )
    if not ok or not name.strip():
        return
    project_name = name.strip()
    project_dir = self.projectsRoot / project_name
    use_existing_project_folder = False
    if project_dir.exists():
        if (project_dir / "project.json").exists():
            QMessageBox.critical(
                self,
                "Project Already Exists",
                f"A project named '{project_name}' already exists. Choose a new "
                "name; existing project data will not be overwritten.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Create Project in Existing Folder?",
            (
                f"The folder already exists but has no project.json:\n{project_dir}\n\n"
                "Create the FPVS Toolbox project in this folder? Existing raw "
                "data and other files will be preserved. The Toolbox will add "
                "project.json and managed output folders only after setup and "
                "source preflight succeed."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        use_existing_project_folder = True

    group_count, ok = QInputDialog.getInt(
        self,
        "Experimental Groups",
        "How many experimental groups does this project have?",
        1,
        1,
        20,
        1,
    )
    if not ok:
        return

    structure, ok = QInputDialog.getItem(
        self,
        "Project Structure",
        (
            "Choose how participant recordings are organized.\n\n"
            "Repeated sessions store the session/phase-at-visit label separately "
            "from visit order and require one raw folder per group and session. "
            "When every participant completes phases in the same order, phase is "
            "confounded with visit/order."
        ),
        [FLAT_PROJECT_STRUCTURE, REPEATED_SESSION_PROJECT_STRUCTURE],
        0,
        False,
    )
    if not ok:
        return

    repeated_manifest: dict[str, object] | None = None
    group_folders: dict[str, str] = {}
    if structure == REPEATED_SESSION_PROJECT_STRUCTURE:
        repeated_manifest = _collect_repeated_session_manifest(
            self,
            project_dir=project_dir,
            project_name=project_name,
            group_count=group_count,
        )
        if repeated_manifest is None:
            return
        _start_repeated_session_preflight(
            self,
            project_dir=project_dir,
            project_name=project_name,
            manifest=repeated_manifest,
            use_existing_project_folder=use_existing_project_folder,
        )
        return
    elif group_count == 1:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Input Folder",
            "",
        )
        if not folder:
            QMessageBox.information(
                self,
                "Project Creation Cancelled",
                "Project creation cancelled.",
            )
            return
        group_folders["Input Folder"] = folder
    else:
        used_folder_paths: set[Path] = set()
        for idx in range(group_count):
            folder = QFileDialog.getExistingDirectory(
                self,
                f"Select Input Folder for group #{idx + 1}",
                "",
            )
            if not folder:
                QMessageBox.information(
                    self,
                    "Project Creation Cancelled",
                    "Project creation cancelled.",
                )
                return
            folder_path = Path(folder).resolve()
            if folder_path in used_folder_paths:
                QMessageBox.warning(
                    self,
                    "Duplicate Group Folder",
                    "Each group must use a unique input folder.",
                )
                return
            used_folder_paths.add(folder_path)
            default_name = folder_path.name or f"Group {idx + 1}"
            while True:
                group_name, ok = QInputDialog.getText(
                    self,
                    "Group Name",
                    f"Enter a name for group #{idx + 1}:",
                    text=default_name,
                )
                if not ok:
                    QMessageBox.information(
                        self,
                        "Project Creation Cancelled",
                        "Project creation cancelled.",
                    )
                    return
                group_name = group_name.strip()
                if not group_name:
                    QMessageBox.warning(
                        self,
                        "Group Name Required",
                        "Group names cannot be empty.",
                    )
                    continue
                try:
                    validate_group_folder_name(group_name)
                except GroupConfigurationError as exc:
                    QMessageBox.warning(
                        self,
                        "Invalid Group Folder Name",
                        (
                            "Group names become output folder names and must be one safe "
                            "Windows folder name.\n\n"
                            f"Group: {group_name}\n"
                            f"Problem: {exc}\n\n"
                            "Please choose another group name."
                        ),
                    )
                    continue
                if group_name.lower() in {existing.lower() for existing in group_folders}:
                    QMessageBox.warning(
                        self,
                        "Duplicate Group",
                        "Each group must have a unique name.",
                    )
                    continue
                group_folders[group_name] = folder
                break

    if not use_existing_project_folder:
        try:
            project_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Project Creation Failed",
                f"Could not create project folder {project_dir}: {exc}",
            )
            return

    if group_count == 1:
        project = Project.load(
            project_dir,
            manifest={
                "name": project_name,
                "input_folder": group_folders["Input Folder"],
                "options": {"mode": "batch"},
                "preprocessing": new_project_preprocessing_settings(),
            },
        )
    else:
        used_group_ids: set[str] = set()
        groups_payload: dict[str, dict[str, object]] = {}
        for group_name, folder in group_folders.items():
            group_id = make_group_id(group_name, used_group_ids)
            groups_payload[group_id] = {
                "label": group_name,
                "folder_name": group_name,
                "raw_input_folder": Path(folder),
            }
        project = Project.load(
            project_dir,
            manifest={
                "name": project_name,
                "options": {"mode": "batch"},
                "groups": groups_payload,
                "preprocessing": new_project_preprocessing_settings(),
            },
        )
    project.name = project_name
    project.options["mode"] = "batch"
    project.participants = {}
    project.groups_locked = False
    project.groups_locked_at = None
    project.save()

    self.currentProject = project
    self.loadProject(project)


def new_project_from_fpvs_config(self, parent: QWidget | None = None) -> Project | None:
    if parent is None:
        parent = getattr(self, "window", lambda: None)() or getattr(self, "parent", lambda: None)() or None

    root = ensure_projects_root(parent)
    if root is None:
        QMessageBox.information(parent, "Projects Root", "Project root not set.")
        return None

    self.projectsRoot = root
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        "Import FPVS Studio Config",
        "",
        f"FPVS Studio Config (*{CONFIG_SUFFIX});;JSON Files (*.json);;All Files (*)",
    )
    if not path:
        return None

    try:
        project = create_project_from_fpvs_config(root, Path(path))
    except FPVSConfigImportError as exc:
        QMessageBox.critical(parent, "Import Failed", str(exc))
        logger.error(
            "Failed to import FPVS config %s: %s",
            path,
            exc,
            exc_info=exc,
            extra={"op": "new_project_from_fpvs_config", "path": path},
        )
        return None

    input_folder = QFileDialog.getExistingDirectory(
        parent,
        "Select Folder Containing BDF Files",
        str(root),
    )
    if input_folder:
        project.input_folder = Path(input_folder)
        project.save()

    self.currentProject = project
    self.loadProject(project)
    logger.info(
        "Created project %s from FPVS config %s.",
        project.project_root,
        path,
        extra={"op": "new_project_from_fpvs_config", "path": path},
    )
    QMessageBox.information(
        parent,
        "Project Created",
        f"Created project '{project.name}' with {len(project.event_map)} condition(s).",
    )
    return project


def import_fpvs_config_project(self, parent: QWidget | None = None) -> Project | None:
    """Compatibility wrapper for the former File menu import action."""
    return new_project_from_fpvs_config(self, parent)


def open_existing_project(self, parent: QWidget | None = None) -> None:
    if _open_selected_project_guard.is_active():
        logger.info(
            "Open existing project skipped because another open is active.",
            extra={"op": "open_existing_project", "path": None},
        )
        return
    if not _open_project_guard.start():
        return

    # Derive a parent if not provided to keep backward compatibility with older callers
    if parent is None:
        parent = getattr(self, "window", lambda: None)() or getattr(self, "parent", lambda: None)() or None

    root = ensure_projects_root(parent)
    if root is None:
        QMessageBox.information(parent, "Projects Root", "Project root not set.")
        logger.warning(
            "Projects root missing.",
            extra={"op": "open_existing_project", "path": None},
        )
        _open_project_guard.end()
        return

    self.projectsRoot = root

    progress = QProgressDialog("Scanning projects...", "Cancel", 0, 100, parent)
    progress.setWindowTitle("Scanning Projects")
    progress.setWindowModality(Qt.WindowModal)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)
    progress.show()

    cleaned = False

    def log_thread_context(label: str) -> None:
        app = QApplication.instance()
        gui_thread = app.thread() if app else None
        current = QThread.currentThread()
        logger.debug(
            "%s thread=%s gui_thread=%s is_gui=%s",
            label,
            current,
            gui_thread,
            current == gui_thread if gui_thread else False,
            extra={"op": "open_existing_project", "path": str(root)},
        )

    def finalize_guard() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        progress.close()
        progress.deleteLater()
        self._active_scan_job = None
        _open_project_guard.end()

    def handle_error(message: str) -> None:
        log_thread_context("handle_error")
        if message == CANCEL_SCAN_MESSAGE:
            logger.debug(
                "Project scan cancelled for %s.",
                root,
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return
        logger.debug(
            "Project scan error for %s: %s",
            root,
            message,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        logger.error(
            "Unable to enumerate projects under %s: %s",
            root,
            message,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        QMessageBox.critical(
            parent,
            "Projects Root Unavailable",
            f"Unable to access projects root:\n{root}\n{message}",
        )
        finalize_guard()

    def handle_finished(metadata: list[ProjectMetadata]) -> None:
        log_thread_context("handle_finished")
        if __debug__:
            app = QApplication.instance()
            assert app is not None
            assert QThread.currentThread() == app.thread()
        logger.debug(
            "Project scan finished for %s with %s projects.",
            root,
            len(metadata),
            extra={"op": "open_existing_project", "path": str(root)},
        )
        if not metadata:
            QMessageBox.information(
                parent,
                "No Projects Found",
                f"No projects found under {root}.",
            )
            logger.debug(
                "No projects discovered under %s.",
                root,
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return

        labels: list[str] = []
        label_to_metadata: dict[str, ProjectMetadata] = {}
        for entry in metadata:
            label = entry.name
            labels.append(label)
            label_to_metadata[label] = entry

        if not labels:
            QMessageBox.warning(
                parent,
                "Projects Unavailable",
                "No valid projects could be loaded.",
            )
            finalize_guard()
            return

        choice, ok = QInputDialog.getItem(
            parent,
            "Open Existing Project",
            "Select a project:",
            labels,
            0,
            editable=False,
        )
        if not ok or choice not in label_to_metadata:
            logger.debug(
                "Project selection cancelled.",
                extra={"op": "open_existing_project", "path": str(root)},
            )
            finalize_guard()
            return

        selected = label_to_metadata[choice]
        finalize_guard()

        _set_open_existing_action_enabled(self, False)
        logger.debug(
            "Project selection confirmed: %s",
            selected.project_root,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        QTimer.singleShot(
            0,
            lambda: _open_selected_project(self, selected, parent, root),
        )

    job = _ProjectScanJob(root)
    job.setAutoDelete(False)
    self._active_scan_job = job
    logger.debug(
        "Starting project scan under %s.",
        root,
        extra={"op": "open_existing_project", "path": str(root)},
    )
    job.signals.error.connect(handle_error, Qt.QueuedConnection)
    job.signals.finished.connect(handle_finished, Qt.QueuedConnection)

    def handle_progress(value: int) -> None:
        log_thread_context("handle_progress")
        progress.setValue(value)

    job.signals.progress.connect(handle_progress, Qt.QueuedConnection)
    progress.canceled.connect(job.request_cancel)
    QThreadPool.globalInstance().start(job)


def _set_open_existing_action_enabled(self, enabled: bool) -> None:
    action = getattr(self, "actionOpenExistingProject", None)
    if action is not None:
        action.setEnabled(enabled)


def _open_selected_project(
    self,
    selected: ProjectMetadata,
    parent: QWidget | None,
    root: Path,
) -> None:
    if __debug__:
        app = QApplication.instance()
        assert app is not None
        assert QThread.currentThread() == app.thread()
    if not _open_selected_project_guard.start():
        logger.debug(
            "Open project request skipped because another open is active.",
            extra={"op": "open_existing_project", "path": str(root)},
        )
        _set_open_existing_action_enabled(self, True)
        return
    logger.debug(
        "Opening project from selection: %s",
        selected.project_root,
        extra={"op": "open_existing_project", "path": str(root)},
    )
    try:
        project = Project.load(
            selected.project_root,
            manifest=selected.manifest,
            manifest_path=selected.manifest_path,
        )
        self.currentProject = project
        self.loadProject(project)
        if hasattr(self, "_on_project_ready"):
            self._on_project_ready()
        logger.debug(
            "Project opened successfully: %s",
            selected.project_root,
            extra={"op": "open_existing_project", "path": str(root)},
        )
    except Exception as exc:
        logger.error(
            "Failed to open project at %s: %s",
            selected.project_root,
            exc,
            exc_info=exc,
            extra={"op": "open_existing_project", "path": str(root)},
        )
        raise
    finally:
        _open_selected_project_guard.end()
        _set_open_existing_action_enabled(self, True)


def openProjectPath(self, folder: str) -> None:
    project = Project.load(folder)
    self.currentProject = project
    self.loadProject(project)

    settings = SettingsManager()
    recent = settings.get_recent_projects()
    if folder in recent:
        recent.remove(folder)
    recent.insert(0, folder)
    settings.set_recent_projects(recent)
    settings.save()


def loadProject(self, project: Project) -> None:
    self.currentProject = project
    self.lbl_currentProject.setText(f"Current Project: {project.name}")

    if not project_group_context(project).has_group_metadata:
        self.settings.set("paths", "data_folder", str(project.input_folder))
        self.settings.save()

    mode = project.options.get("mode", "batch").lower()
    self.rb_single.setChecked(mode == "single")
    self.rb_batch.setChecked(mode == "batch")

    for row in list(self.event_rows):
        row.setParent(None)
    self.event_rows.clear()

    if project.event_map:
        for label, ident in project.event_map.items():
            self.add_event_row(str(label), str(ident))
    else:
        self.add_event_row()

    self.log(f"Loaded project: {project.name}")


def edit_project_settings(self) -> None:
    if not getattr(self, "currentProject", None):
        QMessageBox.warning(self, "No Project", "Please open or create a project first.")
        return
    project = self.currentProject
    groups = getattr(project, "groups", {}) or {}
    if groups:
        if getattr(project, "groups_locked", False):
            QMessageBox.critical(
                self,
                "Group Folders Locked",
                "Group raw-data folders are locked because this project has successful "
                "processed outputs. Restore the registered folders, or create a new "
                "project if the group layout must change.",
            )
            return

        selected_folders: dict[str, Path] = {}
        used_paths: set[Path] = set()
        for group_id, raw_info in groups.items():
            if not isinstance(raw_info, dict):
                QMessageBox.critical(
                    self,
                    "Invalid Group Configuration",
                    f"Group '{group_id}' metadata is invalid. Repair project.json.",
                )
                return
            label = str(raw_info.get("label") or group_id)
            current_folder = Path(raw_info["raw_input_folder"])
            folder = QFileDialog.getExistingDirectory(
                self,
                f"Select Raw Data Folder for {label}",
                str(current_folder),
            )
            if not folder:
                return
            folder_path = Path(folder).resolve()
            if not folder_path.is_dir():
                QMessageBox.critical(
                    self,
                    "Group Folder Missing",
                    f"The selected folder does not exist: {folder_path}",
                )
                return
            if folder_path in used_paths:
                QMessageBox.warning(
                    self,
                    "Duplicate Group Folder",
                    "Each group must use a unique raw-data folder.",
                )
                return
            used_paths.add(folder_path)
            selected_folders[str(group_id)] = folder_path

        updated_groups = {
            str(group_id): {
                **dict(raw_info),
                "raw_input_folder": selected_folders[str(group_id)],
            }
            for group_id, raw_info in groups.items()
        }
        updated_participants = {
            str(participant_id): dict(raw_info)
            for participant_id, raw_info in (
                getattr(project, "participants", {}) or {}
            ).items()
        }
        for participant_id, participant in updated_participants.items():
            group_id = str(
                participant.get("group_id") or participant.get("group") or ""
            ).strip()
            raw_file = participant.get("raw_file")
            if not group_id or not raw_file or group_id not in selected_folders:
                continue
            moved_path = selected_folders[group_id] / Path(raw_file).name
            if not moved_path.is_file():
                QMessageBox.critical(
                    self,
                    "Registered Participant File Missing",
                    f"Participant {participant_id} is registered to "
                    f"{Path(raw_file).name}, but that file is not present in "
                    f"{selected_folders[group_id]}. No project changes were saved.",
                )
                return
            participant["raw_file"] = moved_path

        previous_groups = project.groups
        previous_participants = project.participants
        try:
            project.groups = updated_groups
            project.participants = updated_participants
            project.save()
        except Exception as exc:
            project.groups = previous_groups
            project.participants = previous_participants
            logger.exception("Failed to update multi-group raw folders.")
            QMessageBox.critical(self, "Project Save Error", str(exc))
            return
        self.loadProject(project)
        return

    folder = QFileDialog.getExistingDirectory(
        self, "Select Input Folder", str(project.input_folder)
    )
    if not folder:
        return
    project.input_folder = Path(folder)
    project.save()
    self.loadProject(project)
