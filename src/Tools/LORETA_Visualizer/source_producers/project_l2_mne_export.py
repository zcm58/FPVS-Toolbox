"""Project-level beta L2-MNE source-map export.

This module combines read-only project workbook topographies with a shared
MNE/fsaverage EEG forward model, then writes prepared JSON payloads for the
visualizer importer. It owns calculation orchestration only; it does not import
GUI, renderer, display mesh, or display-transform modules.
"""

from __future__ import annotations

import argparse
import logging
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.error import URLError

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.fsaverage_cache import (
    FSAVERAGE_SUBJECT,
    candidate_fsaverage_subjects_dirs,
    ensure_allowed_fsaverage_subjects_dir,
    fetch_fsaverage_subjects_dir,
    preferred_fsaverage_subjects_dirs,
)
from Tools.LORETA_Visualizer.source_producers.contracts import SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import (
    COORDINATE_SPACE_FSAVERAGE,
    HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
    HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES,
    L2MNECorticalForwardModel,
    L2MNEProducerConfig,
    write_l2_mne_cortical_surface_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    SOURCE_TOPOGRAPHY_METRIC_BCA,
    SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
    ProjectSourceTopographyInputSet,
    build_l2_mne_conditions_from_project,
)

logger = logging.getLogger(__name__)

PROJECT_SOURCE_LOCALIZATION_FOLDER = "6 - Source Localization"
PROJECT_L2_MNE_BETA_OUTPUT_FOLDER = "L2-MNE Cortical Surface Beta"
DEFAULT_MNE_FSAVERAGE_SPACING = "ico3"
DEFAULT_MNE_MINDIST_MM = 5.0
FSAVERAGE_BEM_SOLUTION = "fsaverage-5120-5120-5120-bem-sol.fif"
FSAVERAGE_TRANS = "fsaverage-trans.fif"
SUPPORTED_PROJECT_SOURCE_METRICS = (
    SOURCE_TOPOGRAPHY_METRIC_BCA,
    SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
)


class ProjectL2MNEExportError(RuntimeError):
    """Raised when project-level beta L2-MNE source maps cannot be written."""


@dataclass(frozen=True)
class ProjectL2MNEExportResult:
    """Project source-map export result plus project-input diagnostics."""

    project_inputs: ProjectSourceTopographyInputSet
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


def default_project_l2_mne_output_dir(project_root: str | Path) -> Path:
    """Return the project-local default output directory for 6C beta exports."""
    root = Path(project_root).expanduser().resolve()
    return root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_BETA_OUTPUT_FOLDER


def write_project_l2_mne_cortical_surface_payloads(
    *,
    project_root: str | Path,
    output_dir: str | Path | None = None,
    metric: str = SOURCE_TOPOGRAPHY_METRIC_BCA,
    conditions: Sequence[str] | None = None,
    include_flagged_subjects: bool = False,
    spacing: str = DEFAULT_MNE_FSAVERAGE_SPACING,
    allow_fetch_fsaverage: bool = False,
    harmonic_strategy: str = HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
    forward_model: L2MNECorticalForwardModel | None = None,
) -> ProjectL2MNEExportResult:
    """Write beta L2-MNE cortical source-map JSON for an existing project.

    The default output directory is project-local:
    ``6 - Source Localization/L2-MNE Cortical Surface Beta``.
    """
    root = _project_root(project_root)
    resolved_output = _project_output_dir(root, output_dir)
    project_inputs = build_l2_mne_conditions_from_project(
        root,
        metric=metric,
        conditions=conditions,
        include_flagged_subjects=include_flagged_subjects,
    )
    if not project_inputs.conditions:
        diagnostics = "; ".join(project_inputs.diagnostics) or "no source-ready project conditions were assembled"
        raise ProjectL2MNEExportError(f"Project L2-MNE export has no conditions to write: {diagnostics}.")

    model = forward_model or build_mne_fsaverage_l2_mne_forward_model(
        spacing=spacing,
        allow_fetch_fsaverage=allow_fetch_fsaverage,
    )
    config = L2MNEProducerConfig(
        selected_harmonics_hz=project_inputs.selected_harmonics_hz,
        harmonic_strategy=harmonic_strategy,
        metadata={
            "project_integration": "phase_6c_project_l2_mne_beta",
            "project_root_name": root.name,
            "source_topography_metric": project_inputs.metric,
            "source_topography_sheet": project_inputs.sheet_name,
            "include_flagged_subjects": include_flagged_subjects,
            "excluded_subjects": list(project_inputs.excluded_subjects),
            "flagged_subjects": list(project_inputs.flagged_subjects),
            "project_input_diagnostics": list(project_inputs.diagnostics),
            "output_scope": "project-local",
        },
    )
    producer_result = write_l2_mne_cortical_surface_payloads(
        forward_model=model,
        conditions=project_inputs.conditions,
        config=config,
        output_dir=resolved_output,
        manifest_name="project_l2_mne_cortical_surface_beta_manifest.json",
    )
    logger.info(
        "project_l2_mne_cortical_surface_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(producer_result.output_dir),
            "condition_count": len(producer_result.payloads),
            "metric": project_inputs.metric,
        },
    )
    return ProjectL2MNEExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model,
    )


def build_mne_fsaverage_l2_mne_forward_model(
    *,
    spacing: str = DEFAULT_MNE_FSAVERAGE_SPACING,
    allow_fetch_fsaverage: bool = False,
    mindist_mm: float = DEFAULT_MNE_MINDIST_MM,
) -> L2MNECorticalForwardModel:
    """Build a fixed-orientation BioSemi64/fsaverage forward model with MNE."""
    try:
        import mne
    except (ImportError, ModuleNotFoundError) as exc:
        raise ProjectL2MNEExportError(f"MNE is required for the beta fsaverage forward model: {exc}") from exc

    subjects_dir = _resolve_fsaverage_subjects_dir(mne, allow_fetch=allow_fetch_fsaverage)
    subject_dir = subjects_dir / FSAVERAGE_SUBJECT
    bem_path = subject_dir / "bem" / FSAVERAGE_BEM_SOLUTION
    trans_path = subject_dir / "bem" / FSAVERAGE_TRANS
    _require_file(bem_path, description="fsaverage BEM solution")
    _require_file(trans_path, description="fsaverage transform")

    channel_names = tuple(DEFAULT_ELECTRODE_NAMES_64)
    info = _biosemi64_info(mne, channel_names)
    try:
        src = mne.setup_source_space(
            FSAVERAGE_SUBJECT,
            spacing=str(spacing),
            add_dist=False,
            subjects_dir=subjects_dir,
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
        fixed_forward = mne.convert_forward_solution(
            forward,
            surf_ori=True,
            force_fixed=True,
            use_cps=True,
            verbose=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectL2MNEExportError(f"Unable to build MNE/fsaverage forward model: {exc}") from exc

    leadfield = np.asarray(fixed_forward["sol"]["data"], dtype=float)
    row_names = tuple(str(name) for name in fixed_forward["sol"]["row_names"])
    if row_names != channel_names:
        raise ProjectL2MNEExportError(
            "MNE forward model channel order did not match the expected BioSemi64 order."
        )
    source_points, faces, hemi_counts = _surface_source_points_and_faces(
        fixed_forward["src"],
        coordinate_source_spaces=src,
    )
    if leadfield.shape[1] != len(source_points):
        raise ProjectL2MNEExportError(
            "MNE forward model source count does not match extracted source-space coordinates."
        )

    return L2MNECorticalForwardModel(
        channel_names=channel_names,
        source_points=source_points,
        leadfield=leadfield,
        faces=faces,
        coordinate_space=COORDINATE_SPACE_FSAVERAGE,
        label=f"MNE fsaverage {spacing} BioSemi64 fixed-orientation cortical surface",
        metadata={
            "forward_model_status": "beta MNE/fsaverage template EEG forward model",
            "mne_version": str(mne.__version__),
            "fsaverage_subjects_dir": str(subjects_dir),
            "fsaverage_subject": FSAVERAGE_SUBJECT,
            "source_spacing": str(spacing),
            "mindist_mm": float(mindist_mm),
            "source_points_unit": "FreeSurfer surface millimeters",
            "leadfield_shape": [int(leadfield.shape[0]), int(leadfield.shape[1])],
            "hemi_source_counts": list(hemi_counts),
            "subject_mri": "template fsaverage only",
        },
    )


def _project_root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    return root


def _project_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    target = default_project_l2_mne_output_dir(project_root) if output_dir is None else Path(output_dir)
    if not target.is_absolute():
        target = project_root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Project L2-MNE output directory must stay inside the project root.") from exc
    return resolved


def _resolve_fsaverage_subjects_dir(mne_module, *, allow_fetch: bool) -> Path:  # noqa: ANN001
    try:
        candidates = preferred_fsaverage_subjects_dirs() if allow_fetch else _candidate_subjects_dirs(mne_module)
    except ValueError as exc:
        raise ProjectL2MNEExportError(str(exc)) from exc
    for candidate in candidates:
        fsaverage_dir = candidate / FSAVERAGE_SUBJECT
        if fsaverage_dir.is_dir() and (not allow_fetch or _has_required_forward_model_files(candidate)):
            try:
                return ensure_allowed_fsaverage_subjects_dir(candidate)
            except ValueError as exc:
                raise ProjectL2MNEExportError(str(exc)) from exc

    if not allow_fetch:
        raise ProjectL2MNEExportError("fsaverage is not available and fetching is disabled.")
    try:
        subjects_dir = fetch_fsaverage_subjects_dir()
    except ValueError as exc:
        raise ProjectL2MNEExportError(str(exc)) from exc
    try:
        from mne.datasets import fetch_fsaverage

        fsaverage_dir = Path(fetch_fsaverage(subjects_dir=subjects_dir, verbose=False))
    except (OSError, RuntimeError, ValueError, ImportError, ModuleNotFoundError, URLError, ssl.SSLError, TimeoutError) as exc:
        raise ProjectL2MNEExportError(f"Unable to fetch fsaverage through MNE: {exc}") from exc
    try:
        return ensure_allowed_fsaverage_subjects_dir(fsaverage_dir.parent)
    except ValueError as exc:
        raise ProjectL2MNEExportError(str(exc)) from exc


def _candidate_subjects_dirs(mne_module) -> list[Path]:  # noqa: ANN001
    return candidate_fsaverage_subjects_dirs(mne_module)


def _has_required_forward_model_files(subjects_dir: Path) -> bool:
    subject_dir = subjects_dir / FSAVERAGE_SUBJECT
    return (
        (subject_dir / "bem" / FSAVERAGE_BEM_SOLUTION).is_file()
        and (subject_dir / "bem" / FSAVERAGE_TRANS).is_file()
    )


def _require_file(path: Path, *, description: str) -> None:
    if not path.is_file():
        raise ProjectL2MNEExportError(f"Missing {description}: {path}")


def _biosemi64_info(mne_module, channel_names: tuple[str, ...]):  # noqa: ANN001, ANN202
    montage = mne_module.channels.make_standard_montage("biosemi64")
    missing = sorted(set(channel_names) - set(montage.ch_names))
    if missing:
        raise ProjectL2MNEExportError(f"BioSemi64 montage is missing expected channels: {missing}")
    info = mne_module.create_info(ch_names=list(channel_names), sfreq=100.0, ch_types="eeg")
    info.set_montage(montage, match_case=False)
    return info


def _surface_source_points_and_faces(  # noqa: ANN001
    source_spaces,
    *,
    coordinate_source_spaces=None,
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    points_by_hemi: list[np.ndarray] = []
    faces_by_hemi: list[np.ndarray] = []
    source_counts: list[int] = []
    offset = 0
    coordinate_spaces = source_spaces if coordinate_source_spaces is None else coordinate_source_spaces
    if len(coordinate_spaces) != len(source_spaces):
        raise ProjectL2MNEExportError("MNE source-space coordinate and forward spaces do not match by hemisphere.")
    for source_space, coordinate_space in zip(source_spaces, coordinate_spaces, strict=True):
        vertno = np.asarray(source_space["vertno"], dtype=np.int64)
        rr = np.asarray(coordinate_space["rr"], dtype=float)
        points = rr[vertno] * 1000.0
        faces = _local_source_faces(source_space, vertno=vertno)
        if len(faces):
            faces_by_hemi.append(faces + offset)
        points_by_hemi.append(points.astype(float))
        source_counts.append(int(len(points)))
        offset += len(points)

    if not points_by_hemi:
        raise ProjectL2MNEExportError("MNE source space did not contain cortical source points.")
    source_points = np.vstack(points_by_hemi)
    if not faces_by_hemi:
        raise ProjectL2MNEExportError("MNE source space did not contain triangular cortical faces.")
    faces = np.vstack(faces_by_hemi).astype(np.int64)
    return source_points, faces, tuple(source_counts)


def _local_source_faces(source_space, *, vertno: np.ndarray) -> np.ndarray:  # noqa: ANN001
    use_tris = np.asarray(source_space.get("use_tris", []), dtype=np.int64)
    if use_tris.ndim == 2 and use_tris.shape[1] == 3 and len(use_tris):
        if int(np.max(use_tris)) < len(vertno):
            return use_tris.astype(np.int64)
        return _map_original_vertex_faces(use_tris, vertno=vertno)

    tris = np.asarray(source_space.get("tris", []), dtype=np.int64)
    if tris.ndim == 2 and tris.shape[1] == 3 and len(tris):
        return _map_original_vertex_faces(tris, vertno=vertno)
    return np.empty((0, 3), dtype=np.int64)


def _map_original_vertex_faces(faces: np.ndarray, *, vertno: np.ndarray) -> np.ndarray:
    local_index = {int(vertex): index for index, vertex in enumerate(vertno)}
    mapped: list[list[int]] = []
    for face in np.asarray(faces, dtype=np.int64):
        try:
            mapped.append([local_index[int(face[0])], local_index[int(face[1])], local_index[int(face[2])]])
        except KeyError:
            continue
    return np.asarray(mapped, dtype=np.int64).reshape(-1, 3)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write beta L2-MNE cortical-surface prepared JSON from an FPVS project."
    )
    parser.add_argument("--project-root", required=True, help="FPVS project root.")
    parser.add_argument("--output", help="Project-local output directory. Defaults to the Phase 6C source folder.")
    parser.add_argument(
        "--metric",
        choices=SUPPORTED_PROJECT_SOURCE_METRICS,
        default=SOURCE_TOPOGRAPHY_METRIC_BCA,
        help="Project workbook metric sheet to use for condition topographies.",
    )
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
        "--harmonic-strategy",
        choices=(
            HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
            HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES,
        ),
        default=HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_project_l2_mne_cortical_surface_payloads(
        project_root=args.project_root,
        output_dir=args.output,
        metric=args.metric,
        conditions=args.conditions,
        include_flagged_subjects=args.include_flagged,
        spacing=args.spacing,
        allow_fetch_fsaverage=args.fetch_fsaverage,
        harmonic_strategy=args.harmonic_strategy,
    )
    logger.info(
        "project_l2_mne_export_complete",
        extra={"manifest_path": str(result.manifest_path), "condition_count": len(result.producer_result.payloads)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
