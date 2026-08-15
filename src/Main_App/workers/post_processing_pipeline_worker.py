"""Post-processing orchestration worker for completed project processing runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import ExitStack, nullcontext
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

    def __init__(
        self,
        project: Any,
        *,
        resume_from_selection: bool = False,
        selection_metadata: Mapping[str, object] | None = None,
        previous_selection_fingerprint: str | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._resume_from_selection = bool(resume_from_selection)
        self._dataset_index: Any | None = None
        self._harmonic_selection_metadata: dict[str, object] | None = (
            dict(selection_metadata)
            if isinstance(selection_metadata, Mapping)
            else None
        )
        self._previous_selection_fingerprint = previous_selection_fingerprint
        self._selection_fingerprint: str | None = None
        self._selection_changed = False
        self._artifact_targets: dict[str, Path] = {}
        self._artifact_archives: dict[str, Path] = {}

    @Slot()
    def run(self) -> None:
        steps: list[PostProcessingStepResult] = []
        cache_stack = ExitStack()
        try:
            from Tools.Stats.io.xlsx_selected_reader import xlsx_read_cache_scope

            cache_stack.enter_context(xlsx_read_cache_scope())
            project_root = Path(self._project.project_root).expanduser().resolve()
            self._capture_previous_selection_fingerprint(project_root)
            if self._resume_from_selection:
                self._run_from_accepted_selection(
                    project_root,
                    steps,
                    cache_stack,
                )
                return
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
            # FullFFT provenance belongs to the accepted frequency-domain
            # sources, not to any downstream harmonic-selection policy. Publish
            # it before selection/Stats so FHC remains usable if those sibling
            # derivatives fail.
            steps.append(self._run_full_fft_provenance(project_root, steps))
            harmonic_message = "FPVS Toolbox is currently identifying significant harmonics."
            self._emit_phase_progress(
                _PHASE_HARMONIC_SELECTION,
                1,
                harmonic_message,
            )
            harmonic_step = self._run_harmonic_selection()
            steps.append(harmonic_step)
            self._emit_phase_progress(
                _PHASE_HARMONIC_SELECTION,
                2,
                harmonic_message,
            )
            if harmonic_step.ok:
                self._activate_artifact_freshness(
                    project_root,
                    selection_summary_path=harmonic_step.path or None,
                )
            stats_message = "FPVS Toolbox is preparing analysis files for downstream tools."
            self._emit_phase_progress(
                _PHASE_STATS_READY_EXPORT,
                2,
                stats_message,
            )
            stats_step = self._record_artifact_freshness(
                self._run_stats_ready_export(project_root)
            )
            steps.append(stats_step)
            steps.append(
                self._record_artifact_freshness(
                    self._run_analysis_ready_export(project_root)
                )
            )
            self._emit_phase_progress(
                _PHASE_STATS_READY_EXPORT,
                3,
                stats_message,
            )
            cache_stack.close()
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
        finally:
            self._dataset_index = None
            self._harmonic_selection_metadata = None
            self._selection_fingerprint = None
            self._artifact_targets.clear()
            self._artifact_archives.clear()
            cache_stack.close()
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

    def _run_from_accepted_selection(
        self,
        project_root: Path,
        steps: list[PostProcessingStepResult],
        cache_stack: ExitStack,
    ) -> None:
        """Rebuild only derivatives of an already accepted harmonic selection."""

        if self._harmonic_selection_metadata is None:
            raise RuntimeError(
                "Post-processing resume requires accepted harmonic-selection metadata."
            )
        from Main_App.projects import load_project_dataset_index

        self._activate_artifact_freshness(
            project_root,
            selection_summary_path=(
                project_root
                / "Quality Check"
                / "Harmonic_Selection_Summary.xlsx"
            ),
        )
        self._dataset_index = load_project_dataset_index(project_root)
        if (
            not self._selection_changed
            and self._selection_fingerprint is not None
            and self._project_manifest_exists(project_root)
        ):
            from Main_App.processing.artifact_freshness import (
                selection_dependent_artifacts_are_current,
            )

            if selection_dependent_artifacts_are_current(
                project_root,
                self._selection_fingerprint,
            ):
                message = (
                    "The harmonic selection is unchanged and every dependent "
                    "post-processing artifact is already current."
                )
                self._emit_progress(message)
                self._emit_phase_progress(
                    _PHASE_COMPLETE,
                    POST_PROCESSING_PHASE_COUNT,
                    message,
                )
                self.finished.emit(
                    {
                        "ok": True,
                        "has_warnings": False,
                        "selection_changed": False,
                        "rebuild_skipped": True,
                        "steps": [],
                    }
                )
                return

        stats_message = (
            "FPVS Toolbox is rebuilding analysis files from the accepted harmonic selection."
        )
        self._emit_phase_progress(
            _PHASE_STATS_READY_EXPORT,
            2,
            stats_message,
        )
        steps.append(
            self._record_artifact_freshness(
                self._run_stats_ready_export(project_root)
            )
        )
        steps.append(
            self._record_artifact_freshness(
                self._run_analysis_ready_export(project_root)
            )
        )
        self._emit_phase_progress(
            _PHASE_STATS_READY_EXPORT,
            3,
            stats_message,
        )
        cache_stack.close()
        # The time-domain source maps use durable source-ready derivatives and
        # the accepted harmonic list. Rebuild them after a selection change
        # without returning to raw EEG preprocessing or participant FFT export.
        steps.extend(self._run_source_maps(project_root))

        ok = all(step.ok for step in steps)
        has_warnings = any(step.warning for step in steps)
        completion_message = (
            "Selection-dependent post-processing is current."
            if ok and not has_warnings
            else "Selection-dependent post-processing finished with failures; old artifacts remain stale."
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
                "selection_changed": self._selection_changed,
                "rebuild_skipped": False,
                "steps": [step.as_dict() for step in steps],
            }
        )

    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self._emit_progress("FPVS Toolbox is reviewing frequency-domain QC before final harmonic selection.")
        from Main_App.projects import load_project_dataset_index
        from Main_App.processing.frequency_domain_qc import run_frequency_domain_qc_review

        project_root = Path(self._project.project_root).expanduser().resolve()
        self._dataset_index = load_project_dataset_index(project_root)
        return run_frequency_domain_qc_review(
            self._project,
            log_func=self._emit_progress,
            dataset_index=self._dataset_index,
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
                dataset_index=self._dataset_index,
            )
            metadata = getattr(report, "selection_metadata", None)
            self._harmonic_selection_metadata = (
                dict(metadata) if isinstance(metadata, dict) else None
            )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_harmonic_selection_failed")
            self._harmonic_selection_metadata = None
            return PostProcessingStepResult("harmonic_selection", False, str(exc))
        return PostProcessingStepResult(
            "harmonic_selection",
            True,
            "Significant harmonic selection was recalculated.",
            str(report.workbook_path),
        )

    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self._emit_progress("FPVS Toolbox is preparing analysis files for downstream tools.")
        artifact_id = "stats_ready_summed_bca"
        from Main_App.processing.artifact_freshness import canonical_artifact_path

        self._artifact_targets[artifact_id] = canonical_artifact_path(
            project_root,
            artifact_id,
        )
        try:
            from Tools.LORETA_Visualizer.stats_ready_workbook import (
                default_loreta_stats_ready_workbook_path,
                write_loreta_stats_ready_workbook,
            )

            target = default_loreta_stats_ready_workbook_path(project_root)
            self._artifact_targets[artifact_id] = target
            with self._artifact_rebuild_context(
                artifact_id,
                target,
                label="Stats-ready Summed BCA workbook",
            ) as archive:
                self._delete_file_if_present(
                    target,
                    project_root=project_root,
                    label="Stats-ready Summed BCA workbook",
                )
                result = write_loreta_stats_ready_workbook(
                    project_root,
                    log_callback=self._emit_progress,
                    dataset_index=self._dataset_index,
                )
            if archive is not None:
                self._artifact_archives[artifact_id] = archive
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_stats_ready_export_failed")
            return PostProcessingStepResult("stats_ready_summed_bca", False, str(exc))
        return PostProcessingStepResult(
            "stats_ready_summed_bca",
            True,
            f"Stats-ready Summed BCA workbook generated with {result.row_count} row(s).",
            str(result.workbook_path),
        )

    def _run_analysis_ready_export(
        self,
        project_root: Path,
    ) -> PostProcessingStepResult:
        self._emit_progress(
            "FPVS Toolbox is preparing the full-audit analysis-ready workbook."
        )
        if self._harmonic_selection_metadata is None:
            return PostProcessingStepResult(
                "analysis_ready_full_audit",
                False,
                (
                    "Full-audit analysis-ready workbook was not generated because "
                    "the current processing-time harmonic selection was unavailable."
                ),
            )
        artifact_id = "analysis_ready_full_audit"
        from Main_App.processing.artifact_freshness import canonical_artifact_path

        self._artifact_targets[artifact_id] = canonical_artifact_path(
            project_root,
            artifact_id,
        )
        try:
            from Main_App.exports import (
                default_analysis_ready_workbook_path,
                write_analysis_ready_workbook,
            )

            target = default_analysis_ready_workbook_path(project_root)
            self._artifact_targets[artifact_id] = target
            with self._artifact_rebuild_context(
                artifact_id,
                target,
                label="full-audit analysis-ready workbook",
            ) as archive:
                result = write_analysis_ready_workbook(
                    project_root,
                    dataset_index=self._dataset_index,
                    selection_metadata=self._harmonic_selection_metadata,
                    log_callback=self._emit_progress,
                )
            if archive is not None:
                self._artifact_archives[artifact_id] = archive
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception("post_processing_analysis_ready_export_failed")
            return PostProcessingStepResult(
                "analysis_ready_full_audit",
                False,
                f"Full-audit analysis-ready workbook failed: {exc}",
            )
        return PostProcessingStepResult(
            "analysis_ready_full_audit",
            True,
            (
                "Full-audit analysis-ready workbook generated with "
                f"{result.roi_row_count} ROI row(s); QC decisions were retained "
                "as flags rather than exclusions."
            ),
            str(result.workbook_path),
        )

    def _run_full_fft_provenance(
        self,
        project_root: Path,
        completed_steps: list[PostProcessingStepResult],
    ) -> PostProcessingStepResult:
        """Publish the selection-independent FullFFT source identity after QC."""

        required = {"frequency_domain_qc"}
        successful = {step.name for step in completed_steps if step.ok}
        if not required.issubset(successful):
            return PostProcessingStepResult(
                "full_fft_provenance",
                False,
                "Neutral FullFFT provenance was not published because "
                "frequency-domain QC did not complete.",
            )
        if not self._project_manifest_exists(project_root):
            return PostProcessingStepResult(
                "full_fft_provenance",
                True,
                "Neutral FullFFT provenance is unavailable for an unmanaged project.",
                warning=True,
            )

        try:
            import config
            from Main_App import SettingsManager
            from Main_App.processing.frequency_domain_qc import (
                mark_frequency_domain_outputs_current,
                mark_frequency_domain_outputs_stale,
            )
            from Main_App.processing.full_fft_provenance import (
                write_project_full_fft_provenance,
            )

            base_frequency_hz = float(
                SettingsManager().get("analysis", "base_freq", "6.0")
            )
            oddball_frequency_hz = float(config.DEFAULT_ODDBALL_FREQ)
            mark_frequency_domain_outputs_current(project_root)
            record = write_project_full_fft_provenance(
                project_root,
                base_frequency_hz=base_frequency_hz,
                oddball_frequency_hz=oddball_frequency_hz,
                dataset_index=self._dataset_index,
            )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            try:
                if self._project_manifest_exists(project_root):
                    mark_frequency_domain_outputs_stale(
                        project_root,
                        reason=f"Neutral FullFFT provenance failed: {exc}",
                    )
            except PIPELINE_STEP_EXCEPTIONS:
                logger.debug(
                    "full_fft_provenance_stale_mark_failed",
                    exc_info=True,
                )
            logger.exception("post_processing_full_fft_provenance_failed")
            return PostProcessingStepResult(
                "full_fft_provenance",
                False,
                f"Neutral FullFFT provenance failed: {exc}",
            )
        return PostProcessingStepResult(
            "full_fft_provenance",
            True,
            (
                "Neutral FullFFT provenance published for "
                f"{record.source_workbook_count} active workbook(s)."
            ),
            str(project_root / "project.json"),
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
            steps.append(
                self._record_artifact_freshness(
                    self._run_source_map_mode(project_root, mode)
                )
            )
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
            artifact_id = mode
            from Main_App.processing.artifact_freshness import canonical_artifact_path

            self._artifact_targets[artifact_id] = canonical_artifact_path(
                project_root,
                artifact_id,
            )
            try:
                default_output_dir, write_payloads = _load_source_psd_export_api()
                target = default_output_dir(project_root)
                self._artifact_targets[artifact_id] = target
                with self._artifact_rebuild_context(
                    artifact_id,
                    target,
                    label=label,
                ) as archive:
                    self._clear_output_dir(
                        target,
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
                if archive is not None:
                    self._artifact_archives[artifact_id] = archive
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
            artifact_id = mode
            from Main_App.processing.artifact_freshness import canonical_artifact_path

            self._artifact_targets[artifact_id] = canonical_artifact_path(
                project_root,
                artifact_id,
            )
            try:
                default_output_dir, write_payloads = _load_eloreta_source_psd_export_api()
                target = default_output_dir(project_root)
                self._artifact_targets[artifact_id] = target
                with self._artifact_rebuild_context(
                    artifact_id,
                    target,
                    label=label,
                ) as archive:
                    self._clear_output_dir(
                        target,
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
                if archive is not None:
                    self._artifact_archives[artifact_id] = archive
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

    def _capture_previous_selection_fingerprint(self, project_root: Path) -> None:
        if self._previous_selection_fingerprint is not None:
            return
        if not self._project_manifest_exists(project_root):
            return
        from Main_App.processing.artifact_freshness import (
            load_active_selection_fingerprint,
        )

        self._previous_selection_fingerprint = load_active_selection_fingerprint(
            project_root
        )

    def _activate_artifact_freshness(
        self,
        project_root: Path,
        *,
        selection_summary_path: str | Path | None,
    ) -> None:
        if not self._project_manifest_exists(project_root):
            return
        if self._harmonic_selection_metadata is None:
            raise RuntimeError(
                "Accepted harmonic-selection metadata is unavailable for post-processing."
            )
        from Main_App.processing.artifact_freshness import (
            activate_selection_freshness,
        )

        transition = activate_selection_freshness(
            project_root,
            self._harmonic_selection_metadata,
            previous_fingerprint=self._previous_selection_fingerprint,
            selection_summary_path=selection_summary_path,
        )
        self._selection_fingerprint = transition.selection_fingerprint
        self._selection_changed = transition.changed
        self._previous_selection_fingerprint = transition.previous_fingerprint
        if transition.changed:
            self._emit_progress(
                "The accepted harmonic selection changed; dependent canonical "
                "outputs were marked stale before rebuilding."
            )

    def _artifact_rebuild_context(
        self,
        artifact_id: str,
        target: Path,
        *,
        label: str,
    ):  # noqa: ANN202
        if (
            self._selection_fingerprint is None
            or not self._project_manifest_exists(
                Path(self._project.project_root).expanduser().resolve()
            )
        ):
            return nullcontext(None)
        from Main_App.processing.artifact_freshness import (
            preserve_artifact_for_rebuild,
        )

        if target.exists():
            self._emit_progress(
                f"Preserving the preceding {label} as a stale historical artifact."
            )
        return preserve_artifact_for_rebuild(
            Path(self._project.project_root).expanduser().resolve(),
            artifact_id,
            target,
            self._previous_selection_fingerprint,
        )

    def _record_artifact_freshness(
        self,
        step: PostProcessingStepResult,
    ) -> PostProcessingStepResult:
        project_root = Path(self._project.project_root).expanduser().resolve()
        target = self._artifact_targets.get(step.name)
        if (
            target is None
            or self._selection_fingerprint is None
            or not self._project_manifest_exists(project_root)
        ):
            return step
        try:
            from Main_App.processing.artifact_freshness import (
                mark_artifact_current,
                mark_artifact_failed,
            )

            if step.ok:
                mark_artifact_current(
                    project_root,
                    step.name,
                    target,
                    self._selection_fingerprint,
                    archived_path=self._artifact_archives.get(step.name),
                )
            else:
                mark_artifact_failed(
                    project_root,
                    step.name,
                    target,
                    self._selection_fingerprint,
                    step.message,
                )
        except PIPELINE_STEP_EXCEPTIONS as exc:
            logger.exception(
                "post_processing_artifact_freshness_update_failed artifact_id=%s",
                step.name,
            )
            archived = self._artifact_archives.get(step.name)
            if step.ok and archived is not None:
                try:
                    from Main_App.processing.artifact_freshness import (
                        restore_preserved_artifact,
                    )

                    restore_preserved_artifact(
                        project_root,
                        target,
                        archived,
                    )
                except PIPELINE_STEP_EXCEPTIONS:
                    logger.exception(
                        "post_processing_artifact_restore_failed artifact_id=%s",
                        step.name,
                    )
            return PostProcessingStepResult(
                step.name,
                False,
                f"{step.message} Artifact freshness could not be saved: {exc}",
                step.path,
                warning=step.warning,
            )
        return step

    @staticmethod
    def _project_manifest_exists(project_root: Path) -> bool:
        return (project_root / "project.json").is_file()

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


def run_postprocessing_from_selection(
    project: Any,
    selection_metadata: Mapping[str, object],
    *,
    previous_selection_fingerprint: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
    phase_progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, object]:
    """Synchronously rebuild selection derivatives in the caller's worker thread.

    This entry point intentionally starts after harmonic selection.  It never
    loads raw EEG, preprocesses data, or regenerates participant FullFFT
    workbooks.  GUI callers must invoke it from an existing background worker.
    """

    worker = PostProcessingPipelineWorker(
        project,
        resume_from_selection=True,
        selection_metadata=selection_metadata,
        previous_selection_fingerprint=previous_selection_fingerprint,
    )
    results: list[dict[str, object]] = []
    worker.finished.connect(results.append)
    if progress_callback is not None:
        worker.progress.connect(progress_callback)
    if phase_progress_callback is not None:
        worker.phase_progress.connect(phase_progress_callback)
    worker.run()
    if not results:
        raise RuntimeError(
            "Selection-dependent post-processing finished without a result."
        )
    return dict(results[-1])


__all__ = [
    "POST_PROCESSING_PHASE_COUNT",
    "PostProcessingPipelineWorker",
    "PostProcessingStepResult",
    "run_postprocessing_from_selection",
]
