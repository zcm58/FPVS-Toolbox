"""Read-only processed-workbook discovery for project-aware tools.

This module owns workbook identity, condition discovery, participant matching,
and canonical project-group assignment.  Downstream tools may adapt these
records for their own calculations, but must not infer group identity from
generated output folders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from Main_App.Shared.file_filters import is_excel_workbook_file
from Main_App.io.result_manifest import RESULT_MANIFEST_SUFFIX, resolve_result_path

from .dataset_identity import (
    add_legacy_participant_aliases,
    group_labels_from_manifest,
    infer_workbook_participant_id,
    is_multi_group_manifest,
    participant_group_label_map_from_manifest,
)
from .dataset_paths import (
    DatasetIndexError,
    _is_relative_to,
    _nearest_project_manifest_root,
    _unmanaged_excel_root,
    find_project_manifest_for_dataset_path,
    resolve_project_excel_root,
)
from .dataset_scan import (
    casefold_set,
    is_ignored_workbook_path,
    workbook_candidate_score,
    workbook_location,
)
from .grouping import GroupInfo, ParticipantInfo
from .preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)
from .recordings import (
    RecordingInfo,
    RecordingSourceInfo,
    SessionInfo,
    load_project_recording_context,
)


@dataclass(frozen=True, slots=True)
class WorkbookRecord:
    """Canonical identity and path for one selected processed workbook."""

    participant_id: str
    condition: str
    path: Path
    group_id: str | None
    group_label: str | None
    observed_layout: str
    observed_group_folder: str | None
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None
    days_from_baseline: float | None = None


@dataclass(frozen=True, slots=True)
class DatasetDiagnostic:
    """Non-mutating discovery warning associated with one or more paths."""

    code: str
    message: str
    paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectDatasetIndex:
    """Shared read-only index consumed by project-aware downstream tools."""

    project_root: Path
    excel_root: Path
    scan_root: Path
    manifest: Mapping[str, Any] | None
    groups: Mapping[str, GroupInfo]
    participants: Mapping[str, ParticipantInfo]
    workbooks: tuple[WorkbookRecord, ...]
    excluded_workbooks: tuple[WorkbookRecord, ...]
    diagnostics: tuple[DatasetDiagnostic, ...]
    sessions: Mapping[str, SessionInfo] = field(
        default_factory=lambda: MappingProxyType({})
    )
    recording_sources: Mapping[str, RecordingSourceInfo] = field(
        default_factory=lambda: MappingProxyType({})
    )
    recordings: Mapping[str, RecordingInfo] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @property
    def has_group_metadata(self) -> bool:
        return bool(self.groups)

    @property
    def is_multi_group(self) -> bool:
        return len(self.groups) > 1

    @property
    def is_repeated_session(self) -> bool:
        return bool(self.sessions or self.recording_sources or self.recordings)

    @property
    def conditions(self) -> tuple[str, ...]:
        return tuple(sorted({record.condition for record in self.workbooks}))

    @property
    def participant_ids(self) -> tuple[str, ...]:
        return tuple(sorted({record.participant_id for record in self.workbooks}))

    @property
    def recording_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    record.recording_id
                    for record in self.workbooks
                    if record.recording_id is not None
                },
                key=str.casefold,
            )
        )

    @property
    def session_ids(self) -> tuple[str, ...]:
        return tuple(session.session_id for session in self.ordered_sessions)

    @property
    def ordered_groups(self) -> tuple[GroupInfo, ...]:
        return tuple(
            sorted(self.groups.values(), key=lambda row: (row.label.casefold(), row.group_id))
        )

    @property
    def ordered_sessions(self) -> tuple[SessionInfo, ...]:
        return tuple(
            sorted(
                self.sessions.values(),
                key=lambda row: (
                    row.visit_index,
                    row.label.casefold(),
                    row.session_id.casefold(),
                ),
            )
        )

    def select(
        self,
        *,
        conditions: Iterable[str] | None = None,
        group_ids: Iterable[str] | None = None,
        participant_ids: Iterable[str] | None = None,
        recording_ids: Iterable[str] | None = None,
        session_ids: Iterable[str] | None = None,
        visit_indices: Iterable[int] | None = None,
        require_nonempty_groups: bool = False,
        require_nonempty_recordings: bool = False,
        require_nonempty_sessions: bool = False,
    ) -> tuple[WorkbookRecord, ...]:
        """Return records filtered by stable canonical identities."""

        condition_keys = casefold_set(conditions)
        group_keys = casefold_set(group_ids)
        participant_keys = casefold_set(participant_ids)
        recording_keys = casefold_set(recording_ids)
        session_keys = casefold_set(session_ids)
        visit_keys = (
            None
            if visit_indices is None
            else {int(visit_index) for visit_index in visit_indices}
        )
        selected = tuple(
            record
            for record in self.workbooks
            if (condition_keys is None or record.condition.casefold() in condition_keys)
            and (
                group_keys is None
                or (
                    record.group_id is not None
                    and record.group_id.casefold() in group_keys
                )
            )
            and (
                participant_keys is None
                or record.participant_id.casefold() in participant_keys
            )
            and (
                recording_keys is None
                or (
                    record.recording_id is not None
                    and record.recording_id.casefold() in recording_keys
                )
            )
            and (
                session_keys is None
                or (
                    record.session_id is not None
                    and record.session_id.casefold() in session_keys
                )
            )
            and (
                visit_keys is None
                or (
                    record.visit_index is not None
                    and record.visit_index in visit_keys
                )
            )
        )
        if require_nonempty_groups and group_keys:
            self.require_group_assignments()
            known_groups = {
                group_id.casefold(): group_id for group_id in self.groups
            }
            unknown = sorted(group_keys - known_groups.keys())
            if unknown:
                raise DatasetIndexError(
                    f"Unknown canonical project group_id(s): {', '.join(unknown)}."
                )
            present = {
                record.group_id.casefold()
                for record in selected
                if record.group_id is not None
            }
            empty = sorted(known_groups[key] for key in group_keys - present)
            if empty:
                raise DatasetIndexError(
                    "No indexed workbooks matched canonical project group(s): "
                    f"{', '.join(empty)}."
                )
        if require_nonempty_recordings and recording_keys:
            self.require_recording_assignments()
            known_recordings = {
                recording_id.casefold(): recording_id
                for recording_id in self.recordings
            }
            unknown = sorted(recording_keys - known_recordings.keys())
            if unknown:
                raise DatasetIndexError(
                    "Unknown canonical project recording_id(s): "
                    + ", ".join(unknown)
                    + "."
                )
            present = {
                record.recording_id.casefold()
                for record in selected
                if record.recording_id is not None
            }
            empty = sorted(
                known_recordings[key] for key in recording_keys - present
            )
            if empty:
                raise DatasetIndexError(
                    "No indexed workbooks matched canonical project recording(s): "
                    f"{', '.join(empty)}."
                )
        if require_nonempty_sessions and session_keys:
            self.require_session_assignments()
            known_sessions = {
                session_id.casefold(): session_id for session_id in self.sessions
            }
            unknown = sorted(session_keys - known_sessions.keys())
            if unknown:
                raise DatasetIndexError(
                    "Unknown canonical project session_id(s): "
                    + ", ".join(unknown)
                    + "."
                )
            present = {
                record.session_id.casefold()
                for record in selected
                if record.session_id is not None
            }
            empty = sorted(known_sessions[key] for key in session_keys - present)
            if empty:
                raise DatasetIndexError(
                    "No indexed workbooks matched canonical project session(s): "
                    f"{', '.join(empty)}."
                )
        return selected

    def subject_data(
        self,
        *,
        require_group_assignment: bool = False,
    ) -> dict[str, dict[str, str]]:
        """Return the compatibility ``participant -> condition -> path`` shape."""

        if self.is_repeated_session:
            raise DatasetIndexError(
                "The legacy participant/condition subject_data view cannot represent "
                "multiple recordings without overwriting a visit. Use recording_data(), "
                "select(), or a session partition for repeated-session projects."
            )
        if require_group_assignment:
            self.require_group_assignments()
        result: dict[str, dict[str, str]] = {}
        for record in self.workbooks:
            result.setdefault(record.participant_id, {})[record.condition] = str(
                record.path
            )
        return result

    def recording_data(
        self,
        *,
        require_group_assignment: bool = False,
    ) -> dict[str, dict[str, str]]:
        """Return ``recording -> condition -> path`` without collapsing visits."""

        if require_group_assignment:
            self.require_group_assignments()
        if self.is_repeated_session:
            self.require_recording_assignments()
            self.require_session_assignments()
        result: dict[str, dict[str, str]] = {}
        for record in self.workbooks:
            recording_id = record.recording_id or record.participant_id
            result.setdefault(recording_id, {})[record.condition] = str(record.path)
        return result

    def require_group_assignments(self) -> None:
        """Raise when grouped inputs lack canonical participant membership."""

        if not self.has_group_metadata:
            return
        unassigned = sorted(
            {
                record.participant_id
                for record in self.workbooks
                if record.group_id is None
            }
        )
        if unassigned:
            raise DatasetIndexError(
                "Grouped project workbook identity is incomplete in project.json: "
                "participants without a canonical group assignment: "
                + ", ".join(unassigned)
            )

    def require_recording_assignments(self) -> None:
        """Raise when repeated-session inputs lack canonical recording IDs."""

        if not self.is_repeated_session:
            return
        unassigned = sorted(
            {
                record.path.name
                for record in self.workbooks
                if record.recording_id is None
            }
            | {
                path.name
                for diagnostic in self.diagnostics
                if diagnostic.code == "unresolved_recording"
                for path in diagnostic.paths
            },
            key=str.casefold,
        )
        if unassigned:
            raise DatasetIndexError(
                "Repeated-session workbook identity is incomplete in project.json: "
                "workbooks without a canonical recording assignment: "
                + ", ".join(unassigned)
            )

    def require_session_assignments(self) -> None:
        """Raise when repeated-session workbooks lack canonical session IDs."""

        if not self.is_repeated_session:
            return
        unassigned = sorted(
            {
                record.path.name
                for record in self.workbooks
                if record.session_id is None
            }
            | {
                path.name
                for diagnostic in self.diagnostics
                if diagnostic.code == "unresolved_recording"
                for path in diagnostic.paths
            },
            key=str.casefold,
        )
        if unassigned:
            raise DatasetIndexError(
                "Repeated-session workbook identity is incomplete in project.json: "
                "workbooks without a canonical session assignment: "
                + ", ".join(unassigned)
            )

    def partition_by_session(
        self,
        *,
        conditions: Iterable[str] | None = None,
        group_ids: Iterable[str] | None = None,
        participant_ids: Iterable[str] | None = None,
        recording_ids: Iterable[str] | None = None,
        require_nonempty_sessions: bool = False,
    ) -> tuple[tuple[SessionInfo | None, tuple[WorkbookRecord, ...]], ...]:
        """Partition records by canonical session without folder inference."""

        if not self.sessions:
            return (
                (
                    None,
                    self.select(
                        conditions=conditions,
                        group_ids=group_ids,
                        participant_ids=participant_ids,
                        recording_ids=recording_ids,
                    ),
                ),
            )
        self.require_session_assignments()
        return tuple(
            (
                session,
                self.select(
                    conditions=conditions,
                    group_ids=group_ids,
                    participant_ids=participant_ids,
                    recording_ids=recording_ids,
                    session_ids=(session.session_id,),
                    require_nonempty_sessions=require_nonempty_sessions,
                ),
            )
            for session in self.ordered_sessions
        )

    def partition_by_group_and_session(
        self,
        *,
        conditions: Iterable[str] | None = None,
        participant_ids: Iterable[str] | None = None,
        recording_ids: Iterable[str] | None = None,
        require_nonempty_cells: bool = False,
    ) -> tuple[
        tuple[GroupInfo | None, SessionInfo | None, tuple[WorkbookRecord, ...]],
        ...,
    ]:
        """Partition records into canonical group/session cells."""

        group_rows: tuple[GroupInfo | None, ...] = self.ordered_groups or (None,)
        session_rows: tuple[SessionInfo | None, ...] = self.ordered_sessions or (None,)
        if self.has_group_metadata:
            self.require_group_assignments()
        if self.is_repeated_session:
            self.require_recording_assignments()
            self.require_session_assignments()
        cells = []
        for group in group_rows:
            for session in session_rows:
                records = self.select(
                    conditions=conditions,
                    group_ids=None if group is None else (group.group_id,),
                    participant_ids=participant_ids,
                    recording_ids=recording_ids,
                    session_ids=None if session is None else (session.session_id,),
                )
                if require_nonempty_cells and not records:
                    group_text = "ungrouped" if group is None else group.group_id
                    session_text = (
                        "single-session" if session is None else session.session_id
                    )
                    raise DatasetIndexError(
                        "No indexed workbooks matched canonical group/session cell "
                        f"'{group_text}/{session_text}'."
                    )
                cells.append((group, session, records))
        return tuple(cells)

    def partition_by_group(
        self,
        *,
        conditions: Iterable[str] | None = None,
        participant_ids: Iterable[str] | None = None,
        require_nonempty_groups: bool = False,
    ) -> tuple[tuple[GroupInfo | None, tuple[WorkbookRecord, ...]], ...]:
        """Partition selected records by canonical group without folder inference."""

        if self.has_group_metadata:
            self.require_group_assignments()
        if self.is_multi_group:
            return tuple(
                (
                    group,
                    self.select(
                        conditions=conditions,
                        group_ids=(group.group_id,),
                        participant_ids=participant_ids,
                        require_nonempty_groups=require_nonempty_groups,
                    ),
                )
                for group in self.ordered_groups
            )
        group = self.ordered_groups[0] if len(self.ordered_groups) == 1 else None
        return (
            (
                group,
                self.select(
                    conditions=conditions,
                    participant_ids=participant_ids,
                ),
            ),
        )

    def participant_group_id_map(
        self,
        *,
        uppercase_keys: bool = False,
        include_legacy_aliases: bool = False,
    ) -> dict[str, str]:
        """Return participant IDs mapped to canonical stable group IDs."""

        return _participant_group_map(
            self.participants,
            self.groups,
            value_kind="id",
            uppercase_keys=uppercase_keys,
            include_legacy_aliases=include_legacy_aliases,
        )

    def participant_group_label_map(
        self,
        *,
        uppercase_keys: bool = False,
        include_legacy_aliases: bool = False,
    ) -> dict[str, str]:
        """Return participant IDs mapped to group display labels."""

        return _participant_group_map(
            self.participants,
            self.groups,
            value_kind="label",
            uppercase_keys=uppercase_keys,
            include_legacy_aliases=include_legacy_aliases,
        )


def list_result_files(folder: str | Path, *, recursive: bool = False) -> tuple[Path, ...]:
    """List native/legacy inputs without changing a caller's cohort or identities.

    Flat-folder tools keep their established filename and exclusion handling.
    Only an exact legacy sibling is suppressed when its native anchor exists;
    malformed native anchors are retained for the shared reader to reject.
    """

    root = Path(folder).expanduser()
    candidates = root.rglob("*") if recursive else root.glob("*")
    return tuple(sorted(
        path for path in candidates
        if is_excel_workbook_file(path, suffixes=(".xlsx", RESULT_MANIFEST_SUFFIX))
        and path.is_file()
        and path == resolve_result_path(path)
    ))


def load_project_dataset_index(dataset_path: str | Path) -> ProjectDatasetIndex:
    """Build the shared read-only workbook index for a project or Excel path."""

    requested = Path(dataset_path).expanduser().resolve(strict=False)
    requested_is_file = requested.is_file()
    if requested_is_file and not is_excel_workbook_file(
        requested, suffixes=(".xlsx", RESULT_MANIFEST_SUFFIX)
    ):
        raise DatasetIndexError(
            f"Dataset file inputs must be .fpvs results or .xlsx workbooks: {requested}"
        )
    if requested_is_file:
        requested = resolve_result_path(requested)
    project_root, manifest = find_project_manifest_for_dataset_path(requested)
    diagnostics: list[DatasetDiagnostic] = []
    single_workbook: Path | None = requested if requested_is_file else None

    if project_root is None or manifest is None:
        nearest_project_root = _nearest_project_manifest_root(requested)
        if requested_is_file:
            if nearest_project_root is not None:
                raise DatasetIndexError(
                    "Workbook is outside the configured Excel root for project "
                    f"{nearest_project_root}: {requested}"
                )
            project_root = requested.parent
            excel_root = requested.parent
            scan_root = requested.parent
        elif not requested.is_dir():
            raise DatasetIndexError(f"Processed workbook folder does not exist: {requested}")
        elif nearest_project_root is not None:
            raise DatasetIndexError(
                "Dataset folder is outside the configured Excel root for project "
                f"{nearest_project_root}: {requested}"
            )
        else:
            project_root = requested
            excel_root = _unmanaged_excel_root(requested)
            scan_root = excel_root
        groups: dict[str, GroupInfo] = {}
        participants: dict[str, ParticipantInfo] = {}
        sessions: dict[str, SessionInfo] = {}
        recording_sources: dict[str, RecordingSourceInfo] = {}
        recordings: dict[str, RecordingInfo] = {}
        manifest_view: Mapping[str, Any] | None = None
    else:
        excel_root = resolve_project_excel_root(project_root, manifest)
        if requested_is_file and not _is_relative_to(requested, excel_root):
            raise DatasetIndexError(
                "Workbook is outside the configured project Excel root "
                f"{excel_root}: {requested}"
            )
        if requested == project_root:
            scan_root = excel_root
        elif requested.is_file():
            scan_root = requested.parent
        else:
            scan_root = requested
        try:
            context = load_project_recording_context(project_root)
        except (OSError, ValueError) as exc:
            raise DatasetIndexError(
                f"Unable to load canonical project recording metadata: {exc}"
            ) from exc
        groups = {group.group_id: group for group in context.groups}
        participants = {
            participant.participant_id: participant
            for participant in context.participants
        }
        sessions = {session.session_id: session for session in context.sessions}
        recording_sources = {
            source.source_id: source for source in context.sources
        }
        recordings = {
            recording.recording_id: recording for recording in context.recordings
        }
        manifest_view = MappingProxyType(dict(manifest))

    alias_probe = {
        participant.participant_id: participant.group_id
        for participant in participants.values()
        if participant.group_id is not None
    }
    ambiguous_aliases = add_legacy_participant_aliases(alias_probe)
    for alias in ambiguous_aliases:
        diagnostics.append(
            DatasetDiagnostic(
                code="ambiguous_legacy_participant_alias",
                message=(
                    f"Legacy participant alias '{alias}' maps to multiple canonical "
                    "group assignments and was not assigned."
                ),
            )
        )

    if single_workbook is not None:
        workbook_paths = (single_workbook,)
    elif not scan_root.is_dir():
        diagnostics.append(
            DatasetDiagnostic(
                code="missing_excel_root",
                message=f"Processed workbook folder does not exist: {scan_root}",
                paths=(scan_root,),
            )
        )
        workbook_paths: tuple[Path, ...] = ()
    else:
        try:
            workbook_paths = tuple(
                sorted(
                    path
                    for path in list_result_files(scan_root, recursive=True)
                    if not is_ignored_workbook_path(path, scan_root)
                )
            )
        except OSError as exc:
            raise DatasetIndexError(
                f"Unable to scan processed workbooks under {scan_root}: {exc}"
            ) from exc

    selected: dict[tuple[str, str], tuple[WorkbookRecord, tuple[int, int, str]]] = {}
    duplicate_paths: dict[tuple[str, str], list[Path]] = {}
    repeated_session_project = bool(
        sessions or recording_sources or recordings
    )
    participant_lookup = {
        participant_id.casefold(): participant_id
        for participant_id in participants
    }
    for path in workbook_paths:
        condition, layout, observed_group = workbook_location(
            path,
            excel_root=excel_root,
            scan_root=scan_root,
            project_managed=manifest_view is not None,
        )
        if condition is None:
            diagnostics.append(
                DatasetDiagnostic(
                    code="unresolved_condition",
                    message=f"Unable to determine a condition for {path.name}.",
                    paths=(path,),
                )
            )
            continue
        if layout == "unexpected_nested":
            diagnostics.append(
                DatasetDiagnostic(
                    code="unexpected_workbook_nesting",
                    message=(
                        f"Workbook is nested below the supported condition/group "
                        f"layout and will have lower duplicate priority: {path.name}."
                    ),
                    paths=(path,),
                )
            )
        recording: RecordingInfo | None = None
        session: SessionInfo | None = None
        if repeated_session_project:
            recording_id = _generated_recording_id(
                path,
                condition=condition,
                known_recording_ids=recordings,
            )
            if recording_id is None:
                diagnostics.append(
                    DatasetDiagnostic(
                        code="unresolved_recording",
                        message=(
                            f"Unable to match {path.name} to a canonical recording_id "
                            "in project.json."
                        ),
                        paths=(path,),
                    )
                )
                continue
            recording = recordings[recording_id]
            canonical_id = recording.participant_id
            participant = participants[canonical_id]
            source = recording_sources[recording.source_id]
            group = groups[source.group_id]
            session = sessions[recording.session_id]
        else:
            participant_id = infer_workbook_participant_id(
                path,
                known_participant_ids=participants,
                require_leading_legacy_match=manifest_view is not None,
                generated_condition=condition if manifest_view is not None else None,
            )
            if participant_id is None:
                diagnostics.append(
                    DatasetDiagnostic(
                        code="unresolved_participant",
                        message=f"Unable to determine a participant for {path.name}.",
                        paths=(path,),
                    )
                )
                continue
            canonical_id = participant_lookup.get(
                participant_id.casefold(), participant_id
            )
            participant = participants.get(canonical_id)
            group = (
                groups.get(participant.group_id)
                if participant is not None and participant.group_id is not None
                else None
            )
            if manifest_view is not None and participant is None:
                diagnostics.append(
                    DatasetDiagnostic(
                        code="unassigned_participant",
                        message=(
                            f"Workbook participant '{participant_id}' is not "
                            "registered in project.json; no group was assigned."
                        ),
                        paths=(path,),
                    )
                )
        if group is not None and observed_group is not None:
            if observed_group.casefold() != group.folder_name.casefold():
                diagnostics.append(
                    DatasetDiagnostic(
                        code="group_folder_mismatch",
                        message=(
                            f"Workbook for '{canonical_id}' is under group folder "
                            f"'{observed_group}', but project.json assigns "
                            f"'{group.folder_name}'."
                        ),
                        paths=(path,),
                    )
                )
        elif len(groups) > 1 and group is not None and layout == "condition_flat":
            diagnostics.append(
                DatasetDiagnostic(
                    code="missing_group_folder",
                    message=(
                        f"Workbook for '{canonical_id}' is flat in a multi-group "
                        f"project; project.json assigns group folder "
                        f"'{group.folder_name}'."
                    ),
                    paths=(path,),
                )
            )
        record = WorkbookRecord(
            participant_id=canonical_id,
            condition=condition,
            path=path.resolve(strict=False),
            group_id=None if group is None else group.group_id,
            group_label=None if group is None else group.label,
            observed_layout=layout,
            observed_group_folder=observed_group,
            recording_id=None if recording is None else recording.recording_id,
            session_id=None if session is None else session.session_id,
            session_label=None if session is None else session.label,
            visit_index=None if recording is None else recording.visit_index,
            days_from_baseline=(
                None if recording is None else recording.days_from_baseline
            ),
        )
        score = workbook_candidate_score(
            record.path,
            observed_layout=record.observed_layout,
            observed_group_folder=record.observed_group_folder,
            expected_group_folder=None if group is None else group.folder_name,
        )
        identity_id = (
            recording.recording_id if recording is not None else canonical_id
        )
        key = (identity_id.casefold(), condition.casefold())
        existing = selected.get(key)
        if existing is None or score >= existing[1]:
            selected[key] = (record, score)
        if existing is not None:
            duplicate_paths.setdefault(key, [existing[0].path]).append(path)

    for key, paths in duplicate_paths.items():
        chosen = selected[key][0]
        unique_paths = tuple(dict.fromkeys(path.resolve(strict=False) for path in paths))
        duplicate_code = (
            "duplicate_recording_condition_workbook"
            if chosen.recording_id is not None
            else "duplicate_participant_condition_workbook"
        )
        identity = chosen.recording_id or chosen.participant_id
        diagnostics.append(
            DatasetDiagnostic(
                code=duplicate_code,
                message=(
                    f"Multiple workbooks were found for {identity} / "
                    f"{chosen.condition}; selected {chosen.path.name}."
                ),
                paths=unique_paths,
            )
        )

    all_records = tuple(
        sorted(
            (row[0] for row in selected.values()),
            key=lambda row: (
                row.condition.casefold(),
                row.group_label.casefold() if row.group_label else "",
                row.participant_id.casefold(),
                row.visit_index if row.visit_index is not None else 0,
                row.recording_id.casefold() if row.recording_id else "",
                str(row.path),
            ),
        )
    )
    excluded_pairs: set[tuple[str, str]] = set()
    excluded_recording_ids: set[str] = set()
    excluded_recording_pairs: set[tuple[str, str]] = set()
    if manifest_view is not None:
        preprocessing = manifest_view.get("preprocessing")
        raw_exclusions = None
        exclusion_key = "manual_excluded_participant_conditions"
        if isinstance(preprocessing, Mapping):
            for candidate_key in (
                "manual_excluded_participant_conditions",
                "excluded_participant_conditions",
                "participant_condition_exclusions",
            ):
                if candidate_key in preprocessing:
                    exclusion_key = candidate_key
                    raw_exclusions = preprocessing[candidate_key]
                    break
        try:
            normalized_exclusions = (
                normalize_manual_excluded_participant_conditions(raw_exclusions)
            )
        except ValueError as exc:
            raise DatasetIndexError(
                "Invalid project.json preprocessing setting "
                f"'{exclusion_key}' for {project_root}: {exc}"
            ) from exc
        excluded_pairs = {
            (participant_id.casefold(), condition.casefold())
            for participant_id, conditions in normalized_exclusions.items()
            for condition in conditions
        }
        if isinstance(preprocessing, Mapping):
            try:
                excluded_recording_ids = {
                    recording_id.casefold()
                    for recording_id in normalize_manual_excluded_recordings(
                        preprocessing.get("manual_excluded_recordings")
                    )
                }
                normalized_recording_conditions = (
                    normalize_manual_excluded_recording_conditions(
                        preprocessing.get(
                            "manual_excluded_recording_conditions"
                        )
                    )
                )
            except ValueError as exc:
                raise DatasetIndexError(
                    "Invalid recording-scoped preprocessing exclusion in "
                    f"project.json for {project_root}: {exc}"
                ) from exc
            excluded_recording_pairs = {
                (recording_id.casefold(), condition.casefold())
                for recording_id, conditions in normalized_recording_conditions.items()
                for condition in conditions
            }

    def _record_is_excluded(record: WorkbookRecord) -> bool:
        participant_condition = (
            record.participant_id.casefold(),
            record.condition.casefold(),
        )
        if participant_condition in excluded_pairs:
            return True
        if record.recording_id is None:
            return False
        recording_key = record.recording_id.casefold()
        return recording_key in excluded_recording_ids or (
            recording_key,
            record.condition.casefold(),
        ) in excluded_recording_pairs

    records = tuple(
        record
        for record in all_records
        if not _record_is_excluded(record)
    )
    excluded_records = tuple(
        record
        for record in all_records
        if _record_is_excluded(record)
    )
    for record in excluded_records:
        identity = record.recording_id or record.participant_id
        key = (identity.casefold(), record.condition.casefold())
        paths = duplicate_paths.get(key, [record.path])
        unique_paths = tuple(
            dict.fromkeys(Path(path).resolve(strict=False) for path in paths)
        )
        participant_condition = (
            record.participant_id.casefold(),
            record.condition.casefold(),
        )
        recording_key = (
            record.recording_id.casefold() if record.recording_id else None
        )
        if participant_condition in excluded_pairs:
            code = "excluded_participant_condition"
            message = (
                f"Excluded {record.participant_id} / {record.condition} from "
                "downstream workbook analyses by project QC decision."
            )
        elif recording_key in excluded_recording_ids:
            code = "excluded_recording"
            message = (
                f"Excluded recording {record.recording_id} from downstream "
                "workbook analyses by project QC decision."
            )
        else:
            code = "excluded_recording_condition"
            message = (
                f"Excluded {record.recording_id} / {record.condition} from "
                "downstream workbook analyses by project QC decision."
            )
        diagnostics.append(
            DatasetDiagnostic(
                code=code,
                message=message,
                paths=unique_paths,
            )
        )
    return ProjectDatasetIndex(
        project_root=project_root,
        excel_root=excel_root,
        scan_root=scan_root,
        manifest=manifest_view,
        groups=MappingProxyType(groups),
        participants=MappingProxyType(participants),
        workbooks=records,
        excluded_workbooks=excluded_records,
        diagnostics=tuple(diagnostics),
        sessions=MappingProxyType(sessions),
        recording_sources=MappingProxyType(recording_sources),
        recordings=MappingProxyType(recordings),
    )


def _generated_recording_id(
    workbook_path: str | Path,
    *,
    condition: str,
    known_recording_ids: Mapping[str, RecordingInfo],
) -> str | None:
    """Match only an exact manifest recording ID in a generated filename."""

    stem = Path(workbook_path).stem.strip()
    generated_suffix = f"_{str(condition).strip()}_Results"
    if (
        not stem
        or not condition
        or not stem.casefold().endswith(generated_suffix.casefold())
        or len(stem) <= len(generated_suffix)
    ):
        return None
    observed_id = stem[: -len(generated_suffix)].strip()
    lookup = {
        recording_id.casefold(): recording_id
        for recording_id in known_recording_ids
    }
    return lookup.get(observed_id.casefold())


def _participant_group_map(
    participants: Mapping[str, ParticipantInfo],
    groups: Mapping[str, GroupInfo],
    *,
    value_kind: str,
    uppercase_keys: bool,
    include_legacy_aliases: bool,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for participant in participants.values():
        if participant.group_id is None or participant.group_id not in groups:
            continue
        group = groups[participant.group_id]
        key = (
            participant.participant_id.upper()
            if uppercase_keys
            else participant.participant_id
        )
        result[key] = group.group_id if value_kind == "id" else group.label
    if include_legacy_aliases:
        add_legacy_participant_aliases(result)
    return result


__all__ = [
    "DatasetDiagnostic",
    "ProjectDatasetIndex",
    "WorkbookRecord",
    "group_labels_from_manifest",
    "infer_workbook_participant_id",
    "is_multi_group_manifest",
    "load_project_dataset_index",
    "participant_group_label_map_from_manifest",
]
