"""Utilities for coercing and normalizing preprocessing settings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping

from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    normalize_manual_removed_electrodes_map,
    normalize_removed_electrode_detection_mode,
)

try:  # pragma: no cover - fallback for isolated usage
    import config  # type: ignore
except Exception:  # pragma: no cover - fallback when config unavailable
    class _FallbackConfig:
        DEFAULT_STIM_CHANNEL = "Status"

    config = _FallbackConfig()  # type: ignore


@dataclass(frozen=True)
class _Field:
    name: str
    aliases: tuple[str, ...]
    default: Any
    type: str


_FLOAT = "float"
_INT = "int"
_STR = "str"
_BOOL = "bool"
_REMOVED_ELECTRODE_MODE = "removed_electrode_mode"
_MANUAL_REMOVED_ELECTRODES = "manual_removed_electrodes"
_MANUAL_EXCLUDED_PARTICIPANTS = "manual_excluded_participants"

_GROUP_SIGNIFICANT_POLICY_NAME = "Group-level significant harmonics (Volfart/Retter/Rossion style)"
_GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION = "union_roi_electrodes"
_GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST = "through_highest_significant"
_FIXED_PREDEFINED_DEFAULT_FREQUENCIES = "1.2, 2.4, 3.6, 4.8, 7.2"


_FIELDS: tuple[_Field, ...] = (
    _Field("low_pass", ("low_pass",), 50.0, _FLOAT),
    _Field("high_pass", ("high_pass",), 0.1, _FLOAT),
    _Field("downsample", ("downsample", "downsample_rate"), 256, _INT),
    _Field("rejection_z", ("rejection_z", "reject_thresh", "rejection_thresh"), 5.0, _FLOAT),
    _Field("epoch_start_s", ("epoch_start_s", "epoch_start"), -1.0, _FLOAT),
    _Field("epoch_end_s", ("epoch_end_s", "epoch_end"), 125.0, _FLOAT),
    _Field("ref_chan1", ("ref_chan1", "ref_channel1"), "EXG1", _STR),
    _Field("ref_chan2", ("ref_chan2", "ref_channel2"), "EXG2", _STR),
    _Field(
        "max_chan_idx_keep",
        ("max_chan_idx_keep", "max_idx_keep", "max_chan_idx"),
        64,
        _INT,
    ),
    _Field(
        "max_bad_chans",
        ("max_bad_chans", "max_bad_channels", "max_bad_channels_alert_thresh"),
        20,
        _INT,
    ),
    _Field(
        "auto_detect_removed_electrodes",
        (
            "auto_detect_removed_electrodes",
            "detect_removed_electrodes",
            "auto_mark_removed_electrodes",
        ),
        True,
        _BOOL,
    ),
    _Field(
        "removed_electrode_detection_mode",
        (
            "removed_electrode_detection_mode",
            "removed_electrode_qc_mode",
            "detect_removed_electrodes_mode",
        ),
        REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
        _REMOVED_ELECTRODE_MODE,
    ),
    _Field(
        "manual_removed_electrodes",
        (
            "manual_removed_electrodes",
            "manually_removed_electrodes",
            "manual_removed_electrode_map",
        ),
        {},
        _MANUAL_REMOVED_ELECTRODES,
    ),
    _Field(
        "manual_excluded_participants",
        (
            "manual_excluded_participants",
            "manually_excluded_participants",
            "excluded_participants",
            "participant_exclusions",
        ),
        [],
        _MANUAL_EXCLUDED_PARTICIPANTS,
    ),
    _Field(
        "max_parallel_workers_override",
        ("max_parallel_workers_override", "max_parallel_workers", "max_workers"),
        0,
        _INT,
    ),
    _Field(
        "harmonic_selection_policy",
        ("harmonic_selection_policy", "dv_policy_name", "bca_harmonic_policy"),
        _GROUP_SIGNIFICANT_POLICY_NAME,
        _STR,
    ),
    _Field(
        "group_significant_electrode_scope",
        ("group_significant_electrode_scope", "harmonic_selection_electrode_scope"),
        _GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        _STR,
    ),
    _Field(
        "group_significant_summation_method",
        ("group_significant_summation_method", "harmonic_summation_method"),
        _GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
        _STR,
    ),
    _Field(
        "fixed_harmonic_frequencies_hz",
        ("fixed_harmonic_frequencies_hz", "fixed_harmonics_hz"),
        _FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
        _STR,
    ),
    _Field(
        "fixed_harmonic_auto_exclude_base",
        ("fixed_harmonic_auto_exclude_base", "fixed_harmonics_auto_exclude_base"),
        True,
        _BOOL,
    ),
    _Field("stim_channel", ("stim_channel", "stim", "stim_channel_name"), config.DEFAULT_STIM_CHANNEL, _STR),
)


PREPROCESSING_CANONICAL_KEYS: tuple[str, ...] = tuple(field.name for field in _FIELDS)
PREPROCESSING_DEFAULTS: Dict[str, Any] = {field.name: field.default for field in _FIELDS}

_ALIASES_FOR_OUTPUT: dict[str, Iterable[str]] = {
    "downsample": ("downsample_rate",),
    "rejection_z": ("reject_thresh",),
    "epoch_start_s": ("epoch_start",),
    "epoch_end_s": ("epoch_end",),
    "max_chan_idx_keep": ("max_idx_keep",),
    "max_bad_chans": ("max_bad_channels_alert_thresh",),
    "auto_detect_removed_electrodes": (
        "detect_removed_electrodes",
        "auto_mark_removed_electrodes",
    ),
    "max_parallel_workers_override": ("max_parallel_workers", "max_workers"),
}


def _first_value(data: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    for alias in aliases:
        if alias in data:
            return data[alias]
    return None


def _coerce_float(value: Any, *, default: float, field: str) -> float:
    if value in (None, ""):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Invalid float for '{field}': {value!r}") from exc


def _coerce_int(value: Any, *, default: int, field: str) -> int:
    if value in (None, ""):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Invalid integer for '{field}': {value!r}") from exc


def _coerce_str(value: Any, *, default: str, field: str) -> str:
    if value in (None, ""):
        return str(default)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or str(default)
    raise ValueError(f"Invalid string for '{field}': {value!r}")  # pragma: no cover


def _coerce_bool(value: Any, *, default: bool, field: str) -> bool:
    if value in (None, ""):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        if lowered == "":
            return bool(default)
    raise ValueError(f"Invalid boolean for '{field}': {value!r}")  # pragma: no cover


def _coerce_removed_electrode_mode(value: Any, *, default: str) -> str:
    return normalize_removed_electrode_detection_mode(
        value,
        auto_detect_removed_electrodes=(default == REMOVED_ELECTRODE_DETECTION_MODE_AUTO),
    )


def _participant_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in value if not ch.isdigit()).casefold()
    digits = "".join(ch for ch in value if ch.isdigit())
    number = int(digits) if digits else -1
    return prefix, number, value.casefold()


def normalize_manual_excluded_participants(value: Any) -> list[str]:
    """Normalize user-supplied participant IDs excluded from processing."""

    if value in (None, ""):
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            import json

            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = None
        if decoded is not None:
            return normalize_manual_excluded_participants(decoded)
        raw_items: Iterable[Any] = text.replace(";", ",").split(",")
    elif isinstance(value, Mapping):
        raw_items = (
            key
            for key, enabled in value.items()
            if enabled not in (False, None, "", 0)
        )
    elif isinstance(value, Iterable):
        raw_items = value
    else:
        raw_items = (value,)

    seen: set[str] = set()
    normalized: list[str] = []
    for raw_item in raw_items:
        pid = str(raw_item or "").strip()
        if not pid:
            continue
        key = pid.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(pid)
    return sorted(normalized, key=_participant_sort_key)


def _validate_bandpass(low_pass: float, high_pass: float) -> None:
    """Ensure low/high cutoffs are sensible and not inverted."""

    if low_pass is not None and low_pass <= 0:
        raise ValueError("Low-pass cutoff must be positive.")
    if high_pass is not None and high_pass < 0:
        raise ValueError("High-pass cutoff cannot be negative.")
    if low_pass is not None and high_pass is not None and high_pass > 0 and low_pass <= high_pass:
        raise ValueError(
            f"Low-pass cutoff ({low_pass} Hz) must be greater than high-pass cutoff ({high_pass} Hz). "
            "Please swap the values."
        )


def _looks_like_legacy_bandpass(low_pass: float | None, high_pass: float | None) -> bool:
    """Detect legacy-inverted bandpass values (both positive, low <= high)."""

    if low_pass is None or high_pass is None:
        return False
    if low_pass <= 0 or high_pass <= 0:
        return False
    return low_pass <= high_pass


def normalize_preprocessing_settings(
    raw: Mapping[str, Any] | None,
    *,
    allow_legacy_inversion: bool = False,
    on_legacy_inversion: Callable[[float, float], None] | None = None,
) -> Dict[str, Any]:
    """Normalize preprocessing values into canonical keys and runtime aliases."""

    source: Mapping[str, Any] = raw or {}
    normalized: Dict[str, Any] = {}

    for field in _FIELDS:
        raw_value = _first_value(source, field.aliases)
        if field.type == _FLOAT:
            normalized[field.name] = _coerce_float(raw_value, default=field.default, field=field.name)
        elif field.type == _INT:
            normalized[field.name] = _coerce_int(raw_value, default=field.default, field=field.name)
        elif field.type == _STR:
            normalized[field.name] = _coerce_str(raw_value, default=field.default, field=field.name)
        elif field.type == _BOOL:
            normalized[field.name] = _coerce_bool(raw_value, default=field.default, field=field.name)
        elif field.type == _REMOVED_ELECTRODE_MODE:
            normalized[field.name] = _coerce_removed_electrode_mode(
                raw_value,
                default=str(field.default),
            )
        elif field.type == _MANUAL_REMOVED_ELECTRODES:
            normalized[field.name] = normalize_manual_removed_electrodes_map(raw_value)
        elif field.type == _MANUAL_EXCLUDED_PARTICIPANTS:
            normalized[field.name] = normalize_manual_excluded_participants(raw_value)
        else:  # pragma: no cover - defensive guard
            normalized[field.name] = raw_value if raw_value is not None else field.default

    mode_raw = _first_value(
        source,
        (
            "removed_electrode_detection_mode",
            "removed_electrode_qc_mode",
            "detect_removed_electrodes_mode",
        ),
    )
    if mode_raw in (None, ""):
        normalized["removed_electrode_detection_mode"] = (
            normalize_removed_electrode_detection_mode(
                None,
                auto_detect_removed_electrodes=normalized[
                    "auto_detect_removed_electrodes"
                ],
            )
        )
    normalized["auto_detect_removed_electrodes"] = (
        normalized["removed_electrode_detection_mode"]
        == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
    )

    low_pass_val = float(normalized.get("low_pass")) if "low_pass" in normalized else None
    high_pass_val = float(normalized.get("high_pass")) if "high_pass" in normalized else None
    max_workers_override = int(normalized.get("max_parallel_workers_override", 0))

    try:
        _validate_bandpass(low_pass=low_pass_val, high_pass=high_pass_val)
    except ValueError:
        if allow_legacy_inversion and _looks_like_legacy_bandpass(low_pass_val, high_pass_val):
            normalized["low_pass"], normalized["high_pass"] = high_pass_val, low_pass_val
            _validate_bandpass(
                low_pass=float(normalized.get("low_pass")),
                high_pass=float(normalized.get("high_pass")),
            )
            if on_legacy_inversion is not None:
                on_legacy_inversion(high_pass_val, low_pass_val)
        else:
            raise

    if max_workers_override < 0:
        raise ValueError(
            "max_parallel_workers_override must be zero or a positive integer."
        )

    # Surface runtime aliases expected by legacy helpers without duplicating storage
    for canonical, aliases in _ALIASES_FOR_OUTPUT.items():
        for alias in aliases:
            normalized[alias] = normalized[canonical]

    return normalized


__all__ = [
    "normalize_preprocessing_settings",
    "normalize_manual_excluded_participants",
    "PREPROCESSING_CANONICAL_KEYS",
    "PREPROCESSING_DEFAULTS",
]
