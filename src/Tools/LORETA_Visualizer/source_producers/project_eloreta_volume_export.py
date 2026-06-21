"""Project-level beta eLORETA volume source-space z-score export.

This module combines read-only project FullFFT topographies with an external
MNE/fsaverage EEG volume inverse model, then writes prepared JSON payloads for
the visualizer importer. It owns calculation orchestration only; it does not
import GUI, renderer, display mesh, or display-transform modules.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from Tools.LORETA_Visualizer.source_producers.contracts import SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    DEFAULT_CLUSTER_ALPHA,
    DEFAULT_CLUSTER_FORMING_P_VALUE,
    DEFAULT_CLUSTER_PERMUTATION_COUNT,
    DEFAULT_CLUSTER_PERMUTATION_SEED,
    DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    ELORETAVolumeForwardModel,
    ELORETAVolumeZScoreConfig,
    write_eloreta_volume_participant_zscore_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
    ProjectParticipantSourceFrequencyBinInputSet,
    build_l2_mne_hauk_participant_zscore_conditions_from_project,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    DEFAULT_MNE_MINDIST_MM,
    FSAVERAGE_BEM_SOLUTION,
    FSAVERAGE_SUBJECT,
    FSAVERAGE_TRANS,
    MNE_SOURCE_TOPOGRAPHY_UV_TO_V,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    _biosemi64_info,
    _project_root,
    _require_file,
    _resolve_fsaverage_subjects_dir,
    _with_eeg_average_reference_projection,
)
from Tools.LORETA_Visualizer.source_producers.source_space_statistics import adjacency_from_sparse_matrix
from Tools.LORETA_Visualizer.source_producers.source_validation_report import (
    write_project_source_validation_report,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]

PROJECT_ELORETA_VOLUME_OUTPUT_FOLDER = "eLORETA Volume Beta"
DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME = "project_eloreta_volume_hauk_zscore_beta_manifest.json"
DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM = 10.0
DEFAULT_MNE_ELORETA_LOOSE_ORIENTATION = 1.0


class ProjectELORETAVolumeExportError(RuntimeError):
    """Raised when project-level eLORETA volume maps cannot be written."""


@dataclass(frozen=True)
class ProjectELORETAVolumeExportResult:
    """Project eLORETA volume export result plus project-input diagnostics."""

    project_inputs: ProjectParticipantSourceFrequencyBinInputSet
    producer_result: SourceProducerRunResult
    forward_model: ELORETAVolumeForwardModel
    export_model: str = "participant_first"
    participant_sidecar_path: Path | None = None
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


def default_project_eloreta_volume_output_dir(project_root: str | Path) -> Path:
    """Return the project-local default output directory for eLORETA exports."""
    root = Path(project_root).expanduser().resolve()
    return root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_ELORETA_VOLUME_OUTPUT_FOLDER


def write_project_eloreta_volume_hauk_zscore_payloads(
    *,
    project_root: str | Path,
    output_dir: str | Path | None = None,
    conditions: Sequence[str] | None = None,
    include_flagged_subjects: bool = False,
    volume_pos_mm: float = DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM,
    allow_fetch_fsaverage: bool = False,
    forward_model: ELORETAVolumeForwardModel | None = None,
    noise_window_bins: int = DEFAULT_HAUK_ZSCORE_NOISE_WINDOW_BINS,
    excluded_offsets: Sequence[int] = DEFAULT_HAUK_ZSCORE_EXCLUDED_OFFSETS,
    min_noise_bins: int = DEFAULT_HAUK_ZSCORE_MIN_NOISE_BINS,
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    cluster_mask_enabled: bool = True,
    cluster_forming_p_value: float = DEFAULT_CLUSTER_FORMING_P_VALUE,
    cluster_alpha: float = DEFAULT_CLUSTER_ALPHA,
    cluster_permutation_count: int = DEFAULT_CLUSTER_PERMUTATION_COUNT,
    cluster_permutation_seed: int = DEFAULT_CLUSTER_PERMUTATION_SEED,
    progress_callback: ProgressCallback | None = None,
) -> ProjectELORETAVolumeExportResult:
    """Write eLORETA volume source-space z-score JSON for an existing project."""
    root = _project_root(project_root)
    resolved_output = _project_output_dir(root, output_dir)

    _emit_progress(progress_callback, "Reading participant FullFFT workbooks and selected harmonics...")
    project_inputs = build_l2_mne_hauk_participant_zscore_conditions_from_project(
        root,
        conditions=conditions,
        include_flagged_subjects=include_flagged_subjects,
        noise_window_bins=noise_window_bins,
        excluded_offsets=excluded_offsets,
        min_noise_bins=min_noise_bins,
    )
    if not project_inputs.conditions:
        diagnostics = "; ".join(project_inputs.diagnostics) or "no source-ready FullFFT conditions were assembled"
        raise ProjectELORETAVolumeExportError(
            f"Project eLORETA volume export has no conditions to write: {diagnostics}."
        )
    _emit_progress(
        progress_callback,
        (
            f"Prepared participant-level eLORETA source inputs for {len(project_inputs.conditions)} "
            f"condition(s) using {len(project_inputs.selected_harmonics_hz)} selected harmonic(s)."
        ),
    )

    if forward_model is None:
        _emit_progress(
            progress_callback,
            f"Building fsaverage eLORETA volume inverse model ({volume_pos_mm:g} mm grid); this can take a minute...",
        )
        model_forward = build_mne_fsaverage_eloreta_volume_forward_model(
            volume_pos_mm=volume_pos_mm,
            allow_fetch_fsaverage=allow_fetch_fsaverage,
        )
    else:
        _emit_progress(progress_callback, "Using supplied eLORETA volume inverse model.")
        model_forward = forward_model
    _emit_progress(progress_callback, "eLORETA volume inverse model is ready.")

    config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=project_inputs.selected_harmonics_hz,
        noise_window_bins=project_inputs.bin_plan.noise_window_bins,
        excluded_noise_offsets=project_inputs.bin_plan.excluded_offsets,
        min_noise_bins=project_inputs.bin_plan.min_noise_bins,
        cluster_mask_enabled=cluster_mask_enabled,
        cluster_forming_p_value=cluster_forming_p_value,
        cluster_alpha=cluster_alpha,
        cluster_permutation_count=cluster_permutation_count,
        cluster_permutation_seed=cluster_permutation_seed,
        metadata={
            "project_integration": "project_eloreta_volume_participant_first_hauk_zscore_beta",
            "source_map_model": "participant_first",
            "project_root_name": root.name,
            "source_topography_metric": "fullfft_amplitude_target_and_neighbor_bins",
            "source_topography_sheet": project_inputs.sheet_name,
            "include_flagged_subjects": include_flagged_subjects,
            "excluded_subjects": list(project_inputs.excluded_subjects),
            "flagged_subjects": list(project_inputs.flagged_subjects),
            "project_input_diagnostics": list(project_inputs.diagnostics),
            "frequency_resolution_hz": project_inputs.bin_plan.frequency_resolution_hz,
            "output_scope": "project-local",
            "cluster_mask": "source_space_cluster_permutation" if cluster_mask_enabled else "none",
        },
    )

    participant_result = write_eloreta_volume_participant_zscore_payloads(
        forward_model=model_forward,
        conditions=project_inputs.conditions,
        config=config,
        output_dir=resolved_output,
        manifest_name=DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME,
        aggregations=aggregations,
        trim_fraction=trim_fraction,
        progress_callback=progress_callback,
    )
    producer_result = participant_result.producer_result
    participant_sidecar_path = participant_result.participant_sidecar_path

    _emit_progress(progress_callback, "Writing eLORETA source-validation report...")
    validation_report = write_project_source_validation_report(
        output_dir=producer_result.output_dir,
        manifest_path=producer_result.manifest_path,
        payloads=producer_result.payloads,
        project_inputs=project_inputs,
        export_model="eloreta_volume_participant_first",
        participant_sidecar_path=participant_sidecar_path,
        lateralization_summary_path=None,
        lateralization_summary_csv_path=None,
        forward_model_metadata=model_forward.metadata,
    )
    _emit_progress(progress_callback, f"eLORETA source-map JSON export complete: {producer_result.manifest_path}")
    logger.info(
        "project_eloreta_volume_hauk_zscore_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(producer_result.output_dir),
            "condition_count": len(producer_result.payloads),
            "validation_report_path": str(validation_report.json_path),
        },
    )
    return ProjectELORETAVolumeExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model_forward,
        participant_sidecar_path=participant_sidecar_path,
        validation_report_path=validation_report.json_path,
        validation_report_markdown_path=validation_report.markdown_path,
    )


def build_mne_fsaverage_eloreta_volume_forward_model(
    *,
    volume_pos_mm: float = DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM,
    allow_fetch_fsaverage: bool = False,
    mindist_mm: float = DEFAULT_MNE_MINDIST_MM,
    loose_orientation: float = DEFAULT_MNE_ELORETA_LOOSE_ORIENTATION,
) -> ELORETAVolumeForwardModel:
    """Build a beta BioSemi64/fsaverage eLORETA volume inverse model with MNE."""
    try:
        import mne
        from mne.minimum_norm import apply_inverse, make_inverse_operator
    except (ImportError, ModuleNotFoundError) as exc:
        raise ProjectELORETAVolumeExportError(f"MNE is required for the eLORETA volume model: {exc}") from exc

    subjects_dir = _resolve_fsaverage_subjects_dir(mne, allow_fetch=allow_fetch_fsaverage)
    subject_dir = subjects_dir / FSAVERAGE_SUBJECT
    bem_path = subject_dir / "bem" / FSAVERAGE_BEM_SOLUTION
    trans_path = subject_dir / "bem" / FSAVERAGE_TRANS
    _require_file(bem_path, description="fsaverage BEM solution")
    _require_file(trans_path, description="fsaverage transform")

    from config import DEFAULT_ELECTRODE_NAMES_64

    channel_names = tuple(DEFAULT_ELECTRODE_NAMES_64)
    info = _biosemi64_info(mne, channel_names)
    info = _with_eeg_average_reference_projection(mne, info)
    try:
        src = mne.setup_volume_source_space(
            FSAVERAGE_SUBJECT,
            pos=float(volume_pos_mm),
            bem=bem_path,
            mindist=float(mindist_mm),
            subjects_dir=subjects_dir,
            add_interpolator=False,
            verbose=False,
        )
        forward = mne.make_forward_solution(
            info,
            trans=trans_path,
            src=src,
            bem=bem_path,
            eeg=True,
            meg=False,
            mindist=float(mindist_mm),
            n_jobs=1,
            verbose=False,
        )
        noise_cov = mne.make_ad_hoc_cov(info, verbose=False)
        inverse_operator = make_inverse_operator(
            info,
            forward,
            noise_cov,
            loose=float(loose_orientation),
            depth=None,
            fixed=False,
            verbose=False,
        )
        adjacency_matrix = mne.spatial_src_adjacency(src, verbose=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectELORETAVolumeExportError(f"Unable to build MNE/fsaverage eLORETA volume model: {exc}") from exc

    leadfield = np.asarray(forward["sol"]["data"], dtype=float)
    row_names = tuple(str(name) for name in forward["sol"]["row_names"])
    if row_names != channel_names:
        raise ProjectELORETAVolumeExportError(
            "MNE eLORETA volume forward model channel order did not match the expected BioSemi64 order."
        )
    source_points, source_indices = _volume_source_points(src)
    if leadfield.shape[1] not in {len(source_points), len(source_points) * 3}:
        raise ProjectELORETAVolumeExportError(
            "MNE eLORETA volume leadfield source count does not match extracted source-space coordinates."
        )
    source_adjacency = adjacency_from_sparse_matrix(adjacency_matrix, source_count=len(source_points))
    source_estimator = _make_mne_eloreta_volume_source_estimator(
        mne,
        info=info,
        apply_inverse_func=apply_inverse,
        inverse_operator=inverse_operator,
        source_count=len(source_points),
    )

    return ELORETAVolumeForwardModel(
        channel_names=channel_names,
        source_points=source_points,
        leadfield=leadfield,
        source_adjacency=source_adjacency,
        label=f"MNE fsaverage {volume_pos_mm:g} mm BioSemi64 eLORETA volume",
        metadata={
            "forward_model_status": "beta MNE/fsaverage template EEG eLORETA volume inverse model",
            "inverse_backend": "mne_python",
            "mne_inverse_method": "eLORETA",
            "orientation_constraint": "volume_free",
            "loose_orientation": float(loose_orientation),
            "fixed_orientation": False,
            "depth_weighting": "none",
            "noise_normalization": "eLORETA inverse normalization",
            "noise_covariance": "mne_ad_hoc_diagonal_eeg",
            "average_reference_projection": True,
            "regularization": "MNE inverse lambda2 with SNR=3 default",
            "input_unit_conversion": "uV topographies converted to V before MNE apply_inverse",
            "mne_version": str(mne.__version__),
            "fsaverage_subjects_dir": str(subjects_dir),
            "fsaverage_subject": FSAVERAGE_SUBJECT,
            "volume_pos_mm": float(volume_pos_mm),
            "mindist_mm": float(mindist_mm),
            "source_points_unit": "FreeSurfer volume millimeters",
            "leadfield_shape": [int(leadfield.shape[0]), int(leadfield.shape[1])],
            "source_count": int(len(source_points)),
            "source_space_kind": "volume",
            "source_adjacency": "mne.spatial_src_adjacency",
            "subject_mri": "template fsaverage only",
        },
        source_estimator=source_estimator,
        source_indices=source_indices,
    )


def _make_mne_eloreta_volume_source_estimator(  # noqa: ANN001
    mne_module,
    *,
    info,
    apply_inverse_func,
    inverse_operator,
    source_count: int,
):
    channel_names = tuple(info.ch_names)

    def estimate_source_values(topography, *, lambda2: float, method_params: dict | None = None):  # noqa: ANN001, ANN202
        topography_values = np.asarray(topography, dtype=float)
        single_topography = topography_values.ndim == 1
        if single_topography:
            topography_matrix = topography_values.reshape(1, -1)
        elif topography_values.ndim == 2:
            topography_matrix = topography_values
        else:
            raise ValueError("MNE eLORETA volume estimator expected a 1D or 2D topography array.")
        if topography_matrix.shape[1] != len(channel_names):
            raise ValueError(
                "MNE eLORETA volume estimator expected "
                f"{len(channel_names)} channel values; got shape {topography_matrix.shape}."
            )
        evoked = mne_module.EvokedArray(
            topography_matrix.T * MNE_SOURCE_TOPOGRAPHY_UV_TO_V,
            info.copy(),
            tmin=0.0,
            comment="FPVS eLORETA volume source topography",
            nave=1,
            baseline=None,
            verbose=False,
        )
        try:
            evoked.apply_proj(verbose=False)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise ProjectELORETAVolumeExportError(
                f"Unable to apply MNE projection before eLORETA source estimation: {exc}"
            ) from exc
        source_estimate = apply_inverse_func(
            evoked,
            inverse_operator,
            lambda2=float(lambda2),
            method="eLORETA",
            pick_ori=None,
            method_params=dict(method_params or {}) or None,
            verbose=False,
        )
        source_values = np.asarray(source_estimate.data, dtype=float)
        if source_values.ndim != 2 or source_values.shape[1] < 1:
            raise ProjectELORETAVolumeExportError("MNE eLORETA returned an unexpected source-estimate shape.")
        if source_values.shape[0] != int(source_count):
            raise ProjectELORETAVolumeExportError(
                f"MNE eLORETA returned {source_values.shape[0]} source values; {source_count} expected."
            )
        if source_values.shape[1] != topography_matrix.shape[0]:
            raise ProjectELORETAVolumeExportError(
                "MNE eLORETA returned an unexpected number of topography time points."
            )
        estimates = np.abs(source_values.T).astype(float)
        return estimates[0] if single_topography else estimates

    return estimate_source_values


def _volume_source_points(source_spaces) -> tuple[np.ndarray, tuple[int, ...]]:  # noqa: ANN001
    points_by_space: list[np.ndarray] = []
    indices: list[int] = []
    offset = 0
    for source_space in source_spaces:
        vertno = np.asarray(source_space["vertno"], dtype=np.int64)
        rr = np.asarray(source_space["rr"], dtype=float)
        points = rr[vertno] * 1000.0
        points_by_space.append(points.astype(float))
        indices.extend(int(index + offset) for index in vertno)
        offset += len(rr)
    if not points_by_space:
        raise ProjectELORETAVolumeExportError("MNE volume source space did not contain source points.")
    return np.vstack(points_by_space), tuple(indices)


def _project_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    target = default_project_eloreta_volume_output_dir(project_root) if output_dir is None else Path(output_dir)
    if not target.is_absolute():
        target = project_root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Project eLORETA volume output directory must stay inside the project root.") from exc
    return resolved


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write beta eLORETA volume source-space z-score prepared JSON from an FPVS project."
    )
    parser.add_argument("--project-root", required=True, help="FPVS project root.")
    parser.add_argument("--output", help="Project-local output directory. Defaults to the eLORETA source folder.")
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
        "--volume-pos-mm",
        type=float,
        default=DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM,
        help="MNE volume source-space grid spacing in mm.",
    )
    parser.add_argument(
        "--fetch-fsaverage",
        action="store_true",
        help="Allow MNE to fetch fsaverage into the external user cache if missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_project_eloreta_volume_hauk_zscore_payloads(
        project_root=args.project_root,
        output_dir=args.output,
        conditions=args.conditions,
        include_flagged_subjects=args.include_flagged,
        volume_pos_mm=args.volume_pos_mm,
        allow_fetch_fsaverage=args.fetch_fsaverage,
    )
    logger.info(
        "project_eloreta_volume_export_complete",
        extra={
            "manifest_path": str(result.manifest_path),
            "condition_count": len(result.producer_result.payloads),
            "validation_report_path": str(result.validation_report_path) if result.validation_report_path else "",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
