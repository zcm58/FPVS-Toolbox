"""Reviewed source identity allocation before strict flat-recording discovery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re

from Main_App.io.file_filters import is_eeg_recording_file
from .grouping import project_group_context, validate_group_folder_name
from .raw_identity import infer_raw_participant_id, normalize_source_studies, propose_source_participant_id, registered_raw_identities


@dataclass(frozen=True, slots=True)
class SourceParticipantProposal:
    participant_id: str
    source_study_id: str | None
    source_participant_id: str | None
    group_id: str | None
    group_label: str
    raw_file: Path | None
    existing: bool


@dataclass(frozen=True, slots=True)
class SourceRegistrationReview:
    manifest_sha256: str
    proposals: tuple[SourceParticipantProposal, ...]
    requires_source_review: bool
    selected_path: Path | None = None

    @property
    def additions(self):
        return tuple(row for row in self.proposals if not row.existing)

    def editor_rows(self):
        return [asdict(row) for row in self.proposals]


def prepare_source_registration_review(project, *, selected_path=None):
    """Inspect direct children only; do not read EEG bytes or mutate membership."""
    if project.sessions or project.recordings:
        raise ValueError("Use repeated-session registration for additional visits.")
    path = Path(project.manifest_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    context = project_group_context(project)
    registered = registered_raw_identities(project)
    labels = {row.group_id: row.label for row in context.groups}
    source_by_group = {}
    proposals = []
    for row in context.participants:
        if row.source_study_id:
            source_by_group.setdefault(row.group_id, set()).add(row.source_study_id)
        proposals.append(SourceParticipantProposal(
            row.participant_id, row.source_study_id, row.source_participant_id,
            row.group_id, labels.get(row.group_id, ""), row.raw_file, True,
        ))
    folders = [(row.group_id, row.raw_input_folder) for row in context.groups] or [(None, project.input_folder)]
    selected = Path(selected_path).resolve(strict=False) if selected_path is not None else None
    discovered = set()
    for group_id, folder in folders:
        for raw_file in sorted(Path(folder).iterdir()):
            if not raw_file.is_file() or not is_eeg_recording_file(raw_file):
                continue
            raw_file = raw_file.resolve(strict=False)
            discovered.add(raw_file)
            if raw_file in registered or (selected is not None and raw_file != selected):
                continue
            sources = source_by_group.get(group_id, set())
            namespace = next(iter(sources)) if len(sources) == 1 else str(group_id or "source")
            if not namespace[0].isalpha():
                namespace = "source_" + namespace
            proposals.append(SourceParticipantProposal(
                "", namespace, infer_raw_participant_id(raw_file), group_id,
                labels.get(group_id, ""), raw_file, False,
            ))
    if selected is not None and selected not in discovered:
        raise ValueError("Select a recording inside this project's configured raw-data folder.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("The project changed while preparing source registration. Reopen the review.")
    additions = [row for row in proposals if not row.existing]
    bare_ids = Counter(str(row.source_participant_id).casefold() for row in additions)
    # A legacy participant without a registered raw path still uses the normal
    # filename registration workflow; it is not evidence of a second person.
    existing_ids = {row.participant_id.casefold() for row in context.participants if row.raw_file is not None}
    collision = any(count > 1 or ident in existing_ids for ident, count in bare_ids.items())
    needs_review = bool(additions) and bool(project.source_studies or project.frequency_protocol.condition_trigger_maps or collision)
    return SourceRegistrationReview(digest, tuple(proposals), needs_review, selected)


def validate_source_registration_rows(project, review, rows: Sequence[Mapping], *, trigger_map_assignments=None):
    """Validate user-editable identity fields without accepting ownership edits."""
    if len(rows) != len(review.proposals):
        raise ValueError("The registration review must retain every proposed row.")
    participants, sources, identifiers = {}, {}, set()
    source_pairs = set()
    for proposal, row in zip(review.proposals, rows, strict=True):
        if (row.get("raw_file") != proposal.raw_file or row.get("group_id") != proposal.group_id
                or bool(row.get("existing")) != proposal.existing):
            raise ValueError("Registration cannot change existing raw-file or group ownership.")
        ident = str(row.get("participant_id") or "").strip()
        source = str(row.get("source_study_id") or "").strip()
        local = str(row.get("source_participant_id") or "").strip()
        if proposal.existing and (ident != proposal.participant_id or source != (proposal.source_study_id or "") or local != (proposal.source_participant_id or "")):
            raise ValueError("Registration cannot change existing participant or source identities.")
        if not ident:
            raise ValueError("Choose a project ID for every new participant.")
        sanitized = re.sub(r"[^A-Za-z0-9]", "", ident).casefold()
        if not sanitized or sanitized in identifiers:
            raise ValueError(f"Project ID {ident!r} collides with another participant.")
        identifiers.add(sanitized)
        if source and local:
            pair = source.casefold(), local.casefold()
            if pair in source_pairs:
                raise ValueError(f"Source participant {source!r} / {local!r} already exists. Use repeated-session registration for visits.")
            source_pairs.add(pair)
        if proposal.existing:
            continue
        validate_group_folder_name(ident)
        propose_source_participant_id(source, local)
        if source not in project.source_studies:
            sources[source] = {"label": source}
        entry = {"source_study_id": source, "source_participant_id": local, "raw_file": proposal.raw_file}
        if proposal.group_id:
            entry["group_id"] = proposal.group_id
        participants[ident] = entry
    normalize_source_studies({**project.source_studies, **sources})
    assignments = dict(trigger_map_assignments or {})
    maps = project.frequency_protocol.condition_trigger_maps
    if maps is not None:
        if set(assignments) != set(participants):
            raise ValueError("Choose a source trigger map for every new recording.")
        profiles = {row.profile_id for row in maps.profiles}
        if set(assignments.values()) - profiles:
            raise ValueError("Choose a saved source trigger map for each new recording.")
    elif assignments:
        raise ValueError("Trigger assignments require a project configured with source maps.")
    return participants, sources, assignments


def commit_source_registration_review(project, review, rows, *, trigger_map_assignments=None):
    """Append identities and explicit maps in one validated manifest transaction."""
    if prepare_source_registration_review(project, selected_path=review.selected_path) != review:
        raise ValueError("The project or raw-file list changed after review. Reopen source registration.")
    participants, sources, assignments = validate_source_registration_rows(
        project, review, rows, trigger_map_assignments=trigger_map_assignments,
    )
    if not participants:
        return False
    from Main_App.processing.raw_registration_state import registration_tool_updates

    updates = registration_tool_updates(project.project_root, list(participants))
    project.append_registered_inputs(
        participants=participants, recordings={}, expected_manifest_sha256=review.manifest_sha256,
        tool_namespace_updates=updates, source_studies=sources, trigger_map_assignments=assignments,
    )
    return True
