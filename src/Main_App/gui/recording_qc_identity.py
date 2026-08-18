"""GUI-neutral recording identity and visit-coverage rows for QC surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from Main_App.projects.recordings import (
    ProjectRecordingContext,
    project_recording_context,
)


@dataclass(frozen=True, slots=True)
class QcRecordingIdentity:
    """One participant/session coverage row shown by recording-aware QC editors."""

    participant_id: str
    group_id: str | None
    group_label: str
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None
    source_file: Path | None = None
    coverage_status: str = "Available"

    @property
    def identity_id(self) -> str:
        """Return the recording key, with the legacy participant fallback."""

        return self.recording_id or self.participant_id

    @property
    def is_missing_visit(self) -> bool:
        return self.recording_id is None and self.session_id is not None


def build_recording_coverage_rows(
    context: ProjectRecordingContext,
    raw_file_infos: Sequence[Any] = (),
) -> tuple[QcRecordingIdentity, ...]:
    """Return declared participant × session coverage without fabricating visits."""

    if not context.is_repeated_session:
        return ()

    group_labels = {group.group_id.casefold(): group.label for group in context.groups}
    participant_groups = {
        participant.participant_id.casefold(): participant.group_id
        for participant in context.participants
    }
    participant_casing = {
        participant.participant_id.casefold(): participant.participant_id
        for participant in context.participants
    }
    recording_by_cell = {
        (recording.participant_id.casefold(), recording.session_id.casefold()): recording
        for recording in context.recordings
    }
    raw_by_recording: dict[str, Any] = {}
    for info in raw_file_infos:
        participant_id = str(getattr(info, "subject_id", "") or "").strip()
        if not participant_id:
            continue
        participant_key = participant_id.casefold()
        participant_casing.setdefault(participant_key, participant_id)
        group_id = str(getattr(info, "group", "") or "").strip()
        if group_id:
            participant_groups.setdefault(participant_key, group_id)
        recording_id = str(getattr(info, "recording_id", "") or "").strip()
        session_id = str(getattr(info, "session_id", "") or "").strip()
        if recording_id:
            raw_by_recording[recording_id.casefold()] = info
        if recording_id and session_id:
            recording_by_cell.setdefault(
                (participant_key, session_id.casefold()),
                info,
            )

    for recording in context.recordings:
        participant_casing.setdefault(
            recording.participant_id.casefold(),
            recording.participant_id,
        )

    sessions = tuple(
        sorted(
            context.sessions,
            key=lambda session: (session.visit_index, session.session_id.casefold()),
        )
    )
    rows: list[QcRecordingIdentity] = []
    for participant_key, participant_id in sorted(
        participant_casing.items(),
        key=lambda item: _participant_sort_key(item[1]),
    ):
        group_id = participant_groups.get(participant_key)
        group_label = (
            group_labels.get(str(group_id or "").casefold())
            or group_id
            or "Single group"
        )
        for session in sessions:
            cell_value = recording_by_cell.get(
                (participant_key, session.session_id.casefold())
            )
            recording_id = str(
                getattr(cell_value, "recording_id", "") or ""
            ).strip()
            raw_info = raw_by_recording.get(recording_id.casefold()) if recording_id else None
            source_value = (
                getattr(raw_info, "path", None)
                if raw_info is not None
                else getattr(cell_value, "raw_file", None)
            )
            source_file = Path(source_value) if source_value not in (None, "") else None
            rows.append(
                QcRecordingIdentity(
                    participant_id=participant_id,
                    group_id=group_id,
                    group_label=str(group_label),
                    recording_id=recording_id or None,
                    session_id=session.session_id,
                    session_label=session.label,
                    visit_index=session.visit_index,
                    source_file=source_file,
                    coverage_status=(
                        "Available" if recording_id else "Missing / not registered"
                    ),
                )
            )
    return tuple(rows)


def project_recording_coverage_rows(
    project: Any,
    raw_file_infos: Sequence[Any] = (),
) -> tuple[QcRecordingIdentity, ...]:
    """Build recording coverage from the canonical active project context."""

    return build_recording_coverage_rows(
        project_recording_context(project),
        raw_file_infos,
    )


def _participant_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in value if not ch.isdigit()).casefold()
    digits = "".join(ch for ch in value if ch.isdigit())
    number = int(digits) if digits else -1
    return prefix, number, value.casefold()


__all__ = [
    "QcRecordingIdentity",
    "build_recording_coverage_rows",
    "project_recording_coverage_rows",
]
