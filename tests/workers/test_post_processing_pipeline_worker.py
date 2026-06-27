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
        self._emit_progress("source maps done")
        return [
            PostProcessingStepResult("l2_mne_surface", True, "surface ok", "surface.json"),
            PostProcessingStepResult("eloreta_volume", True, "volume ok", "volume.json"),
        ]


class _StatsFailureWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingStepResult("stats_ready_summed_bca", False, "stats failed")


def test_post_processing_pipeline_runs_steps_in_order(tmp_path) -> None:
    worker = _RecordingWorker(_Project(tmp_path))
    progress: list[str] = []
    logs: list[tuple[str, int]] = []
    finished: list[dict] = []
    worker.progress.connect(progress.append)
    worker.log_message.connect(lambda message, level: logs.append((message, level)))
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == ["harmonics", f"stats:{tmp_path.name}", f"source:{tmp_path.name}"]
    assert progress == ["harmonics done", "stats ready done", "source maps done"]
    assert [message for message, _level in logs] == progress
    assert finished and finished[0]["ok"] is True
    assert [step["name"] for step in finished[0]["steps"]] == [
        "harmonic_selection",
        "stats_ready_summed_bca",
        "l2_mne_surface",
        "eloreta_volume",
    ]


def test_post_processing_pipeline_skips_source_maps_when_stats_ready_fails(tmp_path) -> None:
    worker = _StatsFailureWorker(_Project(tmp_path))
    finished: list[dict] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert worker.calls == ["harmonics", f"stats:{tmp_path.name}"]
    assert finished and finished[0]["ok"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "harmonic_selection",
        "stats_ready_summed_bca",
        "loreta_source_maps",
    ]
    assert "Skipped LORETA source maps" in finished[0]["steps"][-1]["message"]


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
