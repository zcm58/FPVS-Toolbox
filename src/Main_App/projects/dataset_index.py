"""Read-only processed-workbook discovery for project-aware tools.

This module owns workbook identity, condition discovery, participant matching,
and canonical project-group assignment.  Downstream tools may adapt these
records for their own calculations, but must not infer group identity from
generated output folders.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from Main_App.Shared.file_filters import is_excel_workbook_file

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
from .grouping import GroupInfo, ParticipantInfo, load_project_group_context


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
    diagnostics: tuple[DatasetDiagnostic, ...]

    @property
    def has_group_metadata(self) -> bool:
        return bool(self.groups)

    @property
    def is_multi_group(self) -> bool:
        return len(self.groups) > 1

    @property
    def conditions(self) -> tuple[str, ...]:
        return tuple(sorted({record.condition for record in self.workbooks}))

    @property
    def participant_ids(self) -> tuple[str, ...]:
        return tuple(sorted({record.participant_id for record in self.workbooks}))

    @property
    def ordered_groups(self) -> tuple[GroupInfo, ...]:
        return tuple(
            sorted(self.groups.values(), key=lambda row: (row.label.casefold(), row.group_id))
        )

    def select(
        self,
        *,
        conditions: Iterable[str] | None = None,
        group_ids: Iterable[str] | None = None,
        participant_ids: Iterable[str] | None = None,
        require_nonempty_groups: bool = False,
    ) -> tuple[WorkbookRecord, ...]:
        """Return records filtered by stable canonical identities."""

        condition_keys = casefold_set(conditions)
        group_keys = casefold_set(group_ids)
        participant_keys = casefold_set(participant_ids)
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
        return selected

    def subject_data(
        self,
        *,
        require_group_assignment: bool = False,
    ) -> dict[str, dict[str, str]]:
        """Return the compatibility ``participant -> condition -> path`` shape."""

        if require_group_assignment:
            self.require_group_assignments()
        result: dict[str, dict[str, str]] = {}
        for record in self.workbooks:
            result.setdefault(record.participant_id, {})[record.condition] = str(
                record.path
            )
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


def load_project_dataset_index(dataset_path: str | Path) -> ProjectDatasetIndex:
    """Build the shared read-only workbook index for a project or Excel path."""

    requested = Path(dataset_path).expanduser().resolve(strict=False)
    requested_is_file = requested.is_file()
    if requested_is_file and not is_excel_workbook_file(requested):
        raise DatasetIndexError(
            f"Dataset file inputs must be .xlsx workbooks: {requested}"
        )
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
            context = load_project_group_context(project_root)
        except (OSError, ValueError) as exc:
            raise DatasetIndexError(
                f"Unable to load canonical project group metadata: {exc}"
            ) from exc
        groups = {group.group_id: group for group in context.groups}
        participants = {
            participant.participant_id: participant
            for participant in context.participants
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
                    for path in scan_root.rglob("*.xlsx")
                    if path.is_file()
                    and is_excel_workbook_file(path)
                    and not is_ignored_workbook_path(path, scan_root)
                )
            )
        except OSError as exc:
            raise DatasetIndexError(
                f"Unable to scan processed workbooks under {scan_root}: {exc}"
            ) from exc

    selected: dict[tuple[str, str], tuple[WorkbookRecord, tuple[int, int, str]]] = {}
    duplicate_paths: dict[tuple[str, str], list[Path]] = {}
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
        canonical_id = participant_lookup.get(participant_id.casefold(), participant_id)
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
                        f"Workbook participant '{participant_id}' is not registered "
                        "in project.json; no group was assigned."
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
        )
        score = workbook_candidate_score(
            record.path,
            observed_layout=record.observed_layout,
            observed_group_folder=record.observed_group_folder,
            expected_group_folder=None if group is None else group.folder_name,
        )
        key = (canonical_id.casefold(), condition.casefold())
        existing = selected.get(key)
        if existing is None or score >= existing[1]:
            selected[key] = (record, score)
        if existing is not None:
            duplicate_paths.setdefault(key, [existing[0].path]).append(path)

    for key, paths in duplicate_paths.items():
        chosen = selected[key][0]
        unique_paths = tuple(dict.fromkeys(path.resolve(strict=False) for path in paths))
        diagnostics.append(
            DatasetDiagnostic(
                code="duplicate_participant_condition_workbook",
                message=(
                    f"Multiple workbooks were found for {chosen.participant_id} / "
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
                str(row.path),
            ),
        )
    )
    return ProjectDatasetIndex(
        project_root=project_root,
        excel_root=excel_root,
        scan_root=scan_root,
        manifest=manifest_view,
        groups=MappingProxyType(groups),
        participants=MappingProxyType(participants),
        workbooks=all_records,
        diagnostics=tuple(diagnostics),
    )


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
