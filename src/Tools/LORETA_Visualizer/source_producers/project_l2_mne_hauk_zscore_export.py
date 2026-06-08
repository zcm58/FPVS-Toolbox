"""Project-level Hauk-style L2-MNE source-space z-score export.

This module combines read-only project FullFFT topographies with an external
MNE/fsaverage EEG forward model, then writes prepared JSON payloads for the
visualizer importer. It owns calculation orchestration only; it does not import
GUI, renderer, display mesh, or display-transform modules.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from Tools.LORETA_Visualizer.source_producers.contracts import SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    L2MNEHaukZScoreConfig,
    write_l2_mne_hauk_zscore_surface_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
    ProjectSourceFrequencyBinInputSet,
    build_l2_mne_hauk_zscore_conditions_from_project,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    DEFAULT_MNE_FSAVERAGE_SPACING,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    build_mne_fsaverage_l2_mne_forward_model,
)

logger = logging.getLogger(__name__)

PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER = "L2-MNE Hauk Z-Score Beta"
DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME = "project_l2_mne_hauk_zscore_beta_manifest.json"


class ProjectL2MNEHaukZScoreExportError(RuntimeError):
    """Raised when project-level Hauk z-score source maps cannot be written."""


@dataclass(frozen=True)
class ProjectL2MNEHaukZScoreExportResult:
    """Project source z-score export result plus project-input diagnostics."""

    project_inputs: ProjectSourceFrequencyBinInputSet
    producer_result: SourceProducerRunResult
    forward_model: L2MNECorticalForwardModel

    @property
    def output_dir(self) -> Path:
        """Directory containing the manifest and source payload files."""
        return self.producer_result.output_dir

    @property
    def manifest_path(self) -> Path:
        """Manifest JSON path that the visualizer can load."""
        return self.producer_result.manifest_path


def default_project_l2_mne_hauk_zscore_output_dir(project_root: str | Path) -> Path:
    """Return the project-local default output directory for Phase 6D exports."""
    root = Path(project_root).expanduser().resolve()
    return root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER


def write_project_l2_mne_hauk_zscore_payloads(
    *,
    project_root: str | Path,
    output_dir: str | Path | None = None,
    conditions: Sequence[str] | None = None,
    include_flagged_subjects: bool = False,
    spacing: str = DEFAULT_MNE_FSAVERAGE_SPACING,
    allow_fetch_fsaverage: bool = False,
    forward_model: L2MNECorticalForwardModel | None = None,
    noise_window_bins: int = DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    excluded_offsets: Sequence[int] = DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    min_noise_bins: int = DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
) -> ProjectL2MNEHaukZScoreExportResult:
    """Write Hauk-style source-space z-score JSON for an existing project.

    The default output directory is project-local:
    ``6 - Source Localization/L2-MNE Hauk Z-Score Beta``.
    """
    root = _project_root(project_root)
    resolved_output = _project_output_dir(root, output_dir)
    project_inputs = build_l2_mne_hauk_zscore_conditions_from_project(
        root,
        conditions=conditions,
        include_flagged_subjects=include_flagged_subjects,
        noise_window_bins=noise_window_bins,
        excluded_offsets=excluded_offsets,
        min_noise_bins=min_noise_bins,
    )
    if not project_inputs.conditions:
        diagnostics = "; ".join(project_inputs.diagnostics) or "no source-ready FullFFT conditions were assembled"
        raise ProjectL2MNEHaukZScoreExportError(
            f"Project Hauk z-score L2-MNE export has no conditions to write: {diagnostics}."
        )

    model = forward_model or build_mne_fsaverage_l2_mne_forward_model(
        spacing=spacing,
        allow_fetch_fsaverage=allow_fetch_fsaverage,
    )
    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=project_inputs.selected_harmonics_hz,
        noise_window_bins=project_inputs.bin_plan.noise_window_bins,
        excluded_noise_offsets=project_inputs.bin_plan.excluded_offsets,
        min_noise_bins=project_inputs.bin_plan.min_noise_bins,
        metadata={
            "project_integration": "phase_6d_project_l2_mne_hauk_zscore_beta",
            "project_root_name": root.name,
            "source_topography_metric": "fullfft_amplitude_target_and_neighbor_bins",
            "source_topography_sheet": project_inputs.sheet_name,
            "include_flagged_subjects": include_flagged_subjects,
            "excluded_subjects": list(project_inputs.excluded_subjects),
            "flagged_subjects": list(project_inputs.flagged_subjects),
            "project_input_diagnostics": list(project_inputs.diagnostics),
            "frequency_resolution_hz": project_inputs.bin_plan.frequency_resolution_hz,
            "output_scope": "project-local",
        },
    )
    producer_result = write_l2_mne_hauk_zscore_surface_payloads(
        forward_model=model,
        conditions=project_inputs.conditions,
        config=config,
        output_dir=resolved_output,
        manifest_name=DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME,
    )
    logger.info(
        "project_l2_mne_hauk_zscore_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(producer_result.output_dir),
            "condition_count": len(producer_result.payloads),
        },
    )
    return ProjectL2MNEHaukZScoreExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model,
    )


def _project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    return root


def _project_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    target = default_project_l2_mne_hauk_zscore_output_dir(project_root) if output_dir is None else Path(output_dir)
    if not target.is_absolute():
        target = project_root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Project Hauk z-score L2-MNE output directory must stay inside the project root.") from exc
    return resolved


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write Hauk-style L2-MNE source-space z-score prepared JSON from an FPVS project."
    )
    parser.add_argument("--project-root", required=True, help="FPVS project root.")
    parser.add_argument("--output", help="Project-local output directory. Defaults to the Phase 6D source folder.")
    parser.add_argument(
        "--condition",
        dest="conditions",
        action="append",
        help="Condition label to include. Repeat to export a subset.",
    )
    parser.add_argument(
        "--include-flagged",
        action="store_true",
        help="Include participants listed in Flagged Participants.xlsx. Default is to exclude them.",
    )
    parser.add_argument(
        "--spacing",
        default=DEFAULT_MNE_FSAVERAGE_SPACING,
        help="MNE fsaverage source-space spacing, such as ico3 or ico4.",
    )
    parser.add_argument(
        "--fetch-fsaverage",
        action="store_true",
        help="Allow MNE to fetch fsaverage into the external user cache if missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_project_l2_mne_hauk_zscore_payloads(
        project_root=args.project_root,
        output_dir=args.output,
        conditions=args.conditions,
        include_flagged_subjects=args.include_flagged,
        spacing=args.spacing,
        allow_fetch_fsaverage=args.fetch_fsaverage,
    )
    logger.info(
        "project_l2_mne_hauk_zscore_export_complete",
        extra={"manifest_path": str(result.manifest_path), "condition_count": len(result.producer_result.payloads)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
