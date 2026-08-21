"""Project model and manifest persistence helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Collection
from pathlib import Path
from typing import Any, Dict, Mapping

from .grouping import (
    make_group_id as make_group_id,
    normalize_project_groups,
    normalize_project_participants,
)
from .preprocessing_settings import (
    PREPROCESSING_CANONICAL_KEYS,
    REPEATED_SESSION_PREPROCESSING_KEYS,
    normalize_preprocessing_settings,
)
from .recordings import (
    normalize_project_recording_sources,
    normalize_project_recordings,
    normalize_project_sessions,
)

EXCEL_SUBFOLDER_NAME = "1 - Excel Data Files"
SNR_SUBFOLDER_NAME = "2 - SNR Plots"
STATS_SUBFOLDER_NAME = "3 - Statistical Analysis Results"
PROJECT_SCHEMA_VERSION = "2.1.0"
REPEATED_SESSION_PROJECT_SCHEMA_VERSION = "2.2.0"
_LEGACY_BANDPASS_WARNED: set[Path] = set()
logger = logging.getLogger(__name__)

_COMPATIBILITY_MANIFEST_KEY = "compatibility"
_PROCESSING_FINGERPRINT_V9_KEY = "processing_fingerprint_v9"
_PROCESSING_FINGERPRINT_V9_DEFAULTS = {
    "epoch_start_s": -1.0,
    "epoch_end_s": 125.0,
}

# Stable defaults used by GUI/processing
DEFAULTS: Dict[str, Any] = {
    "input_folder": "Input",
    "results_folder": ".",
    "options": {
        "mode": "batch",
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


def _preprocessing_manifest_payload(
    normalized: Mapping[str, Any],
    *,
    repeated_session: bool,
) -> dict[str, Any]:
    """Persist legacy keys exactly and recording-scoped QC only for v2.2."""

    payload = {
        key: normalized[key] for key in PREPROCESSING_CANONICAL_KEYS
    }
    if not repeated_session:
        return payload
    for key in REPEATED_SESSION_PREPROCESSING_KEYS:
        value = normalized.get(key)
        if value in (None, "", [], {}):
            continue
        payload[key] = value
    return payload


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


def _group_lock_fingerprint(groups: Mapping[str, Mapping[str, Any]]) -> str:
    """Return a stable fingerprint for the complete locked group definition."""

    payload = [
        {
            "group_id": group_id,
            "label": str(info.get("label") or ""),
            "folder_name": str(info.get("folder_name") or ""),
            "raw_input_folder": os.path.normcase(
                os.fspath(Path(info["raw_input_folder"]).resolve(strict=False))
            ),
            "description": str(info.get("description") or ""),
        }
        for group_id, info in sorted(groups.items())
    ]
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recordings_lock_fingerprint(
    sessions: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    recordings: Mapping[str, Mapping[str, Any]],
) -> str:
    """Return a stable fingerprint for locked repeated-session assignments."""

    payload = {
        "sessions": [
            {
                "session_id": session_id,
                "label": str(info.get("label") or ""),
                "visit_index": int(info["visit_index"]),
            }
            for session_id, info in sorted(sessions.items())
        ],
        "recording_sources": [
            {
                "source_id": source_id,
                "group_id": str(info["group_id"]),
                "session_id": str(info["session_id"]),
                "raw_input_folder": os.path.normcase(
                    os.fspath(
                        Path(info["raw_input_folder"]).resolve(strict=False)
                    )
                ),
            }
            for source_id, info in sorted(sources.items())
        ],
        "recordings": [
            {
                "recording_id": recording_id,
                "participant_id": str(info["participant_id"]),
                "session_id": str(info["session_id"]),
                "source_id": str(info["source_id"]),
                "raw_file": os.path.normcase(
                    os.fspath(Path(info["raw_file"]).resolve(strict=False))
                ),
                "visit_index": int(info["visit_index"]),
                "days_from_baseline": (
                    float(info["days_from_baseline"])
                    if info.get("days_from_baseline") is not None
                    else None
                ),
            }
            for recording_id, info in sorted(recordings.items())
        ],
    }
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _preserve_disk_tools_metadata(
    manifest_path: Path,
    data: Dict[str, Any],
    *,
    updated_tool_namespaces: Collection[str] = (),
) -> Dict[str, Any]:
    if not manifest_path.exists():
        return data
    try:
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return data
    if not isinstance(current, Mapping):
        return data
    current_tools = current.get("tools")
    if not isinstance(current_tools, Mapping):
        return data
    merged_tools = dict(current_tools)
    in_memory_tools = data.get("tools")
    for tool_name in sorted({str(name) for name in updated_tool_namespaces if name}):
        if isinstance(in_memory_tools, Mapping) and tool_name in in_memory_tools:
            merged_tools[tool_name] = in_memory_tools[tool_name]
        else:
            merged_tools.pop(tool_name, None)
    data["tools"] = merged_tools
    return data


def _processing_fingerprint_v9_compatibility(
    manifest: Mapping[str, Any],
) -> dict[str, float]:
    """Extract retired epoch values solely for exact v9 fingerprint replay."""

    preprocessing = manifest.get("preprocessing")
    preprocessing_source = (
        preprocessing if isinstance(preprocessing, Mapping) else {}
    )
    compatibility = manifest.get(_COMPATIBILITY_MANIFEST_KEY)
    compatibility_source = (
        compatibility if isinstance(compatibility, Mapping) else {}
    )
    fingerprint_v9 = compatibility_source.get(_PROCESSING_FINGERPRINT_V9_KEY)
    fingerprint_source = (
        fingerprint_v9 if isinstance(fingerprint_v9, Mapping) else {}
    )

    values: dict[str, float] = {}
    for canonical_key, runtime_alias in (
        ("epoch_start_s", "epoch_start"),
        ("epoch_end_s", "epoch_end"),
    ):
        default = _PROCESSING_FINGERPRINT_V9_DEFAULTS[canonical_key]
        raw_value = fingerprint_source.get(canonical_key)
        if raw_value in (None, ""):
            raw_value = preprocessing_source.get(canonical_key)
        if raw_value in (None, ""):
            raw_value = preprocessing_source.get(runtime_alias)
        try:
            values[canonical_key] = float(raw_value)
        except (TypeError, ValueError):
            values[canonical_key] = float(default)
    return values


def _store_processing_fingerprint_v9_compatibility(
    manifest: Dict[str, Any],
    values: Mapping[str, Any],
) -> None:
    """Persist non-default v9 replay values outside active preprocessing."""

    normalized = {
        key: float(values.get(key, default))
        for key, default in _PROCESSING_FINGERPRINT_V9_DEFAULTS.items()
    }
    compatibility = manifest.get(_COMPATIBILITY_MANIFEST_KEY)
    compatibility_out = (
        dict(compatibility) if isinstance(compatibility, Mapping) else {}
    )
    if normalized != _PROCESSING_FINGERPRINT_V9_DEFAULTS:
        compatibility_out[_PROCESSING_FINGERPRINT_V9_KEY] = normalized
    else:
        compatibility_out.pop(_PROCESSING_FINGERPRINT_V9_KEY, None)

    if compatibility_out:
        manifest[_COMPATIBILITY_MANIFEST_KEY] = compatibility_out
    else:
        manifest.pop(_COMPATIBILITY_MANIFEST_KEY, None)


class Project:
    """
    Project model for PySide6 GUI.

    Public attributes:
      - project_root: Path
      - name: str
      - input_folder: Path | None (absolute for single-group projects; None when
        groups provide the canonical raw-data roots)
      - results_folder: Path (absolute)
      - subfolders: Dict[str, Path] (absolute paths under results_folder)
      - options: Dict[str, Any]
      - preprocessing: Dict[str, Any]
      - event_map: Dict[str, Any]
      - groups: Dict[str, Dict[str, Any]]
      - participants: Dict[str, Dict[str, Any]]
      - sessions: Dict[str, Dict[str, Any]]
      - recording_sources: Dict[str, Dict[str, Any]]
      - recordings: Dict[str, Dict[str, Any]]
      - processing_fingerprint_v9_compatibility: Dict[str, float]
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
        mode = str(merged_opts.get("mode", "batch")).strip().lower()
        if mode not in {"single", "batch"}:
            raise ValueError(
                "Project options.mode must be either 'single' or 'batch'."
            )
        merged_opts["mode"] = mode
        self.options = merged_opts

        # Preserve retired epoch values only for exact replay of existing v9
        # processing fingerprints. They are not active preprocessing settings.
        self.processing_fingerprint_v9_compatibility = (
            _processing_fingerprint_v9_compatibility(manifest)
        )

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
            logger.warning(
                "Invalid preprocessing settings in manifest; using defaults: %s",
                exc,
                extra={"project_root": str(self.project_root), "manifest_path": str(self.manifest_path)},
            )
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
                logger.warning(
                    "legacy_preprocessing_bandpass_inverted",
                    extra={
                        "project_root": str(self.project_root),
                        "manifest_path": str(self.manifest_path),
                        "detail": message,
                    },
                )
                _LEGACY_BANDPASS_WARNED.add(self.project_root)
        self._legacy_inversion = legacy_inversion if legacy_inversion else None
        manifest["preprocessing"] = _preprocessing_manifest_payload(
            self.preprocessing,
            repeated_session=bool(
                manifest.get("sessions")
                or manifest.get("recording_sources")
                or manifest.get("recordings")
            ),
        )
        _store_processing_fingerprint_v9_compatibility(
            manifest,
            self.processing_fingerprint_v9_compatibility,
        )

        # Event map dict
        ev = manifest.get("event_map", {})
        self.event_map: Dict[str, Any] = ev if isinstance(ev, dict) else {}
        self.groups_locked = bool(manifest.get("groups_locked", False))
        locked_at = manifest.get("groups_locked_at")
        self.groups_locked_at = str(locked_at).strip() if locked_at else None

        # Canonical group/participant metadata. This pure normalizer is also the
        # read-only source consumed by project-aware downstream tools.
        self.groups, group_aliases = normalize_project_groups(
            self.project_root,
            manifest.get("groups", {}),
        )
        self.participants = normalize_project_participants(
            self.project_root,
            manifest.get("participants", {}),
            self.groups,
            group_aliases,
        )
        self.sessions = normalize_project_sessions(manifest.get("sessions", {}))
        self.recording_sources = normalize_project_recording_sources(
            self.project_root,
            manifest.get("recording_sources", {}),
            self.groups,
            self.sessions,
        )
        self.recordings = normalize_project_recordings(
            self.project_root,
            manifest.get("recordings", {}),
            self.groups,
            self.participants,
            self.sessions,
            self.recording_sources,
        )
        if self.groups:
            # Grouped projects have no project-level raw-data folder. Keeping a
            # synthesized ``<project>/Input`` path here would recreate the old
            # ambiguous fallback as runtime state even though it is omitted
            # from project.json.
            self.input_folder = None
        current_group_fingerprint = _group_lock_fingerprint(self.groups)
        stored_group_fingerprint = str(
            manifest.get("groups_lock_fingerprint") or ""
        ).strip()
        if (
            self.groups_locked
            and stored_group_fingerprint
            and stored_group_fingerprint != current_group_fingerprint
        ):
            raise ValueError(
                "Locked project group definitions do not match their stored "
                "fingerprint. Restore the original group IDs, labels, raw folders, "
                "and output folder names, or create a new project."
            )
        self._groups_lock_fingerprint = (
            current_group_fingerprint if self.groups_locked else None
        )
        has_recording_metadata = bool(
            self.sessions or self.recording_sources or self.recordings
        )
        current_recordings_fingerprint = _recordings_lock_fingerprint(
            self.sessions,
            self.recording_sources,
            self.recordings,
        )
        stored_recordings_fingerprint = str(
            manifest.get("recordings_lock_fingerprint") or ""
        ).strip()
        if (
            self.groups_locked
            and has_recording_metadata
            and stored_recordings_fingerprint
            and stored_recordings_fingerprint != current_recordings_fingerprint
        ):
            raise ValueError(
                "Locked project session, recording-source, or recording definitions "
                "do not match their stored fingerprint. Restore the registered "
                "repeated-session layout or create a new project."
            )
        self._recordings_lock_fingerprint = (
            current_recordings_fingerprint
            if self.groups_locked and has_recording_metadata
            else None
        )

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

        # Ensure project-managed directories exist. Multi-group raw folders can
        # live outside the project and must not be silently recreated if moved.
        input_dir = _resolve_subpath(project_root, merged.get("input_folder", DEFAULTS["input_folder"]))
        results_dir = _resolve_subpath(project_root, merged.get("results_folder", DEFAULTS["results_folder"]))
        groups_raw = merged.get("groups", {})
        if not isinstance(groups_raw, Mapping) or not groups_raw:
            input_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        proj = Project(project_root, merged, manifest_path=resolved_manifest_path)
        proj.event_map = ev_map
        # Keep the merged view as the in-memory manifest so subsequent saves retain defaults
        proj.manifest = merged
        if proj._legacy_inversion is not None:
            raw_manifest["preprocessing"] = _preprocessing_manifest_payload(
                proj.preprocessing,
                repeated_session=bool(
                    raw_manifest.get("sessions")
                    or raw_manifest.get("recording_sources")
                    or raw_manifest.get("recordings")
                ),
            )
            _store_processing_fingerprint_v9_compatibility(
                raw_manifest,
                proj.processing_fingerprint_v9_compatibility,
            )
            _write_manifest_if_changed(resolved_manifest_path, raw_manifest)
        return proj

    def save(self, *, updated_tool_namespaces: Collection[str] = ()) -> None:
        """
        Persist manifest. Store relative paths when inside project_root.
        Keep absolute paths for out-of-project locations.

        Disk-authored tool namespaces remain authoritative unless their names
        are explicitly listed in ``updated_tool_namespaces``.
        """
        manifest_path = self.project_root / "project.json"

        # Build from in-memory manifest once
        data: Dict[str, Any] = dict(self.manifest)
        data["schema_version"] = PROJECT_SCHEMA_VERSION

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
        data["results_folder"] = _relativize(self.project_root, current_results)

        # Options: ensure default keys exist, keep user values
        opts = getattr(self, "options", data.get("options", {}))
        if not isinstance(opts, dict):
            opts = {}
        normalized_opts = DEFAULTS["options"].copy()
        normalized_opts.update(opts)
        mode = str(normalized_opts.get("mode", "batch")).strip().lower()
        if mode not in {"single", "batch"}:
            raise ValueError(
                "Project options.mode must be either 'single' or 'batch'."
            )
        normalized_opts["mode"] = mode
        self.options = normalized_opts
        data["options"] = normalized_opts

        # Preprocessing: ensure dict type
        normalized_pp = normalize_preprocessing_settings(
            self.preprocessing if isinstance(self.preprocessing, Mapping) else {}
        )
        self.preprocessing = normalized_pp
        data["preprocessing"] = _preprocessing_manifest_payload(
            normalized_pp,
            repeated_session=bool(
                getattr(self, "sessions", {})
                or getattr(self, "recording_sources", {})
                or getattr(self, "recordings", {})
            ),
        )
        _store_processing_fingerprint_v9_compatibility(
            data,
            self.processing_fingerprint_v9_compatibility,
        )

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
        if getattr(self, "groups_locked", False):
            data["groups_locked"] = True
            if getattr(self, "groups_locked_at", None):
                data["groups_locked_at"] = str(self.groups_locked_at)
        else:
            data.pop("groups_locked", None)
            data.pop("groups_locked_at", None)
            data.pop("groups_lock_fingerprint", None)

        # Groups metadata persisted with stable relative paths when possible
        groups_out: Dict[str, Dict[str, Any]] = {}
        groups_live = getattr(self, "groups", {}) or {}
        normalized_groups, group_aliases = normalize_project_groups(
            self.project_root,
            groups_live,
        )
        current_group_fingerprint = _group_lock_fingerprint(normalized_groups)
        if getattr(self, "groups_locked", False):
            locked_fingerprint = getattr(
                self,
                "_groups_lock_fingerprint",
                None,
            )
            if (
                locked_fingerprint is not None
                and locked_fingerprint != current_group_fingerprint
            ):
                raise ValueError(
                    "Locked project group definitions cannot be changed. Restore "
                    "the registered group layout or create a new project."
                )
            self._groups_lock_fingerprint = current_group_fingerprint
            data["groups_lock_fingerprint"] = current_group_fingerprint
        self.groups = normalized_groups
        for group_id, info in normalized_groups.items():
            group_out: Dict[str, Any] = {
                "label": str(info["label"]),
                "folder_name": str(info["folder_name"]),
                "raw_input_folder": _relativize(
                    self.project_root,
                    Path(info["raw_input_folder"]),
                ),
            }
            if info.get("description"):
                group_out["description"] = str(info["description"])
            groups_out[group_id] = group_out
        if groups_out:
            data["groups"] = groups_out
            data.pop("input_folder", None)
        else:
            data.pop("groups", None)
            data["input_folder"] = _relativize(self.project_root, current_input)

        # Participants metadata
        participants_out: Dict[str, Dict[str, Any]] = {}
        participants_live = getattr(self, "participants", {}) or {}
        normalized_participants = normalize_project_participants(
            self.project_root,
            participants_live,
            normalized_groups,
            group_aliases,
        )
        self.participants = normalized_participants
        for participant_id, info in normalized_participants.items():
            participant_out: Dict[str, Any] = {}
            if info.get("group_id"):
                participant_out["group_id"] = str(info["group_id"])
            if info.get("raw_file"):
                participant_out["raw_file"] = _relativize(
                    self.project_root,
                    Path(info["raw_file"]),
                )
            if participant_out:
                participants_out[participant_id] = participant_out
        if participants_out:
            data["participants"] = participants_out
        else:
            data.pop("participants", None)

        # Optional v2.2 repeated-session metadata. Legacy projects retain the
        # exact v2.1 persisted shape until at least one of these mappings is used.
        normalized_sessions = normalize_project_sessions(
            getattr(self, "sessions", {}) or {}
        )
        normalized_sources = normalize_project_recording_sources(
            self.project_root,
            getattr(self, "recording_sources", {}) or {},
            normalized_groups,
            normalized_sessions,
        )
        normalized_recordings = normalize_project_recordings(
            self.project_root,
            getattr(self, "recordings", {}) or {},
            normalized_groups,
            normalized_participants,
            normalized_sessions,
            normalized_sources,
        )
        self.sessions = normalized_sessions
        self.recording_sources = normalized_sources
        self.recordings = normalized_recordings
        has_recording_metadata = bool(
            normalized_sessions or normalized_sources or normalized_recordings
        )
        current_recordings_fingerprint = _recordings_lock_fingerprint(
            normalized_sessions,
            normalized_sources,
            normalized_recordings,
        )
        locked_recordings_fingerprint = getattr(
            self,
            "_recordings_lock_fingerprint",
            None,
        )
        if (
            getattr(self, "groups_locked", False)
            and locked_recordings_fingerprint is not None
            and locked_recordings_fingerprint != current_recordings_fingerprint
        ):
            raise ValueError(
                "Locked project session, recording-source, and recording assignments "
                "cannot be changed. Restore the registered repeated-session layout "
                "or create a new project."
            )
        if has_recording_metadata:
            data["schema_version"] = REPEATED_SESSION_PROJECT_SCHEMA_VERSION
            data["sessions"] = {
                session_id: {
                    "label": str(info["label"]),
                    "visit_index": int(info["visit_index"]),
                }
                for session_id, info in normalized_sessions.items()
            }
            data["recording_sources"] = {
                source_id: {
                    "group_id": str(info["group_id"]),
                    "session_id": str(info["session_id"]),
                    "raw_input_folder": _relativize(
                        self.project_root,
                        Path(info["raw_input_folder"]),
                    ),
                }
                for source_id, info in normalized_sources.items()
            }
            recordings_out: Dict[str, Dict[str, Any]] = {}
            for recording_id, info in normalized_recordings.items():
                recording_out: Dict[str, Any] = {
                    "participant_id": str(info["participant_id"]),
                    "session_id": str(info["session_id"]),
                    "source_id": str(info["source_id"]),
                    "raw_file": _relativize(
                        self.project_root,
                        Path(info["raw_file"]),
                    ),
                    "visit_index": int(info["visit_index"]),
                }
                if info.get("days_from_baseline") is not None:
                    recording_out["days_from_baseline"] = float(
                        info["days_from_baseline"]
                    )
                recordings_out[recording_id] = recording_out
            data["recordings"] = recordings_out

            if getattr(self, "groups_locked", False):
                self._recordings_lock_fingerprint = current_recordings_fingerprint
                data["recordings_lock_fingerprint"] = (
                    current_recordings_fingerprint
                )
            else:
                self._recordings_lock_fingerprint = None
                data.pop("recordings_lock_fingerprint", None)
        else:
            data["schema_version"] = PROJECT_SCHEMA_VERSION
            data.pop("sessions", None)
            data.pop("recording_sources", None)
            data.pop("recordings", None)
            data.pop("recordings_lock_fingerprint", None)
            self._recordings_lock_fingerprint = None

        data = _preserve_disk_tools_metadata(
            manifest_path,
            data,
            updated_tool_namespaces=updated_tool_namespaces,
        )

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
        self.manifest["preprocessing"] = _preprocessing_manifest_payload(
            normalized,
            repeated_session=bool(
                getattr(self, "sessions", {})
                or getattr(self, "recording_sources", {})
                or getattr(self, "recordings", {})
            ),
        )
        return normalized
