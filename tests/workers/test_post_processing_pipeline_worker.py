from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import Main_App.workers.post_processing_pipeline_worker as worker_module
from Main_App.processing.artifact_freshness import (
    ARTIFACT_STATUS_CURRENT,
    ARTIFACT_STATUS_FAILED,
    ARTIFACT_STATUS_STALE,
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

    def _run_source_maps(self, project_root: Path) -> list[PostProcessingStepResult]:
        self.calls.append(f"source:{project_root.name}")
        return super()._run_source_maps(project_root)

    def _run_source_map_mode(
        self,
        project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        self.calls.append(f"source_mode:{mode}:{project_root.name}")
        assert mode in {"l2_mne_source_psd", "eloreta_volume_source_psd"}
        return PostProcessingStepResult(mode, True, f"{mode} ok", f"{mode}.json")


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


class _CohortWarningWorker(_RecordingWorker):
    def _run_source_map_mode(
        self,
        project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        result = super()._run_source_map_mode(project_root, mode)
        if mode != "l2_mne_source_psd":
            return result
        return PostProcessingStepResult(
            result.name,
            result.ok,
            "P09 was omitted from every source condition.",
            result.path,
            warning=True,
        )


class _RepeatedSessionRecordingWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingPipelineWorker._run_stats_ready_export(
            self,
            project_root,
        )


@pytest.mark.parametrize(
    ("mode", "loader_name", "output_folder"),
    (
        ("l2_mne_source_psd", "_load_source_psd_export_api", "l2"),
        (
            "eloreta_volume_source_psd",
            "_load_eloreta_source_psd_export_api",
            "eloreta",
        ),
    ),
)
def test_each_source_map_step_remains_successful_when_source_participants_are_omitted(
    tmp_path,
    monkeypatch,
    mode: str,
    loader_name: str,
    output_folder: str,
) -> None:
    project = _Project(tmp_path)
    worker = PostProcessingPipelineWorker(project)
    output_dir = tmp_path / output_folder
    manifest_path = output_dir / "manifest.json"

    def _write_payloads(**_kwargs):
        return SimpleNamespace(
            manifest_path=manifest_path,
            included_participants=("P01", "P02"),
            source_ineligible_participants=(
                SimpleNamespace(participant_id="P09"),
            ),
        )

    monkeypatch.setattr(
        worker_module,
        loader_name,
        lambda: (lambda _root: output_dir, _write_payloads),
    )

    result = worker._run_source_map_mode(tmp_path, mode)

    assert result.ok is True
    assert result.warning is True
    assert "generated from 2 source-eligible participant(s)" in result.message
    assert "P09" in result.message
    assert result.as_dict()["warning"] is True


@pytest.mark.parametrize(
    ("mode", "loader_name", "output_folder"),
    (
        ("l2_mne_source_psd", "_load_source_psd_export_api", "l2"),
        (
            "eloreta_volume_source_psd",
            "_load_eloreta_source_psd_export_api",
            "eloreta",
        ),
    ),
)
def test_each_source_map_step_reports_condition_specific_omissions_as_warnings(
    tmp_path,
    monkeypatch,
    mode: str,
    loader_name: str,
    output_folder: str,
) -> None:
    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    output_dir = tmp_path / output_folder

    def _write_payloads(**_kwargs):
        return SimpleNamespace(
            manifest_path=output_dir / "manifest.json",
            included_participants=("P01", "P02"),
            source_ineligible_participants=(),
            source_condition_omissions=(
                SimpleNamespace(
                    participant_id="P01",
                    condition_id="22",
                    reason_code="noncanonical_source_sample_count",
                ),
            ),
        )

    monkeypatch.setattr(
        worker_module,
        loader_name,
        lambda: (lambda _root: output_dir, _write_payloads),
    )

    result = worker._run_source_map_mode(tmp_path, mode)

    assert result.ok is True
    assert result.warning is True
    assert "1 incompatible or unavailable participant-condition" in result.message


@pytest.mark.parametrize(
    "failing_mode",
    ("l2_mne_source_psd", "eloreta_volume_source_psd"),
)
def test_source_map_modes_run_independently_after_a_partial_failure(
    tmp_path,
    monkeypatch,
    failing_mode: str,
) -> None:
    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    calls: list[str] = []

    def _writer(mode: str):
        def write_payloads(**_kwargs):
            calls.append(mode)
            if mode == failing_mode:
                raise RuntimeError(f"{mode} failed intentionally")
            return SimpleNamespace(
                manifest_path=tmp_path / mode / "manifest.json",
                included_participants=("P01", "P02"),
                source_ineligible_participants=(),
            )

        return write_payloads

    monkeypatch.setattr(
        worker_module,
        "_load_source_psd_export_api",
        lambda: (
            lambda _root: tmp_path / "l2_mne_source_psd",
            _writer("l2_mne_source_psd"),
        ),
    )
    monkeypatch.setattr(
        worker_module,
        "_load_eloreta_source_psd_export_api",
        lambda: (
            lambda _root: tmp_path / "eloreta_volume_source_psd",
            _writer("eloreta_volume_source_psd"),
        ),
    )

    results = worker._run_source_maps(tmp_path)

    assert calls == ["l2_mne_source_psd", "eloreta_volume_source_psd"]
    assert [result.name for result in results] == calls
    assert [result.ok for result in results] == [
        mode != failing_mode for mode in calls
    ]
    assert failing_mode in next(result.message for result in results if not result.ok)


def test_failed_source_map_rebuild_restores_preceding_directory_and_marks_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_resume_project(tmp_path)
    summary = tmp_path / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    activate_selection_freshness(
        tmp_path,
        {"selection_fingerprint": "old-selection"},
        selection_summary_path=summary,
    )
    artifact_id = "l2_mne_source_psd"
    output_dir = canonical_artifact_path(tmp_path, artifact_id)
    output_dir.mkdir(parents=True)
    (output_dir / "old.json").write_text("old", encoding="utf-8")
    mark_artifact_current(
        tmp_path,
        artifact_id,
        output_dir,
        "old-selection",
    )

    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    worker._harmonic_selection_metadata = {  # noqa: SLF001
        "selection_fingerprint": "new-selection"
    }
    worker._previous_selection_fingerprint = "old-selection"  # noqa: SLF001
    worker._activate_artifact_freshness(  # noqa: SLF001
        tmp_path,
        selection_summary_path=summary,
    )

    def _fail_after_partial_write(**_kwargs):
        output_dir.mkdir(parents=True)
        (output_dir / "partial.json").write_text("partial", encoding="utf-8")
        raise RuntimeError("source rebuild failed intentionally")

    monkeypatch.setattr(
        worker_module,
        "_load_source_psd_export_api",
        lambda: (lambda _root: output_dir, _fail_after_partial_write),
    )

    step = worker._record_artifact_freshness(  # noqa: SLF001
        worker._run_source_map_mode(tmp_path, artifact_id)  # noqa: SLF001
    )

    assert step.ok is False
    assert (output_dir / "old.json").read_text(encoding="utf-8") == "old"
    assert not (output_dir / "partial.json").exists()
    record = load_artifact_freshness_registry(tmp_path).artifacts[artifact_id]
    assert record.status == ARTIFACT_STATUS_FAILED
    assert record.built_from_selection_fingerprint == "old-selection"


def test_source_map_freshness_save_failure_restores_preceding_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.processing import artifact_freshness as freshness_module

    _write_resume_project(tmp_path)
    summary = tmp_path / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    activate_selection_freshness(
        tmp_path,
        {"selection_fingerprint": "old-selection"},
        selection_summary_path=summary,
    )
    artifact_id = "l2_mne_source_psd"
    output_dir = canonical_artifact_path(tmp_path, artifact_id)
    output_dir.mkdir(parents=True)
    (output_dir / "old.json").write_text("old", encoding="utf-8")
    mark_artifact_current(tmp_path, artifact_id, output_dir, "old-selection")

    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    worker._harmonic_selection_metadata = {  # noqa: SLF001
        "selection_fingerprint": "new-selection"
    }
    worker._previous_selection_fingerprint = "old-selection"  # noqa: SLF001
    worker._activate_artifact_freshness(  # noqa: SLF001
        tmp_path,
        selection_summary_path=summary,
    )

    def _write_replacement(**_kwargs):
        output_dir.mkdir(parents=True)
        manifest = output_dir / "manifest.json"
        manifest.write_text("new", encoding="utf-8")
        return SimpleNamespace(
            manifest_path=manifest,
            included_participants=("P01",),
            source_ineligible_participants=(),
            source_condition_omissions=(),
        )

    monkeypatch.setattr(
        worker_module,
        "_load_source_psd_export_api",
        lambda: (lambda _root: output_dir, _write_replacement),
    )
    source_step = worker._run_source_map_mode(  # noqa: SLF001
        tmp_path,
        artifact_id,
    )
    monkeypatch.setattr(
        freshness_module,
        "mark_artifact_current",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("project.json is locked")
        ),
    )

    recorded = worker._record_artifact_freshness(source_step)  # noqa: SLF001

    assert recorded.ok is False
    assert "freshness could not be saved" in recorded.message
    assert (output_dir / "old.json").read_text(encoding="utf-8") == "old"
    assert not (output_dir / "manifest.json").exists()


def test_pipeline_reports_success_with_source_cohort_warnings(tmp_path) -> None:
    worker = _CohortWarningWorker(_Project(tmp_path))
    phase_progress: list[tuple[str, int, int, str]] = []
    finished: list[dict] = []
    worker.phase_progress.connect(
        lambda phase_id, completed, total, message: phase_progress.append(
            (phase_id, completed, total, message)
        )
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert finished[0]["ok"] is True
    assert finished[0]["has_warnings"] is True
    source_steps = finished[0]["steps"][-2:]
    assert [step["warning"] for step in source_steps] == [True, False]
    assert source_steps[0]["name"] == "l2_mne_source_psd"
    assert source_steps[1]["name"] == "eloreta_volume_source_psd"
    assert phase_progress[-1] == (
        "post_processing_complete",
        5,
        5,
        "Post-processing is complete with source-cohort warnings.",
    )


def test_repeated_session_pipeline_successfully_skips_participant_keyed_loreta(
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
        f"source:{tmp_path.name}",
    ]
    steps = {step["name"]: step for step in finished[0]["steps"]}
    assert steps["stats_ready_summed_bca"]["ok"] is True
    assert "Skipped the legacy LORETA Stats-ready workbook" in steps[
        "stats_ready_summed_bca"
    ]["message"]
    for mode in ("l2_mne_source_psd", "eloreta_volume_source_psd"):
        assert steps[mode]["ok"] is True
        assert "not recording-aware" in steps[mode]["message"]
    assert any("legacy LORETA Stats-ready workbook" in message for message in progress)
    assert any("Automatic LORETA project-source generation" in message for message in progress)
    source_phase_messages = [
        message
        for phase_id, _completed, _total, message in phase_progress
        if phase_id in {"l2_mne_source_maps", "eloreta_source_maps"}
    ]
    assert source_phase_messages
    assert all("not recording-aware" in message for message in source_phase_messages)


def test_repeated_session_loreta_skips_preserve_existing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Tools.LORETA_Visualizer import stats_ready_workbook

    worker = PostProcessingPipelineWorker(_repeated_project(tmp_path))
    stats_target = canonical_artifact_path(tmp_path, "stats_ready_summed_bca")
    stats_target.parent.mkdir(parents=True)
    stats_target.write_text("legacy stats", encoding="utf-8")
    source_targets = {
        mode: canonical_artifact_path(tmp_path, mode)
        for mode in ("l2_mne_source_psd", "eloreta_volume_source_psd")
    }
    for mode, target in source_targets.items():
        target.mkdir(parents=True)
        (target / "existing.json").write_text(mode, encoding="utf-8")
    worker._artifact_targets.update(  # noqa: SLF001
        {"stats_ready_summed_bca": stats_target, **source_targets}
    )

    def _unexpected_call(*_args, **_kwargs):
        raise AssertionError("Participant-keyed LORETA code must not run.")

    monkeypatch.setattr(
        stats_ready_workbook,
        "write_loreta_stats_ready_workbook",
        _unexpected_call,
    )
    monkeypatch.setattr(
        worker_module,
        "_load_source_psd_export_api",
        _unexpected_call,
    )
    monkeypatch.setattr(
        worker_module,
        "_load_eloreta_source_psd_export_api",
        _unexpected_call,
    )

    stats_result = worker._run_stats_ready_export(tmp_path)  # noqa: SLF001
    source_results = worker._run_source_maps(tmp_path)  # noqa: SLF001

    assert stats_result.ok is True
    assert stats_result.path == ""
    assert all(result.ok and not result.path for result in source_results)
    assert stats_target.read_text(encoding="utf-8") == "legacy stats"
    for mode, target in source_targets.items():
        assert (target / "existing.json").read_text(encoding="utf-8") == mode
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
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
        f"source_mode:eloreta_volume_source_psd:{tmp_path.name}",
    ]
    assert progress == [
        "qc done",
        "harmonics done",
        "stats ready done",
        "full audit ready done",
        "Generating Hauk-informed time-domain source-space maps for 3D visualization of oddball responses.",
    ]
    assert [message for message, _level in logs] == progress
    assert [event[:3] for event in phase_progress] == [
        ("frequency_domain_qc", 0, 5),
        ("frequency_domain_qc", 1, 5),
        ("harmonic_selection", 1, 5),
        ("harmonic_selection", 2, 5),
        ("stats_ready_export", 2, 5),
        ("stats_ready_export", 3, 5),
        ("l2_mne_source_maps", 3, 5),
        ("l2_mne_source_maps", 4, 5),
        ("eloreta_source_maps", 4, 5),
        ("eloreta_source_maps", 5, 5),
        ("post_processing_complete", 5, 5),
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
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
    ]
    assert worker._dataset_index is None


def test_base_post_processing_steps_reuse_one_dataset_index(
    tmp_path,
    monkeypatch,
) -> None:
    from Main_App import projects as projects_module
    from Main_App import exports as exports_module
    from Main_App.processing import (
        frequency_domain_qc,
        harmonic_selection_qc,
        processing_ledger,
        recording_condition_outcomes,
        roi_coverage,
    )
    from Tools.LORETA_Visualizer import stats_ready_workbook

    root = tmp_path.resolve()
    sentinel_index = SimpleNamespace(project_root=root)
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

    def run_qc(_project, *, log_func, dataset_index):
        assert callable(log_func)
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

    worker = PostProcessingPipelineWorker(_Project(root))
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
        ("coverage", sentinel_outcomes),
        ("qc", sentinel_index),
        ("harmonics", sentinel_index),
        ("stats", sentinel_index),
        ("audit", sentinel_index),
    ]


def test_post_processing_pipeline_runs_source_psd_when_stats_ready_fails(tmp_path) -> None:
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
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
        f"source_mode:eloreta_volume_source_psd:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert finished[0]["failure_reason"] == "stats failed"
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "full_fft_provenance",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "analysis_ready_full_audit",
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
    ]
    assert phase_progress[-6:] == [
        ("stats_ready_export", 2, 5),
        ("l2_mne_source_maps", 2, 5),
        ("l2_mne_source_maps", 2, 5),
        ("eloreta_source_maps", 2, 5),
        ("eloreta_source_maps", 2, 5),
        ("post_processing_failed", 2, 5),
    ]


def test_post_processing_pipeline_runs_source_psd_when_full_audit_export_fails(
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
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
        f"source_mode:eloreta_volume_source_psd:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "full_fft_provenance",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "analysis_ready_full_audit",
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
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
        ("frequency_domain_qc", 0, 5),
        ("frequency_domain_qc", 1, 5),
    ]
    assert finished[0]["requires_frequency_domain_qc_review"] is True


def test_post_processing_pipeline_invalidates_stale_outputs_inside_project(tmp_path) -> None:
    worker = PostProcessingPipelineWorker(_Project(tmp_path))
    stats_ready = tmp_path / "3 - Statistical Analysis Results" / "Stats_Ready_Summed_BCA.xlsx"
    source_dir = tmp_path / "6 - Source Localization" / "L2-MNE Surface Beta"
    source_file = source_dir / "old_manifest.json"
    stats_ready.parent.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    stats_ready.write_text("stale stats", encoding="utf-8")
    source_file.write_text("stale source", encoding="utf-8")

    worker._delete_file_if_present(
        stats_ready,
        project_root=tmp_path,
        label="Stats-ready Summed BCA workbook",
    )
    worker._clear_output_dir(
        source_dir,
        project_root=tmp_path,
        label="L2-MNE surface source maps",
    )

    assert not stats_ready.exists()
    assert not source_file.exists()
    assert source_dir.exists()


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
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact_id, encoding="utf-8")
            result_path = target
        else:
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "manifest.json"
            result_path.write_text(artifact_id, encoding="utf-8")
        return PostProcessingStepResult(
            artifact_id,
            True,
            f"{artifact_id} rebuilt",
            str(result_path),
        )

    def _run_stats_ready_export(self, _project_root: Path) -> PostProcessingStepResult:
        return self._publish("stats_ready_summed_bca")

    def _run_analysis_ready_export(self, _project_root: Path) -> PostProcessingStepResult:
        return self._publish("analysis_ready_full_audit")

    def _run_source_map_mode(
        self,
        _project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        return self._publish(mode)


def _write_resume_project(root: Path) -> None:
    (root / "project.json").write_text(
        '{"schema_version": "2.1.0"}',
        encoding="utf-8",
    )
    summary = root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    summary.parent.mkdir(parents=True)
    summary.write_text("accepted selection", encoding="utf-8")


def test_selection_resume_rebuilds_only_selection_dependent_artifacts(
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

    assert worker.calls == list(SELECTION_DEPENDENT_ARTIFACTS)
    assert finished[-1]["ok"] is True
    assert finished[-1]["selection_changed"] is True
    registry = load_artifact_freshness_registry(tmp_path)
    assert registry.selection_fingerprint == "new-selection"
    assert all(
        registry.artifacts[artifact_id].status == ARTIFACT_STATUS_CURRENT
        for artifact_id in SELECTION_DEPENDENT_ARTIFACTS
    )
    assert raw_source.read_text(encoding="utf-8") == "raw EEG remains untouched"
    assert full_fft_source.read_text(encoding="utf-8") == "FullFFT remains untouched"


def test_selection_resume_skips_rebuild_when_fingerprint_and_artifacts_are_current(
    tmp_path,
    monkeypatch,
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
    for artifact_id in SELECTION_DEPENDENT_ARTIFACTS:
        target = canonical_artifact_path(tmp_path, artifact_id)
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("current", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
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
    worker = _SelectionResumeWorker(
        _Project(tmp_path),
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
