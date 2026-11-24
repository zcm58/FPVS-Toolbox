from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import Main_App.workers.post_processing_pipeline_worker as worker_module
from Main_App.processing.artifact_freshness import (
    ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
    ARTIFACT_STATUS_CURRENT,
    ARTIFACT_STATUS_STALE,
    ELORETA_VOLUME_SOURCE_PSD_ARTIFACT,
    L2_MNE_SOURCE_PSD_ARTIFACT,
    SELECTION_DEPENDENT_ARTIFACTS,
    STATS_READY_SUMMED_BCA_ARTIFACT,
    activate_selection_freshness,
    canonical_artifact_path,
    load_artifact_freshness_registry,
    mark_artifact_current,
)
from Main_App.workers.post_processing_pipeline_worker import (
    PostProcessingPipelineWorker,
    PostProcessingStepResult,
)


@dataclass
class _Project:
    project_root: Path


def _repeated_project(project_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        project_root=project_root,
        groups={},
        participants={},
        sessions={
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        recording_sources={},
        recordings={},
    )


class _RecordingWorker(PostProcessingPipelineWorker):
    def __init__(self, project: _Project) -> None:
        super().__init__(project)
        self.calls: list[str] = []

    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self.calls.append("qc")
        self._emit_progress("qc done")
        self._recording_condition_outcomes = SimpleNamespace(
            fingerprint="current-outcome-ledger",
            cells=(),
        )
        self._pre_review_roi_coverage = SimpleNamespace(
            fingerprint="current-pre-review-coverage"
        )
        return {"review_required": False, "review_reused": False}

    def _sync_frequency_domain_qc_automatic_state(
        self,
        project_root: Path,
        qc_report: dict[str, object],
    ) -> None:
        assert qc_report["review_required"] is False
        self.calls.append(f"sync:{project_root.name}")

    def _finalize_frequency_qc_release(self, project_root: Path) -> None:
        assert project_root == Path(self._project.project_root).resolve()
        assert self._recording_condition_outcomes is not None
        assert self._pre_review_roi_coverage is not None

    def _run_harmonic_selection(self) -> PostProcessingStepResult:
        self.calls.append("harmonics")
        self._emit_progress("harmonics done")
        return PostProcessingStepResult("harmonic_selection", True, "harmonics ok", "harmonics.xlsx")

    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        self._emit_progress("stats ready done")
        return PostProcessingStepResult("stats_ready_summed_bca", True, "stats ok", "stats.xlsx")

    def _run_analysis_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"audit:{project_root.name}")
        self._emit_progress("full audit ready done")
        return PostProcessingStepResult(
            "analysis_ready_full_audit",
            True,
            "full audit ok",
            "analysis_ready.xlsx",
        )

    def _run_full_fft_provenance(
        self,
        project_root: Path,
        completed_steps: list[PostProcessingStepResult],
    ) -> PostProcessingStepResult:
        self.calls.append(f"full_fft:{project_root.name}")
        successful = {step.name for step in completed_steps if step.ok}
        ok = "frequency_domain_qc" in successful
        return PostProcessingStepResult(
            "full_fft_provenance",
            ok,
            "FullFFT provenance ok" if ok else "FullFFT provenance blocked",
        )


class _StatsFailureWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingStepResult("stats_ready_summed_bca", False, "stats failed")


class _AuditFailureWorker(_RecordingWorker):
    def _run_analysis_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"audit:{project_root.name}")
        return PostProcessingStepResult(
            "analysis_ready_full_audit",
            False,
            "full audit failed",
        )


class _ReviewRequiredWorker(_RecordingWorker):
    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self.calls.append("qc")
        return {"review_required": True, "review_reused": False}


def test_condition_repair_restarts_qc_instead_of_reusing_accepted_selection(tmp_path, monkeypatch):
    from Main_App.processing import condition_interpolation_executor

    monkeypatch.setattr(
        condition_interpolation_executor, "execute_pending_condition_interpolations",
        lambda *_args, **_kwargs: True,
    )
    worker = _ReviewRequiredWorker(_Project(tmp_path))
    worker._resume_from_selection = True
    worker._harmonic_selection_metadata = {"selection_fingerprint": "before-repair"}
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert worker.calls == ["qc"]
    assert worker._resume_from_selection is False
    assert worker._harmonic_selection_metadata is None
    assert results[-1]["requires_frequency_domain_qc_review"] is True


class _RepeatedSessionRecordingWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingPipelineWorker._run_stats_ready_export(
            self,
            project_root,
        )


def test_repeated_session_pipeline_releases_recording_aware_workbook(
    tmp_path: Path,
) -> None:
    worker = _RepeatedSessionRecordingWorker(_repeated_project(tmp_path))
    progress: list[str] = []
    phase_progress: list[tuple[str, int, int, str]] = []
    finished: list[dict] = []
    worker.progress.connect(progress.append)
    worker.phase_progress.connect(
        lambda phase_id, completed, total, message: phase_progress.append(
            (phase_id, completed, total, message)
        )
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert finished[0]["ok"] is True
    assert finished[0]["has_warnings"] is False
    assert worker.calls == [
        "qc",
        f"sync:{tmp_path.name}",
        f"full_fft:{tmp_path.name}",
        "harmonics",
        f"stats:{tmp_path.name}",
        f"audit:{tmp_path.name}",
    ]
    steps = {step["name"]: step for step in finished[0]["steps"]}
    assert steps["stats_ready_summed_bca"]["ok"] is True
    assert "Skipped the legacy LORETA Stats-ready workbook" in steps[
        "stats_ready_summed_bca"
    ]["message"]
    assert set(steps) == {
        "frequency_domain_qc", "full_fft_provenance", "harmonic_selection",
        "stats_ready_summed_bca", "analysis_ready_full_audit",
    }
    assert any("legacy LORETA Stats-ready workbook" in message for message in progress)
    assert phase_progress[-1][:3] == ("post_processing_complete", 3, 3)


def test_repeated_session_skip_preserves_existing_stats_ready_workbook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Tools.LORETA_Visualizer import stats_ready_workbook

    worker = PostProcessingPipelineWorker(_repeated_project(tmp_path))
    stats_target = canonical_artifact_path(tmp_path, "stats_ready_summed_bca")
    stats_target.parent.mkdir(parents=True)
    stats_target.write_text("legacy stats", encoding="utf-8")
    worker._artifact_targets["stats_ready_summed_bca"] = stats_target

    def _unexpected_call(*_args, **_kwargs):
        raise AssertionError("Participant-keyed LORETA code must not run.")

    monkeypatch.setattr(
        stats_ready_workbook,
        "write_loreta_stats_ready_workbook",
        _unexpected_call,
    )

    stats_result = worker._run_stats_ready_export(tmp_path)  # noqa: SLF001

    assert stats_result.ok is True
    assert stats_result.path == ""
    assert stats_target.read_text(encoding="utf-8") == "legacy stats"
    assert worker._artifact_targets == {}  # noqa: SLF001


def test_post_processing_pipeline_runs_steps_in_order(tmp_path) -> None:
    worker = _RecordingWorker(_Project(tmp_path))
    worker._dataset_index = object()
    progress: list[str] = []
    phase_progress: list[tuple[str, int, int, str]] = []
    logs: list[tuple[str, int]] = []
    finished: list[dict] = []
    worker.progress.connect(progress.append)
    worker.phase_progress.connect(
        lambda phase_id, completed, total, message: phase_progress.append((phase_id, completed, total, message))
    )
    worker.log_message.connect(lambda message, level: logs.append((message, level)))
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == [
        "qc",
        f"sync:{tmp_path.name}",
        f"full_fft:{tmp_path.name}",
        "harmonics",
        f"stats:{tmp_path.name}",
        f"audit:{tmp_path.name}",
    ]
    assert progress == [
        "qc done",
        "harmonics done",
        "stats ready done",
        "full audit ready done",
    ]
    assert [message for message, _level in logs] == progress
    assert [event[:3] for event in phase_progress] == [
        ("frequency_domain_qc", 0, 3),
        ("frequency_domain_qc", 1, 3),
        ("harmonic_selection", 1, 3),
        ("harmonic_selection", 2, 3),
        ("stats_ready_export", 2, 3),
        ("stats_ready_export", 3, 3),
        ("post_processing_complete", 3, 3),
    ]
    assert all(message for _phase_id, _completed, _total, message in phase_progress)
    assert finished and finished[0]["ok"] is True
    assert finished[0]["has_warnings"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "full_fft_provenance",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "analysis_ready_full_audit",
    ]
    assert worker._dataset_index is None


def test_base_post_processing_steps_reuse_one_dataset_index(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    from Main_App import projects as projects_module
    from Main_App import exports as exports_module
    from Main_App.processing import (
        frequency_domain_qc,
        full_fft_provenance,
        harmonic_selection_qc,
        processing_ledger,
        recording_condition_outcomes,
        roi_coverage,
    )
    from Tools.LORETA_Visualizer import stats_ready_workbook

    root = tmp_path.resolve()
    sentinel_index = SimpleNamespace(project_root=root)
    sentinel_cache = object()
    loader_calls: list[Path] = []
    captured: list[tuple[str, object]] = []
    sentinel_outcomes = SimpleNamespace(
        fingerprint="current-outcome-ledger",
        cells=(),
    )
    sentinel_coverage = SimpleNamespace(
        fingerprint="current-pre-review-coverage"
    )

    def load_index(project_root):
        loader_calls.append(Path(project_root))
        return sentinel_index

    def run_qc(_project, *, log_func, dataset_index, provisional_cache):
        assert callable(log_func)
        assert provisional_cache is sentinel_cache
        log_func("Frequency-domain QC: Checking electrode findings...")
        log_func("[PERF] technical detail stays in the log")
        captured.append(("qc", dataset_index))
        return {"review_required": False, "review_reused": False}

    def build_coverage(
        project,
        *,
        outcome_ledger,
        processing_ledger,
        persist,
    ):
        assert Path(project.project_root).resolve() == root
        assert outcome_ledger is sentinel_outcomes
        assert processing_ledger == {"root": str(root)}
        assert persist is True
        captured.append(("coverage", outcome_ledger))
        return sentinel_coverage

    def run_harmonics(_project, *, log_func, dataset_index):
        assert callable(log_func)
        captured.append(("harmonics", dataset_index))
        return SimpleNamespace(
            workbook_path=root / "harmonics.xlsx",
            selection_metadata={"selected_harmonics_hz": [1.2, 2.4]},
        )

    def write_stats(_root, *, log_callback, dataset_index):
        assert callable(log_callback)
        captured.append(("stats", dataset_index))
        return SimpleNamespace(
            workbook_path=root / "stats.xlsx",
            row_count=2,
        )

    def write_audit(
        _root,
        *,
        log_callback,
        dataset_index,
        selection_metadata,
    ):
        assert callable(log_callback)
        assert selection_metadata == {"selected_harmonics_hz": [1.2, 2.4]}
        captured.append(("audit", dataset_index))
        return SimpleNamespace(
            workbook_path=root / "analysis_ready.xlsx",
            roi_row_count=2,
        )

    monkeypatch.setattr(projects_module, "load_project_dataset_index", load_index)
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_pre_review_geometry",
        lambda project_root, *, dataset_index: captured.append(("geometry", dataset_index)),
    )
    monkeypatch.setattr(processing_ledger, "load_ledger", lambda project_root: {"root": str(project_root)})
    monkeypatch.setattr(
        recording_condition_outcomes,
        "load_recording_condition_outcomes",
        lambda ledger: sentinel_outcomes,
    )
    monkeypatch.setattr(
        recording_condition_outcomes,
        "require_pre_review_readiness",
        lambda outcomes: captured.append(("readiness", outcomes)),
    )
    monkeypatch.setattr(
        roi_coverage,
        "build_pre_review_roi_coverage",
        build_coverage,
    )
    monkeypatch.setattr(
        frequency_domain_qc,
        "run_frequency_domain_qc_review",
        run_qc,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "run_processing_harmonic_selection_qc",
        run_harmonics,
    )
    monkeypatch.setattr(
        stats_ready_workbook,
        "write_loreta_stats_ready_workbook",
        write_stats,
    )
    monkeypatch.setattr(exports_module, "write_analysis_ready_workbook", write_audit)

    worker = PostProcessingPipelineWorker(_Project(root), provisional_cache=sentinel_cache)
    phase_updates = []
    worker.phase_progress.connect(
        lambda *args: phase_updates.append(args)
    )
    with caplog.at_level(logging.INFO, logger=worker_module.__name__):
        qc_report = worker._run_frequency_domain_qc_review()
    harmonic_result = worker._run_harmonic_selection()
    stats_result = worker._run_stats_ready_export(root)
    audit_result = worker._run_analysis_ready_export(root)

    assert qc_report["review_required"] is False
    assert harmonic_result.ok is True
    assert stats_result.ok is True
    assert audit_result.ok is True
    assert worker._recording_condition_outcomes is sentinel_outcomes
    assert worker._pre_review_roi_coverage is sentinel_coverage
    assert loader_calls == [root]
    assert captured == [
        ("readiness", sentinel_outcomes),
        ("geometry", sentinel_index),
        ("coverage", sentinel_outcomes),
        ("qc", sentinel_index),
        ("harmonics", sentinel_index),
        ("stats", sentinel_index),
        ("audit", sentinel_index),
    ]
    assert [update[3] for update in phase_updates] == [
        "Checking completed condition outputs...",
        "Locating condition data for QC...",
        "Checking processed electrode geometry...",
        "Checking electrode and ROI coverage...",
        "Preparing frequency-domain QC findings...",
        "Checking electrode findings...",
    ]
    assert all(update[:3] == ("frequency_domain_qc", 0, 3) for update in phase_updates)
    timings = [record.message for record in caplog.records if "post_processing_qc_timing" in record.message]
    assert len(timings) == 5
    assert all("completed=True" in message and "elapsed_ms=" in message for message in timings)


def test_qc_stage_logs_elapsed_time_and_preserves_failure(tmp_path, caplog):
    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    with caplog.at_level(logging.INFO, logger=worker_module.__name__):
        with pytest.raises(ValueError, match="invalid source"):
            with worker._frequency_qc_stage("roi_coverage", "Checking coverage..."):
                raise ValueError("invalid source")
    assert "stage=roi_coverage" in caplog.text
    assert "elapsed_ms=" in caplog.text
    assert "completed=False" in caplog.text


def test_post_processing_pipeline_runs_full_audit_when_stats_ready_fails(tmp_path) -> None:
    worker = _StatsFailureWorker(_Project(tmp_path))
    phase_progress: list[tuple[str, int, int]] = []
    finished: list[dict] = []
    worker.phase_progress.connect(
        lambda phase_id, completed, total, _message: phase_progress.append((phase_id, completed, total))
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == [
        "qc",
        f"sync:{tmp_path.name}",
        f"full_fft:{tmp_path.name}",
        "harmonics",
        f"stats:{tmp_path.name}",
        f"audit:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert finished[0]["failure_reason"] == "stats failed"
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "full_fft_provenance",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "analysis_ready_full_audit",
    ]
    assert phase_progress[-2:] == [
        ("stats_ready_export", 2, 3),
        ("post_processing_failed", 2, 3),
    ]


def test_post_processing_pipeline_retains_stats_ready_when_full_audit_fails(
    tmp_path,
) -> None:
    worker = _AuditFailureWorker(_Project(tmp_path))
    finished: list[dict] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == [
        "qc",
        f"sync:{tmp_path.name}",
        f"full_fft:{tmp_path.name}",
        "harmonics",
        f"stats:{tmp_path.name}",
        f"audit:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "full_fft_provenance",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "analysis_ready_full_audit",
    ]


def test_post_processing_pipeline_reports_qc_progress_before_review_pause(tmp_path) -> None:
    worker = _ReviewRequiredWorker(_Project(tmp_path))
    phase_progress: list[tuple[str, int, int]] = []
    finished: list[dict] = []
    worker.phase_progress.connect(
        lambda phase_id, completed, total, _message: phase_progress.append((phase_id, completed, total))
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == ["qc"]
    assert phase_progress == [
        ("frequency_domain_qc", 0, 3),
        ("frequency_domain_qc", 1, 3),
    ]
    assert finished[0]["requires_frequency_domain_qc_review"] is True


def test_post_processing_pipeline_removes_stale_workbook_inside_project(tmp_path) -> None:
    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    stats_ready = tmp_path / "3 - Statistical Analysis Results" / "Stats_Ready_Summed_BCA.xlsx"
    stats_ready.parent.mkdir(parents=True)
    stats_ready.write_text("stale stats", encoding="utf-8")

    worker._delete_file_if_present(
        stats_ready,
        project_root=tmp_path,
        label="Stats-ready Summed BCA workbook",
    )
    assert not stats_ready.exists()


def test_post_processing_pipeline_refuses_to_touch_outputs_outside_project(tmp_path) -> None:
    worker = PostProcessingPipelineWorker(_Project(tmp_path / "project"))
    outside = tmp_path / "outside" / "Stats_Ready_Summed_BCA.xlsx"
    outside.parent.mkdir()
    outside.write_text("outside", encoding="utf-8")

    try:
        worker._delete_file_if_present(
            outside,
            project_root=tmp_path / "project",
            label="Stats-ready Summed BCA workbook",
        )
    except ValueError as exc:
        assert "outside the project root" in str(exc)
    else:
        raise AssertionError("Expected external output invalidation to fail")
    assert outside.exists()


class _SelectionResumeWorker(PostProcessingPipelineWorker):
    def __init__(self, project: _Project, **kwargs) -> None:
        super().__init__(project, **kwargs)
        self.calls: list[str] = []

    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        raise AssertionError("Selection-only resume must not rerun frequency-domain QC.")

    def _run_harmonic_selection(self) -> PostProcessingStepResult:
        raise AssertionError("Selection-only resume must not rerun harmonic selection.")

    def _publish(self, artifact_id: str) -> PostProcessingStepResult:
        self.calls.append(artifact_id)
        target = canonical_artifact_path(self._project.project_root, artifact_id)
        self._artifact_targets[artifact_id] = target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact_id, encoding="utf-8")
        return PostProcessingStepResult(
            artifact_id,
            True,
            f"{artifact_id} rebuilt",
            str(target),
        )

    def _run_stats_ready_export(self, _project_root: Path) -> PostProcessingStepResult:
        return self._publish("stats_ready_summed_bca")

    def _run_analysis_ready_export(self, _project_root: Path) -> PostProcessingStepResult:
        return self._publish("analysis_ready_full_audit")


def _write_resume_project(root: Path) -> None:
    (root / "project.json").write_text(
        '{"schema_version": "2.1.0"}',
        encoding="utf-8",
    )
    summary = root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    summary.parent.mkdir(parents=True)
    summary.write_text("accepted selection", encoding="utf-8")


def test_selection_resume_rebuilds_workbooks_and_invalidates_preserved_source_maps(
    tmp_path,
    monkeypatch,
) -> None:
    _write_resume_project(tmp_path)
    raw_source = tmp_path / "Input" / "P01.bdf"
    full_fft_source = tmp_path / "1 - Excel Data Files" / "P01.xlsx"
    raw_source.parent.mkdir()
    full_fft_source.parent.mkdir()
    raw_source.write_text("raw EEG remains untouched", encoding="utf-8")
    full_fft_source.write_text("FullFFT remains untouched", encoding="utf-8")
    source_ready = tmp_path / "6 - Source Localization" / "Source-Ready Time Domain v1" / "P01-epo.fif"
    source_ready.parent.mkdir(parents=True)
    source_ready.write_bytes(b"source-ready derivative")
    source_artifact_ids = (L2_MNE_SOURCE_PSD_ARTIFACT, ELORETA_VOLUME_SOURCE_PSD_ARTIFACT)
    for artifact_id in source_artifact_ids:
        target = canonical_artifact_path(tmp_path, artifact_id)
        target.mkdir(parents=True)
        (target / "manifest.json").write_bytes(b"preceding publication")
    from Main_App import projects as projects_module

    monkeypatch.setattr(
        projects_module,
        "load_project_dataset_index",
        lambda root: SimpleNamespace(project_root=Path(root)),
    )
    worker = _SelectionResumeWorker(
        _Project(tmp_path),
        resume_from_selection=True,
        selection_metadata={
            "selection_fingerprint": "new-selection",
            "included_harmonics_hz": [1.2, 2.4],
        },
        previous_selection_fingerprint="old-selection",
    )
    finished: list[dict] = []
    worker.finished.connect(finished.append)

    worker.run()

    workbook_ids = [STATS_READY_SUMMED_BCA_ARTIFACT, ANALYSIS_READY_FULL_AUDIT_ARTIFACT]
    assert worker.calls == workbook_ids
    assert finished[-1]["ok"] is True
    assert finished[-1]["selection_changed"] is True
    registry = load_artifact_freshness_registry(tmp_path)
    assert registry.selection_fingerprint == "new-selection"
    assert all(
        registry.artifacts[artifact_id].status == ARTIFACT_STATUS_CURRENT
        for artifact_id in workbook_ids
    )
    for artifact_id in source_artifact_ids:
        assert registry.artifacts[artifact_id].status == ARTIFACT_STATUS_STALE
        target = canonical_artifact_path(tmp_path, artifact_id)
        assert (target / "manifest.json").read_bytes() == b"preceding publication"
    assert source_ready.read_bytes() == b"source-ready derivative"
    assert raw_source.read_text(encoding="utf-8") == "raw EEG remains untouched"
    assert full_fft_source.read_text(encoding="utf-8") == "FullFFT remains untouched"


@pytest.mark.parametrize("repeated_session", [False, True])
def test_selection_resume_skips_rebuild_with_current_workbooks_and_unbuilt_maps(
    tmp_path,
    monkeypatch,
    repeated_session,
) -> None:
    _write_resume_project(tmp_path)
    metadata = {
        "selection_fingerprint": "same-selection",
        "included_harmonics_hz": [1.2, 2.4],
    }
    activate_selection_freshness(
        tmp_path,
        metadata,
        selection_summary_path=(
            tmp_path / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
        ),
    )
    workbook_ids = [ANALYSIS_READY_FULL_AUDIT_ARTIFACT]
    if not repeated_session:
        workbook_ids.append(STATS_READY_SUMMED_BCA_ARTIFACT)
    for artifact_id in workbook_ids:
        target = canonical_artifact_path(tmp_path, artifact_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("current", encoding="utf-8")
        mark_artifact_current(
            tmp_path,
            artifact_id,
            target,
            "same-selection",
        )
    from Main_App import projects as projects_module

    monkeypatch.setattr(
        projects_module,
        "load_project_dataset_index",
        lambda root: SimpleNamespace(project_root=Path(root)),
    )
    project = _repeated_project(tmp_path) if repeated_session else _Project(tmp_path)
    worker = _SelectionResumeWorker(
        project,
        resume_from_selection=True,
        selection_metadata=metadata,
        previous_selection_fingerprint="same-selection",
    )
    finished: list[dict] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == []
    assert finished[-1]["ok"] is True
    assert finished[-1]["rebuild_skipped"] is True


def test_selection_resume_marks_outputs_stale_before_dataset_reload(
    tmp_path,
    monkeypatch,
) -> None:
    _write_resume_project(tmp_path)
    old_metadata = {
        "selection_fingerprint": "old-selection",
        "included_harmonics_hz": [1.2],
    }
    activate_selection_freshness(
        tmp_path,
        old_metadata,
        selection_summary_path=(
            tmp_path / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
        ),
    )
    for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
        target = canonical_artifact_path(tmp_path, artifact_id)
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
        mark_artifact_current(tmp_path, artifact_id, target, "old-selection")
    from Main_App import projects as projects_module

    monkeypatch.setattr(
        projects_module,
        "load_project_dataset_index",
        lambda _root: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    worker = PostProcessingPipelineWorker(
        _Project(tmp_path),
        resume_from_selection=True,
        selection_metadata={
            "selection_fingerprint": "new-selection",
            "included_harmonics_hz": [1.2, 2.4],
        },
        previous_selection_fingerprint="old-selection",
    )
    finished: list[dict] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert finished[-1]["ok"] is False
    assert "index failed" in finished[-1]["steps"][-1]["message"]
    registry = load_artifact_freshness_registry(tmp_path)
    assert all(
        registry.artifacts[artifact_id].status == ARTIFACT_STATUS_STALE
        for artifact_id in SELECTION_DEPENDENT_ARTIFACTS
    )
    assert canonical_artifact_path(
        tmp_path,
        STATS_READY_SUMMED_BCA_ARTIFACT,
    ).read_text(encoding="utf-8") == "old"
