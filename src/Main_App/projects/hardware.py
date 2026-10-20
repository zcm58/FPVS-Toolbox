"""Project-owned acquisition choice, independent of GUI and recording readers.

File extensions supply evidence, never permission to change a project's policy.
Future Studio adapters can pass a verified platform into ``hardware_evidence``;
this module does not assume any field in today's Studio interchange schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

HARDWARE_LABELS = {
    "biosemi": "BioSemi ActiveTwo", "biosemi_active_three": "BioSemi ActiveThree",
    "brain_products": "Brain Products", "unicorn": "Unicorn Hybrid Black",
}
HARDWARE_KEYS = ("hardware_platform", "hardware_confirmed", "hardware_selection_source")
BRAIN_PRODUCTS_KEYS = (
    "initial_reference", "initial_reference_channels", "drop_reference_channels",
    "kurtosis_screening_enabled", "channel_types",
)
HARDWARE_SETTINGS_KEYS = (*HARDWARE_KEYS, *BRAIN_PRODUCTS_KEYS, "acquisition_profile", "recording_event_policy")
RECORDED_GEOMETRY_PLATFORMS = frozenset({"brain_products", "biosemi_active_three"})
BDF_PLATFORMS = frozenset({"biosemi", "biosemi_active_three", "unicorn"})
UNICORN_FACTORY_MAPPING_PROFILE = "unicorn_factory_v1"
_FORMAT_PLATFORMS = {".vhdr": "brain_products", ".bvrh": "brain_products"}


class HardwareChangeConfirmationRequired(ValueError):
    """A saved hardware policy must not change without an explicit warning."""


@dataclass(frozen=True)
class HardwareSelection:
    platform: str
    confirmed: bool
    source: str


def _platform(value: Any) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    normalized = {"brainproducts": "brain_products", "brain products": "brain_products"}.get(normalized, normalized)
    if normalized not in HARDWARE_LABELS:
        raise ValueError(f"Unsupported EEG hardware platform: {value!r}.")
    return normalized


def _boolean(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"{field} must be true or false.")


def resolve_hardware(settings: Mapping[str, Any] | None) -> HardwareSelection:
    source = settings or {}
    if "hardware_platform" not in source:
        return HardwareSelection("biosemi", True, "legacy_biosemi")
    platform = _platform(source["hardware_platform"])
    confirmed = _boolean(source.get("hardware_confirmed", False), "hardware_confirmed")
    origin = str(source.get("hardware_selection_source", "user_selection"))
    return HardwareSelection(platform, confirmed, origin)


def normalize_hardware_settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize explicit hardware metadata without rewriting legacy manifests."""
    source = settings or {}
    if "hardware_platform" not in source:
        return {}
    choice = resolve_hardware(source)
    result = dict(zip(HARDWARE_KEYS, (choice.platform, choice.confirmed, choice.source)))
    if choice.platform == "unicorn":
        if (source.get("initial_reference") not in (None, "", "recorded", "average_scalp")
                or source.get("initial_reference_channels") not in (None, "", [], ())
                or _boolean(source.get("drop_reference_channels", False), "drop_reference_channels")):
            raise ValueError("Unicorn requires its eight-scalp-channel average reference without dropped reference channels.")
        result.update(acquisition_profile=unicorn_acquisition_profile(source),
                      kurtosis_screening_enabled=False)
        if "recording_event_policy" in source:
            result["recording_event_policy"] = normalize_recording_event_policy(source["recording_event_policy"])
        authority = result.get("recording_event_policy", {}).get("authority", "status")
        decoder = result["acquisition_profile"]["event_decoder_id"]
        expected = "explicit_annotations" if authority == "annotations" else "unicorn_sample"
        if decoder != expected:
            raise ValueError("Unicorn event decoder must match its explicit recording event policy.")
        return result
    if "acquisition_profile" in source:
        raise ValueError("An explicit acquisition profile is supported only for Unicorn project settings.")
    if choice.platform not in RECORDED_GEOMETRY_PLATFORMS:
        return result
    reference = str(source.get("initial_reference", "recorded")).strip().lower()
    if reference not in {"recorded", "channels"}:
        raise ValueError("Initial reference must be recorded or channels.")
    channels = source.get("initial_reference_channels", [])
    if isinstance(channels, str):
        channels = [value.strip() for value in channels.split(",") if value.strip()]
    if not isinstance(channels, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in channels
    ):
        raise ValueError("Initial reference channels must be channel names.")
    channels = [value.strip() for value in channels]
    if len(channels) != len(set(channels)):
        raise ValueError("Initial reference channel names must be unique.")
    if reference == "channels" and not channels:
        raise ValueError("Choose at least one initial reference channel.")
    result.update(
        initial_reference=reference,
        initial_reference_channels=channels,
        drop_reference_channels=_boolean(source.get("drop_reference_channels", False), "drop_reference_channels"),
        kurtosis_screening_enabled=_boolean(source.get("kurtosis_screening_enabled", False), "kurtosis_screening_enabled"),
        channel_types=normalize_channel_types(source.get("channel_types", {})),
    )
    return result


def unicorn_acquisition_profile(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate and detach the explicit native-rate, eight-scalp policy."""
    from Main_App.io.acquisition_profiles import (
        UNICORN_FACTORY_MAPPING_SOURCE_URL, UNICORN_FACTORY_RECORDED_LABEL_MAP,
        resolve_acquisition_contract,
    )

    source = settings or {}
    profile = deepcopy(source.get("acquisition_profile", {
        "id": "unicorn_hybrid_black", "version": "1.0",
        "montage_id": "unicorn8", "montage_version": "1.0",
        "event_decoder_id": "unicorn_sample", "event_decoder_version": "1.0",
        "reference_policy": "average_scalp",
    }))
    if source.get("electrode_mapping_profile") == UNICORN_FACTORY_MAPPING_PROFILE:
        if not isinstance(profile, dict):
            raise ValueError("acquisition_profile must be an explicit configuration object.")
        profile.update(
            source_to_canonical=dict(UNICORN_FACTORY_RECORDED_LABEL_MAP),
            label_mapping_evidence={"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL},
        )
    contract = resolve_acquisition_contract({"acquisition_profile": profile})
    if contract.profile.id != "unicorn_hybrid_black":
        raise ValueError("Unicorn projects require the Unicorn Hybrid Black acquisition profile.")
    return profile


def normalize_recording_event_policy(value: Any) -> dict[str, Any]:
    """Persist explicit annotation semantics; numeric text is never guessed."""
    allowed = {"authority", "numeric_annotations", "named_annotation_codes", "marker_labels"}
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ValueError("recording_event_policy must contain supported event-policy fields.")
    authority = value.get("authority", "status")
    if not isinstance(authority, str) or authority not in {"status", "annotations", "reconcile"}:
        raise ValueError("Event authority must be status, annotations, or reconcile.")
    codes = value.get("named_annotation_codes", {})
    if not isinstance(codes, Mapping) or any(
        not isinstance(name, str) or not name.strip() or isinstance(code, bool)
        or not isinstance(code, int) or not 1 <= code <= 255 for name, code in codes.items()
    ):
        raise ValueError("Named annotation codes require nonempty labels and integer codes from 1 to 255.")
    labels = value.get("marker_labels", [])
    if not isinstance(labels, (tuple, list)) or any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Marker labels must be a list of nonempty annotation labels.")
    return {"authority": authority,
            "numeric_annotations": _boolean(value.get("numeric_annotations", False), "numeric_annotations"),
            "named_annotation_codes": dict(codes), "marker_labels": list(labels)}


def normalize_channel_types(value: Any) -> dict[str, str]:
    """Explicit recorded-label overrides; an empty mapping keeps reader metadata."""
    if isinstance(value, str):
        pairs = []
        for entry in value.split(","):
            if not entry.strip():
                continue
            name, separator, role = entry.partition("=")
            if not separator:
                raise ValueError("Channel types must use recorded names, for example VEOG=eog, ECG=ecg.")
            pairs.append((name, role))
    elif isinstance(value, Mapping):
        pairs = list(value.items())
    else:
        raise ValueError("Channel types must map recorded channel names to EEG, EOG, ECG, EMG, or misc.")
    result = {}
    for name, role in pairs:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Channel types require non-empty recorded channel names.")
        name = name.strip()
        if name in result:
            raise ValueError(f"Duplicate channel type override: {name}.")
        if not isinstance(role, str) or role.strip().lower() not in {"eeg", "eog", "ecg", "emg", "misc"}:
            raise ValueError(f"Unsupported channel type for {name!r}: {role!r}.")
        result[name] = role.strip().lower()
    return result


def hardware_evidence(platform: Any, *, source: str) -> HardwareSelection:
    """Receive a platform from a future verified importer without confirming it."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Hardware evidence requires an identified source.")
    return HardwareSelection(_platform(platform), False, source.strip())


def brain_products_qc_defaults(qc_settings: Any) -> Any:
    """Disable BioSemi-calibrated review/repair policies on an explicit switch."""
    return replace(qc_settings, raw_signal_screening_enabled=False,
                   kurtosis_screening_enabled=False, interpolation_burden_review_enabled=False,
                   condition_specific_interpolation_enabled=False,
                   kurtosis_review_auto_interpolate_extreme=False)


def hardware_supports_calibrated_qc(settings: Mapping[str, Any] | None) -> bool:
    """Only the existing ActiveTwo64 policy qualifies the calibrated reviews."""
    return resolve_hardware(settings).platform == "biosemi"


def detect_hardware_from_paths(paths: Iterable[str | Path]) -> str | None:
    suffixes = {Path(path).suffix.lower() for path in paths}
    if ".bdf" in suffixes and suffixes.intersection(_FORMAT_PLATFORMS):
        raise ValueError("This project mixes BDF and BrainVision recordings. Use a separate project for each acquisition hardware platform.")
    # BDF is shared by multiple manufacturers and BioSemi generations.
    detected = {_FORMAT_PLATFORMS[suffix] for suffix in suffixes if suffix in _FORMAT_PLATFORMS}
    return next(iter(detected), None)


def confirm_hardware_selection(
    settings: Mapping[str, Any] | None, platform: str, *, confirmed_change: bool = False,
    source: str = "user_confirmed",
) -> dict[str, Any]:
    """Return a confirmed draft; callers persist only after their dialog succeeds."""
    current = resolve_hardware(settings)
    selected = _platform(platform)
    if current.confirmed and selected != current.platform and not confirmed_change:
        raise HardwareChangeConfirmationRequired(
            "Changing EEG hardware can break Toolbox functionality or invalidate existing results. "
            "Confirm the acquisition system and reprocess this project."
        )
    updated = dict(settings or {})
    changed = selected != current.platform
    updated.update(hardware_platform=selected, hardware_confirmed=True, hardware_selection_source=source)
    if changed:
        for key in (*BRAIN_PRODUCTS_KEYS, "acquisition_profile", "recording_event_policy"):
            updated.pop(key, None)
    if selected in RECORDED_GEOMETRY_PLATFORMS and (changed or "initial_reference" not in updated):
        updated.update(
            initial_reference="recorded", initial_reference_channels=[],
            drop_reference_channels=False, kurtosis_screening_enabled=False, channel_types={},
            electrode_montage="recorded", electrode_mapping_profile="anatomical_labels",
            max_chan_idx_keep=None, max_idx_keep=None,
            ref_chan1="", ref_chan2="", removed_electrode_detection_mode="off",
            auto_detect_removed_electrodes=False, kurtosis_auto_interpolate_all=False,
        )
    elif selected == "unicorn" and (changed or "acquisition_profile" not in updated):
        updated.update(
            electrode_montage="unicorn8", electrode_mapping_profile="anatomical_labels",
            downsample=250, downsample_rate=250, max_chan_idx_keep=8, max_idx_keep=8,
            ref_chan1="", ref_chan2="", kurtosis_screening_enabled=False,
            removed_electrode_detection_mode="off", auto_detect_removed_electrodes=False,
            kurtosis_auto_interpolate_all=False, manual_removed_electrodes_enabled=False,
            manual_removed_electrodes={}, manual_removed_electrodes_by_recording={},
            acquisition_profile=unicorn_acquisition_profile(),
        )
    elif selected == "biosemi" and changed:
        updated.update(electrode_montage="biosemi64", electrode_mapping_profile="anatomical_labels",
                       max_chan_idx_keep=64, max_idx_keep=64, ref_chan1="EXG1", ref_chan2="EXG2")
    return updated


def require_hardware_ready(settings: Mapping[str, Any] | None, paths: Iterable[str | Path] = ()) -> str:
    choice = resolve_hardware(settings)
    paths = tuple(paths)
    detected = detect_hardware_from_paths(paths)
    if not choice.confirmed:
        raise ValueError("Confirm this project's EEG hardware in Settings before processing.")
    if detected is not None and detected != choice.platform:
        raise ValueError(f"Recording format indicates {HARDWARE_LABELS[detected]}, but this project is configured for {HARDWARE_LABELS[choice.platform]}. Confirm the correct hardware in Settings.")
    if any(Path(path).suffix.lower() == ".bdf" for path in paths) and choice.platform not in BDF_PLATFORMS:
        raise ValueError(f"BDF recording format is incompatible with the configured {HARDWARE_LABELS[choice.platform]} reader. Confirm the correct hardware in Settings.")
    return choice.platform
