"""Stable headless orchestration API for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable

from .exports import export_free_harmonic_run
from .models import (
    ClusterPermutationResult,
    ExportReceipt,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    PreparedContrast,
    ProjectAnalysisOptions,
    ProjectContrastRequest,
    ProjectGroupOption,
)


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def _positive_frequency(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise FreeHarmonicInputError(
            f"{label} must be finite and positive."
        ) from exc
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise FreeHarmonicInputError(f"{label} must be finite and positive.")
    return frequency


def inspect_project_analysis_options(
    project_root: str | Path,
    *,
    oddball_frequency_hz: float,
    base_frequency_hz: float,
    noise_half_width_hz: float = 0.1,
) -> ProjectAnalysisOptions:
    """Inspect canonical metadata and FullFFT headers without amplitudes/writes.

    The returned harmonic choices are derived from exactly one deterministic
    representative actual grid and its complete physical noise windows.  This
    keeps page-open discovery cheap; exact selected-cohort grid compatibility
    remains part of :func:`prepare_project_contrast`. Inspection conservatively
    blocks when the project has no current neutral FullFFT provenance;
    app-global settings are never silently treated as processed-project data.
    """

    from Main_App.io import read_xlsx_sheet_header
    from Main_App.processing.full_fft_provenance import (
        FullFftProvenanceError,
        validate_project_full_fft_provenance,
    )
    from Main_App.projects import load_project_dataset_index

    from .preparation import build_available_frequency_window_plan

    supplied_oddball_hz = _positive_frequency(
        oddball_frequency_hz,
        label="oddball_frequency_hz",
    )
    supplied_base_hz = _positive_frequency(
        base_frequency_hz,
        label="base_frequency_hz",
    )
    root = Path(project_root).expanduser().resolve(strict=False)
    if not root.is_dir() or not (root / "project.json").is_file():
        raise FreeHarmonicInputError(
            "project_root must be an existing managed project containing "
            "project.json."
        )
    try:
        dataset = load_project_dataset_index(root)
    except Exception as exc:
        raise FreeHarmonicInputError(
            f"Could not build the managed-project dataset index: {exc}"
        ) from exc
    if dataset.project_root.resolve(strict=False) != root:
        raise FreeHarmonicInputError(
            "The dataset index resolved to a different active project root."
        )
    try:
        full_fft_provenance = validate_project_full_fft_provenance(
            root,
            base_frequency_hz=supplied_base_hz,
            oddball_frequency_hz=supplied_oddball_hz,
            dataset_index=dataset,
        )
    except FullFftProvenanceError as exc:
        raise FreeHarmonicInputError(str(exc)) from exc
    active_source_paths = tuple(full_fft_provenance.source_paths)
    if not active_source_paths:
        raise FreeHarmonicInputError(
            "Neutral FullFFT provenance has no active source workbook. Rerun "
            "post-processing; EEG preprocessing is not required."
        )
    representative_relative = str(active_source_paths[0])
    source = (root / representative_relative).resolve(strict=False)
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise FreeHarmonicInputError(
            "Neutral FullFFT provenance references a workbook outside the active "
            f"project root: {source}"
        ) from exc
    if not source.is_file():
        raise FreeHarmonicInputError(
            f"Representative active workbook is missing: {representative_relative}"
        )
    try:
        header = read_xlsx_sheet_header(
            source,
            sheet_name="FullFFT Amplitude (uV)",
        )
        representative_plan = build_available_frequency_window_plan(
            header,
            oddball_frequency_hz=supplied_oddball_hz,
            base_frequency_hz=supplied_base_hz,
            noise_half_width_hz=noise_half_width_hz,
        )
    except Exception as exc:
        raise FreeHarmonicInputError(
            "Could not inspect the representative FullFFT header in "
            f"{representative_relative}: {exc}"
        ) from exc

    if representative_plan.grid_fingerprint != full_fft_provenance.grid_fingerprint:
        raise FreeHarmonicInputError(
            "The representative FullFFT header does not match the saved neutral "
            "FullFFT grid provenance. Rerun post-processing; EEG preprocessing "
            "is not required."
        )

    compatibility_message = (
        "Neutral processed-project FullFFT provenance matched and the "
        "representative FullFFT header was inspected successfully. Exact grid "
        "compatibility for the selected cohort is validated during Run Analysis."
    )
    diagnostics = tuple(
        f"{diagnostic.code}: {diagnostic.message}"
        for diagnostic in dataset.diagnostics
    )
    groups = tuple(
        ProjectGroupOption(group_id=group.group_id, label=group.label)
        for group in dataset.ordered_groups
    )
    return ProjectAnalysisOptions(
        project_root=root,
        conditions=dataset.conditions,
        groups=groups,
        workbook_count=int(full_fft_provenance.source_workbook_count),
        representative_workbook_relative_path=representative_relative,
        grid_compatible=True,
        grid_compatibility_verified=False,
        compatibility_message=compatibility_message,
        grid_fingerprint=representative_plan.grid_fingerprint,
        frequency_resolution_hz=representative_plan.frequency_resolution_hz,
        fft_upper_frequency_hz=float(
            representative_plan.full_frequencies_hz[-1]
        ),
        effective_harmonic_upper_frequency_hz=float(
            representative_plan.candidate_harmonics_hz[-1]
        ),
        eligible_orders=tuple(
            int(value) for value in representative_plan.candidate_orders
        ),
        eligible_harmonics_hz=tuple(
            float(value)
            for value in representative_plan.candidate_harmonics_hz
        ),
        excluded_base_orders=tuple(
            int(value) for value in representative_plan.excluded_base_orders
        ),
        excluded_base_harmonics_hz=tuple(
            float(value)
            for value in representative_plan.excluded_base_harmonics_hz
        ),
        incompatible_workbooks=(),
        diagnostics=diagnostics,
    )


@dataclass(frozen=True, slots=True)
class FreeHarmonicRun:
    """In-memory preparation, optional inference, and optional export receipt."""

    prepared: PreparedContrast
    result: ClusterPermutationResult | None
    receipt: ExportReceipt | None

    @property
    def prepare_only(self) -> bool:
        return self.result is None


def prepare_project_contrast(
    request: ProjectContrastRequest,
    spec: FreeHarmonicMethodSpec,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> PreparedContrast:
    """Load and prepare one contrast through the managed-project input adapter."""

    from .inputs import prepare_project_contrast as implementation

    return implementation(
        request,
        spec,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def analyze_prepared_contrast(
    prepared: PreparedContrast,
    *,
    batch_size: int = 256,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> ClusterPermutationResult:
    """Run cluster inference on an already prepared in-memory contrast."""

    from .analysis import analyze_prepared_contrast as implementation

    return implementation(
        prepared,
        batch_size=batch_size,
        progress=progress,
        cancel_check=cancel_check,
    )


def run_free_harmonic_clustering(
    request: ProjectContrastRequest,
    spec: FreeHarmonicMethodSpec | None = None,
    *,
    prepare_only: bool = False,
    run_id: str | None = None,
    destination: str | Path | None = None,
    batch_size: int = 256,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> FreeHarmonicRun:
    """Prepare one contrast, optionally infer, and atomically export one run.

    ``prepare_only=True`` is a strict no-write path. It returns the validated
    prepared tensors without creating the default results parent, a staging
    directory, or any run artifact.
    """

    if not isinstance(request, ProjectContrastRequest):
        raise TypeError("request must be a ProjectContrastRequest.")
    method = FreeHarmonicMethodSpec() if spec is None else spec
    if not isinstance(method, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    if isinstance(batch_size, bool) or int(batch_size) < 1:
        raise ValueError("batch_size must be a positive integer.")

    prepared = prepare_project_contrast(
        request,
        method,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if prepare_only:
        return FreeHarmonicRun(prepared=prepared, result=None, receipt=None)

    result = analyze_prepared_contrast(
        prepared,
        batch_size=int(batch_size),
        progress=progress_callback,
        cancel_check=cancel_check,
    )
    receipt = export_free_harmonic_run(
        prepared,
        result,
        run_id=run_id,
        destination=destination,
    )
    return FreeHarmonicRun(prepared=prepared, result=result, receipt=receipt)


__all__ = [
    "FreeHarmonicRun",
    "analyze_prepared_contrast",
    "inspect_project_analysis_options",
    "prepare_project_contrast",
    "run_free_harmonic_clustering",
]
