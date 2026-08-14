"""Shared harmonic-selection API for Stats-consuming tools."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_POLICY_ID,
    GROUP_SIGNIFICANT_POLICY_LABEL,
)

CANONICAL_HARMONIC_SOURCE = "fpvs_toolbox_significant_harmonics"
CUSTOM_HARMONIC_SOURCE = "custom_harmonics"


@dataclass(frozen=True)
class SharedHarmonicSelection:
    """Resolved harmonic list plus user-facing provenance."""

    source: str
    selected_harmonics_hz: tuple[float, ...]
    metadata: dict[str, object]
    fingerprint: dict[str, object]
    fingerprint_text: str
    output_label: str
    exploratory: bool = False


class CanonicalHarmonicSelectionError(RuntimeError):
    """User-actionable harmonic-selection failure."""

    def __init__(self, message: str, *, reason: str = "selection_failed") -> None:
        super().__init__(message)
        self.reason = reason


def load_project_processing_harmonics(
    *,
    project_root: str | Path | None,
    log_func: Callable[[str], None],
) -> SharedHarmonicSelection:
    """Load the processing-time project selection without recalculating it."""

    if project_root in (None, ""):
        raise CanonicalHarmonicSelectionError(
            "A loaded FPVS Toolbox project is required to use the saved "
            "processing-time significant harmonics.",
            reason="missing_project",
        )
    root = Path(project_root).resolve()
    try:
        from Main_App.processing.harmonic_selection_qc import (
            load_processing_harmonic_selection,
        )
        from Main_App.projects.project import Project

        selection = load_processing_harmonic_selection(
            Project.load(root),
            log_func=log_func,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise CanonicalHarmonicSelectionError(
            str(exc),
            reason="missing_processing_selection",
        ) from exc

    metadata = selection.to_metadata()
    return shared_selection_from_metadata(
        metadata,
        project_root=root,
    )


def shared_selection_from_metadata(
    metadata: Mapping[str, object],
    *,
    subjects: Sequence[str] | None = None,
    conditions: Sequence[str] | None = None,
    rois: Mapping[str, Sequence[str]] | None = None,
    project_root: str | Path | None = None,
    max_freq: float | None = None,
) -> SharedHarmonicSelection:
    """Build a shared selection object from Stats harmonic metadata."""

    selected = _float_tuple(
        metadata.get("selected_harmonics_hz")
        or metadata.get("included_harmonics_hz")
        or metadata.get("common_harmonics_hz")
    )
    if not selected:
        raise CanonicalHarmonicSelectionError(
            "FPVS Toolbox did not return any selected significant harmonics for "
            "this analysis definition.",
            reason="no_selected_harmonics",
        )

    fingerprint = harmonic_selection_fingerprint(
        metadata,
        subjects=subjects,
        conditions=conditions,
        rois=rois,
        project_root=project_root,
        max_freq=max_freq,
    )
    exploratory = bool(metadata.get("same_sample_adaptive", False))
    return SharedHarmonicSelection(
        source=CANONICAL_HARMONIC_SOURCE,
        selected_harmonics_hz=selected,
        metadata=dict(metadata),
        fingerprint=fingerprint,
        fingerprint_text=format_harmonic_selection_fingerprint(fingerprint),
        output_label="fpvs_toolbox_significant_harmonics",
        exploratory=exploratory,
    )


def custom_harmonic_selection(
    harmonics_hz: Sequence[float],
    *,
    label: str = "custom_harmonics",
) -> SharedHarmonicSelection:
    """Build provenance for an explicit custom fixed harmonic list."""

    selected = tuple(float(freq) for freq in harmonics_hz)
    metadata: dict[str, object] = {
        "harmonic_policy": CUSTOM_HARMONIC_SOURCE,
        "harmonic_policy_label": "Custom fixed harmonic list",
        "selected_harmonics_hz": list(selected),
        "included_harmonics_hz": list(selected),
        "custom_harmonics_warning": (
            "Custom harmonics may not match the FPVS Toolbox statistically "
            "significant harmonic list."
        ),
    }
    fingerprint = {
        "source": CUSTOM_HARMONIC_SOURCE,
        "policy": CUSTOM_HARMONIC_SOURCE,
        "policy_label": "Custom fixed harmonic list",
        "selected_harmonics_hz": list(selected),
        "exploratory": True,
    }
    return SharedHarmonicSelection(
        source=CUSTOM_HARMONIC_SOURCE,
        selected_harmonics_hz=selected,
        metadata=metadata,
        fingerprint=fingerprint,
        fingerprint_text=format_harmonic_selection_fingerprint(fingerprint),
        output_label=label,
        exploratory=True,
    )


def harmonic_selection_fingerprint(
    metadata: Mapping[str, object],
    *,
    subjects: Sequence[str] | None = None,
    conditions: Sequence[str] | None = None,
    rois: Mapping[str, Sequence[str]] | None = None,
    project_root: str | Path | None = None,
    max_freq: float | None = None,
) -> dict[str, object]:
    """Return a readable provenance payload for the harmonic selection."""

    selection_subjects = _string_list(metadata.get("selection_subjects")) or [
        str(subject) for subject in (subjects or ())
    ]
    selection_conditions = _string_list(metadata.get("selection_conditions")) or [
        str(condition) for condition in (conditions or ())
    ]
    roi_names = sorted(str(name) for name in (rois or {}).keys())
    selected = _float_tuple(
        metadata.get("selected_harmonics_hz")
        or metadata.get("included_harmonics_hz")
        or metadata.get("common_harmonics_hz")
    )
    detected = (
        _float_tuple(metadata.get("detected_significant_harmonics_hz"))
        if "detected_significant_harmonics_hz" in metadata
        else selected
    )
    canonical_fingerprint = str(metadata.get("selection_fingerprint") or "")
    if not canonical_fingerprint:
        canonical_fingerprint = compute_selection_fingerprint(metadata)
    return {
        "source": CANONICAL_HARMONIC_SOURCE,
        "policy": str(metadata.get("harmonic_policy") or GROUP_SIGNIFICANT_POLICY_ID),
        "policy_label": str(
            metadata.get("harmonic_policy_label") or GROUP_SIGNIFICANT_POLICY_LABEL
        ),
        "method_profile_id": str(
            metadata.get("harmonic_selection_profile") or "legacy_fpvs_toolbox"
        ),
        "method_profile_version": str(
            metadata.get("harmonic_selection_profile_version") or "1.0"
        ),
        "selection_fingerprint": canonical_fingerprint,
        "participant_count": len(selection_subjects),
        "participants": selection_subjects,
        "condition_count": len(selection_conditions),
        "conditions": selection_conditions,
        "roi_count": len(roi_names),
        "rois": roi_names,
        "electrode_scope": str(metadata.get("electrode_scope") or ""),
        "summation_method": str(metadata.get("summation_method") or ""),
        "z_threshold": metadata.get("z_threshold"),
        "base_frequency_hz": metadata.get("base_frequency_hz"),
        "oddball_frequency_hz": metadata.get("oddball_frequency_hz"),
        "max_frequency_hz": max_freq,
        "selected_harmonics_hz": list(selected),
        "detected_significant_harmonics_hz": list(detected),
        "highest_included_harmonic_hz": metadata.get("highest_included_harmonic_hz"),
        "summation_gap_guard_rule": metadata.get("summation_gap_guard_rule"),
        "summation_gap_guard_enabled": bool(
            metadata.get("summation_gap_guard_enabled", False)
        ),
        "summation_gap_guard_max_intervening_nonbase_harmonics": metadata.get(
            "summation_gap_guard_max_intervening_nonbase_harmonics"
        ),
        "summation_gap_guard_applied": bool(
            metadata.get("summation_gap_guard_applied", False)
        ),
        "summation_gap_guard_intervening_nonbase_harmonic_count": metadata.get(
            "summation_gap_guard_intervening_nonbase_harmonic_count"
        ),
        "summation_gap_guard_dropped_highest_significant_harmonic_hz": metadata.get(
            "summation_gap_guard_dropped_highest_significant_harmonic_hz"
        ),
        "selection_cache_source": str(metadata.get("selection_cache_source") or ""),
        "selection_cache_saved_at": str(metadata.get("selection_cache_saved_at") or ""),
        "project_root": str(project_root) if project_root not in (None, "") else "",
        "exploratory": bool(metadata.get("same_sample_adaptive", False)),
    }


def compute_selection_fingerprint(
    metadata: Mapping[str, object],
    *,
    scientific_context: Mapping[str, object] | None = None,
) -> str:
    """Hash stable scientific selection provenance, excluding workflow state."""

    transient = {
        "selection_fingerprint",
        "selection_cache_source",
        "selection_cache_saved_at",
        "selection_cache_key",
        "methods_summary",
    }
    payload = {
        str(key): value
        for key, value in metadata.items()
        if str(key) not in transient
    }
    if scientific_context:
        payload["scientific_context"] = dict(scientific_context)
    for key in (
        "selection_subjects",
        "selection_conditions",
        "declared_group_ids",
        "selection_electrode_mask",
    ):
        values = payload.get(key)
        if isinstance(values, (list, tuple, set)):
            payload[key] = sorted(
                (_json_safe(value) for value in values),
                key=lambda value: json.dumps(value, sort_keys=True),
            )
    sources = payload.get("source_workbook_fingerprints")
    if isinstance(sources, (list, tuple)):
        payload["source_workbook_fingerprints"] = sorted(
            (_json_safe(value) for value in sources),
            key=lambda value: json.dumps(value, sort_keys=True),
        )
    cells = payload.get("pooling_cells")
    if isinstance(cells, (list, tuple)):
        canonical_cells: list[object] = []
        for raw_cell in cells:
            cell = dict(raw_cell) if isinstance(raw_cell, Mapping) else raw_cell
            if isinstance(cell, dict) and isinstance(cell.get("participant_ids"), list):
                cell["participant_ids"] = sorted(
                    cell["participant_ids"], key=lambda value: str(value).casefold()
                )
            canonical_cells.append(_json_safe(cell))
        payload["pooling_cells"] = sorted(
            canonical_cells,
            key=lambda value: json.dumps(value, sort_keys=True),
        )
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def format_harmonic_selection_fingerprint(fingerprint: Mapping[str, object]) -> str:
    """Format harmonic provenance for GUI labels, logs, and text exports."""

    selected = _float_tuple(fingerprint.get("selected_harmonics_hz"))
    harmonics = ", ".join(f"{freq:g}" for freq in selected) or "none"
    if bool(fingerprint.get("exploratory")):
        return (
            "Custom/exploratory harmonics | "
            f"selected: {harmonics} Hz"
        )

    conditions = _string_list(fingerprint.get("conditions"))
    condition_text = ", ".join(conditions) if conditions else "not recorded"
    rois = _string_list(fingerprint.get("rois"))
    roi_text = f"{len(rois)} ROI(s)" if rois else "ROI scope from settings"
    z_threshold = fingerprint.get("z_threshold")
    z_text = f"z > {float(z_threshold):g}" if _is_number(z_threshold) else "z threshold not recorded"
    method = str(fingerprint.get("summation_method") or "not recorded")
    gap_text = ""
    if bool(fingerprint.get("summation_gap_guard_applied")):
        dropped = fingerprint.get(
            "summation_gap_guard_dropped_highest_significant_harmonic_hz"
        )
        count = fingerprint.get(
            "summation_gap_guard_intervening_nonbase_harmonic_count"
        )
        if _is_number(dropped) and _is_number(count):
            gap_text = (
                f" | gap guard: excluded {float(dropped):g} Hz "
                f"({int(float(count))} intervening eligible non-base harmonics)"
            )
    return (
        "FPVS Toolbox significant harmonics | "
        f"participants: {fingerprint.get('participant_count', 0)} | "
        f"conditions: {condition_text} | "
        f"scope: {fingerprint.get('electrode_scope') or 'not recorded'} ({roi_text}) | "
        f"{z_text} | method: {method} | selected: {harmonics} Hz"
        f"{gap_text}"
    )


def _float_tuple(value: object) -> tuple[float, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    else:
        try:
            parts = list(value)  # type: ignore[arg-type]
        except TypeError:
            parts = [value]
    out: list[float] = []
    for part in parts:
        try:
            freq = float(part)
        except (TypeError, ValueError):
            continue
        out.append(freq)
    return tuple(out)


def _string_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        return [str(item) for item in value]  # type: ignore[arg-type]
    except TypeError:
        return [str(value)]


def _is_number(value: object) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    return float(number) if math.isfinite(number) else None


__all__ = [
    "CANONICAL_HARMONIC_SOURCE",
    "CUSTOM_HARMONIC_SOURCE",
    "CanonicalHarmonicSelectionError",
    "SharedHarmonicSelection",
    "custom_harmonic_selection",
    "compute_selection_fingerprint",
    "format_harmonic_selection_fingerprint",
    "harmonic_selection_fingerprint",
    "load_project_processing_harmonics",
    "shared_selection_from_metadata",
]
