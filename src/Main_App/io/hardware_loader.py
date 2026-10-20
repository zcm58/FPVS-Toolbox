"""Project-confirmed acquisition loading at the shared EEG boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import re
import mne


def project_acquisition_settings(app: Any, explicit: Mapping | None = None) -> dict:
    if explicit is not None:
        return dict(explicit)
    return dict(getattr(getattr(app, "currentProject", None), "preprocessing", {}) or {})


def open_brain_products_raw(
    app: Any,
    path: str | Path,
    *,
    settings: Mapping,
    preload: bool | str = False,
    stim_channel: str = "Status",
) -> Any:
    from Main_App.io.brain_products import (
        close_brain_products_raw, validate_electrical_channel_units,
    )
    from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
    from Main_App.projects.hardware import require_hardware_ready

    require_hardware_ready(settings, paths=(Path(path),))
    from Main_App.io.bids_loader import read_project_bids_raw
    raw = read_project_bids_raw(
        app, path, settings=settings, preload=preload, stim_channel=stim_channel,
    )
    try:
        roles = settings.get("channel_types") or {}
        if not isinstance(roles, Mapping) or any(
            name not in raw.ch_names or name == stim_channel
            or kind not in {"eeg", "eog", "ecg", "emg", "misc"}
            for name, kind in roles.items()
        ):
            raise ValueError("Channel type overrides must name recorded channels and supported signal roles.")
        validate_electrical_channel_units(raw, roles)
        if roles:
            raw.set_channel_types(dict(roles))
        montage = str(settings.get("electrode_montage") or "recorded")
        attach_raw_recorded_geometry(
            raw, montage_id=montage,
            template_montage=None if montage == "recorded" else montage,
        )
        from Main_App.io.acquisition_metadata import attach_recording_contract
        attach_recording_contract(raw, settings)
        app.log(
            f"Brain Products recording loaded: {len(raw.ch_names)} channels "
            f"at {raw.info['sfreq']:g} Hz."
        )
        return raw
    except BaseException:  # Resource boundary: release owned mappings even on cancellation, then re-raise.
        close_brain_products_raw(raw)
        if isinstance(preload, str):
            Path(preload).unlink(missing_ok=True)
        raise


def open_profiled_bdf_raw(app: Any, path: str | Path, *, settings: Mapping,
                          preload: bool | str = False, stim_channel: str = "Status") -> Any:
    """Admit explicitly selected BDF hardware without the legacy 64-channel policy."""
    from Main_App.io.bids_loader import read_project_bids_raw
    from Main_App.io.brain_products import close_brain_products_raw, validate_electrical_channel_units
    from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
    from Main_App.io.acquisition_metadata import attach_recording_contract
    from Main_App.projects.hardware import require_hardware_ready

    platform = require_hardware_ready(settings, paths=(Path(path),))
    if platform not in {"unicorn", "biosemi_active_three"}:
        raise ValueError("This BDF adapter requires an explicit supported acquisition selection.")
    raw = read_project_bids_raw(app, path, settings=settings, preload=preload, stim_channel=stim_channel)
    try:
        if platform == "unicorn":
            from Main_App.io.acquisition_profiles import resolve_acquisition_contract
            acquisition = resolve_acquisition_contract(settings)
            names = {name.casefold(): name for name in raw.ch_names}
            mapping = {names[source.casefold()]: target for source, target in acquisition.source_to_canonical_items}
            raw.rename_channels(mapping)
            if set(raw.ch_names[index] for index in mne.pick_types(raw.info, eeg=True, exclude=[])) != set(acquisition.montage.channel_names):
                raise ValueError("Mobile EEG loading requires exactly the eight declared scalp channels.")
            attach_raw_recorded_geometry(
                raw, montage_id="unicorn8", template_montage="standard_1020",
                hardware_platform=platform, interpolation_allowed=False,
                mapping_profile=str(settings.get("electrode_mapping_profile") or "anatomical_labels"),
            )
        else:
            # EXG channels are auxiliary unless explicitly selected for a
            # reference followed by removal. Other sensor roles are project-owned.
            roles = {name: "misc" for name in raw.ch_names if re.fullmatch(r"EXG\d+", name, re.IGNORECASE)}
            roles.update(settings.get("channel_types") or {})
            refs = settings.get("initial_reference_channels") or []
            for name in refs:
                if name in roles and roles[name] != "eeg" and settings.get("drop_reference_channels") is True:
                    roles[name] = "eeg"
            if any(name not in raw.ch_names or name == stim_channel or kind not in {"eeg", "eog", "ecg", "emg", "misc"} for name, kind in roles.items()):
                raise ValueError("Channel roles must identify recorded channels without changing stimulus semantics.")
            validate_electrical_channel_units(raw, roles)
            if roles:
                raw.set_channel_types(roles, verbose=False)
            montage = str(settings.get("electrode_montage") or "recorded")
            attach_raw_recorded_geometry(raw, montage_id=montage,
                                         template_montage=None if montage == "recorded" else montage,
                                         hardware_platform=platform)
        attach_recording_contract(raw, settings)
        return raw
    except BaseException:
        close_brain_products_raw(raw)
        if isinstance(preload, str):
            Path(preload).unlink(missing_ok=True)
        raise


def restore_cached_recorded_geometry(raw: Any, identity: Mapping) -> dict:
    """Restore exact source coordinates after the FIF float32 position roundtrip.

    Only representation-level differences are accepted; a changed channel,
    coordinate, or role invalidates the cache before processing can reuse it.
    """
    import numpy as np
    from Main_App.io.recorded_eeg_geometry import (
        validate_recorded_geometry_identity, validate_raw_recorded_geometry,
    )

    validated = validate_recorded_geometry_identity(identity)
    eeg = [name for name, kind in zip(raw.ch_names, raw.get_channel_types(), strict=True) if kind == "eeg"]
    if eeg != validated["retained_scalp_channels"]:
        raise ValueError("Cached EEG channel roles or order differ from source geometry.")
    for name, expected in validated["channel_coordinates_m"].items():
        channel = raw.info["chs"][raw.ch_names.index(name)]
        observed = np.asarray(channel["loc"][:3])
        if expected is not None:
            if not np.allclose(observed, expected, rtol=1e-6, atol=1e-8):
                raise ValueError("Cached EEG coordinates differ from source geometry.")
            channel["loc"][:3] = expected
        elif np.isfinite(observed).all() and np.linalg.norm(observed) > 0:
            raise ValueError("Cached EEG contains coordinates absent from its source geometry.")
    raw._fpvs_eeg_geometry = validated
    return validate_raw_recorded_geometry(raw)
