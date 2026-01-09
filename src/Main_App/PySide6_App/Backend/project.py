# src/Main_App/PySide6_App/Backend/project.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from .preprocessing_settings import (
    PREPROCESSING_CANONICAL_KEYS,
    normalize_preprocessing_settings,
)

EXCEL_SUBFOLDER_NAME = "1 - Excel Data Files"
SNR_SUBFOLDER_NAME = "2 - SNR Plots"
STATS_SUBFOLDER_NAME = "3 - Statistical Analysis Results"
_LEGACY_BANDPASS_WARNED: set[Path] = set()

# Stable defaults used by GUI/processing
DEFAULTS: Dict[str, Any] = {
    "input_folder": "Input",
    "results_folder": ".",
    "options": {
        "mode": "single",
        "loreta": False,
    },
    # Friendly label; UI falls back to folder name if None/missing
    "name": None,
    # Event map expected by loadProject()
    "event_map": {},
    # Optional experimental groups + metadata
    "groups": {},
    # Placeholder for future participant → group mapping
    "participants": {},
    # Result subfolders relative to results_folder
    "subfolders": {
        "excel": EXCEL_SUBFOLDER_NAME,
        "snr": SNR_SUBFOLDER_NAME,
        "stats": STATS_SUBFOLDER_NAME,
    },
    # Preprocessing parameters expected by GUI (dict)
    "preprocessing": {},
}


def _resolve_subpath(project_root: Path, value: str) -> Path:
    """Manifest -> absolute path. Relative values resolve against project_root."""
    p = Path(value)
    return p if p.is_absolute() else (project_root / p).resolve()


def _relativize(project_root: Path, p: Path) -> str:
    """
    Absolute runtime path -> manifest-safe string.
    If inside project_root, store as relative. Else keep absolute.
    """
    try:
        pr = project_root.resolve()
        pp = Path(p).resolve()
        if pr == pp or pr in pp.parents:
            return os.fspath(pp.relative_to(pr))
    except Exception:
        pass
    return os.fspath(p)


def _stable_dump(data: Dict[str, Any]) -> str:
    """
    Deterministic JSON for change-detection comparisons.
    Do not use for on-disk pretty writes.
    """
    return json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _write_manifest_if_changed(manifest_path: Path, data: Dict[str, Any]) -> bool:
    new_compact = _stable_dump(data)
    if manifest_path.exists():
        try:
            current_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(current_dict, dict):
                current_dict = {}
        except Exception:
            current_dict = {}
        current_compact = _stable_dump(current_dict)
        if current_compact == new_compact:
            return False

    payload = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(manifest_path)
    return True


class Project:
    """
    Project model for PySide6 GUI.

    Public attributes:
      - project_root: Path
      - name: str
      - input_folder: Path (absolute)
      - results_folder: Path (absolute)
      - subfolders: Dict[str, Path] (absolute paths under results_folder)
      - options: Dict[str, Any]
      - preprocessing: Dict[str, Any]
      - event_map: Dict[str, Any]
      - groups: Dict[str, Dict[str, Any]]
      - participants: Dict[str, Dict[str, Any]]
      - manifest: Dict[str, Any]  (raw, for persistence)
    """

    def __init__(
        self,
        project_root: Path,
        manifest: Dict[str, Any],
        *,
        manifest_path: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.manifest_path = (
            manifest_path.resolve() if manifest_path is not None else self.project_root / "project.json"
        )
        self.manifest = manifest

        # Friendly name
        raw_name = manifest.get("name")
        self.name: str = str(raw_name) if raw_name else self.project_root.name

        # Resolve folders to absolute at runtime
        self.input_folder = _resolve_subpath(
            self.project_root, manifest.get("input_folder", DEFAULTS["input_folder"])
        )
        self.results_folder = _resolve_subpath(
            self.project_root, manifest.get("results_folder", DEFAULTS["results_folder"])
        )

        # Options with default keys ensured
        opts = manifest.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        merged_opts = DEFAULTS["options"].copy()
        merged_opts.update(opts)
        self.options = merged_opts

        # Preprocessing dict
        pp = manifest.get("preprocessing", {})
        legacy_inversion: dict[str, float] = {}
        try:
            self.preprocessing: Dict[str, Any] = normalize_preprocessing_settings(
                pp if isinstance(pp, Mapping) else {},
                allow_legacy_inversion=True,
                on_legacy_inversion=lambda original_high, original_low: legacy_inversion.update(
                    {"original_high": float(original_high), "original_low": float(original_low)}
                ),
            )
        except ValueError as exc:
            print(f"[PROJECT] Invalid preprocessing settings in manifest; using defaults: {exc}")
            self.preprocessing = normalize_preprocessing_settings({})
        else:
            if legacy_inversion and self.project_root not in _LEGACY_BANDPASS_WARNED:
                corrected_low = float(self.preprocessing.get("low_pass", 0))
                corrected_high = float(self.preprocessing.get("high_pass", 0))
                message = (
                    "Legacy preprocessing bandpass inverted in "
                    f"{self.manifest_path}: raw low_pass={legacy_inversion['original_low']} Hz, "
                    f"high_pass={legacy_inversion['original_high']} Hz -> corrected "
                    f"low_pass={corrected_low} Hz, high_pass={corrected_high} Hz."
                )
                print(f"[PROJECT] {message}")
                _LEGACY_BANDPASS_WARNED.add(self.project_root)
        self._legacy_inversion = legacy_inversion if legacy_inversion else None
        manifest["preprocessing"] = {
            key: self.preprocessing[key] for key in PREPROCESSING_CANONICAL_KEYS
        }

        # Event map dict
        ev = manifest.get("event_map", {})
        self.event_map: Dict[str, Any] = ev if isinstance(ev, dict) else {}

        # Optional groups metadata normalized to runtime-friendly form
        groups_raw = manifest.get("groups", {})
        self.groups: Dict[str, Dict[str, Any]] = {}
        if isinstance(groups_raw, Mapping):
            for raw_name, raw_info in groups_raw.items():
                try:
                    name = str(raw_name).strip()
                except Exception:
                    continue
                if not name:
                    continue
                info = raw_info if isinstance(raw_info, Mapping) else {}
                folder_value = info.get("raw_input_folder") if info else ""
                folder_path = (
                    _resolve_subpath(self.project_root, str(folder_value))
                    if folder_value
                    else self.input_folder
                )
                description_raw = info.get("description", "") if info else ""
                description = str(description_raw) if description_raw is not None else ""
                self.groups[name] = {
                    "raw_input_folder": folder_path,
                    "description": description,
                }

        # Participants metadata placeholder (currently stored verbatim)
        participants_raw = manifest.get("participants", {})
        self.participants: Dict[str, Dict[str, Any]] = {}
        if isinstance(participants_raw, Mapping):
            for raw_pid, raw_data in participants_raw.items():
                try:
                    participant_id = str(raw_pid).strip()
                except Exception:
                    continue
                if not participant_id:
                    continue
                entry = raw_data if isinstance(raw_data, Mapping) else {}
                group_name = entry.get("group") if entry else None
                if group_name is None:
                    self.participants[participant_id] = {}
                else:
                    self.participants[participant_id] = {"group": str(group_name)}

        # Results subfolders (absolute paths under results_folder)
        sub = manifest.get("subfolders", {})
        if not isinstance(sub, dict):
            sub = {}
        merged_sub = DEFAULTS["subfolders"].copy()
        merged_sub.update(sub)
        self.subfolders: Dict[str, Path] = {}
        for key, rel_name in merged_sub.items():
            base = Path(rel_name)
            abs_path = base if base.is_absolute() else (self.results_folder / base)
            abs_path.mkdir(parents=True, exist_ok=True)
            self.subfolders[key] = abs_path

    @staticmethod
    def load(
        path: Path,
        *,
        manifest: Dict[str, Any] | None = None,
        manifest_path: Path | None = None,
    ) -> "Project":
        """
        Load a project from folder. Accepts absolute or relative manifest paths.
        Ensures Input/Results and subfolders exist.
        """
        project_root = Path(path).resolve()
        resolved_manifest_path = (
            manifest_path.resolve() if manifest_path is not None else project_root / "project.json"
        )

        data: Dict[str, Any] = {}
        if manifest is None:
            if resolved_manifest_path.exists():
                data_raw = resolved_manifest_path.read_text(encoding="utf-8")
                try:
                    data = json.loads(data_raw)
                except Exception:
                    data = {}
        else:
            data = dict(manifest)
        if not isinstance(data, dict):
            data = {}
        raw_manifest: Dict[str, Any] = dict(data)

        # Normalize persisted event_map back into memory as {str: int}
        raw_map = data.get("event_map", {})
        if not isinstance(raw_map, dict):
            raw_map = {}
        ev_map: Dict[str, int] = {}
        for k, v in raw_map.items():
            try:
                ev_map[str(k)] = int(v)
            except Exception:
                continue
        data["event_map"] = ev_map

        # Shallow-merge defaults with existing data
        merged: Dict[str, Any] = dict(DEFAULTS)
        merged.update(data)

        # Ensure main directories exist using resolved absolute paths
        input_dir = _resolve_subpath(project_root, merged.get("input_folder", DEFAULTS["input_folder"]))
        results_dir = _resolve_subpath(project_root, merged.get("results_folder", DEFAULTS["results_folder"]))
        input_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        proj = Project(project_root, merged, manifest_path=resolved_manifest_path)
        proj.event_map = ev_map
        # Keep the merged view as the in-memory manifest so subsequent saves retain defaults
        proj.manifest = merged
        if proj._legacy_inversion is not None:
            raw_manifest["preprocessing"] = {
                key: proj.preprocessing[key] for key in PREPROCESSING_CANONICAL_KEYS
            }
            _write_manifest_if_changed(resolved_manifest_path, raw_manifest)
        return proj

    def save(self) -> None:
        """
        Persist manifest. Store relative paths when inside project_root.
        Keep absolute paths for out-of-project locations.
        """
        manifest_path = self.project_root / "project.json"

        # Build from in-memory manifest once
        data: Dict[str, Any] = dict(self.manifest)

        # Friendly name handling
        folder_name = self.project_root.name
        name_value = getattr(self, "name", folder_name)
        if name_value and name_value != folder_name:
            data["name"] = name_value
        else:
            # Drop redundant name equal to folder to keep file clean
            try:
                if "name" in data and str(data["name"]) == folder_name:
                    data.pop("name", None)
            except Exception:
                pass

        # Normalize current runtime folders back into manifest form
        current_input = Path(self.input_folder) if hasattr(self, "input_folder") and self.input_folder else Path(
            data.get("input_folder", DEFAULTS["input_folder"])
        )
        current_results = Path(self.results_folder) if hasattr(self, "results_folder") and self.results_folder else Path(
            data.get("results_folder", DEFAULTS["results_folder"])
        )
        data["input_folder"] = _relativize(self.project_root, current_input)
        data["results_folder"] = _relativize(self.project_root, current_results)

        # Options: ensure default keys exist, keep user values
        opts = data.get("options", {})
        if not isinstance(opts, dict):
            opts = {}
        normalized_opts = DEFAULTS["options"].copy()
        normalized_opts.update(opts)
        data["options"] = normalized_opts

        # Preprocessing: ensure dict type
        normalized_pp = normalize_preprocessing_settings(
            self.preprocessing if isinstance(self.preprocessing, Mapping) else {}
        )
        self.preprocessing = normalized_pp
        data["preprocessing"] = {
            key: normalized_pp[key] for key in PREPROCESSING_CANONICAL_KEYS
        }

        # Persist the live event map from runtime state, normalized to {str: int}
        live_map: Dict[str, Any] = getattr(self, "event_map", {}) or {}
        if not isinstance(live_map, dict):
            live_map = {}
        norm_map: Dict[str, int] = {}
        for k, v in live_map.items():
            try:
                norm_map[str(k)] = int(v)
            except Exception:
                # Skip malformed entries rather than crashing the save path.
                continue
        data["event_map"] = norm_map

        # Subfolders: persist relative names under results_folder when possible
        sub_out: Dict[str, str] = {}
        for key, abs_path in getattr(self, "subfolders", {}).items():
            try:
                rf = self.results_folder.resolve()
                sp = Path(abs_path).resolve()
                if rf == sp or rf in sp.parents:
                    rel = os.fspath(sp.relative_to(rf))
                    sub_out[key] = rel
                else:
                    sub_out[key] = os.fspath(sp)
            except Exception:
                sub_out[key] = os.fspath(abs_path)
        merged_sub = DEFAULTS["subfolders"].copy()
        merged_sub.update(sub_out)
        data["subfolders"] = merged_sub

        # Groups metadata persisted with stable relative paths when possible
        groups_out: Dict[str, Dict[str, Any]] = {}
        groups_live = getattr(self, "groups", {}) or {}
        if isinstance(groups_live, Mapping):
            for raw_name, raw_info in groups_live.items():
                try:
                    name = str(raw_name).strip()
                except Exception:
                    continue
                if not name:
                    continue
                info = raw_info if isinstance(raw_info, Mapping) else {}
                folder_value = info.get("raw_input_folder") if info else None
                folder_path = None
                if folder_value:
                    try:
                        folder_path = Path(folder_value)
                    except Exception:
                        folder_path = None
                folder_str = (
                    _relativize(self.project_root, folder_path)
                    if folder_path is not None
                    else ""
                )
                description = info.get("description", "") if info else ""
                groups_out[name] = {
                    "raw_input_folder": folder_str,
                    "description": str(description) if description is not None else "",
                }
        data["groups"] = groups_out

        # Participants metadata
        participants_out: Dict[str, Dict[str, Any]] = {}
        participants_live = getattr(self, "participants", {}) or {}
        if isinstance(participants_live, Mapping):
            for raw_pid, raw_info in participants_live.items():
                try:
                    participant_id = str(raw_pid).strip()
                except Exception:
                    continue
                if not participant_id:
                    continue
                info = raw_info if isinstance(raw_info, Mapping) else {}
                group_value = info.get("group") if info else None
                if group_value is None:
                    continue
                group_name = str(group_value).strip()
                if not group_name:
                    continue
                participants_out[participant_id] = {"group": group_name}
        data["participants"] = participants_out

        # Keep in-memory manifest consistent for subsequent operations.
        self.manifest = data

        # -------- Change-detection write --------
        # Compute a deterministic compact string for compare only
        new_compact = _stable_dump(data)
        if manifest_path.exists():
            try:
                current_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(current_dict, dict):
                    current_dict = {}
            except Exception:
                current_dict = {}
            current_compact = _stable_dump(current_dict)
            if current_compact == new_compact:
                # No changes; skip disk write
                return

        # Pretty write for human readability
        manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    def update_preprocessing(self, values: Mapping[str, Any]) -> Dict[str, Any]:
        """Update preprocessing settings using the shared normalizer."""

        normalized = normalize_preprocessing_settings(values)
        self.preprocessing = normalized
        self.manifest["preprocessing"] = {
            key: normalized[key] for key in PREPROCESSING_CANONICAL_KEYS
        }
        return normalized
