"""Validated mobile EEG source admission, before BIDS publication."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping
import json

import numpy as np

from Main_App.io.unicorn_raw import open_unicorn_recording_raw


def unicorn_event_options(settings: Mapping) -> dict:
    """Require explicit annotation interpretation; never invent marker numbers."""
    policy = settings.get("recording_event_policy") or {}
    if not isinstance(policy, Mapping) or set(policy) - {
        "authority", "numeric_annotations", "named_annotation_codes", "marker_labels",
    }:
        raise ValueError("Unsupported recording event policy.")
    decoder = settings.get("acquisition_profile", {}).get("event_decoder_id", "unicorn_sample")
    if decoder == "explicit_annotations" and not policy:
        raise ValueError("Annotation events require an explicit recording_event_policy mapping.")
    return {
        "event_authority": policy.get("authority", "status"),
        "numeric_annotations": policy.get("numeric_annotations", False),
        "named_annotation_codes": policy.get("named_annotation_codes"),
        "marker_labels": tuple(policy.get("marker_labels", ())),
        "status_channel": str(settings.get("stim_channel") or "Status"),
    }


@contextmanager
def open_mobile_import_source(path, settings, *, project_root):
    """Reuse the reviewed units/grid reader and preserve its original evidence."""
    with open_unicorn_recording_raw(
        path, settings, project_root=project_root, **unicorn_event_options(settings),
    ) as recording:
        raw, inspection = recording.raw, recording.inspection
        if inspection.events is None:
            raise ValueError("The recording has no unambiguous canonical event interpretation.")
        events = inspection.events.as_mne_events()
        if len(events) and len(np.unique(events[:, 0])) != len(events):
            raise ValueError("Multiple markers at the same sample cannot be represented without loss.")
        # The Recorder also writes quantized, nonidentity CNT calibration. Do
        # not mistake its fractional physical values for dropped samples, or
        # invent integer rounding/rollover semantics for those headers.
        names = {name.casefold(): name for name in raw.ch_names}
        headers = {signal.label.casefold(): signal for signal in inspection.source.header.signals}
        telemetry = {}
        for name in ("valid", "cnt"):
            if name not in names:
                telemetry[name] = {"status": "absent_unverified"}
                continue
            values = raw.get_data(picks=[names[name]])[0]
            if not np.isfinite(values).all():
                raise ValueError(f"Unicorn {name.upper()} contains nonfinite samples.")
            signal = headers[name]
            identity_counts = signal.identity_scaling and not signal.physical_dimension
            telemetry[name] = {
                "status": "identity_counts_checked" if identity_counts else "calibration_semantics_unverified",
                "physical_dimension": signal.physical_dimension,
                "physical_range": [str(signal.physical_minimum), str(signal.physical_maximum)],
                "digital_range": [signal.digital_minimum, signal.digital_maximum],
            }
            if identity_counts and name == "valid" and not np.all(values == 1):
                raise ValueError("Unicorn VALID contains invalid samples; no filling or reconstruction is allowed.")
            if identity_counts and name == "cnt" and (np.any(values != np.floor(values)) or np.any(np.diff(values) != 1)):
                raise ValueError("Unicorn counter is not continuous; gaps, repeats and unqualified rollover require review.")
        raw._fpvs_canonical_events = events
        raw._fpvs_canonical_events_sfreq = float(raw.info["sfreq"])
        raw._fpvs_mobile_import = {
            "reader": recording.reader_provenance,
            "acquisition": inspection.contract.identity,
            "event_policy": json.loads(inspection.event_policy_json),
            "source_format": inspection.source.header.variant,
            "physical_timing": "unknown_uncalibrated",
            "hardware_amplitude_calibration": "unverified",
            "telemetry_policy": "check_identity_unitless_counts; other_calibrations_and_wireless_loss_unverified",
            "telemetry": telemetry,
        }
        yield raw
