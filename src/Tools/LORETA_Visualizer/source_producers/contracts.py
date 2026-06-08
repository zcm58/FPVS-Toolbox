"""Method-neutral source producer result contracts.

These dataclasses describe producer output files and validation status only.
They intentionally avoid renderer, importer, and display-transform types so
future source methods can be swapped without coupling to the visual layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PreparedSourceManifestSpec,
    PreparedSourcePayloadSpec,
)


@dataclass(frozen=True)
class ProducedPayload:
    """One prepared payload emitted by a source-localization producer."""

    condition_id: str
    label: str
    payload_path: Path
    validation: PreparedSourcePayloadSpec


@dataclass(frozen=True)
class SourceProducerRunResult:
    """Files emitted by one source-localization producer run."""

    method_id: str
    output_dir: Path
    manifest_path: Path
    payloads: tuple[ProducedPayload, ...]
    manifest_validation: PreparedSourceManifestSpec
