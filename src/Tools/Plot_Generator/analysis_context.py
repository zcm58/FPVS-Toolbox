"""Resolve immutable analysis rates and provenance for SNR plotting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from Main_App.processing.full_fft_provenance import (
    FULL_FFT_PROVENANCE_SCHEMA_VERSION,
    FULL_FFT_SHEET_NAME,
    FullFftProvenance,
    FullFftProvenanceError,
    FullFftProvenanceStaleError,
    require_current_project_full_fft_provenance,
)
from Main_App.processing.spectral_eligibility import (
    SPECTRAL_ELIGIBILITY_METHOD_VERSION,
    SpectralEligibilityError,
    intersect_eligible_harmonics,
    spectral_eligibility_from_rows,
)
from Main_App.projects import (
    DatasetIndexError,
    FrequencyProtocolError,
    ProjectDatasetIndex,
    load_project_dataset_index,
    normalize_frequency_protocol,
    normalize_preprocessing_settings,
)


_LEGACY_WARNING = (
    "The selected workbook folder is not a managed FPVS project. SNR plots "
    "therefore use the current application analysis rates and cannot attach "
    "managed FullFFT provenance."
)
UNMANAGED_PLOT_DEFAULT_UPPER_HZ = 50.0


@dataclass(frozen=True, slots=True)
class SNRAnalysisContext:
    """Resolved rates, source allowlist, and manifest-ready provenance."""

    project_root: Path | None
    base_frequency_hz: float
    oddball_frequency_hz: float
    allowed_workbook_paths: frozenset[Path] | None
    provenance: Mapping[str, object]
    warnings: tuple[dict[str, str], ...] = ()
    eligible_oddball_frequencies_hz: tuple[float, ...] | None = None
    eligible_frequency_upper_hz: float | None = None
    spectral_eligibility_fingerprint: str | None = None
    spectral_eligibility_domain: "PlotSpectralEligibilityDomain | None" = None

    @property
    def is_managed(self) -> bool:
        return self.project_root is not None


def load_or_reuse_dataset_index(
    dataset_source: str | Path,
    prepared_index: ProjectDatasetIndex | None,
) -> ProjectDatasetIndex:
    """Load an input index or validate a worker-supplied batch snapshot."""

    if prepared_index is None:
        try:
            return load_project_dataset_index(dataset_source)
        except DatasetIndexError as exc:
            raise RuntimeError(
                f"Unable to index processed workbooks under {dataset_source}: {exc}"
            ) from exc

    requested = Path(dataset_source).expanduser().resolve(strict=False)
    indexed_sources = {
        prepared_index.project_root.resolve(strict=False),
        prepared_index.excel_root.resolve(strict=False),
        prepared_index.scan_root.resolve(strict=False),
    }
    if requested not in indexed_sources:
        raise RuntimeError(
            "Prepared workbook index does not belong to the selected "
            f"processed-workbook folder: {dataset_source}"
        )
    return prepared_index


def _positive_rate(value: object, *, fallback: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if math.isfinite(numeric) and numeric > 0.0 else fallback


@dataclass(frozen=True, slots=True)
class PlotSpectralEligibilityDomain:
    """Project-wide technical harmonic domain used for plot annotations."""

    eligible_harmonic_orders: tuple[int, ...]
    eligible_harmonic_frequencies_hz: tuple[float, ...]
    eligible_oddball_frequencies_hz: tuple[float, ...]
    upper_frequency_hz: float
    fingerprint: str


def _managed_payload(
    record: FullFftProvenance,
    domain: PlotSpectralEligibilityDomain,
) -> dict[str, object]:
    return {
        "source_kind": "managed_full_fft_provenance",
        "schema_version": FULL_FFT_PROVENANCE_SCHEMA_VERSION,
        "method_version": record.method_version,
        "resolved_rates_hz": {
            "base": record.base_frequency_hz,
            "oddball": record.oddball_frequency_hz,
        },
        "frequency_protocol_fingerprint": (
            record.frequency_protocol_fingerprint
        ),
        "spectral_eligibility": {
            "method_version": SPECTRAL_ELIGIBILITY_METHOD_VERSION,
            "fingerprint": domain.fingerprint,
            "eligible_harmonic_orders": list(domain.eligible_harmonic_orders),
            "eligible_harmonic_frequencies_hz": list(
                domain.eligible_harmonic_frequencies_hz
            ),
            "eligible_oddball_frequencies_hz": list(
                domain.eligible_oddball_frequencies_hz
            ),
            "upper_frequency_hz": domain.upper_frequency_hz,
        },
        "full_fft_provenance": {
            "status": "current",
            "saved_at": record.saved_at,
            "source_sheet": FULL_FFT_SHEET_NAME,
            "method_version": record.method_version,
            "base_frequency_hz": record.base_frequency_hz,
            "oddball_frequency_hz": record.oddball_frequency_hz,
            "frequency_protocol_fingerprint": (
                record.frequency_protocol_fingerprint
            ),
            "grid": {
                "fingerprint": record.grid_fingerprint,
                "frequency_resolution_hz": record.frequency_resolution_hz,
                "upper_frequency_hz": record.upper_frequency_hz,
                "frequency_column_count": record.frequency_column_count,
            },
            "source_workbooks": {
                "count": record.source_workbook_count,
                "relative_paths": list(record.source_paths),
            },
            "fingerprints": {
                "cohort": record.cohort_fingerprint,
                "sources": record.source_fingerprint,
                "frequency_qc": record.frequency_qc_fingerprint,
                "processing_export": record.processing_export_fingerprint,
            },
        },
    }


def _hash_payload(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _project_protocol_from_manifest(manifest: Mapping[str, object]):
    try:
        protocol = normalize_frequency_protocol(manifest.get("frequency_protocol"))
    except (FrequencyProtocolError, TypeError, ValueError) as exc:
        raise FullFftProvenanceError(
            f"The managed project frequency protocol is invalid: {exc}"
        ) from exc
    if (
        not protocol.is_ready
        or protocol.presentation_rate_hz is None
        or protocol.oddball_rate_hz is None
    ):
        raise FullFftProvenanceError(
            "The managed project frequency protocol is incomplete. Complete it "
            "and rerun post-processing before generating SNR plots."
        )
    return protocol


def _resolve_managed_spectral_eligibility_domain(
    dataset_index: ProjectDatasetIndex,
    record: FullFftProvenance,
) -> PlotSpectralEligibilityDomain:
    """Verify and intersect processing-owned eligibility across active workbooks."""

    manifest = dataset_index.manifest
    if not isinstance(manifest, Mapping):
        raise FullFftProvenanceError(
            "Managed SNR plotting requires a current project manifest."
        )
    protocol = _project_protocol_from_manifest(manifest)
    if protocol.fingerprint != record.frequency_protocol_fingerprint:
        raise FullFftProvenanceStaleError(
            "Neutral FullFFT provenance does not match the current project "
            "frequency protocol. Rerun post-processing."
        )

    results = []
    workbook_rows: list[dict[str, str]] = []
    for relative_path in record.source_paths:
        path = (record.project_root / Path(relative_path)).resolve(strict=False)
        try:
            path.relative_to(record.project_root)
            frame = pd.read_excel(path, sheet_name="Spectral Eligibility")
            result = spectral_eligibility_from_rows(
                frame.to_dict(orient="records"),
                protocol=protocol,
            )
        except SpectralEligibilityError as exc:
            raise FullFftProvenanceError(
                f"{path.name} has invalid spectral eligibility: {exc}"
            ) from exc
        except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
            raise FullFftProvenanceError(
                f"{path.name} has no readable current Spectral Eligibility "
                "sheet. Rerun post-processing before generating SNR plots."
            ) from exc
        if not math.isclose(
            float(result.bin_width_hz),
            record.frequency_resolution_hz,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise FullFftProvenanceError(
                f"{path.name} has a Spectral Eligibility FFT grid that does not "
                "match the current neutral FullFFT provenance. Rerun "
                "post-processing before generating SNR plots."
            )
        results.append(result)
        workbook_rows.append(
            {"path": str(relative_path), "fingerprint": result.fingerprint}
        )

    common_targets = intersect_eligible_harmonics(results)
    if not common_targets:
        raise FullFftProvenanceError(
            "No standard harmonic is technically eligible across the active "
            "workbooks. Review the filter, notch, Nyquist, and analyzed-cycle "
            "settings before plotting."
        )
    orders = tuple(int(target.oddball_harmonic_order) for target in common_targets)
    frequencies = tuple(float(target.frequency_hz) for target in common_targets)
    oddball_frequencies = tuple(
        float(target.frequency_hz)
        for target in common_targets
        if not target.is_presentation_harmonic
    )
    payload = {
        "method_version": SPECTRAL_ELIGIBILITY_METHOD_VERSION,
        "frequency_protocol_fingerprint": protocol.fingerprint,
        "eligible_harmonic_orders": list(orders),
        "workbooks": workbook_rows,
    }
    return PlotSpectralEligibilityDomain(
        eligible_harmonic_orders=orders,
        eligible_harmonic_frequencies_hz=frequencies,
        eligible_oddball_frequencies_hz=oddball_frequencies,
        upper_frequency_hz=max(frequencies),
        fingerprint=_hash_payload(payload),
    )


def project_plot_default_upper_hz(project: Any | None) -> float:
    """Return a project-owned plot default without a legacy BCA ceiling."""

    if project is None:
        return UNMANAGED_PLOT_DEFAULT_UPPER_HZ
    manifest = getattr(project, "manifest", None)
    manifest = manifest if isinstance(manifest, Mapping) else {}
    raw_protocol = getattr(project, "frequency_protocol", None)
    if raw_protocol is None:
        raw_protocol = manifest.get("frequency_protocol")
    try:
        protocol = normalize_frequency_protocol(raw_protocol)
    except (FrequencyProtocolError, TypeError, ValueError):
        protocol = None

    active: object = manifest
    for key in ("tools", "processing", "harmonic_selection", "active"):
        if not isinstance(active, Mapping):
            active = None
            break
        active = active.get(key)
    metadata = active.get("selection_metadata") if isinstance(active, Mapping) else None
    if (
        protocol is not None
        and protocol.is_ready
        and protocol.oddball_rate_hz is not None
        and isinstance(metadata, Mapping)
        and str(metadata.get("frequency_protocol_fingerprint") or "")
        == protocol.fingerprint
        and str(metadata.get("spectral_eligibility_fingerprint") or "")
    ):
        raw_orders = metadata.get("eligible_harmonic_orders")
        if isinstance(raw_orders, Sequence) and not isinstance(
            raw_orders,
            (str, bytes),
        ):
            orders: list[int] = []
            for value in raw_orders:
                if isinstance(value, bool):
                    orders = []
                    break
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    orders = []
                    break
                if numeric <= 0 or numeric != value:
                    orders = []
                    break
                orders.append(numeric)
            if orders:
                return float(max(orders) * protocol.oddball_rate_hz)

    raw_preprocessing = getattr(project, "preprocessing", None)
    if not isinstance(raw_preprocessing, Mapping):
        raw_preprocessing = manifest.get("preprocessing")
    try:
        preprocessing = normalize_preprocessing_settings(
            raw_preprocessing if isinstance(raw_preprocessing, Mapping) else {}
        )
        low_pass_hz = float(preprocessing["low_pass"])
        nyquist_hz = float(preprocessing["downsample"]) / 2.0
        upper_hz = min(low_pass_hz, nyquist_hz)
    except (KeyError, TypeError, ValueError):
        return UNMANAGED_PLOT_DEFAULT_UPPER_HZ
    return (
        upper_hz
        if math.isfinite(upper_hz) and upper_hz > 0.0
        else UNMANAGED_PLOT_DEFAULT_UPPER_HZ
    )


def _allowed_paths(record: FullFftProvenance) -> frozenset[Path]:
    allowed_paths: set[Path] = set()
    for relative in record.source_paths:
        resolved = (record.project_root / Path(relative)).resolve(strict=False)
        try:
            resolved.relative_to(record.project_root)
        except ValueError as exc:
            raise FullFftProvenanceError(
                "Saved FullFFT provenance contains a workbook outside its project root."
            ) from exc
        allowed_paths.add(resolved)
    if not allowed_paths:
        raise FullFftProvenanceError(
            "Saved FullFFT provenance has no active workbook allowlist."
        )
    return frozenset(allowed_paths)


def revalidate_snr_analysis_context(context: SNRAnalysisContext) -> None:
    """Hard-stop when managed project provenance changes during one SNR run."""

    if not context.is_managed:
        return
    current = require_current_project_full_fft_provenance(context.project_root)
    if (
        context.eligible_oddball_frequencies_hz is None
        or context.eligible_frequency_upper_hz is None
        or context.spectral_eligibility_fingerprint is None
    ):
        raise FullFftProvenanceStaleError(
            "Managed SNR plot context has no canonical spectral eligibility. "
            "Restart generation after post-processing."
        )
    domain = context.spectral_eligibility_domain
    if domain is None:
        raise FullFftProvenanceStaleError(
            "Managed SNR plot context lost its canonical spectral eligibility. "
            "Restart generation after post-processing."
        )
    if (
        _managed_payload(current, domain) != dict(context.provenance)
        or _allowed_paths(current) != context.allowed_workbook_paths
        or current.base_frequency_hz != context.base_frequency_hz
        or current.oddball_frequency_hz != context.oddball_frequency_hz
    ):
        raise FullFftProvenanceStaleError(
            "Managed FullFFT provenance changed during SNR plot generation. "
            "Restart generation so cohort, QC, processing-export identity, rates, "
            "and workbook inputs are captured from one current project state."
        )


def resolve_snr_analysis_context(
    dataset_index: ProjectDatasetIndex,
    *,
    legacy_base_frequency_hz: float,
    legacy_oddball_frequency_hz: float,
) -> SNRAnalysisContext:
    """Resolve context from the selected input folder's existing index.

    Managed inputs must have current processing-owned FullFFT provenance.  The
    saved rates are authoritative and the saved workbook family becomes an
    explicit allowlist.  Unmanaged inputs retain the historical application-
    settings fallback without borrowing state from any active GUI project.
    """

    if dataset_index.manifest is not None:
        record = require_current_project_full_fft_provenance(
            dataset_index.project_root,
            dataset_index=dataset_index,
        )
        allowed_paths = _allowed_paths(record)
        domain = _resolve_managed_spectral_eligibility_domain(
            dataset_index,
            record,
        )
        return SNRAnalysisContext(
            project_root=record.project_root,
            base_frequency_hz=record.base_frequency_hz,
            oddball_frequency_hz=record.oddball_frequency_hz,
            allowed_workbook_paths=allowed_paths,
            provenance=_managed_payload(record, domain),
            eligible_oddball_frequencies_hz=(
                domain.eligible_oddball_frequencies_hz
            ),
            eligible_frequency_upper_hz=domain.upper_frequency_hz,
            spectral_eligibility_fingerprint=domain.fingerprint,
            spectral_eligibility_domain=domain,
        )

    base_hz = _positive_rate(legacy_base_frequency_hz, fallback=6.0)
    oddball_hz = _positive_rate(legacy_oddball_frequency_hz, fallback=1.2)
    warning = {
        "code": "legacy_application_settings",
        "item": str(dataset_index.scan_root),
        "message": _LEGACY_WARNING,
    }
    return SNRAnalysisContext(
        project_root=None,
        base_frequency_hz=base_hz,
        oddball_frequency_hz=oddball_hz,
        allowed_workbook_paths=None,
        provenance={
            "source_kind": "legacy_application_settings",
            "schema_version": 1,
            "method_version": "legacy_application_settings",
            "resolved_rates_hz": {
                "base": base_hz,
                "oddball": oddball_hz,
            },
            "full_fft_provenance": None,
        },
        warnings=(warning,),
    )


__all__ = [
    "PlotSpectralEligibilityDomain",
    "SNRAnalysisContext",
    "load_or_reuse_dataset_index",
    "project_plot_default_upper_hz",
    "resolve_snr_analysis_context",
    "revalidate_snr_analysis_context",
]
