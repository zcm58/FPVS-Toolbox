"""Versioned acquisition-specific choices around the shared numerical pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import mne

BRAIN_PRODUCTS_PIPELINE_VERSION = "brain_products_recorded_eeg_v1"


def is_brain_products(settings: Mapping[str, Any]) -> bool:
    return settings.get("hardware_platform") == "brain_products"


def brain_products_policy(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve explicit reference policy without BioSemi reference fallbacks."""
    if settings.get("hardware_confirmed") is not True:
        raise ValueError("Confirm Brain Products hardware in this project's settings before processing.")
    mode = settings.get("initial_reference", "recorded")
    if mode not in {"recorded", "channels"}:
        raise ValueError("Brain Products initial reference must be recorded or channels.")
    channels = settings.get("initial_reference_channels", [])
    if not isinstance(channels, (list, tuple)) or any(
        not isinstance(channel, str) or not channel.strip() for channel in channels
    ) or len(set(channels)) != len(channels):
        raise ValueError("Initial reference channels must be unique recorded channel names.")
    if mode == "channels" and not channels:
        raise ValueError("Select at least one recorded channel for the initial reference.")
    drop = settings.get("drop_reference_channels", False)
    if type(drop) is not bool:
        raise ValueError("Drop reference channels must be a boolean.")
    if mode == "recorded" and (channels or drop):
        raise ValueError("Recorded-reference mode cannot specify or drop reference channels.")
    limit = settings.get("max_idx_keep", settings.get("max_chan_idx_keep"))
    if limit is not None and (type(limit) is not int or limit < 2):
        raise ValueError("Average-reference EEG channel limit must be at least two or unset.")
    return {
        "version": BRAIN_PRODUCTS_PIPELINE_VERSION,
        "hardware_platform": "brain_products", "initial_reference": mode,
        "initial_reference_channels": list(channels), "drop_reference_channels": drop,
        "max_idx_keep": limit, "electrode_montage": settings.get("electrode_montage", "recorded"),
        "channel_types": dict(settings.get("channel_types") or {}),
        "kurtosis_screening_supported": False,
    }


def policy_fingerprint(settings: Mapping[str, Any]) -> str:
    policy = brain_products_policy(settings)
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_brain_products_qc(settings: Mapping[str, Any]) -> None:
    """Do not apply BioSemi-calibrated adaptive screens to arbitrary electrode sets."""
    if settings.get("kurtosis_screening_enabled", False):
        raise ValueError("Normalized kurtosis screening is not qualified for Brain Products montages; disable it in project settings.")


def apply_brain_products_reference(raw: Any, params: dict[str, Any]) -> None:
    policy = brain_products_policy(params)
    validate_brain_products_qc(params)
    params["_fpvs_pipeline_policy"] = policy
    params["_fpvs_initial_reference_mode"] = policy["initial_reference"]
    refs = policy["initial_reference_channels"]
    if not refs:
        if len(mne.pick_types(raw.info, eeg=True, exclude=[])) < 2:
            raise ValueError("Average-reference processing requires at least two retained EEG channels.")
        return
    types = dict(zip(raw.ch_names, raw.get_channel_types(), strict=True))
    if any(types.get(channel) != "eeg" for channel in refs):
        raise ValueError("Every selected initial reference channel must be present and typed as EEG.")
    raw.set_eeg_reference(ref_channels=refs, projection=False, verbose=False)
    params["_fpvs_initial_ref_ok"] = True
    params["_fpvs_initial_ref_pair"] = tuple(refs)
    if policy["drop_reference_channels"]:
        raw.drop_channels(refs)
    if len(mne.pick_types(raw.info, eeg=True, exclude=[])) < 2:
        raise ValueError("Average-reference processing requires at least two retained EEG channels.")
