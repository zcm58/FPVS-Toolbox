"""Compatibility adapters for shared project dataset metadata."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from Main_App.projects import (
    group_labels_from_manifest,
    is_multi_group_manifest,
    load_project_manifest_for_dataset_path,
    participant_group_label_map_from_manifest,
)


def load_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Return shared manifest metadata for a project-managed Excel folder."""

    return load_project_manifest_for_dataset_path(excel_root)


def normalize_participants_map(manifest: dict | None) -> Dict[str, str]:
    """Return the Plot Generator's uppercase participant-to-label adapter."""

    return participant_group_label_map_from_manifest(
        manifest,
        include_legacy_aliases=False,
    )


def extract_group_names(manifest: dict | None) -> list[str]:
    """Return shared group labels in the established presentation order."""

    return list(group_labels_from_manifest(manifest))


def has_multi_groups(manifest: dict | None) -> bool:
    return is_multi_group_manifest(manifest)
