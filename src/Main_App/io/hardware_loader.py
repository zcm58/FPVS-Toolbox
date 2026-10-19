"""Project-confirmed Brain Products loading at the shared EEG boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


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
        close_brain_products_raw, read_brain_products_raw, validate_electrical_channel_units,
    )
    from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
    from Main_App.projects.hardware import require_hardware_ready

    require_hardware_ready(settings, paths=(Path(path),))
    raw = read_brain_products_raw(
        path, preload=preload, event_codes=None, status_channel=stim_channel,
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
