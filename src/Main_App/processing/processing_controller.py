"""Processing helpers for the Main App PySide6 runtime path."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Sequence

from PySide6.QtWidgets import QFileDialog, QMessageBox

from Main_App.Shared.file_filters import is_bdf_file
from Main_App.projects.grouping import project_group_context
from Main_App.projects.recordings import (
    ProjectRecordingContext,
    RecordingConfigurationError,
    RecordingSourceInfo,
    project_recording_context,
)
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.projects.raw_identity import infer_raw_participant_id
from Main_App.projects.recording_preflight import (
    RecordingPreflightReport,
    derive_filename_token_rules,
    preflight_repeated_recording_sources,
)
from Main_App.io.load_utils import (
    format_bdf_recording_not_started_message,
    inspect_bdf_header,
    load_eeg_file,
)
from Main_App.processing.preprocess import (
    perform_preprocessing,
    begin_preproc_audit,
    finalize_preproc_audit,
)
from Main_App.processing.processing import process_data
from Main_App.Shared.post_process import post_process

if TYPE_CHECKING:
    from Main_App.projects.project import Project

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawFileInfo:
    """
    Metadata tracked for each discovered raw file.

    - path: absolute Path to the .bdf file.
    - subject_id: canonical participant label inferred from the file name.
    - group: optional experimental group_id, inferred from the folder
      where the file was discovered (for multi-group projects).
    """

    path: Path
    subject_id: str
    group: str | None = None
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None
    source_id: str | None = None
    days_from_baseline: float | None = None

    @property
    def processing_id(self) -> str:
        """Return the durable per-raw-file identity used by processing state."""

        return self.recording_id or self.subject_id

    @property
    def output_stem(self) -> str:
        """Return the collision-safe workbook/derivative stem."""

        if self.recording_id:
            return self.recording_id
        return self.subject_id


@dataclass(frozen=True)
class ParticipantReviewRow:
    """One participant manifest update that needs user review before processing."""

    participant_id: str
    group_id: str | None
    group_label: str
    raw_file: Path
    status: str
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None


# ``subject_id`` is the canonical participant label inferred from the .bdf file
# name. ``group`` captures the multi-group group_id derived from the folder the
# file was found in. Both values are persisted so that downstream processing,
# participant manifests, and the Stats/Plot tools can reason about consistent
# IDs without re-scanning the filesystem.

def _infer_subject_id(file_path: Path) -> str:
    """Compatibility alias for the shared raw participant parser."""

    return infer_raw_participant_id(file_path)


def _iter_group_folders(project: "Project") -> Iterable[tuple[str | None, Path]]:
    """
    Yield (group_id, folder_path) pairs for all configured input folders.

    For legacy/single-group projects, yields a single (None, project.input_folder)
    entry so callers can treat the iteration uniformly.
    """
    context = project_group_context(project)
    if context.groups:
        for group in context.groups:
            yield group.group_id, group.raw_input_folder
    else:
        if project.input_folder is None:
            raise ValueError(
                "Single-group project is missing its canonical input_folder."
            )
        yield None, Path(project.input_folder)


def _recording_context(project: "Project") -> ProjectRecordingContext:
    return project_recording_context(project)


def validate_repeated_recording_sources_for_processing(
    project: "Project",
    discovered_files: Sequence[RawFileInfo],
) -> RecordingPreflightReport | None:
    """Re-audit already discovered repeated raw sources before registration.

    The GUI supplies the canonical direct-child discovery result so this check
    does not perform a second recursive filesystem scan on the UI thread.
    """

    context = _recording_context(project)
    if not context.is_repeated_session:
        return None
    source_files: dict[str, list[Path]] = {
        source.source_id: [] for source in context.sources
    }
    for info in discovered_files:
        source_id = str(info.source_id or "").strip()
        if not source_id:
            raise ValueError(
                f"Repeated-session raw file '{info.path}' has no canonical source_id."
            )
        try:
            source = context.source(source_id)
        except RecordingConfigurationError as exc:
            raise ValueError(
                f"Repeated-session raw file '{info.path}' references unknown "
                f"source_id '{source_id}'."
            ) from exc
        if str(info.group or "").casefold() != source.group_id.casefold():
            raise ValueError(
                f"Repeated-session raw file '{info.path}' group '{info.group}' "
                f"does not match canonical source group '{source.group_id}'."
            )
        if str(info.session_id or "").casefold() != source.session_id.casefold():
            raise ValueError(
                f"Repeated-session raw file '{info.path}' session "
                f"'{info.session_id}' does not match canonical source session "
                f"'{source.session_id}'."
            )
        source_files[source.source_id].append(info.path)
    group_tokens = derive_filename_token_rules(
        {
            group.group_id: (
                group.group_id,
                group.label,
                group.folder_name,
            )
            for group in context.groups
        }
    )
    session_tokens = derive_filename_token_rules(
        {
            session.session_id: (session.session_id, session.label)
            for session in context.sessions
        }
    )
    report = preflight_repeated_recording_sources(
        context,
        group_filename_tokens=group_tokens,
        session_filename_tokens=session_tokens,
        require_nonempty_cells=True,
        discovered_source_files=source_files,
    )
    if report.is_blocked:
        error_details = "\n".join(
            f"- {issue.code}: {issue.message}" for issue in report.errors
        )
        raise ValueError(
            "Repeated-session source preflight blocked processing before raw "
            "registration or BDF loading.\n\n"
            + report.summary_text()
            + "\n\nBlocking findings:\n"
            + error_details
        )
    if report.warnings:
        logger.warning(
            "repeated_source_preflight_processing_warnings",
            extra={
                "project_root": str(context.project_root),
                "warning_codes": [issue.code for issue in report.warnings],
            },
        )
    return report


def _iter_recording_sources(
    project: "Project",
) -> Iterable[RecordingSourceInfo]:
    context = _recording_context(project)
    yield from context.sources


def raw_selection_start_folder(project: "Project") -> Path:
    """Return a real registered raw root for file-dialog navigation only."""

    recording_context = _recording_context(project)
    if recording_context.is_repeated_session:
        if not recording_context.sources:
            raise ValueError(
                "Repeated-session project is missing canonical recording sources."
            )
        return recording_context.sources[0].raw_input_folder
    context = project_group_context(project)
    if context.groups:
        return context.groups[0].raw_input_folder
    if project.input_folder is None:
        raise ValueError("Project is missing its canonical input_folder.")
    return Path(project.input_folder)


def _is_within_path(parent: Path, child: Path) -> bool:
    try:
        parent_resolved = parent.resolve()
        child_resolved = child.resolve()
    except (OSError, RuntimeError):
        return False
    return parent_resolved == child_resolved or parent_resolved in child_resolved.parents


def _participant_record(
    project: "Project",
    subject_id: str,
) -> tuple[str | None, Mapping[str, Any] | None]:
    participants = getattr(project, "participants", {}) or {}
    if not isinstance(participants, Mapping):
        return None, None

    for candidate in (subject_id, subject_id.upper()):
        if candidate in participants:
            entry = participants[candidate]
            return candidate, entry if isinstance(entry, Mapping) else {}

    subject_key = subject_id.casefold()
    for raw_key, raw_entry in participants.items():
        if str(raw_key).casefold() == subject_key:
            return str(raw_key), raw_entry if isinstance(raw_entry, Mapping) else {}
    return None, None


def _recording_record(
    project: "Project",
    recording_id: str,
) -> tuple[str | None, Mapping[str, Any] | None]:
    recordings = getattr(project, "recordings", {}) or {}
    if not isinstance(recordings, Mapping):
        return None, None
    key = recording_id.casefold()
    for raw_id, raw_entry in recordings.items():
        if str(raw_id).casefold() == key:
            return str(raw_id), raw_entry if isinstance(raw_entry, Mapping) else {}
    return None, None


def _participant_group_id(entry: Mapping[str, Any] | None) -> str | None:
    if not entry:
        return None
    group_value = entry.get("group_id")
    if group_value is None:
        group_value = entry.get("group")
    if group_value is None:
        return None
    group_id = str(group_value).strip()
    return group_id or None


def _participant_raw_file(project: "Project", entry: Mapping[str, Any] | None) -> Path | None:
    if not entry:
        return None
    raw_file_value = entry.get("raw_file")
    if not raw_file_value:
        return None
    raw_path = Path(raw_file_value)
    if raw_path.is_absolute():
        return raw_path
    return Path(getattr(project, "project_root", Path.cwd())) / raw_path


def _same_path(left: Path | None, right: Path) -> bool:
    if left is None:
        return False
    try:
        return left.resolve() == right.resolve()
    except (OSError, RuntimeError):
        return left == right


def _recording_source_for_path(
    context: ProjectRecordingContext,
    file_path: Path,
) -> RecordingSourceInfo | None:
    file_resolved = file_path.resolve(strict=False)
    for source in context.sources:
        source_root = source.raw_input_folder.resolve(strict=False)
        if file_resolved.parent == source_root:
            return source
    return None


def _recording_info_for_source_path(
    context: ProjectRecordingContext,
    source: RecordingSourceInfo,
    file_path: Path,
) -> RawFileInfo:
    resolved = file_path.resolve(strict=False)
    subject_id = _infer_subject_id(resolved)
    session = context.session(source.session_id)
    try:
        registered = context.recording_for_raw_path(resolved)
    except RecordingConfigurationError:
        registered = None
    if registered is not None:
        if registered.source_id != source.source_id:
            raise ValueError(
                f"Recording '{registered.recording_id}' is registered to source "
                f"'{registered.source_id}', but its raw file was discovered in "
                f"source '{source.source_id}'."
            )
        if registered.participant_id.casefold() != subject_id.casefold():
            raise ValueError(
                f"Recording '{registered.recording_id}' is registered to participant "
                f"'{registered.participant_id}', but filename '{resolved.name}' "
                f"resolves to '{subject_id}'. Repair project.json or rename the file."
            )
        recording_id = registered.recording_id
        subject_id = registered.participant_id
        days_from_baseline = registered.days_from_baseline
    else:
        recording_id = f"{subject_id}__{session.session_id}"
        days_from_baseline = None
    return RawFileInfo(
        path=resolved,
        subject_id=subject_id,
        group=source.group_id,
        recording_id=recording_id,
        session_id=session.session_id,
        session_label=session.label,
        visit_index=session.visit_index,
        source_id=source.source_id,
        days_from_baseline=days_from_baseline,
    )


def _group_label(project: "Project", group_id: str | None) -> str:
    if not group_id:
        return "Single group"
    return project_group_context(project).group(group_id).label


def _validate_known_raw_files(
    project: "Project",
    discovered_files: Sequence[RawFileInfo],
) -> None:
    recording_context = _recording_context(project)
    if recording_context.is_repeated_session:
        _validate_known_recordings(recording_context, discovered_files)
        return
    context = project_group_context(project)
    discovered_by_path = {
        info.path.resolve(strict=False): info for info in discovered_files
    }
    missing_files: list[tuple[str, Path]] = []
    missing_metadata: list[str] = []
    undiscovered_files: list[tuple[str, Path]] = []
    for participant in context.participants:
        participant_id = participant.participant_id
        raw_file = participant.raw_file
        if raw_file is None:
            missing_metadata.append(str(participant_id))
            continue
        try:
            raw_exists = raw_file.is_file()
        except OSError:
            raw_exists = False
        if not raw_exists:
            missing_files.append((str(participant_id), raw_file))
            continue
        discovered = discovered_by_path.get(raw_file.resolve(strict=False))
        if discovered is None:
            undiscovered_files.append((str(participant_id), raw_file))
            continue
        if participant.group_id != discovered.group:
            raise ValueError(
                f"Participant '{participant_id}' is assigned to group "
                f"'{participant.group_id}', but its registered raw file was "
                f"discovered in group '{discovered.group}'."
            )
        if participant_id.casefold() != discovered.subject_id.casefold():
            raise ValueError(
                f"Participant '{participant_id}' is registered to {raw_file.name}, "
                "but that filename resolves to participant ID "
                f"'{discovered.subject_id}'. Repair project.json or rename the file."
            )

    if missing_metadata:
        participant_list = ", ".join(sorted(missing_metadata, key=str.casefold))
        raise ValueError(
            "Registered participant metadata is missing raw_file for: "
            f"{participant_list}. Repair project.json before processing."
        )
    if missing_files:
        details = "; ".join(
            f"{participant_id}: {raw_file}"
            for participant_id, raw_file in sorted(
                missing_files,
                key=lambda item: item[0].casefold(),
            )
        )
        raise FileNotFoundError(
            "Registered participant has a missing raw .bdf file. "
            f"Restore or correct the registered path(s): {details}"
        )
    if undiscovered_files:
        details = "; ".join(
            f"{participant_id}: {raw_file}"
            for participant_id, raw_file in sorted(
                undiscovered_files,
                key=lambda item: item[0].casefold(),
            )
        )
        raise ValueError(
            "Registered participant raw file was not found by canonical group "
            f"discovery: {details}"
        )


def _validate_known_recordings(
    context: ProjectRecordingContext,
    discovered_files: Sequence[RawFileInfo],
) -> None:
    discovered_by_path = {
        info.path.resolve(strict=False): info for info in discovered_files
    }
    missing_files: list[tuple[str, Path]] = []
    undiscovered_files: list[tuple[str, Path]] = []
    for recording in context.recordings:
        try:
            raw_exists = recording.raw_file.is_file()
        except OSError:
            raw_exists = False
        if not raw_exists:
            missing_files.append((recording.recording_id, recording.raw_file))
            continue
        discovered = discovered_by_path.get(
            recording.raw_file.resolve(strict=False)
        )
        if discovered is None:
            undiscovered_files.append(
                (recording.recording_id, recording.raw_file)
            )
            continue
        if discovered.recording_id != recording.recording_id:
            raise ValueError(
                f"Registered recording '{recording.recording_id}' was discovered "
                f"as '{discovered.recording_id}'. Repair the recording registry."
            )

    if missing_files:
        details = "; ".join(
            f"{recording_id}: {raw_file}"
            for recording_id, raw_file in sorted(
                missing_files,
                key=lambda item: item[0].casefold(),
            )
        )
        raise FileNotFoundError(
            "Registered recording has a missing raw .bdf file. Restore or "
            f"correct the registered path(s): {details}"
        )
    if undiscovered_files:
        details = "; ".join(
            f"{recording_id}: {raw_file}"
            for recording_id, raw_file in sorted(
                undiscovered_files,
                key=lambda item: item[0].casefold(),
            )
        )
        raise ValueError(
            "Registered recording raw file was not found by canonical source "
            f"discovery: {details}"
        )


def _validate_locked_assignment(project: "Project", info: RawFileInfo) -> None:
    if not bool(getattr(project, "groups_locked", False)):
        return
    participant_key, existing = _participant_record(project, info.subject_id)
    if participant_key is None:
        return
    existing_group = _participant_group_id(existing)
    if existing_group and info.group and existing_group != info.group:
        raise ValueError(
            "Participant "
            f"{participant_key} is registered in group '{existing_group}' but "
            f"the selected raw file is in group '{info.group}'. Restore the "
            "registered raw folder layout or create a new project and reprocess."
        )


def raw_file_info_for_path(project: "Project", file_path: Path) -> RawFileInfo:
    selected_path = Path(file_path).resolve()
    if selected_path.suffix.lower() != ".bdf":
        raise ValueError(f"Selected file is not a .bdf file: {selected_path}")

    recording_context = _recording_context(project)
    if recording_context.is_repeated_session:
        source = _recording_source_for_path(recording_context, selected_path)
        if source is None:
            raise ValueError(
                "Selected .bdf file is outside the registered recording-source "
                "folders for this repeated-session project."
            )
        info = _recording_info_for_source_path(
            recording_context,
            source,
            selected_path,
        )
        if bool(getattr(project, "groups_locked", False)):
            try:
                recording_context.recording_for_raw_path(selected_path)
            except RecordingConfigurationError as exc:
                raise ValueError(
                    "Processed project recording assignments are locked; the "
                    f"selected file is not registered: {selected_path}"
                ) from exc
        _validate_locked_assignment(project, info)
        return info

    groups = getattr(project, "groups", {}) or {}
    group_id: str | None = None
    if isinstance(groups, Mapping) and groups:
        group_id = _group_for_path(project, selected_path)
        if not group_id:
            raise ValueError(
                "Selected .bdf file is outside the registered raw folders for "
                "this multi-group project."
            )
    else:
        input_folder = Path(project.input_folder)
        if not _is_within_path(input_folder, selected_path):
            raise ValueError(
                "Selected .bdf file is outside this project's registered input folder."
            )

    info = RawFileInfo(
        path=selected_path,
        subject_id=_infer_subject_id(selected_path),
        group=group_id,
    )
    _validate_locked_assignment(project, info)
    return info


def discover_raw_files(project: "Project") -> List[RawFileInfo]:
    """
    Discover all .bdf files across the project's configured input folders.

    For multi-group projects, this walks every group-specific folder. For
    legacy projects, this is equivalent to scanning project.input_folder.
    """
    recording_context = _recording_context(project)
    if recording_context.is_repeated_session:
        return _discover_recording_files(project, recording_context)

    files: List[RawFileInfo] = []
    seen_subjects: Dict[str, RawFileInfo] = {}
    for group_name, folder in _iter_group_folders(project):
        folder_path = Path(folder)
        if not folder_path.is_dir():
            raise FileNotFoundError(
                "Registered raw input folder is missing or is not a directory: "
                f"{folder_path}. Restore the folder or update the project definition."
            )
        for candidate in sorted(folder_path.glob("*.bdf")):
            if not is_bdf_file(candidate):
                continue
            file_path = candidate.resolve()
            info = RawFileInfo(
                path=file_path,
                subject_id=_infer_subject_id(file_path),
                group=group_name,
            )
            subject_key = info.subject_id.casefold()
            if subject_key in seen_subjects:
                previous = seen_subjects[subject_key]
                raise ValueError(
                    "Duplicate participant ID detected: "
                    f"{info.subject_id}. Files '{previous.path}' and "
                    f"'{info.path}' infer the same participant ID. A project "
                    "cannot process more than one .bdf per participant in v2.1."
                )
            _validate_locked_assignment(project, info)
            seen_subjects[subject_key] = info
            files.append(info)
    _validate_known_raw_files(project, files)
    logger.debug(
        "discover_raw_files",
        extra={
            "project_root": str(getattr(project, "project_root", "")),
            "n_files": len(files),
            "groups": list({f.group for f in files}),
        },
    )
    return files


def _discover_recording_files(
    project: "Project",
    context: ProjectRecordingContext,
) -> List[RawFileInfo]:
    if not context.sessions:
        raise ValueError(
            "Repeated-session project has no declared sessions."
        )
    if not context.sources:
        raise ValueError(
            "Repeated-session project has no declared recording sources."
        )

    files: list[RawFileInfo] = []
    seen_recordings: dict[str, RawFileInfo] = {}
    seen_participant_sessions: dict[tuple[str, str], RawFileInfo] = {}
    participant_groups: dict[str, tuple[str, Path]] = {}
    registered_paths = {
        recording.raw_file.resolve(strict=False)
        for recording in context.recordings
    }
    for source in context.sources:
        folder_path = source.raw_input_folder
        if not folder_path.is_dir():
            raise FileNotFoundError(
                "Registered recording-source folder is missing or is not a "
                f"directory: {folder_path}. Restore it or update the project."
            )
        for candidate in sorted(folder_path.glob("*.bdf")):
            if not is_bdf_file(candidate):
                continue
            info = _recording_info_for_source_path(context, source, candidate)
            if (
                bool(getattr(project, "groups_locked", False))
                and info.path.resolve(strict=False) not in registered_paths
            ):
                raise ValueError(
                    "Processed project recording assignments are locked; an "
                    f"unregistered BDF was discovered: {info.path}"
                )
            recording_key = info.processing_id.casefold()
            participant_session_key = (
                info.subject_id.casefold(),
                str(info.session_id).casefold(),
            )
            if participant_session_key in seen_participant_sessions:
                previous = seen_participant_sessions[participant_session_key]
                raise ValueError(
                    f"Participant '{info.subject_id}' has more than one BDF for "
                    f"session '{info.session_id}': '{previous.path}' and "
                    f"'{info.path}'."
                )
            if recording_key in seen_recordings:
                previous = seen_recordings[recording_key]
                raise ValueError(
                    f"Duplicate recording ID '{info.processing_id}' detected for "
                    f"'{previous.path}' and '{info.path}'."
                )
            participant_key = info.subject_id.casefold()
            prior_group = participant_groups.get(participant_key)
            if prior_group is not None and prior_group[0] != info.group:
                raise ValueError(
                    f"Participant '{info.subject_id}' was discovered in stable "
                    f"group '{prior_group[0]}' at '{prior_group[1]}' and group "
                    f"'{info.group}' at '{info.path}'. Repeated sessions cannot "
                    "change between-participant group assignment."
                )
            participant_groups[participant_key] = (str(info.group), info.path)
            _validate_locked_assignment(project, info)
            seen_recordings[recording_key] = info
            seen_participant_sessions[participant_session_key] = info
            files.append(info)

    _validate_known_raw_files(project, files)
    logger.debug(
        "discover_raw_recordings",
        extra={
            "project_root": str(getattr(project, "project_root", "")),
            "n_recordings": len(files),
            "n_participants": len(participant_groups),
            "sessions": sorted(
                {str(info.session_id) for info in files},
                key=str.casefold,
            ),
        },
    )
    return files


def _group_for_path(project: "Project", file_path: Path) -> str | None:
    """
    Infer the group name for a manually selected file based on its parent folder.
    """
    file_resolved = file_path.resolve()
    for group_name, folder in _iter_group_folders(project):
        if not group_name:
            continue
        try:
            folder_resolved = Path(folder).resolve()
        except Exception:
            continue
        if folder_resolved == file_resolved.parent or folder_resolved in file_resolved.parents:
            return group_name
    return None


def participant_review_rows(
    project: "Project",
    files: Sequence[RawFileInfo],
) -> list[ParticipantReviewRow]:
    recording_context = _recording_context(project)
    if recording_context.is_repeated_session:
        return _recording_review_rows(project, files)

    rows: list[ParticipantReviewRow] = []
    for info in files:
        participant_id = info.subject_id.strip()
        if not participant_id:
            continue
        _participant_key, existing = _participant_record(project, participant_id)
        existing_group = _participant_group_id(existing)
        existing_raw_file = _participant_raw_file(project, existing)
        if existing is None:
            status = "New participant"
        elif info.group and existing_group != info.group:
            status = "Group assignment conflict"
        elif not _same_path(existing_raw_file, info.path):
            status = "Update raw file path"
        else:
            continue
        rows.append(
            ParticipantReviewRow(
                participant_id=participant_id,
                group_id=info.group,
                group_label=_group_label(project, info.group),
                raw_file=info.path,
                status=status,
            )
        )
    return rows


def _recording_review_rows(
    project: "Project",
    files: Sequence[RawFileInfo],
) -> list[ParticipantReviewRow]:
    rows: list[ParticipantReviewRow] = []
    for info in files:
        participant_id = info.subject_id.strip()
        recording_id = str(info.recording_id or "").strip()
        if not participant_id or not recording_id:
            continue
        participant_key, participant_entry = _participant_record(
            project,
            participant_id,
        )
        existing_group = _participant_group_id(participant_entry)
        recording_key, recording_entry = _recording_record(
            project,
            recording_id,
        )
        if participant_key is None:
            status = "New participant and recording"
        elif info.group and existing_group != info.group:
            status = "Stable group assignment conflict"
        elif recording_key is None:
            status = "New session recording"
        elif str(recording_entry.get("participant_id") or "").casefold() != (
            participant_id.casefold()
        ):
            status = "Recording participant conflict"
        elif str(recording_entry.get("session_id") or "").casefold() != str(
            info.session_id or ""
        ).casefold():
            status = "Recording session conflict"
        elif str(recording_entry.get("source_id") or "").casefold() != str(
            info.source_id or ""
        ).casefold():
            status = "Recording source conflict"
        elif not _same_path(
            _participant_raw_file(project, recording_entry),
            info.path,
        ):
            status = "Update recording raw file path"
        else:
            continue
        rows.append(
            ParticipantReviewRow(
                participant_id=participant_id,
                group_id=info.group,
                group_label=_group_label(project, info.group),
                raw_file=info.path,
                status=status,
                recording_id=recording_id,
                session_id=info.session_id,
                session_label=info.session_label,
                visit_index=info.visit_index,
            )
        )
    return rows


def _update_project_participants(project: "Project", files: Sequence[RawFileInfo]) -> bool:
    """
    Merge subject→group assignments from the given files into project.participants.

    Conflicting assignments hard-fail so no caller can silently preserve an
    ambiguous participant/group mapping.
    """
    if not files:
        return False
    if _recording_context(project).is_repeated_session:
        return _update_project_recordings(project, files)

    participants: Dict[str, Dict[str, Any]] = {}
    if isinstance(getattr(project, "participants", None), dict):
        participants = dict(project.participants)

    changed = False
    for info in files:
        group = info.group
        participant_id = info.subject_id.strip()
        if not participant_id:
            continue
        existing_key, existing = _participant_record(project, participant_id)
        participant_key = existing_key or participant_id
        existing_group = _participant_group_id(existing)
        if group and existing_group and existing_group != group:
            raise ValueError(
                f"Participant '{participant_key}' is already assigned to group "
                f"'{existing_group}' and cannot be registered to '{group}'."
            )
        existing_entry = dict(existing or {})
        existing_entry.pop("group", None)
        updated_entry = dict(existing_entry)
        if group:
            updated_entry["group_id"] = group
        elif not getattr(project, "groups", {}) and "group_id" in updated_entry:
            updated_entry.pop("group_id", None)
        updated_entry["raw_file"] = info.path
        if updated_entry != existing_entry:
            participants[participant_key] = updated_entry
            changed = True

    if changed:
        logger.info(
            "participants_updated",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "n_participants": len(participants),
            },
        )
        project.participants = participants
        project.save()
    return changed


def _case_insensitive_mapping_key(
    mapping: Mapping[str, object],
    requested: str,
) -> str | None:
    key = requested.casefold()
    for candidate in mapping:
        if str(candidate).casefold() == key:
            return str(candidate)
    return None


def _update_project_recordings(
    project: "Project",
    files: Sequence[RawFileInfo],
) -> bool:
    participants: dict[str, dict[str, Any]] = {
        str(key): dict(value) if isinstance(value, Mapping) else {}
        for key, value in (getattr(project, "participants", {}) or {}).items()
    }
    recordings: dict[str, dict[str, Any]] = {
        str(key): dict(value) if isinstance(value, Mapping) else {}
        for key, value in (getattr(project, "recordings", {}) or {}).items()
    }
    changed = False
    for info in files:
        participant_id = info.subject_id.strip()
        recording_id = str(info.recording_id or "").strip()
        session_id = str(info.session_id or "").strip()
        source_id = str(info.source_id or "").strip()
        if not participant_id or not recording_id or not session_id or not source_id:
            raise ValueError(
                f"Repeated-session raw file '{info.path}' is missing canonical "
                "participant, recording, session, or source identity."
            )

        participant_key = (
            _case_insensitive_mapping_key(participants, participant_id)
            or participant_id
        )
        participant_entry = dict(participants.get(participant_key, {}))
        existing_group = _participant_group_id(participant_entry)
        if info.group and existing_group and existing_group != info.group:
            raise ValueError(
                f"Participant '{participant_key}' is already assigned to stable "
                f"group '{existing_group}' and cannot register recording "
                f"'{recording_id}' from group '{info.group}'."
            )
        updated_participant = dict(participant_entry)
        updated_participant.pop("group", None)
        updated_participant.pop("raw_file", None)
        if info.group:
            updated_participant["group_id"] = info.group
        if updated_participant != participant_entry:
            participants[participant_key] = updated_participant
            changed = True

        recording_key = (
            _case_insensitive_mapping_key(recordings, recording_id)
            or recording_id
        )
        existing_recording = dict(recordings.get(recording_key, {}))
        updated_recording: dict[str, Any] = {
            "participant_id": participant_key,
            "session_id": session_id,
            "source_id": source_id,
            "raw_file": info.path,
            "visit_index": int(info.visit_index or 0),
        }
        if updated_recording["visit_index"] < 1:
            raise ValueError(
                f"Recording '{recording_id}' requires a positive visit_index."
            )
        if info.days_from_baseline is not None:
            updated_recording["days_from_baseline"] = float(
                info.days_from_baseline
            )
        if updated_recording != existing_recording:
            recordings[recording_key] = updated_recording
            changed = True

    if not changed:
        return False
    if bool(getattr(project, "groups_locked", False)):
        raise ValueError(
            "Processed project recording assignments are locked. Restore the "
            "registered raw files or create a new repeated-session project."
        )
    project.participants = participants
    project.recordings = recordings
    logger.info(
        "recordings_updated",
        extra={
            "project_root": str(getattr(project, "project_root", "")),
            "n_participants": len(participants),
            "n_recordings": len(recordings),
        },
    )
    project.save()
    return True


def register_participants(project: "Project", files: Sequence[RawFileInfo]) -> bool:
    """Persist reviewed participant raw-file assignments to project.json."""
    return _update_project_participants(project, files)


def prepare_batch_file_infos(project: "Project") -> List[RawFileInfo]:
    """
    Build the raw-file metadata list for batch processing without mutating project.json.

    - For multi-group projects (project.groups non-empty), this uses
      discover_raw_files(project) so that all configured group folders
      contribute their .bdf files.

    - For single-group projects, this scans
      project.input_folder directly, preserving the original behavior.

    This is the single source-of-truth used by the PySide6 GUI when
    constructing the data_files list for the performance runner.
    """
    infos = discover_raw_files(project)
    groups = getattr(project, "groups", {}) or {}
    if isinstance(groups, dict) and groups:
        logger.debug(
            "prepare_batch_files_multi_group",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "n_files": len(infos),
            },
        )
    else:
        logger.debug(
            "prepare_batch_files_single_group",
            extra={
                "project_root": str(getattr(project, "project_root", "")),
                "input_folder": str(getattr(project, "input_folder", "")),
                "n_files": len(infos),
            },
        )
    return infos


def prepare_batch_files(project: "Project") -> List[Path]:
    """Build the list of .bdf files for batch processing."""
    return [info.path for info in prepare_batch_file_infos(project)]


def _animate_progress_to(self, value: int) -> None:
    """Non-blocking progress animation helper."""
    try:
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(value)
        self._progress_anim.start()
    except Exception:
        # Progress animation is best-effort; do not fail the run over UI niceties.
        pass


def _settings_get(self, section: str, key: str, default=None):
    try:
        return self.settings.get(section, key, default)
    except Exception:
        return default


def _promote_refs_to_eeg(self, raw, ref1: str, ref2: str, filename: str) -> None:
    """If legacy loader demoted EXG refs to misc, coerce them back to EEG before referencing."""
    promote = {}
    for ch in (ref1, ref2):
        if ch in raw.ch_names:
            try:
                ctype = raw.get_channel_types(picks=[ch])[0]
            except Exception:
                ctype = None
            if ctype != "eeg":
                promote[ch] = "eeg"
    if promote:
        raw.set_channel_types(promote)
        self.log(f"[PROMOTE] {list(promote)} → EEG before referencing for {filename}")
        try:
            logger.debug(
                "promote_refs_to_eeg",
                extra={"file": filename, "promoted": list(promote)},
            )
        except Exception:
            logger.debug("promote_refs_to_eeg_logging_failed", extra={"file": filename})


def start_processing(self) -> None:
    """
    Run the pipeline on one or more .bdf files using the active preprocessing owner.
    Preserves the rest of the pipeline and adds structured audit logging.
    """
    try:
        project: Project = self.currentProject
        input_dir = raw_selection_start_folder(project)

        batch_mode = bool(getattr(self, "rb_batch", None) and self.rb_batch.isChecked())

        try:
            logger.info(
                "start_processing_begin",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "input_folder": str(input_dir),
                    "batch_mode": batch_mode,
                },
            )
        except Exception:
            logger.debug(
                "start_processing_begin_logging_failed",
                extra={"input_folder": str(input_dir)},
            )

        raw_file_infos: List[RawFileInfo]
        if batch_mode:
            raw_file_infos = discover_raw_files(project)
            if not raw_file_infos:
                raise FileNotFoundError(
                    "No .bdf files found in the configured input folders for this project."
                )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select .BDF File",
                str(input_dir),
                "BDF Files (*.bdf)",
            )
            if not file_path:
                self.log("No file selected, aborting.")
                logger.info(
                    "start_processing_no_file_selected",
                    extra={"input_folder": str(input_dir)},
                )
                return
            selected_path = Path(file_path)
            raw_file_infos = [raw_file_info_for_path(project, selected_path)]

        bdf_files = [info.path for info in raw_file_infos]

        try:
            logger.info(
                "start_processing_file_list",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "n_files": len(bdf_files),
                    "files": [str(p) for p in bdf_files],
                },
            )
        except Exception:
            logger.debug(
                "start_processing_file_list_logging_failed",
                extra={"n_files": len(bdf_files)},
            )

        _update_project_participants(project, raw_file_infos)

        # Preprocessing parameters with precedence: project → settings → defaults
        p = project.preprocessing or {}
        line_noise_settings = normalize_preprocessing_settings(
            {
                "line_noise_filter_enabled": p.get("line_noise_filter_enabled"),
                "line_noise_frequency_hz": p.get("line_noise_frequency_hz"),
            }
        )

        ref1 = (
            p.get("ref_channel1")
            or p.get("ref_chan1")
            or _settings_get(self, "preprocessing", "ref_channel1")
            or "EXG1"
        )
        ref2 = (
            p.get("ref_channel2")
            or p.get("ref_chan2")
            or _settings_get(self, "preprocessing", "ref_channel2")
            or "EXG2"
        )
        stim = (
            p.get("stim_channel")
            or _settings_get(self, "stim", "channel", "Status")
            or "Status"
        )

        params = {
            "downsample_rate": p.get("downsample"),
            "low_pass": p.get("low_pass"),
            "high_pass": p.get("high_pass"),
            "line_noise_filter_enabled": bool(
                line_noise_settings["line_noise_filter_enabled"]
            ),
            "line_noise_frequency_hz": int(
                line_noise_settings["line_noise_frequency_hz"]
            ),
            "reject_thresh": p.get("rejection_z"),
            "kurtosis_auto_interpolate_all": bool(p.get("kurtosis_auto_interpolate_all", False)),
            "ref_channel1": ref1,
            "ref_channel2": ref2,
            "max_idx_keep": p.get("max_chan_idx_keep"),
            "stim_channel": stim,
        }

        self.log(
            "Using Main App preprocessing: "
            "Main_App.processing.preprocess.perform_preprocessing"
        )
        logger.info(
            "Preproc route: Main_App.processing.preprocess with params=%s",
            {k: v for k, v in params.items() if k not in {"reject_thresh"}},
        )

        excluded_recording_files: list[str] = []

        for fp in bdf_files:
            try:
                logger.info(
                    "start_processing_file_begin",
                    extra={
                        "file": str(fp),
                        "project_root": str(getattr(project, "project_root", "")),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_begin_logging_failed",
                    extra={"file": str(fp)},
                )

            # Load
            self.log(f"Loading EEG file: {fp.name}")
            preflight = inspect_bdf_header(fp)
            if preflight and preflight.recording_not_started:
                excluded_recording_files.append(fp.name)
                logger.warning(
                    "start_processing_file_excluded file=%s reason=recording_not_started size=%s header_bytes=%s",
                    fp,
                    preflight.file_size,
                    preflight.header_bytes,
                )
                continue

            raw = load_eeg_file(self, str(fp))
            if raw is None:
                self.log(
                    f"Skipping file {fp.name} because it could not be loaded.",
                    level=logging.WARNING,
                )
                logger.warning("start_processing_file_load_skipped file=%s", fp)
                continue

            # Ensure reference channels are EEG before referencing
            _promote_refs_to_eeg(self, raw, ref1, ref2, fp.name)

            # Preprocess (single pass) with audit
            audit_before = begin_preproc_audit(raw, params, fp.name)
            processed_raw, n_bad = perform_preprocessing(raw, params, self.log, fp.name)
            raw = processed_raw or raw
            finalize_preproc_audit(
                audit_before,
                raw,
                params,
                fp.name,
                events_info=None,
                fif_written=0,
                n_rejected=int(n_bad or 0),
            )

            try:
                logger.info(
                    "start_processing_file_preproc_done",
                    extra={
                        "file": str(fp),
                        "n_bad_kurtosis": int(n_bad or 0),
                        "n_channels": len(getattr(raw.info, "ch_names", [])),
                        "sfreq": float(raw.info.get("sfreq", -1.0)),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_preproc_done_logging_failed",
                    extra={"file": str(fp)},
                )

            # Main processing and post-processing
            out_dir = str(
                self.currentProject.project_root
                / self.currentProject.subfolders["excel"]
            )
            self.log("Running main processing")
            logger.debug(
                "start_processing_call_process_data",
                extra={"file": str(fp), "out_dir": out_dir},
            )
            process_data(raw, out_dir)

            condition_labels = list(self.currentProject.event_map.keys())
            self.log(f"Post-process condition labels: {condition_labels}")
            logger.debug(
                "start_processing_call_post_process",
                extra={"file": str(fp), "condition_labels": condition_labels},
            )
            post_process(self, condition_labels)

            try:
                logger.info(
                    "start_processing_file_done",
                    extra={
                        "file": str(fp),
                        "n_condition_labels": len(condition_labels),
                    },
                )
            except Exception:
                logger.debug(
                    "start_processing_file_done_logging_failed",
                    extra={"file": str(fp)},
                )

        _animate_progress_to(self, 100)
        if excluded_recording_files:
            self.log(
                format_bdf_recording_not_started_message(excluded_recording_files),
                level=logging.WARNING,
            )
        self.log("Processing complete")
        try:
            logger.info(
                "start_processing_complete",
                extra={
                    "project_root": str(getattr(project, "project_root", "")),
                    "n_files": len(bdf_files),
                },
            )
        except Exception:
            logger.debug(
                "start_processing_complete_logging_failed",
                extra={"n_files": len(bdf_files)},
            )

    except Exception as e:
        self.log(f"Processing failed: {e}", level=logging.ERROR)
        try:
            logger.exception(
                "start_processing_failed",
                extra={
                    "project_root": str(
                        getattr(getattr(self, "currentProject", None), "project_root", "")
                    ),
                },
            )
        except Exception:
            logger.debug("start_processing_failed_logging_failed")
        try:
            QMessageBox.critical(self, "Processing Error", str(e))
        except Exception:
            # If the GUI is in a bad state, we still want the log message.
            pass
