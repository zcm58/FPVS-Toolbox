"""Helpers for loading project manifest data for the Plot Generator."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


def load_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Return the nearest ``project.json`` manifest for the provided Excel folder."""

    try:
        current = excel_root.resolve()
    except Exception:  # pragma: no cover - best effort resolution
        current = excel_root
    for candidate in (current, *current.parents):
        manifest = candidate / "project.json"
        if manifest.is_file():
            try:
                return json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - log and fall back
                logger.warning("Failed to load manifest %s: %s", manifest, exc)
                return None
    return None


def normalize_participants_map(manifest: dict | None) -> Dict[str, str]:
    """Return an uppercase ``{subject_id -> group}`` mapping."""

    if not isinstance(manifest, dict):
        return {}
    participants = manifest.get("participants", {})
    if not isinstance(participants, dict):
        return {}
    normalized: Dict[str, str] = {}
    for pid, info in participants.items():
        if not isinstance(pid, str):
            continue
        if not isinstance(info, dict):
            continue
        group = info.get("group")
        if not isinstance(group, str) or not group.strip():
            continue
        normalized[pid.strip().upper()] = group.strip()
    return normalized


def extract_group_names(manifest: dict | None) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        return []
    names = [name for name in groups.keys() if isinstance(name, str) and name.strip()]
    return sorted({name.strip() for name in names})


def has_multi_groups(manifest: dict | None) -> bool:
    return len(extract_group_names(manifest)) >= 2
