"""Controller layer for coordinating Stats pipelines.

StatsController orchestrates the Single and Between pipelines, owns run state,
schedules workers, and routes progress back to the view (StatsWindow). The
controller contains orchestration only; computational work lives in
stats_workers and legacy analysis modules.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

import pandas as pd
import sys
from PySide6.QtCore import QThreadPool

from . import stats_workers
from .stats_core import PipelineId, PipelineStep, StepId
from .stats_logging import format_step_event
from .stats_data_loader import load_manifest_data, load_project_scan, resolve_project_subfolder
from Main_App.PySide6_App.Backend.project import STATS_SUBFOLDER_NAME

logger = logging.getLogger(__name__)


class StatsViewProtocol:
    """Minimal interface the controller expects from the view (StatsWindow)."""

    def append_log(self, section: str, message: str, level: str = "info") -> None: ...

    def set_busy(self, is_busy: bool) -> None: ...

    def start_step_worker(
        self,
        pipeline_id: PipelineId,
        step: PipelineStep,
        *,
        finished_cb: Callable[[PipelineId, StepId, object], None],
        error_cb: Callable[[PipelineId, StepId, str], None],
        message_cb: Optional[Callable[[str], None]] = None,
    ) -> None: ...

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None: ...

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None: ...

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool: ...

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool: ...

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None: ...

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]: ...

    def ensure_results_dir(self) -> str: ...

    def prompt_phase_folder(self, title: str, start_dir: str | None = None) -> Optional[str]: ...

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict]: ...


@dataclass
class SectionRunState:
    pipeline_id: PipelineId
    current_step_index: int = 0
    steps: Sequence[PipelineStep] = field(default_factory=tuple)
    running: bool = False
    failed: bool = False
    start_ts: float = 0.0
    results: Dict[StepId, dict] = field(default_factory=dict)
    run_exports: bool = True
    run_summary: bool = True
    process_mode: bool = False
    process_job_path: Optional[Path] = None
    process_summary_path: Optional[Path] = None


SINGLE_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.RM_ANOVA,
    StepId.MIXED_MODEL,
    StepId.INTERACTION_POSTHOCS,
    StepId.HARMONIC_CHECK,
)
"""Default ordered steps for the Single pipeline."""

BETWEEN_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.BETWEEN_GROUP_ANOVA,
    StepId.BETWEEN_GROUP_MIXED_MODEL,
    StepId.GROUP_CONTRASTS,
    StepId.HARMONIC_CHECK,
)
"""Default ordered steps for the Between pipeline."""

STEP_LABELS: Dict[StepId, str] = {
    StepId.RM_ANOVA: "RM-ANOVA",
    StepId.MIXED_MODEL: "Mixed Model",
    StepId.INTERACTION_POSTHOCS: "Interaction Post-hocs",
    StepId.BETWEEN_GROUP_ANOVA: "Between-Group ANOVA",
    StepId.BETWEEN_GROUP_MIXED_MODEL: "Between-Group Mixed Model",
    StepId.GROUP_CONTRASTS: "Group Contrasts",
    StepId.HARMONIC_CHECK: "Harmonic Check",
}

WORKER_FN_BY_STEP: Dict[StepId, Callable[..., Any]] = {
    StepId.RM_ANOVA: stats_workers.run_rm_anova,
    StepId.MIXED_MODEL: stats_workers.run_lmm,
    StepId.INTERACTION_POSTHOCS: stats_workers.run_posthoc,
    StepId.BETWEEN_GROUP_ANOVA: stats_workers.run_between_group_anova,
    StepId.BETWEEN_GROUP_MIXED_MODEL: stats_workers.run_lmm,
    StepId.GROUP_CONTRASTS: stats_workers.run_group_contrasts,
    StepId.HARMONIC_CHECK: stats_workers.run_harmonic_check,
}


class StatsController:
    def __init__(self, view: StatsViewProtocol) -> None:
        self._view = view
        self._states: Dict[PipelineId, SectionRunState] = {
            PipelineId.SINGLE: SectionRunState(pipeline_id=PipelineId.SINGLE),
            PipelineId.BETWEEN: SectionRunState(pipeline_id=PipelineId.BETWEEN),
        }
        self._lela_running = False

    def run_single_group_analysis(
        self,
        *,
        step_ids: Optional[Sequence[StepId]] = None,
        run_exports: bool = True,
        run_summary: bool = True,
        require_anova: bool = False,
    ) -> None:
        self._start_pipeline(
            PipelineId.SINGLE,
            step_ids or SINGLE_PIPELINE_STEPS,
            run_exports=run_exports,
            run_summary=run_summary,
            require_anova=require_anova,
        )

    def run_single_group_rm_anova_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.RM_ANOVA,), run_exports=False, run_summary=False
        )

    def run_single_group_mixed_model_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.MIXED_MODEL,), run_exports=False, run_summary=False
        )

    def run_single_group_posthoc_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.INTERACTION_POSTHOCS,),
            run_exports=False,
            run_summary=False,
            require_anova=True,
        )

    def run_harmonic_check_only(self) -> None:
        self._start_pipeline(
            PipelineId.SINGLE,
            (StepId.HARMONIC_CHECK,),
            run_exports=False,
            run_summary=False,
        )

    def run_between_group_analysis(
        self,
        *,
        step_ids: Optional[Sequence[StepId]] = None,
        run_exports: bool = True,
        run_summary: bool = True,
    ) -> None:
        self._start_pipeline(
            PipelineId.BETWEEN,
            step_ids or BETWEEN_PIPELINE_STEPS,
            run_exports=run_exports,
            run_summary=run_summary,
        )

    def run_between_group_anova_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.BETWEEN_GROUP_ANOVA,),
            run_exports=False,
            run_summary=False,
        )

    def run_between_group_mixed_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.BETWEEN_GROUP_MIXED_MODEL,),
            run_exports=False,
            run_summary=False,
        )

    def run_between_group_contrasts_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.GROUP_CONTRASTS,),
            run_exports=False,
            run_summary=False,
        )

    def run_lela_mode_analysis(self) -> None:
        """
        Build and launch a generic cross-phase LMM job ("Lela Mode") in the
        legacy subprocess.
        """

        section = self._section_label(PipelineId.BETWEEN)
        if self._states[PipelineId.BETWEEN].running or self._lela_running:
            self._view.append_log(
                section,
                "[Between] Another analysis is already running; Lela Mode request ignored.",
                level="warning",
            )
            return

        try:
            base_freq, _alpha, roi_map = self._view.get_analysis_settings_snapshot()
        except Exception as exc:  # noqa: BLE001
            self._view.append_log(section, f"[Between] Unable to load analysis settings: {exc}", level="error")
            return

        phase_specs: dict[str, dict] = {}
        phase_roots: list[tuple[Path, dict | None]] = []
        phase_subject_counts: list[tuple[str, int]] = []
        for idx in range(2):
            title = f"Select Phase {idx + 1} project folder"
            folder = self._view.prompt_phase_folder(title)
            if not folder:
                self._view.append_log(section, "[Between] Lela Mode cancelled (no folder selected).")
                return
            try:
                scan = load_project_scan(folder)
            except Exception as exc:  # noqa: BLE001
                self._view.append_log(
                    section,
                    f"[Between] Failed to read phase project at {folder}: {exc}",
                    level="error",
                )
                return
            phase_label = Path(folder).name or f"Phase {idx + 1}"
            phase_specs[phase_label] = {
                "subjects": scan.subjects,
                "conditions": scan.conditions,
                "subject_data": scan.subject_data,
                "group_map": scan.subject_groups,
            }
            phase_subject_counts.append((phase_label, len(scan.subjects)))
            phase_roots.append((Path(folder), scan.manifest))

        missing_data_phase = next(
            (
                label
                for label, spec in phase_specs.items()
                if not spec.get("subjects") or not spec.get("subject_data")
            ),
            None,
        )
        if missing_data_phase:
            self._view.append_log(
                section,
                "[Between] Lela Mode requires both phase projects to have scanned subject data. "
                "Please run a standard Stats scan for each project first and save the project.",
                level="error",
            )
            return

        output_dir = self._resolve_stats_output_dir(*phase_roots[0]) if phase_roots else Path.cwd()
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        job_spec_path = output_dir / f"cross_phase_job_{ts}.json"
        summary_path = output_dir / "CrossPhase_LMM_Summary.json"
        excel_path = output_dir / "Cross-Phase LMM Analysis.xlsx"

        job_spec = {
            "mode": "cross_phase_lmm",
            "phase_projects": phase_specs,
            "roi_map": roi_map,
            "base_freq": base_freq,
            "output": {
                "summary_json": str(summary_path),
                "excel_report": str(excel_path),
            },
        }

        phase_log = ", ".join(
            f"{label}: {count} subjects" for label, count in phase_subject_counts
        )
        self._view.append_log(
            section,
            f"[Between] Lela Mode spec ready for phases: {', '.join(phase_specs.keys())}. "
            f"Subjects per phase: {phase_log}",
        )

        job_spec_path.write_text(json.dumps(job_spec, indent=2))

        self._lela_running = True
        self._view.set_busy(True)
        self._view.append_log(section, "[Between] Launching Lela Mode (cross-phase LMM)…")
        self._view.append_log(section, "[Between] Lela Mode: running cross-phase LMM…")

        worker = stats_workers.StatsWorker(
            stats_workers.run_between_group_process_task,
            job_spec_path=str(job_spec_path),
            _op="cross_phase_lmm",
        )
        worker.signals.message.connect(
            lambda msg, pid=PipelineId.BETWEEN: self._on_between_process_message(pid, msg)
        )
        worker.signals.finished.connect(
            lambda payload, excel=excel_path: self._on_lela_mode_finished(payload, excel)
        )
        worker.signals.error.connect(self._on_lela_mode_error)
        QThreadPool.globalInstance().start(worker)

    def is_running(self, pipeline_id: PipelineId) -> bool:
        return self._states[pipeline_id].running

    def _start_pipeline(
        self,
        pipeline_id: PipelineId,
        step_ids: Sequence[StepId],
        *,
        run_exports: bool = True,
        run_summary: bool = True,
        require_anova: bool = False,
    ) -> None:
        state = self._states[pipeline_id]
        state.process_mode = False
        state.process_job_path = None
        state.process_summary_path = None

        if state.running:
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} already running; new request ignored.",
                level="warning",
            )
            return

        if not step_ids:
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} requested with no steps; aborting.",
                level="error",
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message="No steps to run",
                exports_ran=False,
            )
            return

        if not self._view.ensure_pipeline_ready(
            pipeline_id, require_anova=require_anova
        ):
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} prerequisites not met; aborting.",
                level="error",
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message="Precheck failed",
                exports_ran=False,
            )
            return

        try:
            state.steps = self._build_steps(pipeline_id, step_ids)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_build_steps_failed", exc_info=True)
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=f"Failed to prepare steps: {exc}",
                exports_ran=False,
            )
            return
        state.running = True
        state.failed = False
        state.current_step_index = 0
        state.results.clear()
        state.start_ts = time.perf_counter()
        state.run_exports = run_exports
        state.run_summary = run_summary

        self._view.set_busy(True)
        self._view.on_pipeline_started(pipeline_id)
        summary = f"{self._section_name(pipeline_id)} started with {len(state.steps)} steps"
        logger.info(
            "stats_pipeline_start",
            extra={
                "pipeline": pipeline_id.name,
                "step_count": len(state.steps),
                "steps": [s.id.name for s in state.steps],
            },
        )
        self._view.append_log(self._section_label(pipeline_id), summary)

        if (
            pipeline_id is PipelineId.BETWEEN
            and tuple(step_ids) == tuple(BETWEEN_PIPELINE_STEPS)
        ):
            try:
                self._start_between_process_pipeline()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_between_process_start_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name},
                )
                self._finalize_pipeline(
                    pipeline_id,
                    success=False,
                    error_message=str(exc),
                    exports_ran=False,
                )
            return

        try:
            self._run_next_step(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_pipeline_start_failed",
                exc_info=True,
                extra={"pipeline": pipeline_id.name},
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=str(exc),
                exports_ran=False,
            )

    def _build_steps(
        self, pipeline_id: PipelineId, step_ids: Sequence[StepId]
    ) -> Sequence[PipelineStep]:
        steps: list[PipelineStep] = []
        for step_id in step_ids:
            worker_fn = WORKER_FN_BY_STEP[step_id]
            kwargs, handler = self._view.get_step_config(pipeline_id, step_id)
            steps.append(
                PipelineStep(
                    step_id,
                    STEP_LABELS.get(step_id, step_id.name),
                    worker_fn,
                    kwargs,
                    handler,
                )
            )
        return tuple(steps)

    def _start_between_process_pipeline(self) -> None:
        pipeline_id = PipelineId.BETWEEN
        state = self._states[pipeline_id]
        state.process_mode = True

        job_spec_path, summary_path = self._build_between_job_spec(state)
        state.process_job_path = job_spec_path
        state.process_summary_path = summary_path

        self._view.append_log(
            self._section_label(pipeline_id),
            "Launching between-group pipeline in isolated process…",
        )

        process_step = PipelineStep(
            StepId.BETWEEN_GROUP_ANOVA,
            "Between-Group Pipeline",
            stats_workers.run_between_group_process_task,
            {"job_spec_path": str(job_spec_path), "python_executable": sys.executable},
            handler=lambda payload: None,
        )

        self._view.start_step_worker(
            pipeline_id,
            process_step,
            finished_cb=self._on_between_process_finished,
            error_cb=self._on_between_process_error,
            message_cb=lambda msg, pid=pipeline_id: self._on_between_process_message(
                pid, msg
            ),
        )

    def _build_between_job_spec(self, state: SectionRunState) -> tuple[Path, Path]:
        def _find_kwargs(step_id: StepId) -> dict:
            for step in state.steps:
                if step.id is step_id:
                    return step.kwargs
            return {}

        anova_kwargs = _find_kwargs(StepId.BETWEEN_GROUP_ANOVA)
        mixed_kwargs = _find_kwargs(StepId.BETWEEN_GROUP_MIXED_MODEL)
        harmonic_kwargs = _find_kwargs(StepId.HARMONIC_CHECK)

        results_dir = Path(self._view.ensure_results_dir())
        results_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        job_spec_path = results_dir / f"between_group_job_{ts}.json"
        summary_path = results_dir / "between_group_summary.json"

        tail = (
            "greater"
            if harmonic_kwargs.get("selected_metric") in ("Z Score", "SNR")
            else "two-sided"
        )

        spec = {
            "subjects": anova_kwargs.get("subjects", []),
            "conditions": anova_kwargs.get("conditions", []),
            "subject_data": anova_kwargs.get("subject_data", {}),
            "subject_groups": anova_kwargs.get("subject_groups", {}),
            "roi_map": anova_kwargs.get("rois", {}),
            "base_freq": anova_kwargs.get("base_freq", 6.0),
            "alpha": mixed_kwargs.get("alpha", 0.05),
            "harmonic_options": {
                "metric": harmonic_kwargs.get("selected_metric", "Z Score"),
                "mean_value_threshold": harmonic_kwargs.get("mean_value_threshold", 0.0),
                "base_freq": harmonic_kwargs.get("base_freq", anova_kwargs.get("base_freq", 6.0)),
                "correction_method": harmonic_kwargs.get("correction_method", "holm"),
                "tail": tail,
                "max_freq": harmonic_kwargs.get("max_freq"),
                "min_subjects": harmonic_kwargs.get("min_subjects", 3),
                "oddball_every_n": harmonic_kwargs.get("oddball_every_n", 5),
                "limit_n_harmonics": harmonic_kwargs.get("limit_n_harmonics"),
                "do_wilcoxon_sensitivity": harmonic_kwargs.get(
                    "do_wilcoxon_sensitivity", True
                ),
            },
            "output": {
                "summary_json": str(summary_path),
            },
        }

        job_spec_path.write_text(json.dumps(spec, indent=2))
        return job_spec_path, summary_path

    def _resolve_stats_output_dir(self, excel_root: Path, manifest: dict | None) -> Path:
        project_root = self._find_project_root(excel_root)
        results_folder, subfolders = load_manifest_data(project_root, manifest)
        return resolve_project_subfolder(
            project_root,
            results_folder,
            subfolders,
            "stats",
            STATS_SUBFOLDER_NAME,
        )

    @staticmethod
    def _find_project_root(path: Path) -> Path:
        for candidate in (path, *path.parents):
            if (candidate / "project.json").is_file():
                return candidate
        return path

    def _run_next_step(self, pipeline_id: PipelineId) -> None:
        try:
            state = self._states[pipeline_id]
            if not state.running:
                logger.info(
                    "stats_step_skip_inactive",
                    extra={"pipeline": pipeline_id.name},
                )
                return
            if not state.steps or state.current_step_index >= len(state.steps):
                self._complete_pipeline(pipeline_id)
                return

            step = state.steps[state.current_step_index]
            section = self._section_label(pipeline_id)
            logger.info(
                "stats_step_start",
                extra={"pipeline": pipeline_id.name, "step": step.id.name},
            )
            self._view.append_log(
                section,
                format_step_event(
                    pipeline_id,
                    step.id,
                    event="start",
                    message=f"Starting {step.name}",
                ),
            )
            self._view.start_step_worker(
                pipeline_id,
                step,
                finished_cb=self._on_step_finished,
                error_cb=self._on_step_error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_run_next_step_failed",
                exc_info=True,
                extra={"pipeline": pipeline_id.name},
            )
            section = self._section_label(pipeline_id)
            if "step" in locals():
                self._view.append_log(
                    section,
                    format_step_event(
                        pipeline_id,
                        step.id,
                        event="error",
                        message=f"ERROR: {exc}",
                    ),
                    level="error",
                )
            else:
                self._view.append_log(
                    section,
                    f"[{pipeline_id.name}] ERROR: {exc}",
                    level="error",
                )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=str(exc),
                exports_ran=False,
            )

    def _on_between_process_message(self, pipeline_id: PipelineId, message: str) -> None:
        state = self._states[pipeline_id]
        section = self._section_label(pipeline_id)
        text = (message or "").strip()
        if not text:
            return

        if text.startswith("STAGE_START:") or text.startswith("STAGE_DONE:"):
            step_name = text.split(":", 1)[1]
            try:
                step_id = StepId[step_name]
            except KeyError:
                self._view.append_log(section, text)
                return
            event = "start" if text.startswith("STAGE_START:") else "complete"
            self._view.append_log(
                section,
                format_step_event(
                    pipeline_id, step_id, event=event, message=f"{event.title()}"
                ),
            )
            idx = next((i for i, s in enumerate(state.steps) if s.id is step_id), None)
            if idx is not None:
                state.current_step_index = max(state.current_step_index, idx + (1 if event == "complete" else 0))
            return

        self._view.append_log(section, text)

    def _on_lela_mode_finished(self, payload: object, excel_path: Path) -> None:
        section = self._section_label(PipelineId.BETWEEN)
        self._lela_running = False
        self._view.set_busy(False)
        self._view.append_log(section, "[Between] Lela Mode: complete — see Cross-Phase LMM Analysis.xlsx")
        self._view.append_log(section, f"  • Excel: {excel_path}")

    def _on_lela_mode_error(self, error_message: str) -> None:
        section = self._section_label(PipelineId.BETWEEN)
        self._lela_running = False
        self._view.set_busy(False)
        self._view.append_log(section, f"[Between] Lela Mode error: {error_message}", level="error")

    def _deserialize_between_payload(self, step_id: StepId, raw: dict) -> dict:
        def _df(payload: Optional[dict]) -> Optional[pd.DataFrame]:
            if not payload:
                return None
            cols = payload.get("columns")
            data = payload.get("data", [])
            return pd.DataFrame(data, columns=cols) if cols is not None else pd.DataFrame(data)

        if step_id is StepId.BETWEEN_GROUP_ANOVA:
            return {"anova_df_results": _df(raw.get("anova_df_results"))}
        if step_id is StepId.BETWEEN_GROUP_MIXED_MODEL:
            return {
                "mixed_results_df": _df(raw.get("mixed_results_df")),
                "output_text": raw.get("output_text", ""),
            }
        if step_id is StepId.GROUP_CONTRASTS:
            return {
                "results_df": _df(raw.get("results_df")),
                "output_text": raw.get("output_text", ""),
            }
        if step_id is StepId.HARMONIC_CHECK:
            return {
                "output_text": raw.get("output_text", ""),
                "findings": raw.get("findings", []),
            }
        return raw

    def _on_between_process_finished(
        self, pipeline_id: PipelineId, step_id: StepId, payload: object
    ) -> None:
        try:
            state = self._states[pipeline_id]
            summary = payload.get("summary") if isinstance(payload, dict) else None
            steps_data = summary.get("steps", {}) if isinstance(summary, dict) else {}

            if not steps_data:
                raise RuntimeError("Between-group process returned no results.")

            for step in state.steps:
                raw_payload = steps_data.get(step.id.name, {})
                deserialized = self._deserialize_between_payload(step.id, raw_payload)
                handler = getattr(step, "handler", None)
                if handler:
                    handler(deserialized)
                state.results[step.id] = deserialized
                self._view.append_log(
                    self._section_label(pipeline_id),
                    format_step_event(
                        pipeline_id,
                        step.id,
                        event="complete",
                        message=f"{step.name} completed",
                    ),
                )

            state.current_step_index = len(state.steps)
            self._complete_pipeline(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_between_process_finish_error",
                exc_info=True,
                extra={"pipeline": pipeline_id.name, "error": str(exc)},
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=str(exc),
                exports_ran=False,
            )

    def _on_between_process_error(self, pipeline_id: PipelineId, step_id: StepId, error_message: str) -> None:
        state = self._states[pipeline_id]
        state.failed = True
        section = self._section_label(pipeline_id)
        self._view.append_log(
            section,
            format_step_event(
                pipeline_id,
                step_id,
                event="error",
                message=f"ERROR: {error_message}",
            ),
            level="error",
        )
        self._finalize_pipeline(
            pipeline_id,
            success=False,
            error_message=error_message,
            exports_ran=False,
        )

    def _on_step_finished(self, pipeline_id: PipelineId, step_id: StepId, payload: object) -> None:
        try:
            state = self._states[pipeline_id]
            if not state.running:
                return
            if state.current_step_index >= len(state.steps):
                raise RuntimeError("Received step finished signal with no pending step")
            step = state.steps[state.current_step_index]
            step_name = getattr(step, "name", step_id.name)

            logger.info(
                "stats_step_finished_signal",
                extra={
                    "pipeline": pipeline_id.name,
                    "step": step_id.name,
                    "expected_step": step.id.name,
                },
            )

            if step_id is StepId.HARMONIC_CHECK:
                logger.info(
                    "stats_harmonic_check_signal",
                    extra={"pipeline": pipeline_id.name, "step_name": step_name},
                )

            handler = getattr(step, "handler", None)
            if handler is None:
                logger.error(
                    "stats_step_handler_missing",
                    extra={"pipeline": pipeline_id.name, "step": step_id.name},
                )
                self._on_step_error(pipeline_id, step_id, "No handler registered for step.")
                return

            try:
                handler(payload)
                state.results[step_id] = payload if isinstance(payload, dict) else {"result": payload}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "stats_step_handler_error",
                    extra={
                        "pipeline": pipeline_id.name,
                        "step": step_id.name,
                        "error": str(exc),
                    },
                )
                self._on_step_error(pipeline_id, step_id, f"Step handler failed: {exc}")
                return

            logger.info(
                "stats_step_complete",
                extra={"pipeline": pipeline_id.name, "step": step_id.name},
            )
            self._view.append_log(
                self._section_label(pipeline_id),
                format_step_event(
                    pipeline_id,
                    step_id,
                    event="complete",
                    message=f"{step.name} completed",
                ),
            )
            state.current_step_index += 1
            self._run_next_step(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_step_finished_handler_error",
                exc_info=True,
                extra={"pipeline": pipeline_id.name, "step": step_id.name},
            )
            try:
                self._view.append_log(
                    self._section_label(pipeline_id),
                    format_step_event(
                        pipeline_id,
                        step_id,
                        event="error",
                        message=f"ERROR: {exc}",
                    ),
                    level="error",
                )
            except Exception:
                logger.exception(
                    "stats_step_finished_view_log_error",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "step": step_id.name},
                )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=str(exc),
                exports_ran=False,
            )

    def _on_step_error(self, pipeline_id: PipelineId, step_id: StepId, error_message: str) -> None:
        try:
            state = self._states[pipeline_id]
            section = self._section_label(pipeline_id)
            state.failed = True
            logger.error(
                "stats_step_error",
                extra={
                    "pipeline": pipeline_id.name,
                    "step": step_id.name,
                    "error": error_message,
                },
            )
            self._view.append_log(
                section,
                format_step_event(
                    pipeline_id,
                    step_id,
                    event="error",
                    message=f"ERROR: {error_message}",
                ),
                level="error",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_step_error_handler_failed",
                exc_info=True,
                extra={"pipeline": pipeline_id.name, "step": step_id.name},
            )
            error_message = f"{error_message} (and handler failed: {exc})"
        finally:
            self._finalize_pipeline(
                pipeline_id, success=False, error_message=error_message, exports_ran=False
            )

    def _complete_pipeline(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        section = self._section_label(pipeline_id)
        elapsed = time.perf_counter() - state.start_ts if state.start_ts else 0.0
        exports_ran = False
        success = True
        error_message: Optional[str] = None

        try:
            if state.run_exports:
                exported = self._view.export_pipeline_results(pipeline_id)
                exports_ran = bool(exported)
                if not exported:
                    self._view.append_log(
                        section,
                        "  • Export failed; see log for details",
                        level="error",
                    )
                    success = False
                    error_message = "Export failed"

            if success and state.run_summary:
                self._view.build_and_render_summary(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "stats_pipeline_complete_error",
                exc_info=True,
                extra={"pipeline": pipeline_id.name, "exc": str(exc)},
            )
            self._view.append_log(
                section,
                f"  • Error during finalization for {pipeline_id.name}: {exc}",
                level="error",
            )
            success = False
            error_message = error_message or f"Error during finalization for {pipeline_id.name}: {exc}"
        finally:
            try:
                if success:
                    self._view.append_log(
                        section,
                        f"{self._section_name(pipeline_id)} finished in {elapsed:.1f} s",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_pipeline_finalize_log_error",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )
                success = False
                error_message = error_message or f"Error finalizing pipeline log: {exc}"

            finalize_exports_ran = exports_ran if success else False
            try:
                self._finalize_pipeline(
                    pipeline_id,
                    success=success,
                    error_message=error_message,
                    exports_ran=finalize_exports_ran,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_pipeline_finalize_error",
                    exc_info=True,
                    extra={
                        "pipeline": pipeline_id.name,
                        "success": success,
                        "error": str(exc),
                    },
                )

        logger.info(
            "stats_pipeline_complete",
            extra={
                "pipeline": pipeline_id.name,
                "elapsed_s": elapsed,
                "exports_ran": exports_ran,
                "success": success,
            },
        )

    def _finalize_pipeline(
        self,
        pipeline_id: PipelineId,
        *,
        success: bool,
        error_message: Optional[str],
        exports_ran: bool = False,
    ) -> None:
        state = self._states[pipeline_id]
        state.running = False
        state.failed = not success
        state.steps = ()
        state.run_exports = True
        state.run_summary = True
        state.start_ts = 0.0

        logger.info(
            "stats_finalize_start",
            extra={
                "pipeline": pipeline_id.name,
                "success": success,
                "error_message": error_message,
                "exports_ran": exports_ran,
            },
        )

        try:
            self._view.set_busy(False)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_finalize_view_error",
                exc_info=True,
                extra={
                    "pipeline": pipeline_id.name,
                    "view_method": "set_busy",
                    "error": str(exc),
                },
            )

        try:
            self._view.on_analysis_finished(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran if success else False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_finalize_view_error",
                exc_info=True,
                extra={
                    "pipeline": pipeline_id.name,
                    "view_method": "on_analysis_finished",
                    "error": str(exc),
                },
            )

        logger.info(
            "stats_finalize_end",
            extra={
                "pipeline": pipeline_id.name,
                "success": success,
                "error_message": error_message,
                "exports_ran": exports_ran,
            },
        )

    def _section_label(self, pipeline_id: PipelineId) -> str:
        return "Single" if pipeline_id is PipelineId.SINGLE else "Between"

    def _section_name(self, pipeline_id: PipelineId) -> str:
        return "Single-Group Analysis" if pipeline_id is PipelineId.SINGLE else "Between-Group Analysis"


__all__ = ["StatsController", "SectionRunState", "StatsViewProtocol"]
