"""Resolve immutable analysis rates and provenance for SNR plotting."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping

from Main_App.processing.full_fft_provenance import (
    FULL_FFT_PROVENANCE_SCHEMA_VERSION,
    FULL_FFT_SHEET_NAME,
    FullFftProvenance,
    FullFftProvenanceError,
    FullFftProvenanceStaleError,
    require_current_project_full_fft_provenance,
)
from Main_App.projects import (
    DatasetIndexError,
    ProjectDatasetIndex,
    load_project_dataset_index,
)


_LEGACY_WARNING = (
    "The selected workbook folder is not a managed FPVS project. SNR plots "
    "therefore use the current application analysis rates and cannot attach "
    "managed FullFFT provenance."
)


@dataclass(frozen=True, slots=True)
class SNRAnalysisContext:
    """Resolved rates, source allowlist, and manifest-ready provenance."""

    project_root: Path | None
    base_frequency_hz: float
    oddball_frequency_hz: float
    allowed_workbook_paths: frozenset[Path] | None
    provenance: Mapping[str, object]
    warnings: tuple[dict[str, str], ...] = ()

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


def _managed_payload(record: FullFftProvenance) -> dict[str, object]:
    return {
        "source_kind": "managed_full_fft_provenance",
        "schema_version": FULL_FFT_PROVENANCE_SCHEMA_VERSION,
        "method_version": record.method_version,
        "resolved_rates_hz": {
            "base": record.base_frequency_hz,
            "oddball": record.oddball_frequency_hz,
        },
        "full_fft_provenance": {
            "status": "current",
            "saved_at": record.saved_at,
            "source_sheet": FULL_FFT_SHEET_NAME,
            "method_version": record.method_version,
            "base_frequency_hz": record.base_frequency_hz,
            "oddball_frequency_hz": record.oddball_frequency_hz,
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
        _managed_payload(current) != dict(context.provenance)
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
        return SNRAnalysisContext(
            project_root=record.project_root,
            base_frequency_hz=record.base_frequency_hz,
            oddball_frequency_hz=record.oddball_frequency_hz,
            allowed_workbook_paths=_allowed_paths(record),
            provenance=_managed_payload(record),
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
    "SNRAnalysisContext",
    "load_or_reuse_dataset_index",
    "resolve_snr_analysis_context",
    "revalidate_snr_analysis_context",
]
