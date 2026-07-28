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
SOURCE_OUTPUT_MODES = (
    "l2_mne_source_psd",
    "eloreta_volume_source_psd",
)
POST_PROCESSING_PHASE_COUNT = 3 + len(SOURCE_OUTPUT_MODES)

_PHASE_FREQUENCY_DOMAIN_QC = "frequency_domain_qc"
_PHASE_HARMONIC_SELECTION = "harmonic_selection"
_PHASE_STATS_READY_EXPORT = "stats_ready_export"
_PHASE_COMPLETE = "post_processing_complete"
_SOURCE_PHASE_BY_MODE = {
    "l2_mne_source_psd": "l2_mne_source_maps",
    "eloreta_volume_source_psd": "eloreta_source_maps",
}
_SOURCE_PHASE_MESSAGE_BY_MODE = {
    "l2_mne_source_psd": (
        "Generating Hauk-informed time-domain L2-MNE source maps for 3D visualization of oddball responses."
    ),
    "eloreta_volume_source_psd": (
        "Generating Hauk-informed time-domain eLORETA volume maps for 3D visualization of oddball responses."
    ),
}


@dataclass(frozen=True)
class PostProcessingStepResult:
    """Serializable summary for one post-processing pipeline step."""

    name: str
    ok: bool
    message: str
    path: str = ""
    warning: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "path": self.path,
            "warning": self.warning,
        }


class PostProcessingPipelineWorker(QObject):
    """Run downstream analysis prep after preprocessing without touching widgets."""

    progress = Signal(str)
    phase_progress = Signal(str, int, int, str)
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
            qc_message = "FPVS Toolbox is checking summed BCA values before final harmonic selection."
            self._emit_phase_progress(
                _PHASE_FREQUENCY_DOMAIN_QC,
                0,
                qc_message,
            )
            qc_report = self._run_frequency_domain_qc_review()
            self._emit_phase_progress(
                _PHASE_FREQUENCY_DOMAIN_QC,
                1,
                qc_message,
            )
            if qc_report.get("review_required"):
                steps.append(
                    PostProcessingStepResult(
                        "frequency_domain_qc",
                        False,
                        "Frequency-domain QC review is required before final harmonic selection.",
                    )
                )
                self.finished.emit(
                    {
                        "ok": False,
                        "requires_frequency_domain_qc_review": True,
                        "frequency_domain_qc_report": qc_report,
                        "steps": [step.as_dict() for step in steps],
                    }
                )
                return
            self._sync_frequency_domain_qc_automatic_state(project_root, qc_report)
            if qc_report.get("review_reused"):
                steps.append(
                    PostProcessingStepResult(
                        "frequency_domain_qc",
                        True,
                        "Frequency-domain QC review was previously accepted for these inputs.",
                    )
                )
            else:
                steps.append(
                    PostProcessingStepResult(
                        "frequency_domain_qc",
                        True,
                        "Frequency-domain QC found no review-blocking flags.",
                    )
                )
            harmonic_message = "FPVS Toolbox is currently identifying significant harmonics."
            self._emit_phase_progress(
                _PHASE_HARMONIC_SELECTION,
                1,
                harmonic_message,
            )
            steps.append(self._run_harmonic_selection())
            self._emit_phase_progress(
                _PHASE_HARMONIC_SELECTION,
                2,
                harmonic_message,
            )
            stats_message = "FPVS Toolbox is preparing analysis files for downstream tools."
            self._emit_phase_progress(
                _PHASE_STATS_READY_EXPORT,
                2,
                stats_message,
            )
            stats_step = self._run_stats_ready_export(project_root)
            steps.append(stats_step)
            self._emit_phase_progress(
                _PHASE_STATS_READY_EXPORT,
                3,
                stats_message,
            )
            # Stats-ready export and source localization are sibling consumers
            # of the accepted harmonic selection. A failure in one must not
            # suppress the other scientific workflow.
            steps.extend(self._run_source_maps(project_root))
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
        has_warnings = any(step.warning for step in steps)
        completion_message = (
            "Post-processing is complete."
            if ok and not has_warnings
            else "Post-processing is complete with source-cohort warnings."
            if ok
            else "Post-processing finished with warnings; review the processing log for details."
        )
        self._emit_phase_progress(
            _PHASE_COMPLETE,
            POST_PROCESSING_PHASE_COUNT,
            completion_message,
        )
        self.finished.emit(
            {
                "ok": ok,
                "has_warnings": has_warnings,
                "steps": [step.as_dict() for step in steps],
            }
        )

    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self._emit_progress("FPVS Toolbox is reviewing frequency-domain QC before final harmonic selection.")
        from Main_App.processing.frequency_domain_qc import run_frequency_domain_qc_review

        return run_frequency_domain_qc_review(
            self._project,
            log_func=self._emit_progress,
        )

    def _sync_frequency_domain_qc_automatic_state(
        self,
        project_root: Path,
        qc_report: dict[str, object],
    ) -> None:
        from Main_App.processing.frequency_domain_qc import (
            sync_frequency_domain_qc_automatic_state,
        )

        sync_frequency_domain_qc_automatic_state(project_root, qc_report)

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
        self._emit_progress(
            "Generating Hauk-informed time-domain source-space maps for 3D visualization of oddball responses."
        )
        steps: list[PostProcessingStepResult] = []
        completed_before_source_maps = POST_PROCESSING_PHASE_COUNT - len(SOURCE_OUTPUT_MODES)
        for index, mode in enumerate(SOURCE_OUTPUT_MODES, start=1):
            phase_id = _SOURCE_PHASE_BY_MODE[mode]
            phase_message = _SOURCE_PHASE_MESSAGE_BY_MODE[mode]
            self._emit_phase_progress(
                phase_id,
                completed_before_source_maps + index - 1,
                phase_message,
            )
            steps.append(self._run_source_map_mode(project_root, mode))
            self._emit_phase_progress(
                phase_id,
                completed_before_source_maps + index,
                phase_message,
            )
        return steps

    def _run_source_map_mode(
        self,
        project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        if mode == "l2_mne_source_psd":
            label = "Hauk-informed time-domain L2-MNE source maps"
            try:
                default_output_dir, write_payloads = _load_source_psd_export_api()

                self._clear_output_dir(
                    default_output_dir(project_root),
                    project_root=project_root,
                    label=label,
                )
                result = write_payloads(
                    project=self._project,
                    project_root=project_root,
                    include_flagged_subjects=False,
                    allow_fetch_fsaverage=True,
                    progress_callback=self._emit_progress,
                )
            except PIPELINE_STEP_EXCEPTIONS as exc:
                logger.exception("post_processing_l2_mne_source_psd_maps_failed")
                return PostProcessingStepResult(mode, False, f"{label} failed: {exc}")
            source_ineligible = tuple(
                getattr(result, "source_ineligible_participants", ()) or ()
            )
            source_condition_omissions = tuple(
                getattr(result, "source_condition_omissions", ()) or ()
            )
            if source_ineligible or source_condition_omissions:
                skipped_ids = ", ".join(
                    str(getattr(item, "participant_id", "")).strip()
                    for item in source_ineligible
                    if str(getattr(item, "participant_id", "")).strip()
                )
                warning_parts = [
                    (
                        f"{label} generated from "
                        f"{len(tuple(getattr(result, 'included_participants', ()) or ()))} "
                        "source-eligible participant(s)"
                    )
                ]
                if source_ineligible:
                    warning_parts.append(
                        "source-ineligible participant(s) were omitted from "
                        f"every condition: {skipped_ids}"
                    )
                if source_condition_omissions:
                    warning_parts.append(
                        f"{len(source_condition_omissions)} incompatible or "
                        "unavailable participant-condition input(s) were omitted"
                    )
                return PostProcessingStepResult(
                    mode,
                    True,
                    "; ".join(warning_parts) + ".",
                    str(result.manifest_path),
                    warning=True,
                )
            return PostProcessingStepResult(
                mode,
                True,
                f"{label} generated.",
                str(result.manifest_path),
            )

        if mode == "eloreta_volume_source_psd":
            label = "Hauk-informed time-domain eLORETA volume source maps"
            try:
                default_output_dir, write_payloads = _load_eloreta_source_psd_export_api()

                self._clear_output_dir(
                    default_output_dir(project_root),
                    project_root=project_root,
                    label=label,
                )
                result = write_payloads(
                    project=self._project,
                    project_root=project_root,
                    include_flagged_subjects=False,
                    allow_fetch_fsaverage=True,
                    progress_callback=self._emit_progress,
                )
            except PIPELINE_STEP_EXCEPTIONS as exc:
                logger.exception("post_processing_eloreta_volume_source_psd_maps_failed")
                return PostProcessingStepResult(mode, False, f"{label} failed: {exc}")
            source_ineligible = tuple(
                getattr(result, "source_ineligible_participants", ()) or ()
            )
            source_condition_omissions = tuple(
                getattr(result, "source_condition_omissions", ()) or ()
            )
            if source_ineligible or source_condition_omissions:
                skipped_ids = ", ".join(
                    str(getattr(item, "participant_id", "")).strip()
                    for item in source_ineligible
                    if str(getattr(item, "participant_id", "")).strip()
                )
                warning_parts = [
                    (
                        f"{label} generated from "
                        f"{len(tuple(getattr(result, 'included_participants', ()) or ()))} "
                        "source-eligible participant(s)"
                    )
                ]
                if source_ineligible:
                    warning_parts.append(
                        "source-ineligible participant(s) were omitted from "
                        f"every condition: {skipped_ids}"
                    )
                if source_condition_omissions:
                    warning_parts.append(
                        f"{len(source_condition_omissions)} incompatible or "
                        "unavailable participant-condition input(s) were omitted"
                    )
                return PostProcessingStepResult(
                    mode,
                    True,
                    "; ".join(warning_parts) + ".",
                    str(result.manifest_path),
                    warning=True,
                )
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

    def _emit_phase_progress(
        self,
        phase_id: str,
        completed_units: int,
        message: str,
    ) -> None:
        """Emit coarse, structured progress across the downstream phases."""

        completed = max(0, min(POST_PROCESSING_PHASE_COUNT, int(completed_units)))
        self.phase_progress.emit(
            str(phase_id),
            completed,
            POST_PROCESSING_PHASE_COUNT,
            str(message).strip(),
        )


def _load_source_psd_export_api():  # noqa: ANN202
    """Import the time-domain exporter through one narrow integration seam."""
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export import (
        default_project_l2_mne_hauk_source_psd_output_dir,
        write_project_l2_mne_hauk_source_psd_payloads,
    )

    return (
        default_project_l2_mne_hauk_source_psd_output_dir,
        write_project_l2_mne_hauk_source_psd_payloads,
    )


def _load_eloreta_source_psd_export_api():  # noqa: ANN202
    """Import the time-domain eLORETA exporter through one integration seam."""

    from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_hauk_source_psd_export import (
        default_project_eloreta_volume_hauk_source_psd_output_dir,
        write_project_eloreta_volume_hauk_source_psd_payloads,
    )

    return (
        default_project_eloreta_volume_hauk_source_psd_output_dir,
        write_project_eloreta_volume_hauk_source_psd_payloads,
    )


__all__ = [
    "POST_PROCESSING_PHASE_COUNT",
    "PostProcessingPipelineWorker",
    "PostProcessingStepResult",
]
