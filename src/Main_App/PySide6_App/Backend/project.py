# src/Main_App/PySide6_App/Backend/project.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

# Stable defaults used by GUI/processing
DEFAULTS: Dict[str, Any] = {
    "input_folder": "Input",
    "results_folder": "Results",
    "options": {
        "mode": "single",
        "loreta": False,
    },
    # Friendly label; UI falls back to folder name if None/missing
    "name": None,
    # Event map expected by loadProject()
    "event_map": {},
    # Result subfolders relative to results_folder
    "subfolders": {
        "excel": "Excel",
        "snr": "SNR",
        "stats": "Stats",
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
      - manifest: Dict[str, Any]  (raw, for persistence)
    """

    def __init__(self, project_root: Path, manifest: Dict[str, Any]) -> None:
        self.project_root = project_root.resolve()
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
        self.preprocessing: Dict[str, Any] = pp if isinstance(pp, dict) else {}

        # Event map dict
        ev = manifest.get("event_map", {})
        self.event_map: Dict[str, Any] = ev if isinstance(ev, dict) else {}

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
    def load(path: Path) -> "Project":
        """
        Load a project from folder. Accepts absolute or relative manifest paths.
        Ensures Input/Results and subfolders exist.
        """
        project_root = Path(path).resolve()
        manifest_path = project_root / "project.json"

        if manifest_path.exists():
            data_raw = manifest_path.read_text(encoding="utf-8")
            try:
                data = json.loads(data_raw)
            except Exception:
                data = {}
        else:
            data = {}
        if not isinstance(data, dict):
            data = {}

        # Normalize persisted event_map back into memory as {str: int}
        raw_map = data.get("event_map", {})
        if not isinstance(raw_map, dict):
            raw_map = {}
        ev_map: dict[str, int] = {}
        for k, v in raw_map.items():
            try:
                ev_map[str(k)] = int(v)
            except Exception:
                continue
        data["event_map"] = ev_map

        # Shallow-merge defaults with existing data
        merged: Dict[str, Any] = {}
        merged.update(DEFAULTS)
        merged.update(data)

        # Ensure main directories exist using resolved absolute paths
        input_dir = _resolve_subpath(project_root, merged.get("input_folder", DEFAULTS["input_folder"]))
        results_dir = _resolve_subpath(project_root, merged.get("results_folder", DEFAULTS["results_folder"]))
        input_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        proj = Project(project_root, merged)
        proj.event_map = ev_map
        proj.manifest = data
        return proj

    def save(self) -> None:
        """
        Persist manifest. Store relative paths when inside project_root.
        Keep absolute paths for out-of-project locations.
        """
        manifest_path = self.project_root / "project.json"

        # Start from in-memory manifest to preserve unknown keys
        base_manifest = self.manifest if isinstance(self.manifest, dict) else {}
        data: Dict[str, Any] = dict(base_manifest)

        # Friendly name handling
        folder_name = self.project_root.name
        name_value = getattr(self, "name", folder_name)
        if name_value and name_value != folder_name:
            data["name"] = name_value
        else:
            if "name" in data:
                try:
                    if str(data["name"]) == folder_name:
                        data.pop("name", None)
                except Exception:
                    pass

        # Normalize current runtime folders back into manifest form
        current_input = Path(data.get("input_folder", DEFAULTS["input_folder"]))
        current_results = Path(data.get("results_folder", DEFAULTS["results_folder"]))

        if hasattr(self, "input_folder") and self.input_folder:
            current_input = Path(self.input_folder)
        if hasattr(self, "results_folder") and self.results_folder:
            current_results = Path(self.results_folder)

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
        pp = data.get("preprocessing", {})
        data["preprocessing"] = pp if isinstance(pp, dict) else {}

        # Persist the live event map from runtime state.
        # Normalize to {str: int} without altering keys used elsewhere.
        live_map: dict[str, Any] = getattr(self, "event_map", {}) or {}
        if not isinstance(live_map, dict):
            live_map = {}
        norm_map: dict[str, int] = {}
        for k, v in live_map.items():
            try:
                key_s = str(k)
                val_i = int(v)
                norm_map[key_s] = val_i
            except Exception:
                # Skip malformed entries rather than crashing the save path.
                continue
        data["event_map"] = norm_map
        # Keep in-memory manifest consistent for subsequent operations.
        self.manifest = data

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

        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
