from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Main_App.workers.post_processing_pipeline_worker import (
    PostProcessingPipelineWorker,
    PostProcessingStepResult,
)


@dataclass
class _Project:
    project_root: Path


class _RecordingWorker(PostProcessingPipelineWorker):
    def __init__(self, project: _Project) -> None:
        super().__init__(project)
        self.calls: list[str] = []

    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self.calls.append("qc")
        self._emit_progress("qc done")
        return {"review_required": False, "review_reused": False}

    def _sync_frequency_domain_qc_automatic_state(
        self,
        project_root: Path,
        qc_report: dict[str, object],
    ) -> None:
        assert qc_report["review_required"] is False
        self.calls.append(f"sync:{project_root.name}")

    def _run_harmonic_selection(self) -> PostProcessingStepResult:
        self.calls.append("harmonics")
        self._emit_progress("harmonics done")
        return PostProcessingStepResult("harmonic_selection", True, "harmonics ok", "harmonics.xlsx")

    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        self._emit_progress("stats ready done")
        return PostProcessingStepResult("stats_ready_summed_bca", True, "stats ok", "stats.xlsx")

    def _run_source_maps(self, project_root: Path) -> list[PostProcessingStepResult]:
        self.calls.append(f"source:{project_root.name}")
        return super()._run_source_maps(project_root)

    def _run_source_map_mode(
        self,
        project_root: Path,
        mode: str,
    ) -> PostProcessingStepResult:
        self.calls.append(f"source_mode:{mode}:{project_root.name}")
        assert mode == "l2_mne_source_psd"
        return PostProcessingStepResult(mode, True, "source PSD ok", "source_psd.json")


class _StatsFailureWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingStepResult("stats_ready_summed_bca", False, "stats failed")


class _ReviewRequiredWorker(_RecordingWorker):
    def _run_frequency_domain_qc_review(self) -> dict[str, object]:
        self.calls.append("qc")
        return {"review_required": True, "review_reused": False}


def test_post_processing_pipeline_runs_steps_in_order(tmp_path) -> None:
    worker = _RecordingWorker(_Project(tmp_path))
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
        "harmonics",
        f"stats:{tmp_path.name}",
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
    ]
    assert progress == [
        "qc done",
        "harmonics done",
        "stats ready done",
        "Generating Hauk-informed time-domain source-space maps for 3D visualization of oddball responses.",
    ]
    assert [message for message, _level in logs] == progress
    assert [event[:3] for event in phase_progress] == [
        ("frequency_domain_qc", 0, 4),
        ("frequency_domain_qc", 1, 4),
        ("harmonic_selection", 1, 4),
        ("harmonic_selection", 2, 4),
        ("stats_ready_export", 2, 4),
        ("stats_ready_export", 3, 4),
        ("l2_mne_source_maps", 3, 4),
        ("l2_mne_source_maps", 4, 4),
        ("post_processing_complete", 4, 4),
    ]
    assert all(message for _phase_id, _completed, _total, message in phase_progress)
    assert finished and finished[0]["ok"] is True
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "l2_mne_source_psd",
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
        "harmonics",
        f"stats:{tmp_path.name}",
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "l2_mne_source_psd",
    ]
    assert phase_progress[-4:] == [
        ("stats_ready_export", 3, 4),
        ("l2_mne_source_maps", 3, 4),
        ("l2_mne_source_maps", 4, 4),
        ("post_processing_complete", 4, 4),
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
        ("frequency_domain_qc", 0, 4),
        ("frequency_domain_qc", 1, 4),
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
