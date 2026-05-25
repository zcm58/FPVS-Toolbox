"""Helpers for loading project manifest data for the Plot Generator."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from Main_App.projects.project import EXCEL_SUBFOLDER_NAME

logger = logging.getLogger(__name__)


def _expected_excel_path(manifest_root: Path, cfg: dict) -> Path | None:
    """Return the resolved Excel folder path declared in ``project.json``."""

    results_folder = cfg.get("results_folder") if isinstance(cfg, dict) else None
    base = manifest_root
    if isinstance(results_folder, str) and results_folder.strip():
        candidate = Path(results_folder.strip())
        base = candidate if candidate.is_absolute() else (manifest_root / candidate)
    subfolders = cfg.get("subfolders") if isinstance(cfg, dict) else {}
    excel_name = EXCEL_SUBFOLDER_NAME
    if isinstance(subfolders, dict):
        excel_name = subfolders.get("excel", excel_name)
    try:
        excel_path = Path(excel_name)
        if not excel_path.is_absolute():
            excel_path = (base / excel_path).resolve()
        else:
            excel_path = excel_path.resolve()
        return excel_path
    except Exception:  # pragma: no cover - invalid manifest paths
        return None


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
                cfg = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - log and fall back
                logger.warning("Failed to load manifest %s: %s", manifest, exc)
                return None
            expected_excel = _expected_excel_path(candidate, cfg)
            if expected_excel is not None:
                allowed = {current, *current.parents}
                if expected_excel not in allowed:
                    continue
            return cfg
    return None


def normalize_participants_map(manifest: dict | None) -> Dict[str, str]:
    """Return an uppercase ``{subject_id -> group}`` mapping."""

    if not isinstance(manifest, dict):
        return {}
    group_labels = _group_label_aliases(manifest)
    participants = manifest.get("participants", {})
    if not isinstance(participants, dict):
        return {}
    normalized: Dict[str, str] = {}
    for pid, info in participants.items():
        if not isinstance(pid, str):
            continue
        if not isinstance(info, dict):
            continue
        group = info.get("group_id")
        if group is None:
            group = info.get("group")
        if not isinstance(group, str) or not group.strip():
            continue
        group_key = group.strip()
        normalized[pid.strip().upper()] = group_labels.get(group_key, group_key)
    return normalized


def _group_label_aliases(manifest: dict | None) -> dict[str, str]:
    if not isinstance(manifest, dict):
        return {}
    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        return {}
    aliases: dict[str, str] = {}
    for raw_group_id, raw_info in groups.items():
        if not isinstance(raw_group_id, str) or not raw_group_id.strip():
            continue
        info = raw_info if isinstance(raw_info, dict) else {}
        label = str(
            info.get("label")
            or info.get("folder_name")
            or raw_group_id
        ).strip()
        if not label:
            label = raw_group_id.strip()
        for alias in (
            raw_group_id,
            info.get("group_id"),
            info.get("label"),
            info.get("folder_name"),
        ):
            if isinstance(alias, str) and alias.strip():
                aliases[alias.strip()] = label
    return aliases


def extract_group_names(manifest: dict | None) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    groups = manifest.get("groups")
    if not isinstance(groups, dict):
        return []
    aliases = _group_label_aliases(manifest)
    names = [
        aliases.get(name.strip(), name.strip())
        for name in groups.keys()
        if isinstance(name, str) and name.strip()
    ]
    return sorted({name.strip() for name in names})


def has_multi_groups(manifest: dict | None) -> bool:
    return len(extract_group_names(manifest)) >= 2
