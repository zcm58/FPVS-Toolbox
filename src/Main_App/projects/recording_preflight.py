"""Read-only source audit and manifest preview for repeated-session projects."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from Main_App.Shared.file_filters import is_bdf_file

from .raw_identity import infer_raw_participant_id
from .recordings import ProjectRecordingContext


class RecordingPreflightCancelled(RuntimeError):
    """Raised when a repeated-source audit receives a cancellation request."""


@dataclass(frozen=True, slots=True)
class RecordingPreflightRow:
    """Canonical identity proposed for one directly owned BDF recording."""

    participant_id: str
    recording_id: str
    group_id: str
    session_id: str
    visit_index: int
    source_id: str
    raw_file: Path


@dataclass(frozen=True, slots=True)
class RecordingPreflightIssue:
    """One actionable source-layout or identity finding."""

    severity: str
    code: str
    message: str
    paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordingPreflightReport:
    """Complete dry-run result without project or raw-data mutation."""

    rows: tuple[RecordingPreflightRow, ...]
    issues: tuple[RecordingPreflightIssue, ...]
    declared_group_ids: tuple[str, ...]
    declared_session_ids: tuple[str, ...]

    @property
    def errors(self) -> tuple[RecordingPreflightIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[RecordingPreflightIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def is_blocked(self) -> bool:
        return bool(self.errors)

    @property
    def participant_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({row.participant_id for row in self.rows}, key=str.casefold)
        )

    @property
    def n_complete_participants(self) -> int:
        required = {session.casefold() for session in self.declared_session_ids}
        observed: dict[str, set[str]] = defaultdict(set)
        groups: dict[str, set[str]] = defaultdict(set)
        session_counts: dict[tuple[str, str], int] = defaultdict(int)
        for row in self.rows:
            participant_key = row.participant_id.casefold()
            session_key = row.session_id.casefold()
            observed[participant_key].add(session_key)
            groups[participant_key].add(row.group_id.casefold())
            session_counts[(participant_key, session_key)] += 1
        return sum(
            sessions == required
            and len(groups[participant_key]) == 1
            and all(
                session_counts[(participant_key, session_key)] == 1
                for session_key in required
            )
            for participant_key, sessions in observed.items()
        )

    def participants_manifest(self) -> dict[str, dict[str, object]]:
        """Build stable participant/group rows when the preflight is unambiguous."""

        if self.is_blocked:
            raise ValueError("Blocked recording preflight cannot populate participants.")
        result: dict[str, dict[str, object]] = {}
        for row in self.rows:
            result.setdefault(row.participant_id, {"group_id": row.group_id})
        return result

    def recordings_manifest(self) -> dict[str, dict[str, object]]:
        """Build recording rows when the preflight is unambiguous."""

        if self.is_blocked:
            raise ValueError("Blocked recording preflight cannot populate recordings.")
        return {
            row.recording_id: {
                "participant_id": row.participant_id,
                "session_id": row.session_id,
                "source_id": row.source_id,
                "raw_file": row.raw_file,
                "visit_index": row.visit_index,
            }
            for row in self.rows
        }

    def summary_text(self, *, max_issues: int = 12) -> str:
        status = "BLOCKED" if self.is_blocked else "READY"
        lines = [
            f"Repeated-session source preflight: {status}",
            (
                f"{len(self.rows)} recordings; {len(self.participant_ids)} participants; "
                f"{self.n_complete_participants} unambiguous complete across all "
                f"{len(self.declared_session_ids)} sessions."
            ),
        ]
        if self.issues:
            lines.append("")
            for issue in self.issues[:max_issues]:
                lines.append(f"[{issue.severity.upper()}] {issue.message}")
            remaining = len(self.issues) - max_issues
            if remaining > 0:
                lines.append(f"…and {remaining} more finding(s).")
        return "\n".join(lines)


def _normalized_tokens(
    values: Iterable[object] | object,
) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        values = (values,)
    return frozenset(
        str(value).strip().casefold()
        for value in values
        if str(value).strip()
    )


def _filename_tokens(path: Path) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+", path.stem)
        if token
    )


def _recognized_filename_ids(
    path: Path,
    rules: Mapping[str, Iterable[object]] | None,
) -> set[str]:
    if not rules:
        return set()
    tokens = _filename_tokens(path)
    return {
        identifier
        for identifier, aliases in rules.items()
        if tokens & _normalized_tokens(aliases)
    }


def derive_filename_token_rules(
    identity_labels: Mapping[str, Iterable[object] | object],
) -> dict[str, tuple[str, ...]]:
    """Derive conservative unique filename tokens from IDs and display labels.

    Only tokens owned by one declared identity are retained. Prefix initials
    make common study abbreviations such as ``Birth Control Group -> BC`` and
    ``Follicular Phase -> F`` available to the optional filename/source audit.
    """

    candidates: dict[str, set[str]] = {}
    owners: dict[str, set[str]] = defaultdict(set)
    for identifier, raw_labels in identity_labels.items():
        values = (
            (raw_labels,)
            if isinstance(raw_labels, (str, bytes))
            else tuple(raw_labels)
        )
        aliases: set[str] = set()
        for value in (identifier, *values):
            words = tuple(
                token.casefold()
                for token in re.findall(r"[A-Za-z0-9]+", str(value))
                if token
            )
            aliases.update(words)
            aliases.update(
                "".join(word[0] for word in words[:length])
                for length in range(1, len(words) + 1)
            )
        aliases.discard("")
        candidates[identifier] = aliases
        for alias in aliases:
            owners[alias].add(identifier)
    return {
        identifier: tuple(
            sorted(
                (
                    alias
                    for alias in aliases
                    if len(owners[alias]) == 1
                ),
                key=lambda value: (-len(value), value),
            )
        )
        for identifier, aliases in candidates.items()
    }


def preflight_repeated_recording_sources(
    context: ProjectRecordingContext,
    *,
    group_filename_tokens: Mapping[str, Iterable[object]] | None = None,
    session_filename_tokens: Mapping[str, Iterable[object]] | None = None,
    require_nonempty_cells: bool = True,
    cancel_requested: Callable[[], bool] | None = None,
    discovered_source_files: Mapping[str, Iterable[str | Path]] | None = None,
) -> RecordingPreflightReport:
    """Audit BDF identity and pairing using canonical source ownership only.

    Filename token rules are optional diagnostics. They never assign group or
    session membership; canonical source metadata remains the sole owner.

    ``discovered_source_files`` is a GUI-safe adapter for callers that already
    performed canonical direct-child discovery. When supplied, the same
    identity, cell-coverage, filename-token, and pairing checks run without a
    second directory walk. Nested-file detection remains the responsibility of
    the source-scanning route; direct-child processing discovery intentionally
    ignores nested BDF files.
    """

    if not context.is_repeated_session or not context.sessions or not context.sources:
        raise ValueError(
            "Repeated recording preflight requires declared sessions and sources."
        )
    sessions = tuple(
        sorted(
            context.sessions,
            key=lambda session: (session.visit_index, session.session_id.casefold()),
        )
    )
    session_by_id = {session.session_id.casefold(): session for session in sessions}
    group_ids = tuple(group.group_id for group in context.groups)
    issues: list[RecordingPreflightIssue] = []
    rows: list[RecordingPreflightRow] = []
    supplied_files = (
        {
            str(source_id).casefold(): tuple(Path(path) for path in paths)
            for source_id, paths in discovered_source_files.items()
        }
        if discovered_source_files is not None
        else None
    )

    def check_cancelled() -> None:
        if cancel_requested is not None and cancel_requested():
            raise RecordingPreflightCancelled(
                "Repeated-session source preflight was cancelled."
            )

    for source in context.sources:
        check_cancelled()
        folder = source.raw_input_folder.resolve(strict=False)
        if supplied_files is None:
            if not folder.is_dir():
                issues.append(
                    RecordingPreflightIssue(
                        "error",
                        "missing_source_folder",
                        f"Source '{source.source_id}' folder is missing: {folder}",
                        (folder,),
                    )
                )
                continue
            direct_candidates: list[Path] = []
            for candidate in folder.iterdir():
                check_cancelled()
                if candidate.is_file() and is_bdf_file(candidate):
                    direct_candidates.append(candidate.resolve(strict=False))
            direct_files = tuple(
                sorted(direct_candidates, key=lambda path: path.name.casefold())
            )
            nested_candidates: list[Path] = []
            for candidate in folder.rglob("*"):
                check_cancelled()
                if (
                    candidate.is_file()
                    and candidate.parent != folder
                    and is_bdf_file(candidate)
                ):
                    nested_candidates.append(candidate.resolve(strict=False))
            nested_files = tuple(
                sorted(nested_candidates, key=lambda path: str(path).casefold())
            )
            if nested_files:
                issues.append(
                    RecordingPreflightIssue(
                        "error",
                        "nested_bdf_files",
                        f"Source '{source.source_id}' contains nested BDF files; "
                        "recordings must be direct children of the registered source folder.",
                        nested_files,
                    )
                )
        else:
            direct_files = tuple(
                sorted(
                    (
                        path.resolve(strict=False)
                        for path in supplied_files.get(
                            source.source_id.casefold(),
                            (),
                        )
                    ),
                    key=lambda path: path.name.casefold(),
                )
            )
        if require_nonempty_cells and not direct_files:
            issues.append(
                RecordingPreflightIssue(
                    "error",
                    "empty_source_cell",
                    f"Group/session source '{source.group_id}/{source.session_id}' "
                    "contains no direct BDF files.",
                    (folder,),
                )
            )
        session = session_by_id[source.session_id.casefold()]
        for path in direct_files:
            check_cancelled()
            participant_id = infer_raw_participant_id(path)
            recording_id = f"{participant_id}__{session.session_id}"
            rows.append(
                RecordingPreflightRow(
                    participant_id=participant_id,
                    recording_id=recording_id,
                    group_id=source.group_id,
                    session_id=session.session_id,
                    visit_index=session.visit_index,
                    source_id=source.source_id,
                    raw_file=path,
                )
            )
            recognized_groups = _recognized_filename_ids(
                path,
                group_filename_tokens,
            )
            if recognized_groups and recognized_groups != {source.group_id}:
                issues.append(
                    RecordingPreflightIssue(
                        "error",
                        "filename_group_token_conflict",
                        f"Filename '{path.name}' indicates group token(s) "
                        f"{sorted(recognized_groups)}, but its canonical source is "
                        f"group '{source.group_id}'.",
                        (path,),
                    )
                )
            recognized_sessions = _recognized_filename_ids(
                path,
                session_filename_tokens,
            )
            if recognized_sessions and recognized_sessions != {session.session_id}:
                issues.append(
                    RecordingPreflightIssue(
                        "error",
                        "filename_session_token_conflict",
                        f"Filename '{path.name}' indicates session token(s) "
                        f"{sorted(recognized_sessions)}, but its canonical source is "
                        f"session '{session.session_id}'.",
                        (path,),
                    )
                )

    by_participant_session: dict[tuple[str, str], list[RecordingPreflightRow]] = defaultdict(list)
    groups_by_participant: dict[str, dict[str, list[Path]]] = defaultdict(
        lambda: defaultdict(list)
    )
    recording_ids: dict[str, list[RecordingPreflightRow]] = defaultdict(list)
    for row in rows:
        check_cancelled()
        participant_key = row.participant_id.casefold()
        by_participant_session[(participant_key, row.session_id.casefold())].append(row)
        groups_by_participant[participant_key][row.group_id].append(row.raw_file)
        recording_ids[row.recording_id.casefold()].append(row)

    for (participant_key, session_key), matches in by_participant_session.items():
        check_cancelled()
        if len(matches) > 1:
            issues.append(
                RecordingPreflightIssue(
                    "error",
                    "duplicate_participant_session",
                    f"Participant '{matches[0].participant_id}' has {len(matches)} BDF "
                    f"files for session '{matches[0].session_id}'.",
                    tuple(row.raw_file for row in matches),
                )
            )
    for participant_key, group_paths in groups_by_participant.items():
        check_cancelled()
        if len(group_paths) > 1:
            participant = next(
                row.participant_id
                for row in rows
                if row.participant_id.casefold() == participant_key
            )
            issues.append(
                RecordingPreflightIssue(
                    "error",
                    "unstable_participant_group",
                    f"Participant '{participant}' appears in multiple stable groups: "
                    f"{', '.join(sorted(group_paths, key=str.casefold))}.",
                    tuple(path for paths in group_paths.values() for path in paths),
                )
            )
    for matches in recording_ids.values():
        check_cancelled()
        if len(matches) > 1:
            issues.append(
                RecordingPreflightIssue(
                    "error",
                    "duplicate_recording_id",
                    f"Recording ID '{matches[0].recording_id}' resolves from more "
                    "than one BDF file.",
                    tuple(row.raw_file for row in matches),
                )
            )

    required_sessions = {session.session_id.casefold() for session in sessions}
    sessions_by_participant: dict[str, set[str]] = defaultdict(set)
    display_by_participant: dict[str, str] = {}
    for row in rows:
        check_cancelled()
        key = row.participant_id.casefold()
        display_by_participant.setdefault(key, row.participant_id)
        sessions_by_participant[key].add(row.session_id.casefold())
    for key, observed in sessions_by_participant.items():
        check_cancelled()
        missing = required_sessions - observed
        if missing:
            missing_display = [
                session.session_id
                for session in sessions
                if session.session_id.casefold() in missing
            ]
            issues.append(
                RecordingPreflightIssue(
                    "warning",
                    "incomplete_recording_pair",
                    f"Participant '{display_by_participant[key]}' is missing session(s): "
                    f"{', '.join(missing_display)}.",
                    tuple(
                        row.raw_file
                        for row in rows
                        if row.participant_id.casefold() == key
                    ),
                )
            )

    ordered_rows = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.participant_id.casefold(),
                row.visit_index,
                row.raw_file.name.casefold(),
            ),
        )
    )
    ordered_issues = tuple(
        sorted(
            issues,
            key=lambda issue: (
                0 if issue.severity == "error" else 1,
                issue.code,
                issue.message.casefold(),
            ),
        )
    )
    return RecordingPreflightReport(
        rows=ordered_rows,
        issues=ordered_issues,
        declared_group_ids=group_ids,
        declared_session_ids=tuple(session.session_id for session in sessions),
    )


__all__ = [
    "RecordingPreflightIssue",
    "RecordingPreflightReport",
    "RecordingPreflightRow",
    "RecordingPreflightCancelled",
    "derive_filename_token_rules",
    "preflight_repeated_recording_sources",
]
