"""Utilities for coercing and normalizing preprocessing settings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping

from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    REMOVED_ELECTRODE_DETECTION_MODE_OFF,
    normalize_manual_removed_electrodes_map,
    normalize_removed_electrode_detection_mode,
)
from Main_App.processing.interpolation_burden import (
    InterpolationBurdenError,
    normalize_interpolation_burden_review_decision,
)
from Main_App.processing.kurtosis_qc import (
    KurtosisQCError,
    normalize_kurtosis_review_decisions_by_recording,
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
_LINE_NOISE_FREQUENCY = "line_noise_frequency"
_ELECTRODE_MONTAGE = "electrode_montage"
_ELECTRODE_MAPPING_PROFILE = "electrode_mapping_profile"
_REMOVED_ELECTRODE_LEGACY_BOOL = "removed_electrode_legacy_bool"
_REMOVED_ELECTRODE_MODE = "removed_electrode_mode"
_MANUAL_REMOVED_ELECTRODES = "manual_removed_electrodes"
_MANUAL_REMOVED_ELECTRODES_BY_RECORDING = (
    "manual_removed_electrodes_by_recording"
)
MANUAL_REMOVED_ELECTRODES_ENABLED_KEY = "manual_removed_electrodes_enabled"
_MANUAL_REMOVED_ELECTRODES_ENABLED_ALIASES = (
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    "apply_manual_removed_electrodes",
    "use_manual_removed_electrodes",
)
_MANUAL_EXCLUDED_PARTICIPANTS = "manual_excluded_participants"
_MANUAL_EXCLUDED_RECORDINGS = "manual_excluded_recordings"
_MANUAL_EXCLUDED_PARTICIPANT_CONDITIONS = (
    "manual_excluded_participant_conditions"
)
_MANUAL_EXCLUDED_RECORDING_CONDITIONS = (
    "manual_excluded_recording_conditions"
)
INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY = (
    "interpolation_burden_review_decisions"
)
_INTERPOLATION_BURDEN_REVIEW_DECISIONS = "interpolation_burden_review_decisions"
KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY = (
    "kurtosis_review_decisions_by_recording"
)
KURTOSIS_AUTO_INTERPOLATE_ALL_KEY = "kurtosis_auto_interpolate_all"
_KURTOSIS_REVIEW_DECISIONS_BY_RECORDING = (
    "kurtosis_review_decisions_by_recording"
)

_GROUP_SIGNIFICANT_POLICY_NAME = "Group-level significant harmonics (Volfart/Retter/Rossion style)"
_FIXED_PREDEFINED_POLICY_NAME = "Fixed / predefined harmonic list"
_GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION = "union_roi_electrodes"
_GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL = "all_scalp_electrodes"
_GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST = "through_highest_significant"
_GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES = "two_consecutive_failures"
_FIXED_PREDEFINED_DEFAULT_FREQUENCIES = "1.2, 2.4, 3.6, 4.8, 7.2"
_FIXED_HARMONIC_INPUT_FREQUENCY_LIST = "frequency_list"
_FIXED_HARMONIC_INPUT_UPPER_HARMONIC = "upper_harmonic_index"
_NEW_PROJECT_FIXED_UPPER_HARMONIC_INDEX = 6

LEGACY_HARMONIC_SELECTION_PROFILE = "legacy_fpvs_toolbox"
FIXED_HARMONIC_SELECTION_PROFILE = "fixed_preregistered_domain"
SIGNIFICANT_ONLY_HARMONIC_SELECTION_PROFILE = "significant_only_exploratory"
NEW_PROJECT_HARMONIC_SELECTION_PROFILE = (
    "dzhelyova_poncet_two_consecutive_failures"
)
HARMONIC_SELECTION_PROFILE_VERSION = "1.0"

REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION = "1.0.0"
REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY = "ready"
REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED = (
    "confirmation_required"
)
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF = (
    "new_project_default_off"
)
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE = "saved_mode"
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN = "legacy_boolean"
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING = "legacy_missing"
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE = (
    "invalid_saved_value"
)
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT = (
    "fpvs_studio_import"
)
REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED = "user_confirmed"

_REMOVED_ELECTRODE_MODE_ALIASES = (
    "removed_electrode_detection_mode",
    "removed_electrode_qc_mode",
    "detect_removed_electrodes_mode",
)
_REMOVED_ELECTRODE_LEGACY_BOOLEAN_ALIASES = (
    "auto_detect_removed_electrodes",
    "detect_removed_electrodes",
    "auto_mark_removed_electrodes",
)
_REMOVED_ELECTRODE_CHOICE_METADATA_KEYS = (
    "removed_electrode_detection_choice_schema_version",
    "removed_electrode_detection_choice_status",
    "removed_electrode_detection_choice_source",
)
REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS = (
    "removed_electrode_detection_mode",
    "auto_detect_removed_electrodes",
    *_REMOVED_ELECTRODE_CHOICE_METADATA_KEYS,
)


class RemovedElectrodeDetectionConfirmationRequired(RuntimeError):
    """Raised when an older project needs an explicit detector choice."""

ELECTRODE_MONTAGE_BIOSEMI64 = "biosemi64"
ELECTRODE_MAPPING_PROFILE_ANATOMICAL = "anatomical_labels"
ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1 = "biosemi64_1020_ab_v1"
SUPPORTED_ELECTRODE_MONTAGES: tuple[tuple[str, str], ...] = (
    (ELECTRODE_MONTAGE_BIOSEMI64, "BioSemi ActiveTwo 64"),
)
SUPPORTED_ELECTRODE_MAPPING_PROFILES: tuple[tuple[str, str], ...] = (
    (ELECTRODE_MAPPING_PROFILE_ANATOMICAL, "Anatomical BDF labels (default)"),
    (
        ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
        "BioSemi standard 64 10-20 A1-A32 / B1-B32 wiring (v1)",
    ),
)


_FIELDS: tuple[_Field, ...] = (
    _Field("low_pass", ("low_pass",), 50.0, _FLOAT),
    _Field("high_pass", ("high_pass",), 0.1, _FLOAT),
    _Field("downsample", ("downsample", "downsample_rate"), 256, _INT),
    _Field(
        "line_noise_filter_enabled",
        ("line_noise_filter_enabled",),
        True,
        _BOOL,
    ),
    _Field(
        "line_noise_frequency_hz",
        ("line_noise_frequency_hz",),
        60,
        _LINE_NOISE_FREQUENCY,
    ),
    _Field("rejection_z", ("rejection_z", "reject_thresh", "rejection_thresh"), 5.0, _FLOAT),
    _Field("ref_chan1", ("ref_chan1", "ref_channel1"), "EXG1", _STR),
    _Field("ref_chan2", ("ref_chan2", "ref_channel2"), "EXG2", _STR),
    _Field(
        "electrode_montage",
        ("electrode_montage",),
        ELECTRODE_MONTAGE_BIOSEMI64,
        _ELECTRODE_MONTAGE,
    ),
    _Field(
        "electrode_mapping_profile",
        ("electrode_mapping_profile",),
        ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        _ELECTRODE_MAPPING_PROFILE,
    ),
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
        _REMOVED_ELECTRODE_LEGACY_BOOLEAN_ALIASES,
        False,
        _REMOVED_ELECTRODE_LEGACY_BOOL,
    ),
    _Field(
        "removed_electrode_detection_mode",
        _REMOVED_ELECTRODE_MODE_ALIASES,
        REMOVED_ELECTRODE_DETECTION_MODE_OFF,
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
        MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
        _MANUAL_REMOVED_ELECTRODES_ENABLED_ALIASES,
        False,
        _BOOL,
    ),
    _Field(
        "manual_removed_electrodes_by_recording",
        (
            "manual_removed_electrodes_by_recording",
            "recording_removed_electrodes",
        ),
        {},
        _MANUAL_REMOVED_ELECTRODES_BY_RECORDING,
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
        "manual_excluded_recordings",
        (
            "manual_excluded_recordings",
            "excluded_recordings",
            "recording_exclusions",
        ),
        [],
        _MANUAL_EXCLUDED_RECORDINGS,
    ),
    _Field(
        "manual_excluded_participant_conditions",
        (
            "manual_excluded_participant_conditions",
            "excluded_participant_conditions",
            "participant_condition_exclusions",
        ),
        {},
        _MANUAL_EXCLUDED_PARTICIPANT_CONDITIONS,
    ),
    _Field(
        "manual_excluded_recording_conditions",
        (
            "manual_excluded_recording_conditions",
            "excluded_recording_conditions",
            "recording_condition_exclusions",
        ),
        {},
        _MANUAL_EXCLUDED_RECORDING_CONDITIONS,
    ),
    _Field(
        INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY,
        (INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY,),
        {},
        _INTERPOLATION_BURDEN_REVIEW_DECISIONS,
    ),
    _Field(
        KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
        (KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,),
        {},
        _KURTOSIS_REVIEW_DECISIONS_BY_RECORDING,
    ),
    _Field(KURTOSIS_AUTO_INTERPOLATE_ALL_KEY, (KURTOSIS_AUTO_INTERPOLATE_ALL_KEY,), False, _BOOL),
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
        "harmonic_selection_profile",
        (
            "harmonic_selection_profile",
            "harmonic_selection_profile_id",
            "harmonic_method_profile",
        ),
        LEGACY_HARMONIC_SELECTION_PROFILE,
        _STR,
    ),
    _Field(
        "harmonic_selection_profile_version",
        ("harmonic_selection_profile_version",),
        HARMONIC_SELECTION_PROFILE_VERSION,
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
        "fixed_harmonic_input_mode",
        ("fixed_harmonic_input_mode",),
        _FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
        _STR,
    ),
    _Field(
        "fixed_harmonic_upper_harmonic_index",
        ("fixed_harmonic_upper_harmonic_index",),
        0,
        _INT,
    ),
    _Field(
        "fixed_harmonic_upper_frequency_hz",
        ("fixed_harmonic_upper_frequency_hz",),
        0.0,
        _FLOAT,
    ),
    _Field(
        "fixed_harmonic_auto_exclude_base",
        ("fixed_harmonic_auto_exclude_base", "fixed_harmonics_auto_exclude_base"),
        True,
        _BOOL,
    ),
    _Field(
        "group_significant_selection_electrodes",
        (
            "group_significant_selection_electrodes",
            "harmonic_selection_electrodes",
        ),
        "",
        _STR,
    ),
    _Field("stim_channel", ("stim_channel", "stim", "stim_channel_name"), config.DEFAULT_STIM_CHANNEL, _STR),
)


REPEATED_SESSION_PREPROCESSING_KEYS: tuple[str, ...] = (
    "manual_removed_electrodes_by_recording",
    "manual_excluded_recordings",
    "manual_excluded_recording_conditions",
)
PREPROCESSING_CANONICAL_KEYS: tuple[str, ...] = tuple(
    field.name
    for field in _FIELDS
    if field.name not in REPEATED_SESSION_PREPROCESSING_KEYS
) + _REMOVED_ELECTRODE_CHOICE_METADATA_KEYS
PREPROCESSING_DEFAULTS: Dict[str, Any] = {field.name: field.default for field in _FIELDS}


def new_project_preprocessing_settings() -> Dict[str, Any]:
    """Return explicit settings for a genuinely new Toolbox project.

    Missing profile fields continue to normalize to the historical method so
    opening an older project never silently changes its scientific outcome.
    Project-creation entry points call this helper to opt new projects into the
    publication-aligned, balanced two-consecutive-failure profile.
    """

    return normalize_preprocessing_settings(
        {
            **PREPROCESSING_DEFAULTS,
            "removed_electrode_detection_mode": (
                REMOVED_ELECTRODE_DETECTION_MODE_OFF
            ),
            "auto_detect_removed_electrodes": False,
            "removed_electrode_detection_choice_schema_version": (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            ),
            "removed_electrode_detection_choice_status": (
                REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
            ),
            "removed_electrode_detection_choice_source": (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF
            ),
            "harmonic_selection_profile": NEW_PROJECT_HARMONIC_SELECTION_PROFILE,
            "harmonic_selection_profile_version": HARMONIC_SELECTION_PROFILE_VERSION,
            "group_significant_electrode_scope": _GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
            "group_significant_summation_method": (
                _GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
            ),
            "fixed_harmonic_input_mode": (
                _FIXED_HARMONIC_INPUT_UPPER_HARMONIC
            ),
            "fixed_harmonic_upper_harmonic_index": (
                _NEW_PROJECT_FIXED_UPPER_HARMONIC_INDEX
            ),
        }
    )

_ALIASES_FOR_OUTPUT: dict[str, Iterable[str]] = {
    "downsample": ("downsample_rate",),
    "rejection_z": ("reject_thresh",),
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


def _first_present_nonblank_value(
    data: Mapping[str, Any],
    aliases: Iterable[str],
) -> tuple[bool, Any]:
    for alias in aliases:
        if alias in data and data[alias] not in (None, ""):
            return True, data[alias]
    return False, None


def _normalize_explicit_removed_electrode_mode(value: Any) -> str | None:
    if isinstance(value, bool):
        return (
            REMOVED_ELECTRODE_DETECTION_MODE_AUTO
            if value
            else REMOVED_ELECTRODE_DETECTION_MODE_OFF
        )
    if value in (None, ""):
        return None
    text = str(value).strip().casefold().replace("_", " ").replace("-", " ")
    if text in {"auto", "conservative", "conservative auto", "true", "on"}:
        return REMOVED_ELECTRODE_DETECTION_MODE_AUTO
    if text in {"manual", "manual list", "manual metadata"}:
        return REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
    if text in {"off", "false", "none", "no"}:
        return REMOVED_ELECTRODE_DETECTION_MODE_OFF
    return None


def _normalize_removed_electrode_detection_choice(
    source: Mapping[str, Any],
    normalized: Dict[str, Any],
) -> None:
    """Resolve detector choice without mistaking a missing legacy value for Auto."""

    mode_present, mode_raw = _first_present_nonblank_value(
        source,
        _REMOVED_ELECTRODE_MODE_ALIASES,
    )
    boolean_present, boolean_raw = _first_present_nonblank_value(
        source,
        _REMOVED_ELECTRODE_LEGACY_BOOLEAN_ALIASES,
    )
    explicit_mode = (
        _normalize_explicit_removed_electrode_mode(mode_raw)
        if mode_present
        else None
    )
    boolean_mode: str | None = None
    if boolean_present:
        try:
            boolean_enabled = _coerce_bool(
                boolean_raw,
                default=False,
                field="auto_detect_removed_electrodes",
            )
        except ValueError:
            pass
        else:
            boolean_mode = (
                REMOVED_ELECTRODE_DETECTION_MODE_AUTO
                if boolean_enabled
                else REMOVED_ELECTRODE_DETECTION_MODE_OFF
            )
    metadata_present = any(
        key in source for key in _REMOVED_ELECTRODE_CHOICE_METADATA_KEYS
    )

    if metadata_present:
        version = str(
            source.get("removed_electrode_detection_choice_schema_version") or ""
        ).strip()
        status = str(
            source.get("removed_electrode_detection_choice_status") or ""
        ).strip()
        choice_source = str(
            source.get("removed_electrode_detection_choice_source") or ""
        ).strip()
        valid_sources = {
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED,
        }
        valid_statuses = {
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY,
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
        }
        metadata_is_valid = (
            version == REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            and status in valid_statuses
            and choice_source in valid_sources
            and (
                status != REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
                or choice_source
                in {
                    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING,
                    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
                }
            )
            and (
                status != REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
                or explicit_mode is not None
                or boolean_mode is not None
            )
        )
        if metadata_is_valid:
            if (
                status
                == REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
            ):
                resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
            else:
                resolved_mode = explicit_mode or boolean_mode
        elif (
            status
            == REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
        ):
            # A recorded pending choice is never converted into consent merely
            # because the provisional Off/Auto compatibility field is present.
            version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
            choice_source = (
                choice_source
                if choice_source
                in {
                    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING,
                    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
                }
                else REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE
            )
            resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
        elif explicit_mode is not None:
            # Recover a partially written/corrupt provenance record from the
            # valid saved behavior without discarding unrelated preprocessing.
            version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
            choice_source = REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE
            resolved_mode = explicit_mode
        elif boolean_mode is not None:
            version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
            choice_source = REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN
            resolved_mode = boolean_mode
        else:
            version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
            choice_source = (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE
            )
            resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
    elif explicit_mode is not None:
        version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
        status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
        choice_source = REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE
        resolved_mode = explicit_mode
    elif boolean_present:
        version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
        if boolean_mode is None:
            status = (
                REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
            )
            choice_source = (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE
            )
            resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
        else:
            status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
            choice_source = (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN
            )
            resolved_mode = boolean_mode
    elif mode_present:
        version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
        status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
        choice_source = (
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE
        )
        resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
    else:
        version = REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
        status = REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
        choice_source = REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING
        resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF

    normalized["removed_electrode_detection_mode"] = resolved_mode
    if resolved_mode == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL:
        # ``Manual`` was the legacy mutually exclusive mode.  The v3 control
        # separates it into automatic detection Off plus an independently
        # active manual list, preserving its actual historical behavior.
        resolved_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
        normalized[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = True
    normalized["auto_detect_removed_electrodes"] = (
        resolved_mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
    )
    normalized["removed_electrode_detection_mode"] = resolved_mode
    normalized["removed_electrode_detection_choice_schema_version"] = version
    normalized["removed_electrode_detection_choice_status"] = status
    normalized["removed_electrode_detection_choice_source"] = choice_source


def removed_electrode_detection_choice_was_saved(
    raw: Mapping[str, Any] | None,
) -> bool:
    """Return whether a manifest contains an explicit detector-choice signal."""

    source = raw if isinstance(raw, Mapping) else {}
    if any(key in source for key in _REMOVED_ELECTRODE_CHOICE_METADATA_KEYS):
        return True
    mode_present, mode_raw = _first_present_nonblank_value(
        source,
        _REMOVED_ELECTRODE_MODE_ALIASES,
    )
    if mode_present and _normalize_explicit_removed_electrode_mode(mode_raw) is not None:
        return True
    boolean_present, boolean_raw = _first_present_nonblank_value(
        source,
        _REMOVED_ELECTRODE_LEGACY_BOOLEAN_ALIASES,
    )
    if not boolean_present:
        return False
    try:
        _coerce_bool(
            boolean_raw,
            default=False,
            field="auto_detect_removed_electrodes",
        )
    except ValueError:
        return False
    return True


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


def _coerce_line_noise_frequency(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return int(default)
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Line-noise frequency must be exactly 50 or 60 Hz."
        ) from exc
    if not numeric.is_integer() or int(numeric) not in {50, 60}:
        raise ValueError("Line-noise frequency must be exactly 50 or 60 Hz.")
    return int(numeric)


def _coerce_supported_choice(
    value: Any,
    *,
    default: str,
    field: str,
    supported: Iterable[str],
    description: str,
) -> str:
    if value in (None, ""):
        return default
    if not isinstance(value, str):
        raise ValueError(f"Invalid {description} for '{field}': {value!r}")
    normalized = value.strip().casefold()
    allowed = tuple(supported)
    if normalized not in allowed:
        allowed_text = ", ".join(allowed)
        raise ValueError(
            f"Unsupported {description} {value!r}. Supported value(s): "
            f"{allowed_text}."
        )
    return normalized


def normalize_electrode_montage(value: Any) -> str:
    """Return the sole supported project-owned EEG montage identifier."""

    return _coerce_supported_choice(
        value,
        default=ELECTRODE_MONTAGE_BIOSEMI64,
        field="electrode_montage",
        supported=(item[0] for item in SUPPORTED_ELECTRODE_MONTAGES),
        description="electrode montage",
    )


def normalize_electrode_mapping_profile(value: Any) -> str:
    """Return a supported explicit BioSemi64 channel-label mapping profile."""

    return _coerce_supported_choice(
        value,
        default=ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        field="electrode_mapping_profile",
        supported=(item[0] for item in SUPPORTED_ELECTRODE_MAPPING_PROFILES),
        description="electrode mapping profile",
    )


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


def normalize_manual_excluded_recordings(value: Any) -> list[str]:
    """Normalize canonical recording IDs excluded from processing."""

    return normalize_manual_excluded_participants(value)


def normalize_interpolation_burden_review_decisions(
    value: Any,
) -> dict[str, dict[str, object]]:
    """Validate recording-scoped QC-07 decisions without applying them."""

    if value in (None, ""):
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            import json

            decoded = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Interpolation-burden decisions must be a recording-to-decision map."
            ) from exc
        return normalize_interpolation_burden_review_decisions(decoded)
    if not isinstance(value, Mapping):
        raise ValueError(
            "Interpolation-burden decisions must be a recording-to-decision map."
        )

    normalized: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for raw_key, raw_decision in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        try:
            decision = normalize_interpolation_burden_review_decision(raw_decision)
        except InterpolationBurdenError as exc:
            raise ValueError(str(exc)) from exc
        if key.casefold() != decision.processing_id.casefold():
            raise ValueError(
                "Interpolation-burden decision key does not match its recording identity."
            )
        if key.casefold() in seen:
            raise ValueError(
                "Interpolation-burden decisions contain duplicate recording identities."
            )
        seen.add(key.casefold())
        normalized[decision.processing_id] = decision.to_payload()
    return dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))


def normalize_manual_excluded_participant_conditions(
    value: Any,
) -> dict[str, list[str]]:
    """Normalize participant-scoped condition exclusions for downstream tools."""

    if value in (None, ""):
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            import json

            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = None
        if decoded is None:
            raise ValueError(
                "Participant-condition exclusions must be a PID-to-condition map."
            )
        return normalize_manual_excluded_participant_conditions(decoded)
    if not isinstance(value, Mapping):
        raise ValueError(
            "Participant-condition exclusions must be a PID-to-condition map."
        )

    participant_casing: dict[str, str] = {}
    conditions_by_participant: dict[str, dict[str, str]] = {}
    for raw_pid, raw_conditions in value.items():
        pid = str(raw_pid or "").strip()
        if not pid:
            continue
        pid_key = pid.casefold()
        participant_casing.setdefault(pid_key, pid)
        if raw_conditions in (None, ""):
            continue
        if isinstance(raw_conditions, str):
            condition_items: Iterable[Any] = raw_conditions.replace(";", ",").split(",")
        elif isinstance(raw_conditions, Mapping):
            condition_items = (
                condition
                for condition, enabled in raw_conditions.items()
                if enabled not in (False, None, "", 0)
            )
        elif isinstance(raw_conditions, Iterable):
            condition_items = raw_conditions
        else:
            condition_items = (raw_conditions,)

        condition_lookup = conditions_by_participant.setdefault(pid_key, {})
        for raw_condition in condition_items:
            condition = str(raw_condition or "").strip()
            if not condition:
                continue
            condition_lookup.setdefault(condition.casefold(), condition)

    normalized: dict[str, list[str]] = {}
    for pid_key in sorted(
        conditions_by_participant,
        key=lambda key: _participant_sort_key(participant_casing[key]),
    ):
        condition_lookup = conditions_by_participant[pid_key]
        if not condition_lookup:
            continue
        normalized[participant_casing[pid_key]] = sorted(
            condition_lookup.values(),
            key=str.casefold,
        )
    return normalized


def normalize_manual_excluded_recording_conditions(
    value: Any,
) -> dict[str, list[str]]:
    """Normalize recording-scoped condition exclusions for downstream tools."""

    return normalize_manual_excluded_participant_conditions(value)


def is_participant_condition_excluded(
    exclusions: Mapping[str, Iterable[str]] | None,
    participant_id: str,
    condition: str,
) -> bool:
    """Return whether a participant-condition pair is excluded, case-insensitively."""

    participant_key = str(participant_id or "").strip().casefold()
    condition_key = str(condition or "").strip().casefold()
    if not participant_key or not condition_key:
        return False
    normalized = normalize_manual_excluded_participant_conditions(exclusions)
    return any(
        pid.casefold() == participant_key
        and any(label.casefold() == condition_key for label in labels)
        for pid, labels in normalized.items()
    )


def is_recording_condition_excluded(
    exclusions: Mapping[str, Iterable[str]] | None,
    recording_id: str,
    condition: str,
) -> bool:
    """Return whether a recording-condition pair is excluded."""

    return is_participant_condition_excluded(
        normalize_manual_excluded_recording_conditions(exclusions),
        recording_id,
        condition,
    )


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
        elif field.type == _REMOVED_ELECTRODE_LEGACY_BOOL:
            try:
                normalized[field.name] = _coerce_bool(
                    raw_value,
                    default=field.default,
                    field=field.name,
                )
            except ValueError:
                # Choice migration below records the malformed legacy value as
                # unresolved. Do not let it discard unrelated preprocessing.
                normalized[field.name] = bool(field.default)
        elif field.type == _LINE_NOISE_FREQUENCY:
            normalized[field.name] = _coerce_line_noise_frequency(
                raw_value,
                default=int(field.default),
            )
        elif field.type == _ELECTRODE_MONTAGE:
            normalized[field.name] = normalize_electrode_montage(raw_value)
        elif field.type == _ELECTRODE_MAPPING_PROFILE:
            normalized[field.name] = normalize_electrode_mapping_profile(raw_value)
        elif field.type == _REMOVED_ELECTRODE_MODE:
            normalized[field.name] = _coerce_removed_electrode_mode(
                raw_value,
                default=str(field.default),
            )
        elif field.type == _MANUAL_REMOVED_ELECTRODES:
            normalized[field.name] = normalize_manual_removed_electrodes_map(raw_value)
        elif field.type == _MANUAL_REMOVED_ELECTRODES_BY_RECORDING:
            normalized[field.name] = normalize_manual_removed_electrodes_map(raw_value)
        elif field.type == _MANUAL_EXCLUDED_PARTICIPANTS:
            normalized[field.name] = normalize_manual_excluded_participants(raw_value)
        elif field.type == _MANUAL_EXCLUDED_RECORDINGS:
            normalized[field.name] = normalize_manual_excluded_recordings(raw_value)
        elif field.type == _MANUAL_EXCLUDED_PARTICIPANT_CONDITIONS:
            normalized[field.name] = (
                normalize_manual_excluded_participant_conditions(raw_value)
            )
        elif field.type == _MANUAL_EXCLUDED_RECORDING_CONDITIONS:
            normalized[field.name] = (
                normalize_manual_excluded_recording_conditions(raw_value)
            )
        elif field.type == _INTERPOLATION_BURDEN_REVIEW_DECISIONS:
            normalized[field.name] = normalize_interpolation_burden_review_decisions(
                raw_value
            )
        elif field.type == _KURTOSIS_REVIEW_DECISIONS_BY_RECORDING:
            try:
                normalized[field.name] = (
                    normalize_kurtosis_review_decisions_by_recording(raw_value)
                )
            except KurtosisQCError as exc:
                raise ValueError(str(exc)) from exc
        else:  # pragma: no cover - defensive guard
            normalized[field.name] = raw_value if raw_value is not None else field.default

    # Keep the legacy policy-name field and the new versioned profile coherent.
    # This also migrates old fixed-policy manifests that predate profile IDs.
    profile = str(normalized["harmonic_selection_profile"])
    policy_name = str(normalized["harmonic_selection_policy"])
    if policy_name == _FIXED_PREDEFINED_POLICY_NAME and profile == LEGACY_HARMONIC_SELECTION_PROFILE:
        profile = FIXED_HARMONIC_SELECTION_PROFILE
        normalized["harmonic_selection_profile"] = profile
    if profile == FIXED_HARMONIC_SELECTION_PROFILE:
        normalized["harmonic_selection_policy"] = _FIXED_PREDEFINED_POLICY_NAME
    else:
        normalized["harmonic_selection_policy"] = _GROUP_SIGNIFICANT_POLICY_NAME
    if (
        profile
        in {
            SIGNIFICANT_ONLY_HARMONIC_SELECTION_PROFILE,
            NEW_PROJECT_HARMONIC_SELECTION_PROFILE,
        }
        and _first_value(
            source,
            ("group_significant_electrode_scope", "harmonic_selection_electrode_scope"),
        )
        in (None, "")
    ):
        normalized["group_significant_electrode_scope"] = (
            _GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL
        )

    _normalize_removed_electrode_detection_choice(source, normalized)

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

    channel_limit = int(normalized["max_chan_idx_keep"])
    if not 1 <= channel_limit <= 64:
        raise ValueError(
            "max_chan_idx_keep must be between 1 and 64 for the supported "
            "BioSemi ActiveTwo 64 montage."
        )

    # Surface runtime aliases expected by legacy helpers without duplicating storage
    for canonical, aliases in _ALIASES_FOR_OUTPUT.items():
        for alias in aliases:
            normalized[alias] = normalized[canonical]

    return normalized


def removed_electrode_detection_choice_requires_confirmation(
    settings: Mapping[str, Any] | None,
) -> bool:
    """Return whether processing must pause for an explicit project choice."""

    normalized = normalize_preprocessing_settings(settings)
    return (
        normalized["removed_electrode_detection_choice_status"]
        == REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
    )


def require_removed_electrode_detection_choice_ready(
    settings: Mapping[str, Any] | None,
) -> str:
    """Return the effective mode or raise before processing an unresolved project."""

    normalized = normalize_preprocessing_settings(settings)
    if (
        normalized["removed_electrode_detection_choice_status"]
        != REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    ):
        raise RemovedElectrodeDetectionConfirmationRequired(
            "Choose whether to enable experimental removed-electrode detection "
            "before processing this project. Off is recommended unless the "
            "development-lab detector is intentionally being used."
        )
    return str(normalized["removed_electrode_detection_mode"])


def confirm_removed_electrode_detection_choice(
    settings: Mapping[str, Any] | None,
    mode: Any,
    *,
    source: str = REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED,
) -> Dict[str, Any]:
    """Return settings with one explicit user-confirmed detector choice."""

    normalized_mode = _normalize_explicit_removed_electrode_mode(mode)
    if normalized_mode is None:
        raise ValueError(f"Invalid removed-electrode detector mode: {mode!r}")
    legacy_manual_mode = (
        normalized_mode == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
    )
    if legacy_manual_mode:
        normalized_mode = REMOVED_ELECTRODE_DETECTION_MODE_OFF
    normalized_source = str(source or "").strip()
    if normalized_source not in {
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED,
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT,
    }:
        raise ValueError(
            "An explicit removed-electrode detector choice source must be "
            "'user_confirmed' or 'fpvs_studio_import'."
        )
    updated = dict(settings or {})
    updated.update(
        {
            "removed_electrode_detection_mode": normalized_mode,
            "auto_detect_removed_electrodes": (
                normalized_mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
            ),
            MANUAL_REMOVED_ELECTRODES_ENABLED_KEY: (
                True
                if legacy_manual_mode
                else bool(
                    normalize_preprocessing_settings(settings).get(
                        MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
                        False,
                    )
                )
            ),
            "removed_electrode_detection_choice_schema_version": (
                REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION
            ),
            "removed_electrode_detection_choice_status": (
                REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
            ),
            "removed_electrode_detection_choice_source": (
                normalized_source
            ),
        }
    )
    return normalize_preprocessing_settings(updated)


__all__ = [
    "ELECTRODE_MAPPING_PROFILE_ANATOMICAL",
    "ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1",
    "ELECTRODE_MONTAGE_BIOSEMI64",
    "HARMONIC_SELECTION_PROFILE_VERSION",
    "FIXED_HARMONIC_SELECTION_PROFILE",
    "LEGACY_HARMONIC_SELECTION_PROFILE",
    "MANUAL_REMOVED_ELECTRODES_ENABLED_KEY",
    "NEW_PROJECT_HARMONIC_SELECTION_PROFILE",
    "SIGNIFICANT_ONLY_HARMONIC_SELECTION_PROFILE",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SCHEMA_VERSION",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED",
    "REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY",
    "RemovedElectrodeDetectionConfirmationRequired",
    "confirm_removed_electrode_detection_choice",
    "new_project_preprocessing_settings",
    "normalize_electrode_mapping_profile",
    "normalize_electrode_montage",
    "normalize_preprocessing_settings",
    "removed_electrode_detection_choice_requires_confirmation",
    "removed_electrode_detection_choice_was_saved",
    "require_removed_electrode_detection_choice_ready",
    "normalize_manual_excluded_participants",
    "normalize_manual_excluded_recordings",
    "normalize_interpolation_burden_review_decisions",
    "normalize_manual_excluded_participant_conditions",
    "normalize_manual_excluded_recording_conditions",
    "is_participant_condition_excluded",
    "is_recording_condition_excluded",
    "INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY",
    "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY",
    "KURTOSIS_AUTO_INTERPOLATE_ALL_KEY",
    "PREPROCESSING_CANONICAL_KEYS",
    "REPEATED_SESSION_PREPROCESSING_KEYS",
    "PREPROCESSING_DEFAULTS",
    "SUPPORTED_ELECTRODE_MAPPING_PROFILES",
    "SUPPORTED_ELECTRODE_MONTAGES",
]
