"""Pure repeated-session control state for the SNR Plot Generator."""

from __future__ import annotations

from dataclasses import dataclass

from Main_App.projects import ProjectDatasetIndex


SESSION_MODE_CONDITION = "condition"
SESSION_MODE_COMPARISON = "session_comparison"
FIXED_ORDER_CAVEAT = (
    "Descriptive view only: phase is confounded with visit order and elapsed time "
    "because every participant completed the sessions in the same order."
)


class RepeatedSessionControlError(ValueError):
    """Raised when a repeated project cannot be selected without guessing identity."""


@dataclass(frozen=True, slots=True)
class SessionChoice:
    """One canonical session option shown to the user."""

    session_id: str
    label: str
    visit_index: int

    @property
    def display_label(self) -> str:
        return f"{self.label} — Visit {self.visit_index}"


@dataclass(frozen=True, slots=True)
class RepeatedSessionControlState:
    """GUI-neutral repeated-session selector state."""

    repeated: bool
    sessions: tuple[SessionChoice, ...] = ()
    caveat: str = ""

    @property
    def default_mode(self) -> str:
        return SESSION_MODE_COMPARISON if self.repeated else SESSION_MODE_CONDITION

    def validate_selection(
        self,
        *,
        mode: str,
        single_session_id: str = "",
        reference_session_id: str = "",
        comparison_session_id: str = "",
    ) -> tuple[str, ...]:
        """Return canonical session IDs for one valid UI selection."""

        if not self.repeated:
            return ()
        known = {choice.session_id.casefold(): choice.session_id for choice in self.sessions}
        if mode == SESSION_MODE_CONDITION:
            key = str(single_session_id).strip().casefold()
            if key not in known:
                raise RepeatedSessionControlError(
                    "Choose one canonical session for the condition plot."
                )
            return (known[key],)
        if mode != SESSION_MODE_COMPARISON:
            raise RepeatedSessionControlError("Unknown repeated-session plot mode.")
        reference_key = str(reference_session_id).strip().casefold()
        comparison_key = str(comparison_session_id).strip().casefold()
        if reference_key not in known or comparison_key not in known:
            raise RepeatedSessionControlError(
                "Choose canonical reference and comparison sessions."
            )
        if reference_key == comparison_key:
            raise RepeatedSessionControlError(
                "Reference and comparison sessions must be different."
            )
        return known[reference_key], known[comparison_key]


def repeated_session_control_state(
    index: ProjectDatasetIndex,
) -> RepeatedSessionControlState:
    """Build selector state, failing instead of inferring missing identity."""

    if not index.is_repeated_session:
        return RepeatedSessionControlState(repeated=False)
    sessions = tuple(
        SessionChoice(
            session_id=session.session_id,
            label=session.label,
            visit_index=session.visit_index,
        )
        for session in index.ordered_sessions
    )
    if len(sessions) < 2:
        raise RepeatedSessionControlError(
            "Repeated-session SNR plots require at least two declared sessions."
        )
    session_by_id = {choice.session_id.casefold(): choice for choice in sessions}
    participant_groups: dict[str, str] = {}
    seen: set[tuple[str, str, str]] = set()
    for record in index.workbooks:
        missing = [
            field
            for field in ("recording_id", "session_id", "session_label", "visit_index")
            if getattr(record, field, None) in (None, "")
        ]
        if record.group_id in (None, ""):
            missing.append("group_id")
        if missing:
            raise RepeatedSessionControlError(
                "Repeated-session SNR plots require canonical "
                + ", ".join(missing)
                + f" for {record.path}."
            )
        session = session_by_id.get(str(record.session_id).casefold())
        if session is None:
            raise RepeatedSessionControlError(
                f"Workbook session_id {record.session_id!r} is not declared by the project."
            )
        if (
            str(record.session_label) != session.label
            or int(record.visit_index) != session.visit_index
        ):
            raise RepeatedSessionControlError(
                f"Workbook session metadata changed for {record.session_id!r}; reopen the project."
            )
        participant_key = record.participant_id.casefold()
        prior_group = participant_groups.setdefault(participant_key, str(record.group_id))
        if prior_group.casefold() != str(record.group_id).casefold():
            raise RepeatedSessionControlError(
                f"Participant {record.participant_id!r} changes group between sessions."
            )
        identity = (
            participant_key,
            record.condition.casefold(),
            str(record.session_id).casefold(),
        )
        if identity in seen:
            raise RepeatedSessionControlError(
                f"Participant {record.participant_id!r} has duplicate workbooks for "
                f"{record.condition!r} and session {record.session_id!r}."
            )
        seen.add(identity)
    return RepeatedSessionControlState(
        repeated=True,
        sessions=sessions,
        caveat=FIXED_ORDER_CAVEAT,
    )


__all__ = [
    "FIXED_ORDER_CAVEAT",
    "RepeatedSessionControlError",
    "RepeatedSessionControlState",
    "SESSION_MODE_COMPARISON",
    "SESSION_MODE_CONDITION",
    "SessionChoice",
    "repeated_session_control_state",
]
