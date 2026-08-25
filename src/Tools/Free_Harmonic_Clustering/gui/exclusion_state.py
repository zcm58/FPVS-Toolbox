"""Project-local persistence for FHC recording exclusions."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path

from .models import AnalysisRecordingExclusion


EXCLUSION_STATE_SCHEMA_VERSION = 1
EXCLUSION_STATE_FILENAME = "project_settings.json"


class ExclusionStateError(RuntimeError):
    """Raised when project-local FHC exclusion state cannot be read or written."""


def exclusion_state_path(results_parent: str | Path) -> Path:
    """Return the preference path beneath the resolved FHC results parent."""

    parent = Path(results_parent).expanduser().resolve(strict=False)
    return parent / EXCLUSION_STATE_FILENAME


def load_project_recording_exclusions(
    results_parent: str | Path,
    recording_ids: Sequence[str],
) -> tuple[AnalysisRecordingExclusion, ...]:
    """Load exclusions that still match canonical recordings in the project."""

    path = exclusion_state_path(results_parent)
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("the root value must be an object")
        if payload.get("schema_version") != EXCLUSION_STATE_SCHEMA_VERSION:
            raise ValueError("the schema version is unsupported")
        raw_exclusions = payload.get("recording_exclusions")
        if not isinstance(raw_exclusions, list):
            raise ValueError("recording_exclusions must be a list")

        loaded: dict[str, AnalysisRecordingExclusion] = {}
        for raw in raw_exclusions:
            if not isinstance(raw, dict):
                raise ValueError("each recording exclusion must be an object")
            exclusion = AnalysisRecordingExclusion(
                recording_id=raw.get("recording_id", ""),
                reason=raw.get("reason", ""),
            )
            key = exclusion.recording_id.casefold()
            if key in loaded:
                raise ValueError(
                    f"duplicate recording exclusion: {exclusion.recording_id}"
                )
            loaded[key] = exclusion
    except (OSError, TypeError, ValueError) as exc:
        raise ExclusionStateError(
            f"Could not load saved FHC recording exclusions from {path}: {exc}"
        ) from exc

    canonical_ids = tuple(str(value).strip() for value in recording_ids)
    return tuple(
        AnalysisRecordingExclusion(recording_id, loaded[recording_id.casefold()].reason)
        for recording_id in canonical_ids
        if recording_id.casefold() in loaded
    )


def save_project_recording_exclusions(
    results_parent: str | Path,
    exclusions: Sequence[AnalysisRecordingExclusion],
) -> Path:
    """Atomically persist the current project-specific FHC exclusions."""

    path = exclusion_state_path(results_parent)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    payload = {
        "schema_version": EXCLUSION_STATE_SCHEMA_VERSION,
        "recording_exclusions": [
            {
                "recording_id": exclusion.recording_id,
                "reason": exclusion.reason,
            }
            for exclusion in exclusions
        ],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise ExclusionStateError(
            f"Could not save FHC recording exclusions to {path}: {exc}"
        ) from exc
    return path


__all__ = [
    "EXCLUSION_STATE_FILENAME",
    "EXCLUSION_STATE_SCHEMA_VERSION",
    "ExclusionStateError",
    "exclusion_state_path",
    "load_project_recording_exclusions",
    "save_project_recording_exclusions",
]
