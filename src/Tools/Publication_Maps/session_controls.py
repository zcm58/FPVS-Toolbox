"""GUI-neutral repeated-session controls for publication scalp maps."""

from __future__ import annotations

from dataclasses import dataclass

from Main_App.projects import ProjectDatasetIndex


SESSION_MODE_CONDITION = "condition"
SESSION_MODE_COMPARISON = "session_comparison"
class PublicationSessionControlError(ValueError):
    """Raised when canonical repeated-session selections are incomplete."""


@dataclass(frozen=True, slots=True)
class PublicationSessionChoice:
    session_id: str
    label: str
    visit_index: int

    @property
    def display_label(self) -> str:
        return f"{self.label} — Visit {self.visit_index}"


@dataclass(frozen=True, slots=True)
class PublicationSessionState:
    repeated: bool
    sessions: tuple[PublicationSessionChoice, ...] = ()

    @property
    def default_mode(self) -> str:
        return SESSION_MODE_COMPARISON if self.repeated else SESSION_MODE_CONDITION

    def selected_ids(
        self,
        *,
        mode: str,
        single_session_id: str = "",
        reference_session_id: str = "",
        comparison_session_id: str = "",
    ) -> tuple[str, ...]:
        if not self.repeated:
            return ()
        known = {choice.session_id.casefold(): choice.session_id for choice in self.sessions}
        if mode == SESSION_MODE_CONDITION:
            key = str(single_session_id).strip().casefold()
            if key not in known:
                raise PublicationSessionControlError(
                    "Choose one canonical session for the condition maps."
                )
            return (known[key],)
        if mode != SESSION_MODE_COMPARISON:
            raise PublicationSessionControlError("Unknown Scalp Maps comparison mode.")
        reference = str(reference_session_id).strip().casefold()
        comparison = str(comparison_session_id).strip().casefold()
        if reference not in known or comparison not in known:
            raise PublicationSessionControlError(
                "Choose canonical reference and comparison sessions."
            )
        if reference == comparison:
            raise PublicationSessionControlError(
                "Reference and comparison sessions must be different."
            )
        return known[reference], known[comparison]


def publication_session_state(index: ProjectDatasetIndex) -> PublicationSessionState:
    """Return repeated-session choices and reject identity gaps."""

    if not index.is_repeated_session:
        return PublicationSessionState(repeated=False)
    sessions = tuple(
        PublicationSessionChoice(
            session_id=session.session_id,
            label=session.label,
            visit_index=session.visit_index,
        )
        for session in index.ordered_sessions
    )
    if len(sessions) < 2:
        raise PublicationSessionControlError(
            "Repeated-session Scalp Maps requires at least two declared sessions."
        )
    known = {session.session_id.casefold(): session for session in sessions}
    stable_groups: dict[str, str] = {}
    seen: set[tuple[str, str, str]] = set()
    for record in index.workbooks:
        missing = [
            field
            for field in (
                "recording_id",
                "session_id",
                "session_label",
                "visit_index",
                "group_id",
            )
            if getattr(record, field, None) in (None, "")
        ]
        if missing:
            raise PublicationSessionControlError(
                "Repeated-session Scalp Maps requires canonical "
                + ", ".join(missing)
                + f" for {record.path}."
            )
        session = known.get(str(record.session_id).casefold())
        if session is None:
            raise PublicationSessionControlError(
                f"Workbook session_id {record.session_id!r} is not declared."
            )
        if (
            str(record.session_label) != session.label
            or int(record.visit_index) != session.visit_index
        ):
            raise PublicationSessionControlError(
                f"Workbook session metadata changed for {record.session_id!r}."
            )
        participant_key = record.participant_id.casefold()
        previous = stable_groups.setdefault(participant_key, str(record.group_id))
        if previous.casefold() != str(record.group_id).casefold():
            raise PublicationSessionControlError(
                f"Participant {record.participant_id!r} changes group between sessions."
            )
        identity = (
            participant_key,
            record.condition.casefold(),
            str(record.session_id).casefold(),
        )
        if identity in seen:
            raise PublicationSessionControlError(
                f"Participant {record.participant_id!r} has duplicate workbooks for "
                f"{record.condition!r} and session {record.session_id!r}."
            )
        seen.add(identity)
    return PublicationSessionState(repeated=True, sessions=sessions)


__all__ = [
    "PublicationSessionChoice",
    "PublicationSessionControlError",
    "PublicationSessionState",
    "SESSION_MODE_COMPARISON",
    "SESSION_MODE_CONDITION",
    "publication_session_state",
]
