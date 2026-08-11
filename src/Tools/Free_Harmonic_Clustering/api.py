"""Stable headless orchestration API for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .exports import export_free_harmonic_run
from .models import (
    ClusterPermutationResult,
    ExportReceipt,
    FreeHarmonicMethodSpec,
    PreparedContrast,
    ProjectContrastRequest,
)


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


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
    "prepare_project_contrast",
    "run_free_harmonic_clustering",
]
