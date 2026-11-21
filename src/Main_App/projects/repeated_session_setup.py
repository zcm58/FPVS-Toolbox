"""Build repeated-session project manifests and apply their source preflight."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace

from Main_App.projects.grouping import GroupConfigurationError, normalize_project_groups
from Main_App.projects.preprocessing_settings import new_project_preprocessing_settings
from Main_App.projects.recording_preflight import RecordingPreflightReport, derive_filename_token_rules
from Main_App.projects.recordings import (
    ProjectRecordingContext,
    RecordingConfigurationError,
    normalize_project_recording_sources,
    normalize_project_sessions,
    project_recording_context,
)


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


def repeated_preflight_inputs(
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


def is_empty_repeated_source_scaffold(report: RecordingPreflightReport) -> bool:
    """Return whether every declared source is present but contains no BDFs."""

    return not report.rows and all(
        issue.code == "empty_source_cell" for issue in report.issues
    )


def apply_repeated_session_preflight_report(
    manifest: Mapping[str, object],
    report: RecordingPreflightReport,
) -> dict[str, object]:
    """Return a copied manifest populated from one accepted source audit."""

    if report.is_blocked and not is_empty_repeated_source_scaffold(report):
        raise RepeatedSessionProjectSetupError(report.summary_text())
    completed = deepcopy(dict(manifest))
    if is_empty_repeated_source_scaffold(report):
        completed["participants"] = {}
        completed["recordings"] = {}
    else:
        completed["participants"] = report.participants_manifest()
        completed["recordings"] = report.recordings_manifest()
    return completed
