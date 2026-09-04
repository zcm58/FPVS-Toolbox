"""Managed-project QC-20/QC-21 coverage for Individual Detectability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManagedWorkbookCoverage:
    """Frozen source-row contract for one released project workbook."""

    workbook_path: Path
    retained_scalp_channels: tuple[str, ...]
    allowed_auxiliary_rows: tuple[str, ...]
    source_evidence_fingerprint: str
    final_release_receipt_fingerprint: str

    @property
    def cache_fingerprint(self) -> str:
        """Return the release identity that must participate in cache reuse."""

        return (
            f"{self.source_evidence_fingerprint}:"
            f"{self.final_release_receipt_fingerprint}"
        )


def load_managed_workbook_coverage(
    project_root: str | Path,
) -> dict[Path, ManagedWorkbookCoverage]:
    """Require the current final release and index its contributing workbooks."""

    from Main_App.processing.roi_coverage import (
        RoiCoverageGateError,
        require_project_final_release,
    )

    _outcomes, final_coverage, receipt = require_project_final_release(project_root)
    by_workbook: dict[Path, ManagedWorkbookCoverage] = {}
    for cell in final_coverage.cells:
        source = cell.source_evidence
        if source is None:
            continue
        workbook_path = Path(cell.workbook_path).expanduser().resolve(strict=False)
        if workbook_path in by_workbook:
            raise RoiCoverageGateError(
                "Individual Detectability found duplicate final QC-21 coverage for "
                f"workbook {workbook_path}."
            )
        by_workbook[workbook_path] = ManagedWorkbookCoverage(
            workbook_path=workbook_path,
            retained_scalp_channels=tuple(source.retained_scalp_identity.channels),
            allowed_auxiliary_rows=tuple(source.allowed_auxiliary_rows),
            source_evidence_fingerprint=str(source.fingerprint),
            final_release_receipt_fingerprint=str(receipt.fingerprint),
        )
    return by_workbook


def require_managed_workbook_coverage(
    workbook_path: str | Path,
    coverage_by_workbook: Mapping[Path, ManagedWorkbookCoverage],
) -> ManagedWorkbookCoverage:
    """Return exact released coverage for one selected managed workbook."""

    from Main_App.processing.roi_coverage import RoiCoverageGateError

    resolved = Path(workbook_path).expanduser().resolve(strict=False)
    coverage = coverage_by_workbook.get(resolved)
    if coverage is None:
        raise RoiCoverageGateError(
            "Individual Detectability selected a workbook that is not a current "
            f"QC-20/QC-21 released output: {resolved}. Rerun reviewed "
            "post-processing before generating this figure."
        )
    return coverage


def require_selected_workbooks_released(
    workbook_paths: Sequence[str | Path],
    coverage_by_workbook: Mapping[Path, ManagedWorkbookCoverage],
) -> None:
    """Require every selected managed workbook to belong to the final release."""

    for workbook_path in workbook_paths:
        require_managed_workbook_coverage(workbook_path, coverage_by_workbook)


def validate_managed_fullfft_rows(
    rows: object,
    *,
    coverage: ManagedWorkbookCoverage,
    required_columns: Sequence[str],
    electrode_column: str,
) -> None:
    """Validate complete FullFFT source rows before detectability calculations."""

    from Main_App.processing.roi_coverage import (
        RoiCoverageGateError,
        RoiSourceCoverageError,
        validate_roi_source_rows,
    )

    try:
        validate_roi_source_rows(
            rows,
            retained_scalp=coverage.retained_scalp_channels,
            required_columns=required_columns,
            electrode_column=electrode_column,
            allowed_auxiliary_rows=coverage.allowed_auxiliary_rows,
        )
    except RoiSourceCoverageError as exc:
        raise RoiCoverageGateError(
            "Individual Detectability cannot use incomplete or ambiguous FullFFT "
            f"electrode rows in {coverage.workbook_path.name}: {exc}"
        ) from exc


__all__ = [
    "ManagedWorkbookCoverage",
    "load_managed_workbook_coverage",
    "require_managed_workbook_coverage",
    "require_selected_workbooks_released",
    "validate_managed_fullfft_rows",
]
