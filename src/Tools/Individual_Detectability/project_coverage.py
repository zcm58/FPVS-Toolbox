"""Managed-project QC-20/QC-21 coverage for Individual Detectability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Main_App.processing.full_fft_provenance import FullFftProvenance
    from Main_App.projects import ProjectDatasetIndex

    from .core import ConditionInfo


@dataclass(frozen=True, slots=True)
class ManagedWorkbookCoverage:
    """Frozen source-row contract for one released project workbook."""

    workbook_path: Path
    retained_scalp_channels: tuple[str, ...]
    allowed_auxiliary_rows: tuple[str, ...]
    source_evidence_fingerprint: str
    final_release_receipt_fingerprint: str
    participant_id: str = ""

    @property
    def cache_fingerprint(self) -> str:
        """Return the release identity that must participate in cache reuse."""

        fingerprint = (
            f"{self.source_evidence_fingerprint}:"
            f"{self.final_release_receipt_fingerprint}"
        )
        return f"{fingerprint}:{self.participant_id}" if self.participant_id else fingerprint


@dataclass(frozen=True, slots=True)
class ManagedProjectCoverage:
    """Keep authorized omissions separate from missing released coverage."""

    by_workbook: Mapping[Path, ManagedWorkbookCoverage]
    excluded_workbooks: frozenset[Path]


def load_managed_project_coverage(
    project_root: str | Path,
) -> ManagedProjectCoverage:
    """Freeze active source coverage and explicit exclusions from one release."""

    from Main_App.processing.roi_coverage import (
        RoiCoverageGateError,
        require_project_final_release,
    )

    _outcomes, final_coverage, receipt = require_project_final_release(project_root)
    by_workbook: dict[Path, ManagedWorkbookCoverage] = {}
    excluded: set[Path] = set()
    seen: set[Path] = set()
    for cell in final_coverage.cells:
        if not cell.workbook_path:
            continue
        workbook_path = Path(cell.workbook_path).expanduser().resolve(strict=False)
        if workbook_path in seen:
            raise RoiCoverageGateError(
                "Individual Detectability found duplicate final QC-21 coverage for "
                f"workbook {workbook_path}."
            )
        seen.add(workbook_path)
        if cell.downstream_cell_excluded:
            excluded.add(workbook_path)
            continue
        source = cell.source_evidence
        if source is None:
            continue
        by_workbook[workbook_path] = ManagedWorkbookCoverage(
            workbook_path=workbook_path,
            retained_scalp_channels=tuple(source.retained_scalp_identity.channels),
            allowed_auxiliary_rows=tuple(source.allowed_auxiliary_rows),
            source_evidence_fingerprint=str(source.fingerprint),
            final_release_receipt_fingerprint=str(receipt.fingerprint),
            participant_id=str(cell.participant_id),
        )
    return ManagedProjectCoverage(by_workbook, frozenset(excluded))


def load_managed_workbook_coverage(
    project_root: str | Path,
) -> dict[Path, ManagedWorkbookCoverage]:
    """Return only contributing workbooks, never excluded source evidence."""

    return dict(load_managed_project_coverage(project_root).by_workbook)


def select_managed_conditions(
    conditions: Sequence[ConditionInfo],
    *,
    dataset_index: ProjectDatasetIndex,
    provenance: FullFftProvenance,
    coverage: ManagedProjectCoverage,
    excluded_participants: set[str],
) -> list[ConditionInfo]:
    """Omit only authorized exclusions, then strictly validate retained paths."""

    from Main_App.processing.roi_coverage import RoiCoverageGateError
    from Main_App.projects import normalize_preprocessing_settings

    manifest = dataset_index.manifest or {}
    raw = manifest.get("preprocessing")
    preprocessing = normalize_preprocessing_settings(
        raw if isinstance(raw, Mapping) else {}
    )
    excluded_ids = {
        str(value).strip().casefold()
        for value in (
            *excluded_participants,
            *preprocessing.get("manual_excluded_participants", ()),
        )
        if str(value).strip()
    }
    by_path = {}
    for record in (*dataset_index.workbooks, *dataset_index.excluded_workbooks):
        path = record.path.expanduser().resolve(strict=False)
        if path in by_path:
            raise RoiCoverageGateError(
                f"Individual Detectability found ambiguous canonical identity: {path}."
            )
        by_path[path] = record
    excluded_paths = coverage.excluded_workbooks | {
        record.path.expanduser().resolve(strict=False)
        for record in dataset_index.excluded_workbooks
    }
    allowed_paths = {
        (provenance.project_root / path).resolve(strict=False)
        for path in provenance.source_paths
    }
    selected: list[ConditionInfo] = []
    for condition in conditions:
        retained: list[Path] = []
        for workbook_path in condition.files:
            resolved = workbook_path.expanduser().resolve(strict=False)
            if resolved in excluded_paths:
                continue
            record = by_path.get(resolved)
            if record is None:
                raise RoiCoverageGateError(
                    "Individual Detectability selected a workbook without canonical "
                    f"project identity: {resolved}. Refresh the selected inputs."
                )
            if record.participant_id.casefold() in excluded_ids:
                continue
            if resolved not in allowed_paths:
                raise RoiCoverageGateError(
                    "Individual Detectability selected a workbook outside the current "
                    f"FullFFT source release: {resolved}. Refresh the selected inputs "
                    "or complete reviewed post-processing."
                )
            require_managed_workbook_coverage(resolved, coverage.by_workbook)
            retained.append(workbook_path)
        if retained:
            selected.append(replace(condition, files=retained))
    return selected


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
    "ManagedProjectCoverage",
    "load_managed_project_coverage",
    "load_managed_workbook_coverage",
    "require_managed_workbook_coverage",
    "require_selected_workbooks_released",
    "select_managed_conditions",
    "validate_managed_fullfft_rows",
]
