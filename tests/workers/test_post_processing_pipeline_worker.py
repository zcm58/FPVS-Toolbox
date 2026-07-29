from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import Main_App.workers.post_processing_pipeline_worker as worker_module
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
        assert mode in {"l2_mne_source_psd", "eloreta_volume_source_psd"}
        return PostProcessingStepResult(mode, True, f"{mode} ok", f"{mode}.json")


class _StatsFailureWorker(_RecordingWorker):
    def _run_stats_ready_export(self, project_root: Path) -> PostProcessingStepResult:
        self.calls.append(f"stats:{project_root.name}")
        return PostProcessingStepResult("stats_ready_summed_bca", False, "stats failed")


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
        "harmonics",
        f"stats:{tmp_path.name}",
        f"source:{tmp_path.name}",
        f"source_mode:l2_mne_source_psd:{tmp_path.name}",
        f"source_mode:eloreta_volume_source_psd:{tmp_path.name}",
    ]
    assert progress == [
        "qc done",
        "harmonics done",
        "stats ready done",
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
        "harmonic_selection",
        "stats_ready_summed_bca",
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
    ]
    assert worker._dataset_index is None


def test_base_post_processing_steps_reuse_one_dataset_index(
    tmp_path,
    monkeypatch,
) -> None:
    from Main_App import projects as projects_module
    from Main_App.processing import frequency_domain_qc, harmonic_selection_qc
    from Tools.LORETA_Visualizer import stats_ready_workbook

    root = tmp_path.resolve()
    sentinel_index = SimpleNamespace(project_root=root)
    loader_calls: list[Path] = []
    captured: list[tuple[str, object]] = []

    def load_index(project_root):
        loader_calls.append(Path(project_root))
        return sentinel_index

    def run_qc(_project, *, log_func, dataset_index):
        assert callable(log_func)
        captured.append(("qc", dataset_index))
        return {"review_required": False, "review_reused": False}

    def run_harmonics(_project, *, log_func, dataset_index):
        assert callable(log_func)
        captured.append(("harmonics", dataset_index))
        return SimpleNamespace(workbook_path=root / "harmonics.xlsx")

    def write_stats(_root, *, log_callback, dataset_index):
        assert callable(log_callback)
        captured.append(("stats", dataset_index))
        return SimpleNamespace(
            workbook_path=root / "stats.xlsx",
            row_count=2,
        )

    monkeypatch.setattr(projects_module, "load_project_dataset_index", load_index)
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

    worker = PostProcessingPipelineWorker(_Project(root))
    qc_report = worker._run_frequency_domain_qc_review()
    harmonic_result = worker._run_harmonic_selection()
    stats_result = worker._run_stats_ready_export(root)

    assert qc_report["review_required"] is False
    assert harmonic_result.ok is True
    assert stats_result.ok is True
    assert loader_calls == [root]
    assert captured == [
        ("qc", sentinel_index),
        ("harmonics", sentinel_index),
        ("stats", sentinel_index),
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
        f"source_mode:eloreta_volume_source_psd:{tmp_path.name}",
    ]
    assert finished and finished[0]["ok"] is False
    assert [step["name"] for step in finished[0]["steps"]] == [
        "frequency_domain_qc",
        "harmonic_selection",
        "stats_ready_summed_bca",
        "l2_mne_source_psd",
        "eloreta_volume_source_psd",
    ]
    assert phase_progress[-6:] == [
        ("stats_ready_export", 3, 5),
        ("l2_mne_source_maps", 3, 5),
        ("l2_mne_source_maps", 4, 5),
        ("eloreta_source_maps", 4, 5),
        ("eloreta_source_maps", 5, 5),
        ("post_processing_complete", 5, 5),
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
