"""Post-processing orchestration worker for completed project processing runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

PIPELINE_STEP_EXCEPTIONS = (
    OSError,
    RuntimeError,
    ValueError,
    ImportError,
    ModuleNotFoundError,
    KeyError,
    TypeError,
)
SOURCE_OUTPUT_MODES = ("l2_mne_surface", "eloreta_volume")
PARTICIPANT_FIRST_ZSCORE_MODEL = "participant_first"


@dataclass(frozen=True)
class PostProcessingStepResult:
    """Serializable summary for one post-processing pipeline step."""

    name: str
    ok: bool
    message: str
    path: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "path": self.path,
        }


class PostProcessingPipelineWorker(QObject):
    """Run downstream analysis prep after preprocessing without touching widgets."""

    progress = Signal(str)
    log_message = Signal(str, int)
    finished = Signal(dict)

    def __init__(self, project: Any) -> None:
        super().__init__()
        self._project = project

    @Slot()
    def run(self) -> None:
        steps: list[PostProcessingStepResult] = []
        try:
            project_root = Path(self._project.project_root).expanduser().resolve()
            steps.append(self._run_harmonic_selection())
            stats_step = self._run_stats_ready_export(project_root)
            steps.append(stats_step)
            if stats_step.ok:
                steps.extend(self._run_source_maps(project_root))
            else:
                steps.append(
                    PostProcessingStepResult(
                        "loreta_source_maps",
                        False,
                        "Skipped LORETA source maps because the Stats-ready Summed BCA workbook was not generated.",
                    )
                )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_pipeline_failed")
            steps.append(
                PostProcessingStepResult(
                    "post_processing_pipeline",
                    False,
                    str(exc),
                )
            )
        ok = all(step.ok for step in steps)
        self.finished.emit(
            {
                "ok": ok,
                "steps": [step.as_dict() for step in steps],
            }
        )

    def _run_harmonic_selection(self) -> PostProcessingStepResult:
        self._emit_progress("FPVS Toolbox is currently identifying significant harmonics.")
        try:
            from Main_App.processing.harmonic_selection_qc import (
                run_processing_harmonic_selection_qc,
            )

            report = run_processing_harmonic_selection_qc(
                self._project,
                log_func=self._emit_progress,
            )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_harmonic_selection_failed")
            return PostProcessingStepResult("harmonic_selection", False, str(exc))
        return PostProcessingStepResult(
            "harmonic_selection",
            True,
            "Significant harmonic selection was recalculated.",
            str(report.workbook_path),
        )

    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self._emit_progress("FPVS Toolbox is preparing analysis files for downstream tools.")
        try:
            from Tools.LORETA_Visualizer.stats_ready_workbook import (
                default_loreta_stats_ready_workbook_path,
                write_loreta_stats_ready_workbook,
            )

            self._delete_file_if_present(
                default_loreta_stats_ready_workbook_path(project_root),
                project_root=project_root,
                label="Stats-ready Summed BCA workbook",
            )
            result = write_loreta_stats_ready_workbook(
                project_root,
                log_callback=self._emit_progress,
            )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_stats_ready_export_failed")
            return PostProcessingStepResult("stats_ready_summed_bca", False, str(exc))
        return PostProcessingStepResult(
            "stats_ready_summed_bca",
            True,
            f"Stats-ready Summed BCA workbook generated with {result.row_count} row(s).",
            str(result.workbook_path),
        )

    def _run_source_maps(self, project_root: Path) -> list[PostProcessingStepResult]:
        self._emit_progress("Generating source-space maps for 3D visualization of oddball responses.")
        steps: list[PostProcessingStepResult] = []
        for mode in SOURCE_OUTPUT_MODES:
            steps.append(self._run_source_map_mode(project_root, mode))
        return steps

    def _run_source_map_mode(
        self,
        project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        if mode == "l2_mne_surface":
            label = "L2-MNE surface source maps"
            try:
                from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
                    default_project_l2_mne_hauk_zscore_output_dir,
                    write_project_l2_mne_hauk_zscore_payloads,
                )

                self._clear_output_dir(
                    default_project_l2_mne_hauk_zscore_output_dir(project_root),
                    project_root=project_root,
                    label=label,
                )
                result = write_project_l2_mne_hauk_zscore_payloads(
                    project_root=project_root,
                    include_flagged_subjects=False,
                    zscore_model=PARTICIPANT_FIRST_ZSCORE_MODEL,
                    progress_callback=self._emit_progress,
                )
            except PIPELINE_STEP_EXCEPTIONS as exc:
                logger.exception("post_processing_l2_mne_source_maps_failed")
                return PostProcessingStepResult(mode, False, f"{label} failed: {exc}")
            return PostProcessingStepResult(
                mode,
                True,
                f"{label} generated.",
                str(result.manifest_path),
            )

        if mode == "eloreta_volume":
            label = "eLORETA volume source maps"
            try:
                from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
                    default_project_eloreta_volume_output_dir,
                    write_project_eloreta_volume_hauk_zscore_payloads,
                )

                self._clear_output_dir(
                    default_project_eloreta_volume_output_dir(project_root),
                    project_root=project_root,
                    label=label,
                )
                result = write_project_eloreta_volume_hauk_zscore_payloads(
                    project_root=project_root,
                    include_flagged_subjects=False,
                    progress_callback=self._emit_progress,
                )
            except PIPELINE_STEP_EXCEPTIONS as exc:
                logger.exception("post_processing_eloreta_source_maps_failed")
                return PostProcessingStepResult(mode, False, f"{label} failed: {exc}")
            return PostProcessingStepResult(
                mode,
                True,
                f"{label} generated.",
                str(result.manifest_path),
            )

        return PostProcessingStepResult(mode, False, f"Unsupported source-map mode: {mode}")

    def _delete_file_if_present(
        self,
        path: Path,
        *,
        project_root: Path,
        label: str,
    ) -> None:
        target = self._assert_under_project_root(path, project_root=project_root, label=label)
        if not target.is_file():
            return
        self._emit_progress(f"Removing stale {label}: {target}")
        target.unlink()

    def _clear_output_dir(
        self,
        output_dir: Path,
        *,
        project_root: Path,
        label: str,
    ) -> None:
        root = self._assert_under_project_root(output_dir, project_root=project_root, label=label)
        if not root.exists():
            return
        if root == project_root:
            raise ValueError(f"Refusing to clear project root for {label}: {root}")
        self._emit_progress(f"Removing stale {label} outputs...")
        for path in root.rglob("*"):
            if path.is_file():
                path.unlink()

    @staticmethod
    def _assert_under_project_root(path: Path, *, project_root: Path, label: str) -> Path:
        target = Path(path).expanduser().resolve()
        root = project_root.expanduser().resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Refusing to touch {label} outside the project root: {target}") from exc
        return target

    def _emit_progress(self, message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        self.progress.emit(text)
        self.log_message.emit(text, logging.DEBUG)


__all__ = ["PostProcessingPipelineWorker", "PostProcessingStepResult"]
