from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")

from Main_App.Shared.settings_manager import SettingsManager  # noqa: E402
from Main_App.gui import main_window as main_window_module  # noqa: E402
import Main_App.gui.update_manager as update_manager  # noqa: E402
from Tools.Free_Harmonic_Clustering.gui import (  # noqa: E402
    FreeHarmonicClusteringPage,
    ProjectFrequencySnapshot,
    cancel_all_active_operations,
    has_active_operations,
)
from Tools.Free_Harmonic_Clustering.gui.models import (  # noqa: E402
    GroupChoice,
    ProjectAnalysisOptions,
    RunOutcome,
)
from Tools.Free_Harmonic_Clustering.gui.workers import _CancellableWorker  # noqa: E402
from Tools.Free_Harmonic_Clustering.gui.operation_registry import (  # noqa: E402
    register_active_operation,
    release_active_operation,
)


class _FakeBackend:
    def __init__(self, results_parent: Path) -> None:
        self._results_parent = results_parent

    def results_parent(self, _project_root: Path) -> Path:
        return self._results_parent

    def inspect_project(self, *_args, **_kwargs):  # pragma: no cover - worker path
        raise AssertionError("This smoke applies discovery directly.")

    def prepare(self, *_args, **_kwargs):  # pragma: no cover - worker path
        raise AssertionError("This smoke applies preparation directly.")

    def run(self, *_args, **_kwargs):  # pragma: no cover - worker path
        raise AssertionError("This smoke applies results directly.")


def _options(project_root: Path) -> ProjectAnalysisOptions:
    return ProjectAnalysisOptions(
        project_root=project_root,
        conditions=("Neutral Happy", "Neutral Fear", "Positive Happy"),
        groups=(
            GroupChoice("anxious", "Anxious"),
            GroupChoice("non_anxious", "Non-Anxious"),
        ),
        eligible_orders=(1, 2, 3, 4, 6),
        eligible_harmonics_hz=(1.2, 2.4, 3.6, 4.8, 7.2),
        excluded_base_orders=(5,),
        excluded_base_harmonics_hz=(6.0,),
        fft_upper_hz=20.0,
        effective_harmonic_upper_hz=19.2,
        frequency_resolution_hz=0.01,
        compatibility_message="Exact cohort grids are checked during Prepare.",
    )


def _prepared(project_root: Path):
    return SimpleNamespace(
        project_root=project_root,
        request=SimpleNamespace(design=SimpleNamespace(value="independent_groups")),
        arm_a_label="Anxious",
        arm_b_label="Non-Anxious",
        participant_ids_a=("P01", "P02"),
        participant_ids_b=("P03", "P04"),
        sensor_names=("C1", "Cz", "CPz"),
        harmonic_orders=(1, 2),
        harmonics_hz=(1.2, 2.4),
        method=SimpleNamespace(
            harmonic_selection_mode=SimpleNamespace(value="automatic"),
            fixed_highest_harmonic_order=None,
        ),
        selection=SimpleNamespace(
            candidate_orders=(1, 2, 3),
            arm_a_z=(4.2, 3.8, 1.1),
            arm_b_z=(3.6, 2.0, 0.8),
            detected_arm_a=(True, True, False),
            detected_arm_b=(True, False, False),
            z_threshold=3.29,
            highest_detected_order=2,
        ),
        provenance=SimpleNamespace(
            source_sheet="FullFFT Amplitude (uV)",
            workbook_count=4,
            selected_frequency_column_count=23,
            ledger_excluded_participants=("P20",),
            manual_excluded_participants=(),
            frequency_qc_excluded_participants=(),
            incomplete_pair_participants=(),
            participant_condition_exclusions=(
                SimpleNamespace(
                    participant_id="P10",
                    condition="Neutral Happy",
                    reason="frequency_qc",
                ),
            ),
        ),
        frequency_plan=SimpleNamespace(
            excluded_base_orders=(5,),
            excluded_base_harmonics_hz=(6.0,),
            frequency_resolution_hz=0.01,
        ),
    )


def _page(qtbot, tmp_path: Path) -> FreeHarmonicClusteringPage:
    results_parent = tmp_path / "3 - Statistical Analysis Results" / (
        "Free Harmonic Clustering Analysis"
    )
    results_parent.mkdir(parents=True)
    page = FreeHarmonicClusteringPage(
        project_root=tmp_path,
        frequency_snapshot=ProjectFrequencySnapshot(1.2, 6.0),
        backend=_FakeBackend(results_parent),
        auto_discover=False,
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    page._on_inspection_completed(_options(tmp_path))
    return page


def test_project_setup_is_dynamic_and_results_folder_is_reachable(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(qtbot, tmp_path)

    assert page.project_root == tmp_path.resolve()
    assert page.tabs.count() == 2
    assert page.tabs.tabText(0) == "Setup & Preparation"
    assert page.tabs.tabText(1) == "Results"
    assert not page.tabs.isTabEnabled(1)
    assert page.design_combo.currentText() == "Paired Conditions"
    assert page.harmonic_mode_combo.currentText() == "Hermann automatic selection"
    assert page.paired_condition_a_combo.count() == 3
    assert page.paired_group_filter_combo.itemData(0) is None
    assert page.setup_open_results_button.isEnabled()
    assert page.open_results_button.isEnabled()

    page.harmonic_mode_combo.setCurrentIndex(1)
    assert page.fixed_highest_combo.isEnabled()
    assert [
        page.fixed_highest_combo.itemData(index)
        for index in range(page.fixed_highest_combo.count())
    ] == [1, 2, 3, 4, 6]
    assert "6 Hz" not in " ".join(
        page.fixed_highest_combo.itemText(index)
        for index in range(page.fixed_highest_combo.count())
    )

    original_a = page.paired_condition_a_combo.currentText()
    original_b = page.paired_condition_b_combo.currentText()
    qtbot.mouseClick(page.swap_button, QtCore.Qt.LeftButton)
    assert page.paired_condition_a_combo.currentText() == original_b
    assert page.paired_condition_b_combo.currentText() == original_a
    assert "positive clusters indicate" in page.direction_label.text()

    page._active_stage = "inspection"
    page._on_operation_cancelled()
    assert page._inspection_failed


def test_preparation_and_results_use_locked_current_session_presentation(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = _page(qtbot, tmp_path)
    prepared = _prepared(tmp_path)
    page._on_preparation_completed(prepared)

    assert page.run_button.isEnabled()
    assert "P20" in page.review_exclusions_label.text()
    assert "P10 / Neutral Happy" in page.review_exclusions_label.text()
    assert "Strict z > 3.29" in page.review_selection_audit_label.text()
    assert "H2 (z=3.80)" in page.review_selection_audit_label.text()
    assert "H5 (6 Hz)" in page.review_frequency_domain_label.text()
    assert "4 managed workbook" in page.review_source_coverage_label.text()
    assert "2 + 2 participants" in page.review_shape_label.text()

    significant = SimpleNamespace(
        cluster_id=1,
        sign="positive",
        mass=14.8662,
        p_value=0.0043,
        adjusted_two_sided_p_value=0.0086,
        p_ci_low=0.0031,
        p_ci_high=0.0260,
        confidence_interval_straddles_alpha=True,
        significant=True,
        sensor_indices=(0, 1, 2),
        harmonic_indices=(0, 0, 0),
        effect_size=2.288,
        effect_size_kind="Cohen's d",
    )
    nonsignificant = SimpleNamespace(
        cluster_id=-1,
        sign="negative",
        mass=-5.0,
        p_value=0.21,
        adjusted_two_sided_p_value=0.42,
        p_ci_low=0.19,
        p_ci_high=0.23,
        confidence_interval_straddles_alpha=False,
        significant=False,
        sensor_indices=(1,),
        harmonic_indices=(1,),
        effect_size=-0.4,
        effect_size_kind="Cohen's d",
    )
    result = SimpleNamespace(
        clusters=(nonsignificant, significant),
        permutations_evaluated=10_000,
        degrees_of_freedom=32,
        cluster_forming_threshold=2.738,
        seed=1729,
    )
    run_folder = tmp_path / "run-001"
    outcome = RunOutcome(
        result=result,
        receipt=SimpleNamespace(output_directory=run_folder),
    )
    page._on_run_completed(outcome)

    assert page.tabs.isTabEnabled(1)
    assert page.tabs.currentWidget() is page.results_tab
    assert page.significant_table.rowCount() == 1
    assert page.all_clusters_table.rowCount() == 2
    assert page.all_clusters_table.item(0, 5).text() == "0.0043"
    assert page.all_clusters_table.item(0, 9).text() == "Yes"
    assert page.all_clusters_table.item(1, 9).text() == "No"
    assert "more permutations are recommended" in page.result_status.text()
    assert "p <= .025" in page.significant_status.text()

    assert not page.refresh_project_context(
        project_root=tmp_path,
        frequency_snapshot=ProjectFrequencySnapshot(1.2, 6.0),
    )
    assert page.tabs.isTabEnabled(1)
    assert not page.has_active_work

    page._inspection_failed = True
    retries: list[bool] = []
    monkeypatch.setattr(
        page,
        "_begin_project_inspection",
        lambda: retries.append(True),
    )
    assert page.refresh_project_context(
        project_root=tmp_path,
        frequency_snapshot=ProjectFrequencySnapshot(1.2, 6.0),
    )
    assert retries == [True]
    page._inspection_failed = False

    assert page.refresh_project_context(
        project_root=tmp_path,
        frequency_snapshot=None,
    )
    assert not page.tabs.isTabEnabled(1)
    assert not page.prepare_button.isEnabled()
    assert "Project Settings" in page.workflow_status.text()


def test_worker_reports_success_when_cancel_arrives_after_return() -> None:
    class LateCancelWorker(_CancellableWorker):
        def _execute(self) -> object:
            self.cancel()
            return "published receipt"

    worker = LateCancelWorker()
    completed: list[object] = []
    cancelled: list[bool] = []
    worker.completed.connect(completed.append)
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert completed == ["published receipt"]
    assert cancelled == []


def test_retired_page_operation_remains_globally_cancellable(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(qtbot, tmp_path)

    class Worker:
        cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    token = object()
    worker = Worker()
    register_active_operation(token, worker)
    try:
        page.shutdown()
        assert has_active_operations()
        assert cancel_all_active_operations() == 1
        assert worker.cancel_calls == 1
    finally:
        release_active_operation(token)

    assert not has_active_operations()


def test_main_window_close_waits_for_retired_page_operations(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(
        update_manager,
        "check_for_updates_on_launch",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda window: setattr(window, "projectsRoot", tmp_path),
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        lambda *_args, **_kwargs: None,
    )
    SettingsManager().save()
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)

    class Worker:
        cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    token = object()
    worker = Worker()
    ignored: list[bool] = []
    event = SimpleNamespace(ignore=lambda: ignored.append(True))
    register_active_operation(token, worker)
    try:
        window.closeEvent(event)
        assert ignored == [True]
        assert worker.cancel_calls == 1
        assert has_active_operations()
    finally:
        release_active_operation(token)

    assert not has_active_operations()
