"""Stats-ready workbook generation helpers for the LORETA Visualizer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from pathlib import Path

from Main_App import SettingsManager
from Main_App.processing.post_processing_context import post_processing_validation_scope
from Main_App.processing.artifact_freshness import (
    STATS_READY_SUMMED_BCA_ARTIFACT,
    StalePostProcessingArtifactError,
    require_current_artifact,
)
from Main_App.projects import (
    ProjectDatasetIndex,
    STATS_SUBFOLDER_NAME,
    load_project_dataset_index,
)
from Tools.Stats.analysis.canonical_harmonics import (
    CanonicalHarmonicSelectionError,
    load_project_processing_harmonics,
)
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Stats.io.stats_ready_export import STATS_READY_WORKBOOK_NAME, prepare_stats_ready_export


@dataclass(frozen=True)
class LoretaStatsReadyExportResult:
    """Summary of a Stats-ready workbook generated from the LORETA workflow."""

    workbook_path: Path
    row_count: int
    sheet_names: tuple[str, ...]
    subject_count: int
    condition_count: int


def default_loreta_stats_ready_workbook_path(project_root: str | Path) -> Path:
    """Return the workbook path currently required by LORETA project source-map producers."""

    return Path(project_root) / STATS_SUBFOLDER_NAME / STATS_READY_WORKBOOK_NAME


def stats_ready_workbook_exists(project_root: str | Path) -> bool:
    """Return whether the LORETA prerequisite exists and is current."""

    root = Path(project_root).expanduser().resolve()
    workbook_path = default_loreta_stats_ready_workbook_path(root)
    if not workbook_path.is_file():
        return False
    if not (root / "project.json").is_file():
        return True
    try:
        require_current_artifact(
            root,
            STATS_READY_SUMMED_BCA_ARTIFACT,
            workbook_path,
        )
    except (StalePostProcessingArtifactError, OSError, ValueError):
        return False
    return True


@post_processing_validation_scope()
def write_loreta_stats_ready_workbook(
    project_root: str | Path,
    *,
    log_callback: Callable[[str], None] | None = None,
    dataset_index: ProjectDatasetIndex | None = None,
) -> LoretaStatsReadyExportResult:
    """Generate the Stats-ready workbook needed before project source-map visualization."""

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project folder does not exist: {root}")

    log = log_callback or (lambda _message: None)
    log("Scanning processed project workbooks for the LORETA summary report...")
    if dataset_index is None:
        dataset_index = load_project_dataset_index(root)
    elif dataset_index.project_root.resolve() != root:
        raise ValueError(
            "The supplied dataset index belongs to a different project root."
        )
    for diagnostic in dataset_index.diagnostics:
        log(f"Dataset index: {diagnostic.message}")
    dataset_index.require_group_assignments()
    subjects = list(dataset_index.participant_ids)
    conditions = list(dataset_index.conditions)
    subject_data = dataset_index.subject_data()
    if not subjects or not conditions:
        raise RuntimeError(
            "No processed participant workbooks were found. Process the project data before generating the "
            "LORETA summary report."
        )

    manager = SettingsManager()
    rois = load_rois_from_settings(manager)
    if not rois:
        raise RuntimeError("No ROI definitions were found in Settings. Add at least one ROI before generating the report.")

    try:
        canonical_harmonics = load_project_processing_harmonics(
            project_root=root,
            log_func=log,
        )
        base_freq = float(canonical_harmonics.metadata["base_frequency_hz"])
    except (CanonicalHarmonicSelectionError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "The LORETA summary report requires the current project harmonic "
            "selection and its presentation rate. Recalculate Harmonics before "
            "generating the report."
        ) from exc
    if not math.isfinite(base_freq) or base_freq <= 0:
        raise RuntimeError(
            "The accepted project harmonic selection has an invalid presentation rate. "
            "Recalculate Harmonics before generating the LORETA summary report."
        )
    group_ids = dataset_index.participant_group_id_map(
        uppercase_keys=True,
        include_legacy_aliases=True,
    )
    group_map = {
        subject: group_ids.get(subject.upper())
        for subject in subjects
    }
    group_labels = dataset_index.participant_group_label_map(
        uppercase_keys=True,
        include_legacy_aliases=True,
    )
    group_label_map = {
        subject: group_labels.get(subject.upper())
        for subject in subjects
    }
    workbook_path = default_loreta_stats_ready_workbook_path(root)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    export = prepare_stats_ready_export(
        subjects=list(subjects),
        conditions=list(conditions),
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        # Managed-project export resolves the accepted canonical profile inside
        # the Stats export facade; this writer must not impose a group policy.
        dv_policy=None,
        group_map=group_map,
        group_label_map=group_label_map,
        log_func=log,
        save_path=workbook_path,
        # Managed projects consume the exact processing-owned harmonic list.
        # A second application-level frequency ceiling must not narrow it.
        max_freq=None,
        selection_conditions=list(conditions),
        project_root=str(root),
    )
    if export.workbook_path is None:
        raise RuntimeError("Stats-ready workbook generation finished without writing a workbook.")

    return LoretaStatsReadyExportResult(
        workbook_path=Path(export.workbook_path),
        row_count=int(export.row_count),
        sheet_names=tuple(str(name) for name in export.frames.keys()),
        subject_count=len(subjects),
        condition_count=len(conditions),
    )
