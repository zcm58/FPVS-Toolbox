"""Immutable acquisition definitions for explicit, versioned source interpretation.

Resolution is inspection policy, not scientific qualification. In particular, a
label mapping does not establish reference, amplitude, telemetry, or timing
validity. Legacy BioSemi settings are never rewritten by this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from types import MappingProxyType

from Main_App.io.eeg_geometry import (
    BIOSEMI64_1020_AB_CHANNEL_MAP,
    BIOSEMI64_CHANNELS,
)


class AcquisitionProfileError(ValueError):
    """An acquisition definition or requested combination is unsupported."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AcquisitionProfileError(f"{field} must be nonempty, trimmed text.")
    return value


def _tuple(values: object, field: str) -> tuple:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise AcquisitionProfileError(f"{field} must be a sequence.")
    return tuple(values)


def _strings(values: object, field: str) -> tuple[str, ...]:
    result = tuple(_text(value, field) for value in _tuple(values, field))
    if not result or len({value.casefold() for value in result}) != len(result):
        raise AcquisitionProfileError(f"{field} must be nonempty and unique ignoring case.")
    return result


def _definition(value: object) -> None:
    _text(value.id, "Definition id")
    _text(value.version, "Definition version")


def _mapping(values: object, channels: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    entries = values.items() if isinstance(values, Mapping) else _tuple(values, "Channel mapping")
    by_target: dict[str, str] = {}
    sources: set[str] = set()
    for entry in entries:
        pair = _tuple(entry, "Channel mapping pair")
        if len(pair) != 2:
            raise AcquisitionProfileError("Each channel mapping pair must have two labels.")
        source, target = (_text(value, "Channel label") for value in pair)
        if source.casefold() in sources or target in by_target:
            raise AcquisitionProfileError("Channel mappings must be one-to-one, with unique source labels.")
        if target not in channels:
            raise AcquisitionProfileError(f"Unknown canonical channel {target!r} in channel mapping.")
        sources.add(source.casefold())
        by_target[target] = source
    if set(by_target) != set(channels):
        raise AcquisitionProfileError("Channel mapping must cover the complete montage without missing sensors.")
    return tuple((by_target[target], target) for target in channels)


@dataclass(frozen=True, slots=True)
class FormatAdapterDefinition:
    id: str
    version: str
    extensions: tuple[str, ...]

    def __post_init__(self) -> None:
        _definition(self)
        extensions = _strings(self.extensions, "Format extensions")
        if any(not extension.startswith(".") or extension != extension.lower() for extension in extensions):
            raise AcquisitionProfileError("Format extensions must be lowercase and begin with a dot.")
        object.__setattr__(self, "extensions", extensions)


@dataclass(frozen=True, slots=True)
class MontageDefinition:
    id: str
    version: str
    channel_names: tuple[str, ...]
    source_to_canonical_items: tuple[tuple[str, str], ...]
    coordinate_source: str
    coordinate_frame: str

    def __post_init__(self) -> None:
        _definition(self)
        channels = _strings(self.channel_names, "Montage channels")
        object.__setattr__(self, "channel_names", channels)
        object.__setattr__(self, "source_to_canonical_items", _mapping(self.source_to_canonical_items, channels))
        _text(self.coordinate_source, "Coordinate source and version")
        _text(self.coordinate_frame, "Coordinate frame")


@dataclass(frozen=True, slots=True)
class EventDecoderDefinition:
    id: str
    version: str

    def __post_init__(self) -> None:
        _definition(self)


@dataclass(frozen=True, slots=True)
class AcquisitionCapabilities:
    native_sfreq: float | None
    allow_resampling: bool
    allow_interpolation: bool
    normalized_kurtosis: bool
    spatial_tools: bool

    def __post_init__(self) -> None:
        if self.native_sfreq is not None:
            if isinstance(self.native_sfreq, bool) or not isinstance(self.native_sfreq, (float, int)):
                raise AcquisitionProfileError("Native sampling frequency must be a positive finite number.")
            if not math.isfinite(self.native_sfreq) or self.native_sfreq <= 0:
                raise AcquisitionProfileError("Native sampling frequency must be a positive finite number.")
            object.__setattr__(self, "native_sfreq", float(self.native_sfreq))
        for field in ("allow_resampling", "allow_interpolation", "normalized_kurtosis", "spatial_tools"):
            if not isinstance(getattr(self, field), bool):
                raise AcquisitionProfileError(f"Capability {field} must be boolean.")


@dataclass(frozen=True, slots=True)
class AcquisitionProfile:
    id: str
    version: str
    format_id: str
    montage_ids: tuple[str, ...]
    decoder_ids: tuple[str, ...]
    capabilities: AcquisitionCapabilities
    reference_policies: tuple[str, ...]

    def __post_init__(self) -> None:
        _definition(self)
        _text(self.format_id, "Format adapter id")
        for field in ("montage_ids", "decoder_ids", "reference_policies"):
            object.__setattr__(self, field, _strings(getattr(self, field), field))
        if not isinstance(self.capabilities, AcquisitionCapabilities):
            raise AcquisitionProfileError("A profile requires validated acquisition capabilities.")


@dataclass(frozen=True, slots=True)
class AcquisitionRegistry:
    format_adapters: tuple[FormatAdapterDefinition, ...]
    montages: tuple[MontageDefinition, ...]
    event_decoders: tuple[EventDecoderDefinition, ...]
    profiles: tuple[AcquisitionProfile, ...]

    def __post_init__(self) -> None:
        for field, expected in (
            ("format_adapters", FormatAdapterDefinition), ("montages", MontageDefinition),
            ("event_decoders", EventDecoderDefinition), ("profiles", AcquisitionProfile),
        ):
            definitions = _tuple(getattr(self, field), field)
            if not definitions or any(not isinstance(item, expected) for item in definitions):
                raise AcquisitionProfileError(f"Registry {field} requires validated definitions.")
            _strings([item.id for item in definitions], f"Registry {field} IDs")
            object.__setattr__(self, field, definitions)
        for profile in self.profiles:
            self.lookup("format_adapters", profile.format_id)
            for montage in profile.montage_ids:
                self.lookup("montages", montage)
            for decoder in profile.decoder_ids:
                self.lookup("event_decoders", decoder)

    def lookup(self, component: str, identifier: str, version: str | None = None):
        if component not in {"format_adapters", "montages", "event_decoders", "profiles"}:
            raise AcquisitionProfileError(f"Unknown registry component {component!r}.")
        for definition in getattr(self, component):
            if definition.id == identifier:
                if version is not None and definition.version != version:
                    raise AcquisitionProfileError(f"Unsupported version {version!r} for {identifier!r}.")
                return definition
        raise AcquisitionProfileError(f"Unknown {component} id {identifier!r}.")


@dataclass(frozen=True, slots=True)
class ResolvedAcquisitionContract:
    profile: AcquisitionProfile
    format_adapter: FormatAdapterDefinition
    montage: MontageDefinition
    event_decoder: EventDecoderDefinition
    reference_policy: str
    source_to_canonical_items: tuple[tuple[str, str], ...]
    label_mapping_evidence_status: str
    label_mapping_evidence_reference: str
    legacy_default: bool

    def __post_init__(self) -> None:
        if not isinstance(self.profile, AcquisitionProfile) or not isinstance(self.montage, MontageDefinition):
            raise AcquisitionProfileError("Resolved acquisition requires validated profile and montage definitions.")
        if not isinstance(self.format_adapter, FormatAdapterDefinition) or not isinstance(
            self.event_decoder, EventDecoderDefinition
        ):
            raise AcquisitionProfileError("Resolved acquisition requires validated format and decoder definitions.")
        if (
            self.format_adapter.id != self.profile.format_id
            or self.montage.id not in self.profile.montage_ids
            or self.event_decoder.id not in self.profile.decoder_ids
            or self.reference_policy not in self.profile.reference_policies
        ):
            raise AcquisitionProfileError("Resolved acquisition definitions are incompatible.")
        object.__setattr__(
            self, "source_to_canonical_items", _mapping(self.source_to_canonical_items, self.montage.channel_names)
        )
        if self.label_mapping_evidence_status not in ("anatomical_labels", "registered", "unverified", "verified"):
            raise AcquisitionProfileError("Resolved label mapping evidence status is unsupported.")
        if not isinstance(self.label_mapping_evidence_reference, str) or not isinstance(self.legacy_default, bool):
            raise AcquisitionProfileError("Resolved evidence reference and legacy state have invalid types.")
        if self.label_mapping_evidence_status in ("registered", "verified"):
            _text(self.label_mapping_evidence_reference, "Label mapping evidence reference")

    @property
    def identity(self) -> dict[str, object]:
        """Return detached selected definitions, without unrelated registry entries."""
        return {
            "contract_version": "acquisition_contract_v1",
            "profile": asdict(self.profile),
            "format_adapter": asdict(self.format_adapter),
            "montage": asdict(self.montage),
            "event_decoder": asdict(self.event_decoder),
            "reference_policy": self.reference_policy,
            "source_to_canonical_items": [list(pair) for pair in self.source_to_canonical_items],
            "label_mapping_evidence": {
                "status": self.label_mapping_evidence_status,
                "reference": self.label_mapping_evidence_reference,
            },
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


UNICORN_CHANNELS = ("Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8")
UNICORN_FACTORY_RECORDED_LABEL_MAP: Mapping[str, str] = MappingProxyType({
    f"EEG {number}": channel for number, channel in enumerate(UNICORN_CHANNELS, start=1)
})
UNICORN_FACTORY_MAPPING_SOURCE_URL = (
    "https://github.com/unicorn-bi/Unicorn-Suite-Hybrid-Black-User-Manual/blob/main/UnicornHybridBlack.md"
)
UNICORN_RECORDER_SOURCE_URL = "https://github.com/unicorn-bi/Unicorn-Recorder-Hybrid-Black/blob/main/README.md"

# The documented factory cap layout does not verify an operator's custom wiring.
# Keep numbered labels opt-in rather than silently selecting this mapping.
BUILTIN_REGISTRY = AcquisitionRegistry(
    format_adapters=(FormatAdapterDefinition("bdf", "1.0", (".bdf",)),),
    montages=(
        MontageDefinition(
            "biosemi64", "1.0", BIOSEMI64_CHANNELS,
            tuple((name, name) for name in BIOSEMI64_CHANNELS),
            "MNE 1.9.0 biosemi64 template, canonical head-coordinate transform v1", "head",
        ),
        MontageDefinition(
            "unicorn8", "1.0", UNICORN_CHANNELS,
            tuple((name, name) for name in UNICORN_CHANNELS),
            "MNE 1.9.0 standard_1020 template subset, head-coordinate transform v1; not measured headset positions",
            "head",
        ),
    ),
    event_decoders=(
        EventDecoderDefinition("biosemi_edge", "1.0"), EventDecoderDefinition("unicorn_sample", "1.0"),
        EventDecoderDefinition("explicit_annotations", "1.0"),
    ),
    profiles=(
        AcquisitionProfile(
            "biosemi_active_two_64", "1.0", "bdf", ("biosemi64",), ("biosemi_edge",),
            AcquisitionCapabilities(None, True, True, True, True), ("biosemi_exg_pair_then_average",),
        ),
        AcquisitionProfile(
            "unicorn_hybrid_black", "1.0", "bdf", ("unicorn8",), ("unicorn_sample", "explicit_annotations"),
            AcquisitionCapabilities(250.0, False, False, False, False), ("average_scalp",),
        ),
    ),
)


def resolve_acquisition_contract(
    settings: Mapping[str, object] | None,
    *,
    registry: AcquisitionRegistry = BUILTIN_REGISTRY,
) -> ResolvedAcquisitionContract:
    """Resolve an explicit nested profile, or the unchanged legacy BioSemi policy.

    An optional ``source_to_canonical`` mapping must cover every montage sensor.
    Its optional ``label_mapping_evidence`` object records ``status`` (unverified
    or verified) and an independent evidence ``reference``. Verified mappings
    require that reference; neither state qualifies acquisition or processing.
    """
    if settings is not None and not isinstance(settings, Mapping):
        raise AcquisitionProfileError("Acquisition settings must be an object.")
    if not isinstance(registry, AcquisitionRegistry):
        raise AcquisitionProfileError("Acquisition resolution requires a validated registry.")
    source = settings if settings is not None else {}
    legacy = "acquisition_profile" not in source
    if legacy:
        if source.get("electrode_montage", "biosemi64") not in (None, "", "biosemi64"):
            raise AcquisitionProfileError("A non-BioSemi montage requires an explicit acquisition profile.")
        requested = {
            "id": "biosemi_active_two_64", "version": "1.0",
            "montage_id": "biosemi64", "montage_version": "1.0",
            "event_decoder_id": "biosemi_edge", "event_decoder_version": "1.0",
            "reference_policy": "biosemi_exg_pair_then_average",
        }
    else:
        requested = source["acquisition_profile"]
        if not isinstance(requested, Mapping):
            raise AcquisitionProfileError("acquisition_profile must be an explicit configuration object.")
    required = {"id", "version", "montage_id", "montage_version", "event_decoder_id",
                "event_decoder_version", "reference_policy"}
    allowed = required | {"source_to_canonical", "label_mapping_evidence"}
    if set(requested) - allowed or required - set(requested):
        raise AcquisitionProfileError("Acquisition profile fields are missing or unsupported.")
    for field in required:
        _text(requested[field], f"acquisition_profile.{field}")
    profile = registry.lookup("profiles", requested["id"], requested["version"])
    montage = registry.lookup("montages", requested["montage_id"], requested["montage_version"])
    decoder = registry.lookup("event_decoders", requested["event_decoder_id"], requested["event_decoder_version"])
    if montage.id not in profile.montage_ids or decoder.id not in profile.decoder_ids:
        raise AcquisitionProfileError("Requested montage or event decoder is incompatible with the acquisition profile.")
    if requested["reference_policy"] not in profile.reference_policies:
        raise AcquisitionProfileError("Requested reference policy is incompatible with the acquisition profile.")
    mapping = montage.source_to_canonical_items
    evidence_status, evidence_reference = "anatomical_labels", "Registered anatomical source labels"
    if any(source != target for source, target in mapping):
        evidence_status, evidence_reference = "registered", f"{montage.id}/{montage.version}"
    if legacy:
        mapping_profile = source.get("electrode_mapping_profile", "anatomical_labels")
        if mapping_profile == "biosemi64_1020_ab_v1":
            mapping = _mapping(BIOSEMI64_1020_AB_CHANNEL_MAP, montage.channel_names)
            evidence_status, evidence_reference = "registered", "biosemi64_1020_ab_v1"
        elif mapping_profile not in (None, "", "anatomical_labels"):
            raise AcquisitionProfileError("Unknown legacy BioSemi electrode mapping profile.")
    if "source_to_canonical" in requested:
        mapping = _mapping(requested["source_to_canonical"], montage.channel_names)
        evidence = requested.get("label_mapping_evidence", {"status": "unverified"})
        if not isinstance(evidence, Mapping) or set(evidence) - {"status", "reference"}:
            raise AcquisitionProfileError("Label mapping evidence must declare its status and optional reference.")
        evidence_status = evidence.get("status")
        evidence_reference = evidence.get("reference", "")
        if evidence_status not in ("unverified", "verified") or not isinstance(evidence_reference, str):
            raise AcquisitionProfileError("Label mapping evidence requires an unverified or verified status.")
        if evidence_status == "verified":
            _text(evidence_reference, "Verified label mapping evidence reference")
    elif "label_mapping_evidence" in requested:
        raise AcquisitionProfileError("Label mapping evidence requires an explicit source_to_canonical mapping.")
    return ResolvedAcquisitionContract(
        profile, registry.lookup("format_adapters", profile.format_id), montage, decoder,
        requested["reference_policy"], mapping, evidence_status, evidence_reference, legacy,
    )
