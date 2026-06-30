"""Shared harmonic-selection API for Stats-consuming tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from Main_App import SettingsManager
from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    GROUP_SIGNIFICANT_POLICY_ID,
    GROUP_SIGNIFICANT_POLICY_LABEL,
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
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


def analysis_base_frequency_hz() -> float:
    """Return the configured FPVS base frequency used by Stats."""

    try:
        return float(SettingsManager().get("analysis", "base_freq", "6.0"))
    except (TypeError, ValueError):
        return 6.0


def analysis_bca_upper_limit_hz() -> float | None:
    """Return the configured BCA candidate harmonic ceiling used by Stats."""

    try:
        value = float(SettingsManager().get("analysis", "bca_upper_limit", "16.8"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def select_canonical_group_harmonics(
    *,
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
    base_frequency_hz: float,
    rois: Mapping[str, Sequence[str]] | None,
    log_func: Callable[[str], None],
    dv_policy: dict[str, object] | DVPolicySettings | None = None,
    max_freq: float | None = None,
    project_root: str | Path | None = None,
) -> SharedHarmonicSelection:
    """Resolve the canonical FPVS Toolbox significant-harmonic list."""

    settings = (
        dv_policy
        if isinstance(dv_policy, DVPolicySettings)
        else normalize_dv_policy(dv_policy)
    )
    if settings.name != GROUP_SIGNIFICANT_POLICY_NAME:
        raise CanonicalHarmonicSelectionError(
            "The canonical FPVS Toolbox harmonic selection uses group-level "
            "significant harmonics. Fixed harmonic lists are custom/exploratory "
            "overrides and cannot replace the canonical selection.",
            reason="custom_policy_selected",
        )

    subject_list = [str(subject) for subject in subjects]
    condition_list = [str(condition) for condition in conditions]
    try:
        selection = build_group_significant_harmonic_selection(
            subjects=subject_list,
            conditions=condition_list,
            subject_data={
                str(subject): {
                    str(condition): str(path)
                    for condition, path in (condition_map or {}).items()
                }
                for subject, condition_map in subject_data.items()
            },
            base_frequency_hz=float(base_frequency_hz),
            rois={str(name): [str(ch) for ch in channels] for name, channels in (rois or {}).items()},
            log_func=log_func,
            settings=settings,
            max_freq=max_freq,
            project_root=project_root,
        )
    except RuntimeError as exc:
        raise CanonicalHarmonicSelectionError(
            _user_message_for_selection_failure(str(exc)),
            reason=_reason_for_selection_failure(str(exc)),
        ) from exc

    metadata = selection.to_metadata()
    return shared_selection_from_metadata(
        metadata,
        subjects=subject_list,
        conditions=condition_list,
        rois=rois,
        project_root=project_root,
        max_freq=max_freq,
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
    return SharedHarmonicSelection(
        source=CANONICAL_HARMONIC_SOURCE,
        selected_harmonics_hz=selected,
        metadata=dict(metadata),
        fingerprint=fingerprint,
        fingerprint_text=format_harmonic_selection_fingerprint(fingerprint),
        output_label="fpvs_toolbox_significant_harmonics",
        exploratory=False,
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
    detected = _float_tuple(
        metadata.get("detected_significant_harmonics_hz") or selected
    )
    return {
        "source": CANONICAL_HARMONIC_SOURCE,
        "policy": str(metadata.get("harmonic_policy") or GROUP_SIGNIFICANT_POLICY_ID),
        "policy_label": str(
            metadata.get("harmonic_policy_label") or GROUP_SIGNIFICANT_POLICY_LABEL
        ),
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
        "selection_cache_source": str(metadata.get("selection_cache_source") or ""),
        "selection_cache_saved_at": str(metadata.get("selection_cache_saved_at") or ""),
        "project_root": str(project_root) if project_root not in (None, "") else "",
        "exploratory": False,
    }


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
    return (
        "FPVS Toolbox significant harmonics | "
        f"participants: {fingerprint.get('participant_count', 0)} | "
        f"conditions: {condition_text} | "
        f"scope: {fingerprint.get('electrode_scope') or 'not recorded'} ({roi_text}) | "
        f"{z_text} | method: {method} | selected: {harmonics} Hz"
    )


def _user_message_for_selection_failure(message: str) -> str:
    reason = _reason_for_selection_failure(message)
    if reason == "missing_processed_data":
        return (
            "FPVS Toolbox could not find the processed FullFFT/BCA outputs needed "
            "to identify significant harmonics. Reprocess the project data, then "
            "run this tool again so harmonic selection can be performed automatically.\n\n"
            f"Details: {message}"
        )
    if reason == "no_significant_harmonics":
        return (
            "No group-level significant harmonics were found for the current "
            "analysis definition. The canonical workflow has stopped. You can "
            "run an exploratory fixed-list check from Advanced > custom harmonics, "
            "but those outputs will be labeled as custom/exploratory.\n\n"
            f"Details: {message}"
        )
    return message


def _reason_for_selection_failure(message: str) -> str:
    lower = message.lower()
    if "found no oddball harmonics above" in lower or "no significant harmonics" in lower:
        return "no_significant_harmonics"
    missing_tokens = (
        "fullfft amplitude",
        "full-spectrum",
        "bca (uv)",
        "missing columns",
        "requires workbooks",
        "regenerate workbooks",
        "processed excel outputs",
    )
    if any(token in lower for token in missing_tokens):
        return "missing_processed_data"
    return "selection_failed"


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


__all__ = [
    "CANONICAL_HARMONIC_SOURCE",
    "CUSTOM_HARMONIC_SOURCE",
    "CanonicalHarmonicSelectionError",
    "SharedHarmonicSelection",
    "analysis_base_frequency_hz",
    "analysis_bca_upper_limit_hz",
    "custom_harmonic_selection",
    "format_harmonic_selection_fingerprint",
    "harmonic_selection_fingerprint",
    "select_canonical_group_harmonics",
    "shared_selection_from_metadata",
]
