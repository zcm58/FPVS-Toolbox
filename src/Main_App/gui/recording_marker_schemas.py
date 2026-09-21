"""GUI-neutral canonical recording choices and explicit trigger-schema checks."""

from __future__ import annotations

from dataclasses import dataclass

from Main_App.projects import FrequencyProtocolError, project_recording_context
from .recording_qc_identity import participant_sort_key


@dataclass(frozen=True, slots=True)
class RecordingMarkerIdentity:
    recording_id: str
    label: str


def recording_marker_editor_rows(project) -> tuple[RecordingMarkerIdentity, ...]:
    """Use registered recordings, or canonical participants for flat projects."""

    context = project_recording_context(project)
    if context.is_repeated_session:
        session_labels = {row.session_id: row.label for row in context.sessions}
        return tuple(
            RecordingMarkerIdentity(row.recording_id, f"{row.participant_id} · {session_labels[row.session_id]}")
            for row in sorted(context.recordings, key=lambda item: (participant_sort_key(item.participant_id), item.visit_index, item.recording_id))
        )
    return tuple(
        RecordingMarkerIdentity(row.participant_id, row.participant_id)
        for row in sorted(context.participants, key=lambda item: participant_sort_key(item.participant_id))
    )


def validate_recording_marker_assignments(identities, assignments) -> None:
    """New or unknown recordings require explicit review, never a fallback."""

    expected = {row.recording_id.casefold() for row in identities}
    supplied = {str(recording_id).casefold() for recording_id, _codes in assignments}
    if not expected:
        raise FrequencyProtocolError("Register the project recordings before configuring their trigger schemas.")
    if expected != supplied:
        missing = [row.recording_id for row in identities if row.recording_id.casefold() not in supplied]
        unknown = [recording_id for recording_id, _ in assignments if str(recording_id).casefold() not in expected]
        details = []
        if missing:
            details.append("Not configured: " + _identity_summary(missing))
        if unknown:
            details.append("No longer registered: " + _identity_summary(unknown))
        raise FrequencyProtocolError("Review recording-specific trigger schemas. " + "; ".join(details))


def _identity_summary(values) -> str:
    return ", ".join(str(value) for value in values[:6]) + (f" (+{len(values) - 6} more)" if len(values) > 6 else "")
