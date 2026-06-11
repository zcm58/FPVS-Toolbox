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
from typing import Callable, Sequence

from Tools.LORETA_Visualizer.source_producers.contracts import SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    L2MNEHaukZScoreConfig,
    write_l2_mne_hauk_participant_zscore_surface_payloads,
    write_l2_mne_hauk_zscore_surface_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
    ProjectParticipantSourceFrequencyBinInputSet,
    ProjectSourceFrequencyBinInputSet,
    build_l2_mne_hauk_participant_zscore_conditions_from_project,
    build_l2_mne_hauk_zscore_conditions_from_project,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    DEFAULT_MNE_FSAVERAGE_SPACING,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    build_mne_fsaverage_l2_mne_forward_model,
)
from Tools.LORETA_Visualizer.source_producers.source_validation_report import (
    write_project_source_validation_report,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]

PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER = "L2-MNE Hauk Z-Score Beta"
DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME = "project_l2_mne_hauk_zscore_beta_manifest.json"
PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST = "participant_first"
PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST = "deprecated_group_first"


class ProjectL2MNEHaukZScoreExportError(RuntimeError):
    """Raised when project-level Hauk z-score source maps cannot be written."""


@dataclass(frozen=True)
class ProjectL2MNEHaukZScoreExportResult:
    """Project source z-score export result plus project-input diagnostics."""

    project_inputs: ProjectSourceFrequencyBinInputSet | ProjectParticipantSourceFrequencyBinInputSet
    producer_result: SourceProducerRunResult
    forward_model: L2MNECorticalForwardModel
    export_model: str = PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST
    participant_sidecar_path: Path | None = None
    lateralization_summary_path: Path | None = None
    lateralization_summary_csv_path: Path | None = None
    validation_report_path: Path | None = None
    validation_report_markdown_path: Path | None = None

    @property
    def output_dir(self) -> Path:
        """Directory containing the manifest and source payload files."""
        return self.producer_result.output_dir

    @property
    def manifest_path(self) -> Path:
        """Manifest JSON path that the visualizer can load."""
        return self.producer_result.manifest_path


def default_project_l2_mne_hauk_zscore_output_dir(project_root: str | Path) -> Path:
    """Return the project-local default output directory for Hauk z-score exports."""
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
    zscore_model: str = PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST,
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    cluster_mask_enabled: bool = True,
    cluster_forming_p_value: float = 0.05,
    cluster_alpha: float = 0.05,
    cluster_permutation_count: int = 10000,
    cluster_permutation_seed: int = 20260609,
    progress_callback: ProgressCallback | None = None,
) -> ProjectL2MNEHaukZScoreExportResult:
    """Write Hauk-style source-space z-score JSON for an existing project.

    The default output directory is project-local:
    ``6 - Source Localization/L2-MNE Hauk Z-Score Beta``.
    """
    root = _project_root(project_root)
    resolved_output = _project_output_dir(root, output_dir)
    model = _validate_zscore_model(zscore_model)
    participant_first = model == PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST

    if participant_first:
        _emit_progress(progress_callback, "Reading participant FullFFT workbooks and selected harmonics...")
        project_inputs = build_l2_mne_hauk_participant_zscore_conditions_from_project(
            root,
            conditions=conditions,
            include_flagged_subjects=include_flagged_subjects,
            noise_window_bins=noise_window_bins,
            excluded_offsets=excluded_offsets,
            min_noise_bins=min_noise_bins,
        )
    else:
        _emit_progress(progress_callback, "Reading project FullFFT workbooks for deprecated group-first z-scores...")
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
    input_scope = "participant-level" if participant_first else "deprecated group-level"
    _emit_progress(
        progress_callback,
        (
            f"Prepared {input_scope} source inputs for {len(project_inputs.conditions)} condition(s) "
            f"using {len(project_inputs.selected_harmonics_hz)} selected harmonic(s)."
        ),
    )

    if forward_model is None:
        _emit_progress(
            progress_callback,
            f"Building fsaverage L2-MNE inverse model ({spacing}); this can take a minute...",
        )
        model_forward = build_mne_fsaverage_l2_mne_forward_model(
            spacing=spacing,
            allow_fetch_fsaverage=allow_fetch_fsaverage,
        )
    else:
        _emit_progress(progress_callback, "Using supplied L2-MNE inverse model.")
        model_forward = forward_model
    _emit_progress(progress_callback, "L2-MNE inverse model is ready.")

    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=project_inputs.selected_harmonics_hz,
        noise_window_bins=project_inputs.bin_plan.noise_window_bins,
        excluded_noise_offsets=project_inputs.bin_plan.excluded_offsets,
        min_noise_bins=project_inputs.bin_plan.min_noise_bins,
        cluster_mask_enabled=cluster_mask_enabled and participant_first,
        cluster_forming_p_value=cluster_forming_p_value,
        cluster_alpha=cluster_alpha,
        cluster_permutation_count=cluster_permutation_count,
        cluster_permutation_seed=cluster_permutation_seed,
        metadata={
            "project_integration": (
                "phase_6h_a2_project_l2_mne_participant_first_hauk_zscore"
                if participant_first
                else "phase_6d_project_l2_mne_hauk_zscore_beta_deprecated_group_first"
            ),
            "source_map_model": "participant_first" if participant_first else "deprecated_group_first",
            "project_root_name": root.name,
            "source_topography_metric": "fullfft_amplitude_target_and_neighbor_bins",
            "source_topography_sheet": project_inputs.sheet_name,
            "include_flagged_subjects": include_flagged_subjects,
            "excluded_subjects": list(project_inputs.excluded_subjects),
            "flagged_subjects": list(project_inputs.flagged_subjects),
            "project_input_diagnostics": list(project_inputs.diagnostics),
            "frequency_resolution_hz": project_inputs.bin_plan.frequency_resolution_hz,
            "output_scope": "project-local",
            "cluster_mask": (
                "source_space_cluster_permutation"
                if cluster_mask_enabled and participant_first
                else "none"
            ),
        },
    )

    if participant_first:
        participant_result = write_l2_mne_hauk_participant_zscore_surface_payloads(
            forward_model=model_forward,
            conditions=project_inputs.conditions,
            config=config,
            output_dir=resolved_output,
            manifest_name=DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME,
            aggregations=aggregations,
            trim_fraction=trim_fraction,
            progress_callback=progress_callback,
        )
        producer_result = participant_result.producer_result
        participant_sidecar_path = participant_result.participant_sidecar_path
        lateralization_summary_path = participant_result.lateralization_summary_path
        lateralization_summary_csv_path = participant_result.lateralization_summary_csv_path
    else:
        producer_result = write_l2_mne_hauk_zscore_surface_payloads(
            forward_model=model_forward,
            conditions=project_inputs.conditions,
            config=config,
            output_dir=resolved_output,
            manifest_name=DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME,
            progress_callback=progress_callback,
        )
        participant_sidecar_path = None
        lateralization_summary_path = None
        lateralization_summary_csv_path = None

    _emit_progress(progress_callback, "Writing project source-validation report...")
    validation_report = write_project_source_validation_report(
        output_dir=producer_result.output_dir,
        manifest_path=producer_result.manifest_path,
        payloads=producer_result.payloads,
        project_inputs=project_inputs,
        export_model=model,
        participant_sidecar_path=participant_sidecar_path,
        lateralization_summary_path=lateralization_summary_path,
        lateralization_summary_csv_path=lateralization_summary_csv_path,
        forward_model_metadata=model_forward.metadata,
    )
    _emit_progress(progress_callback, f"Source-map JSON export complete: {producer_result.manifest_path}")
    logger.info(
        "project_l2_mne_hauk_zscore_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(producer_result.output_dir),
            "condition_count": len(producer_result.payloads),
            "zscore_model": model,
            "lateralization_summary_path": str(lateralization_summary_path) if lateralization_summary_path else "",
            "validation_report_path": str(validation_report.json_path),
        },
    )
    return ProjectL2MNEHaukZScoreExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model_forward,
        export_model=model,
        participant_sidecar_path=participant_sidecar_path,
        lateralization_summary_path=lateralization_summary_path,
        lateralization_summary_csv_path=lateralization_summary_csv_path,
        validation_report_path=validation_report.json_path,
        validation_report_markdown_path=validation_report.markdown_path,
    )


def write_project_l2_mne_hauk_zscore_group_first_payloads(
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
    progress_callback: ProgressCallback | None = None,
) -> ProjectL2MNEHaukZScoreExportResult:
    """Write the deprecated group-first source z-score maps."""
    return write_project_l2_mne_hauk_zscore_payloads(
        project_root=project_root,
        output_dir=output_dir,
        conditions=conditions,
        include_flagged_subjects=include_flagged_subjects,
        spacing=spacing,
        allow_fetch_fsaverage=allow_fetch_fsaverage,
        forward_model=forward_model,
        noise_window_bins=noise_window_bins,
        excluded_offsets=excluded_offsets,
        min_noise_bins=min_noise_bins,
        zscore_model=PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
        progress_callback=progress_callback,
    )


def _validate_zscore_model(value: str) -> str:
    model = str(value).strip().lower()
    if model in {"", PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST}:
        return PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST
    if model == PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST:
        return PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST
    raise ValueError(
        "Unsupported project Hauk z-score model: "
        f"{value!r}. Expected {PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST!r} "
        f"or {PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST!r}."
    )


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


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
    parser.add_argument("--output", help="Project-local output directory. Defaults to the source folder.")
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
    parser.add_argument(
        "--deprecated-group-first",
        action="store_true",
        help="Use the deprecated group-first z-score model instead of participant-first maps.",
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
        zscore_model=(
            PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST
            if args.deprecated_group_first
            else PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST
        ),
    )
    logger.info(
        "project_l2_mne_hauk_zscore_export_complete",
        extra={
            "manifest_path": str(result.manifest_path),
            "condition_count": len(result.producer_result.payloads),
            "zscore_model": result.export_model,
            "lateralization_summary_path": (
                str(result.lateralization_summary_path) if result.lateralization_summary_path else ""
            ),
            "validation_report_path": str(result.validation_report_path) if result.validation_report_path else "",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
