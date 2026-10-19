"""Generic initial-reference operation for the shared numerical pipeline."""

from __future__ import annotations

from typing import Any

import mne

from Main_App.io.recording_contract import RecordingContract


def apply_recorded_reference(
    raw: Any, params: dict[str, Any], policy: RecordingContract,
) -> None:
    """Apply an explicitly resolved recorded/channel-reference method."""
    policy.validate_qc(params)
    params["_fpvs_pipeline_policy"] = policy.provenance
    params["_fpvs_initial_reference_mode"] = policy.initial_reference_mode
    refs = list(policy.initial_reference_channels)
    if refs:
        types = dict(zip(raw.ch_names, raw.get_channel_types(), strict=True))
        if any(types.get(channel) != "eeg" for channel in refs):
            raise ValueError("Every selected initial reference channel must be present and typed as EEG.")
        raw.set_eeg_reference(ref_channels=refs, projection=False, verbose=False)
        params["_fpvs_initial_ref_ok"] = True
        params["_fpvs_initial_ref_pair"] = tuple(refs)
        if policy.drop_reference_channels:
            raw.drop_channels(refs)
    if len(mne.pick_types(raw.info, eeg=True, exclude=[])) < 2:
        raise ValueError("Average-reference processing requires at least two retained EEG channels.")
