"""Read-only acquisition inspection; not a processing or QC release path.

This composes format, acquisition and event definitions without changing legacy
BioSemi loading. A successful parse cannot qualify hardware loss semantics,
physical timing, a source's raw-logging mode, or scientific processing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Mapping

from Main_App.io.acquisition_profiles import (
    AcquisitionProfileError, AcquisitionRegistry, BUILTIN_REGISTRY, ResolvedAcquisitionContract,
    resolve_acquisition_contract,
)
from Main_App.io.bdf_format import BdfInspection, inspect_bdf_format
from Main_App.io.recording_events import (
    CanonicalEvents, EventAuthority, RecordingAnnotation, RecordingEventError,
    decode_annotation_events, decode_sample_status, reconcile_event_sources,
)


@dataclass(frozen=True)
class InspectionIssue:
    code: str
    detail: str


@dataclass(frozen=True)
class RecordingInspection:
    contract: ResolvedAcquisitionContract
    source: BdfInspection
    events: CanonicalEvents | None
    issues: tuple[InspectionIssue, ...]
    event_policy_json: str

    @property
    def scientific_processing_allowed(self) -> bool:
        return False

    def summary(self) -> dict:
        """Detached path-free inspection evidence, never an analysis fingerprint."""
        return {
            "schema_version": "recording_inspection_v1",
            "source_sha256": self.source.file_sha256,
            "format": self.source.header.variant,
            "record_count": self.source.header.data_records,
            "record_duration_seconds": str(self.source.header.record_duration),
            "first_sample_onset_seconds": str(self.source.first_sample_onset),
            "acquisition": self.contract.identity,
            "channels": [
                {"label": signal.label, "physical_dimension": signal.physical_dimension,
                 "sampling_rate_hz": str(Decimal(signal.samples_per_record) / self.source.header.record_duration),
                 "physical_minimum": str(signal.physical_minimum),
                 "physical_maximum": str(signal.physical_maximum),
                 "digital_minimum": signal.digital_minimum,
                 "digital_maximum": signal.digital_maximum}
                for signal in self.source.header.signals if not signal.is_annotation
            ],
            "event_policy": json.loads(self.event_policy_json),
            "event_count": len(self.events.events) if self.events is not None else None,
            "event_decoder": self.events.decoder_id if self.events is not None else None,
            "event_decoder_version": self.events.decoder_version if self.events is not None else None,
            "events": [asdict(event) for event in self.events.events] if self.events is not None else [],
            "annotation_count": len(self.source.annotations),
            "record_onsets_seconds": [str(onset) for onset in self.source.record_onsets],
            "annotations": [
                {**asdict(item), "onset_seconds": str(item.onset_seconds),
                 "duration_seconds": str(item.duration_seconds) if item.duration_seconds is not None else None}
                for item in self.source.annotations
            ],
            "issues": [asdict(issue) for issue in self.issues],
            "physical_timing": "unknown_uncalibrated",
            "scientific_processing_allowed": False,
        }

    @property
    def inspection_fingerprint(self) -> str:
        payload = json.dumps(self.summary(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inspect_eeg_recording(
    path: str | Path, settings: Mapping, *, event_authority: EventAuthority,
    numeric_annotations: bool = False,
    named_annotation_codes: Mapping[str, int] | None = None,
    marker_labels: tuple[str, ...] = (), status_channel: str = "Status",
    registry: AcquisitionRegistry = BUILTIN_REGISTRY,
) -> RecordingInspection:
    """Inspect explicitly selected sample/annotation encodings on a native grid.

    All inspection is read-only; no Raw, synthetic stim, memmap, project change,
    exclusion, or manual-QC approval is produced. BDF+D evidence is retained but
    never converted to a fictitious continuous event grid. Legacy BioSemi edge
    decoding remains in the unchanged production loader until common integration.
    """
    contract = resolve_acquisition_contract(settings, registry=registry)
    if contract.event_decoder.id not in {"unicorn_sample", "explicit_annotations"}:
        raise ValueError("This inspection entry point requires an explicit sample/annotation acquisition profile.")
    capabilities = contract.profile.capabilities
    if ((contract.format_adapter.id, contract.format_adapter.version) != ("bdf", "1.0")
            or capabilities.native_sfreq is None):
        raise ValueError("Inspection requires a BDF profile with an explicit native sample rate.")
    if not isinstance(status_channel, str) or not status_channel.strip():
        raise ValueError("An explicit Status channel name is required (it may be absent for annotations).")
    if event_authority not in {"status", "annotations", "reconcile"}:
        raise ValueError("Unknown event-source authority.")
    selected_decoder = "explicit_annotations" if event_authority == "annotations" else "unicorn_sample"
    required_decoders = {selected_decoder}
    if event_authority == "reconcile":
        required_decoders.add("explicit_annotations")
    if (contract.event_decoder.id != selected_decoder
            or not required_decoders <= set(contract.profile.decoder_ids)):
        raise ValueError("Selected decoder and profile capabilities do not support the event authority.")
    for decoder in required_decoders:
        registry.lookup("event_decoders", decoder, "1.0")
    source = inspect_bdf_format(path, optional_digital_channels=(status_channel,))
    issues = [InspectionIssue("format_continuity", detail) for detail in source.processing_blockers]
    signals = {signal.label.casefold(): signal for signal in source.header.signals if not signal.is_annotation}
    expected_rate = Decimal(str(capabilities.native_sfreq))
    expected_samples = source.header.record_duration * expected_rate
    if expected_samples != expected_samples.to_integral_value():
        issues.append(InspectionIssue("native_grid", "Record duration does not contain integral native samples."))
    for name, canonical in contract.source_to_canonical_items:
        signal = signals.get(name.casefold())
        if signal is None:
            issues.append(InspectionIssue("missing_scalp_label", f"Missing explicit source {name!r} for {canonical}."))
            continue
        if signal.samples_per_record != expected_samples:
            issues.append(InspectionIssue("native_grid", f"{name} does not have the profile's native sampling grid."))
        if signal.physical_dimension not in {"uV", "mV", "V"}:
            issues.append(InspectionIssue("unqualified_unit", f"{name} has unqualified physical unit {signal.physical_dimension!r}; no scaling inferred."))
    if contract.label_mapping_evidence_status == "unverified":
        issues.append(InspectionIssue("unverified_mapping", "The selected source-to-electrode mapping lacks reviewed evidence."))
    events = None
    if not any(issue.code in {"native_grid", "format_continuity"} for issue in issues):
        try:
            actual_decoders = {"unicorn_sample"} if source.digital_signals else set()
            has_annotations = any(signal.is_annotation for signal in source.header.signals)
            if has_annotations:
                actual_decoders.add("explicit_annotations")
            for decoder in actual_decoders:
                if decoder not in contract.profile.decoder_ids:
                    raise RecordingEventError(f"Profile does not support the recorded secondary source decoder {decoder!r}.")
                registry.lookup("event_decoders", decoder, "1.0")
            rate = float(expected_rate)
            samples = int(expected_samples) * source.header.data_records
            annotations = decode_annotation_events(
                tuple(RecordingAnnotation(
                    item.source_id, item.source_order,
                    float(Fraction(item.onset_seconds) - Fraction(source.first_sample_onset)),
                    float(item.duration_seconds or 0), item.text,
                ) for item in source.annotations),
                sfreq=rate, n_samples=samples, numeric_codes=numeric_annotations,
                named_codes={} if named_annotation_codes is None else named_annotation_codes,
                marker_labels=marker_labels,
            )
            if not has_annotations:
                annotations = None
            status = None
            if source.digital_signals:
                channel, values = source.digital_signals[0]
                signal = signals[channel.casefold()]
                if not signal.identity_scaling or signal.samples_per_record != expected_samples:
                    raise RecordingEventError("Status needs verified identity scaling and the native EEG sample grid.")
                status = decode_sample_status(values, sfreq=rate, channel=channel)
            events = reconcile_event_sources(status, annotations, authority=event_authority)
        except (RecordingEventError, AcquisitionProfileError) as exc:
            issues.append(InspectionIssue("event_contract", str(exc)))
    issues.extend((
        InspectionIssue("unqualified_acquisition", "Raw logging, amplitude interpretation and CNT/VALID/DT loss semantics require source-specific qualification."),
        InspectionIssue("integration_pending", "Native preprocessing, manual QC release, provenance and downstream capability gates are not yet integrated; inspection does not authorize processing."),
    ))
    policy = json.dumps({
        "authority": event_authority, "numeric_annotations": numeric_annotations,
        "named_annotation_codes": dict(named_annotation_codes or {}),
        "marker_labels": list(marker_labels), "status_channel": status_channel,
    }, sort_keys=True)
    return RecordingInspection(contract, source, events, tuple(issues), policy)
