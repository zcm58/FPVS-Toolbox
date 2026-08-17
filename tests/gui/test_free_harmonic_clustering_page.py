from __future__ import annotations

from pathlib import Path
from threading import get_ident
import time
from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from Main_App.Shared.settings_manager import SettingsManager  # noqa: E402
from Main_App.gui import main_window as main_window_module  # noqa: E402
from Main_App.processing.full_fft_provenance import (  # noqa: E402
    FullFftProvenanceError,
    FullFftProvenanceMissingError,
)
import Main_App.gui.update_manager as update_manager  # noqa: E402
from Tools.Free_Harmonic_Clustering.gui import (  # noqa: E402
    FreeHarmonicClusteringPage,
    ProjectFrequencySnapshot,
    cancel_all_active_operations,
    has_active_operations,
)
from Tools.Free_Harmonic_Clustering.gui.models import (  # noqa: E402
    FreeHarmonicInputError,
    GuiAnalysisDesign,
    GuiHarmonicMode,
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


def _options(
    project_root: Path,
    *,
    diagnostics: tuple[str, ...] = (),
) -> ProjectAnalysisOptions:
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
        diagnostics=diagnostics,
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


def _page(
    qtbot,
    tmp_path: Path,
    *,
    diagnostics: tuple[str, ...] = (),
) -> FreeHarmonicClusteringPage:
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
    page._on_inspection_completed(_options(tmp_path, diagnostics=diagnostics))
    return page


def test_project_setup_is_dynamic_and_results_folder_is_reachable(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(qtbot, tmp_path)
    page.resize(1280, 900)
    QtWidgets.QApplication.processEvents()

    assert page.project_root == tmp_path.resolve()
    header_text = {
        label.text() for label in page.findChildren(QtWidgets.QLabel)
    }
    assert "Free Harmonic Clustering Analysis" in header_text
    assert "CLUSTER ANALYSIS TOOL" not in header_text
    assert not any(text.startswith("Compare one ordered") for text in header_text)
    assert "BETA ANALYSIS TOOL" not in header_text
    assert page.findChildren(QtWidgets.QTabWidget) == []
    assert page.findChildren(QtWidgets.QScrollArea) == []
    assert page.setup_panel.isVisible()
    assert page.results_panel.isHidden()
    comparison_card = page.findChild(
        QtWidgets.QWidget,
        "free_harmonic_comparison_card",
    )
    harmonics_card = page.findChild(
        QtWidgets.QWidget,
        "free_harmonic_harmonics_card",
    )
    assert comparison_card is page.comparison_card
    assert harmonics_card is page.harmonics_card
    assert not comparison_card.isAncestorOf(harmonics_card)
    assert not harmonics_card.isAncestorOf(comparison_card)
    assert comparison_card.geometry().top() == harmonics_card.geometry().top()
    assert comparison_card.geometry().bottom() == harmonics_card.geometry().bottom()
    assert abs(comparison_card.width() - harmonics_card.width()) <= 1
    assert comparison_card.height() < page.workspace.height() * 0.75
    comparison_field_x = {
        widget.mapTo(comparison_card, QtCore.QPoint(0, 0)).x()
        for widget in (
            page.design_combo,
            page.paired_condition_a_combo,
            page.paired_condition_b_combo,
            page.paired_group_filter_combo,
        )
    }
    assert len(comparison_field_x) == 1
    assert (
        page.harmonic_mode_combo.mapTo(harmonics_card, QtCore.QPoint(0, 0)).x()
        == page.design_combo.mapTo(comparison_card, QtCore.QPoint(0, 0)).x()
    )
    for removed_object_name in (
        "free_harmonic_beta_banner",
        "free_harmonic_profile_card",
        "free_harmonic_discovery_note",
        "free_harmonic_swap_button",
        "free_harmonic_setup_card",
        "free_harmonic_main_tabs",
        "free_harmonic_review_tab",
        "free_harmonic_results_tabs",
        "free_harmonic_result_run_summary",
    ):
        assert page.findChild(QtWidgets.QWidget, removed_object_name) is None
    assert page.setup_panel.isAncestorOf(page.design_combo)
    assert page.results_panel.isAncestorOf(page.significant_table)
    for widget in (
        page.workflow_status,
        page.progress_bar,
        page.workflow_actions,
        page.run_analysis_button,
        page.cancel_button,
        page.open_results_button,
    ):
        assert page.isAncestorOf(widget)
    assert page.design_combo.currentText() == "Paired Conditions"
    assert page.harmonic_mode_combo.currentText() == "Hermann automatic selection"
    assert page.paired_condition_a_combo.count() == 3
    assert page.paired_group_filter_combo.itemData(0) is None
    assert "Run Analysis" in page.workflow_status.text()
    assert "show the results below" in page.workflow_status.text()
    assert page.open_results_button.isEnabled()
    for combo in (
        page.paired_condition_a_combo,
        page.paired_condition_b_combo,
        page.paired_group_filter_combo,
        page.independent_group_a_combo,
        page.independent_group_b_combo,
    ):
        assert (
            combo.sizePolicy().horizontalPolicy()
            == QtWidgets.QSizePolicy.Expanding
        )
        assert combo.minimumContentsLength() >= 24
    assert (
        page.design_stack.sizePolicy().horizontalPolicy()
        == QtWidgets.QSizePolicy.Expanding
    )

    page.harmonic_mode_combo.setCurrentIndex(1)
    assert page.fixed_highest_combo.isEnabled()
    assert [
        page.fixed_highest_combo.itemData(index)
        for index in range(page.fixed_highest_combo.count())
    ] == [1, 2, 3, 4, 6]
    fixed_harmonic_labels = [
        page.fixed_highest_combo.itemText(index)
        for index in range(page.fixed_highest_combo.count())
    ]
    assert "H5 (6 Hz)" not in fixed_harmonic_labels

    requested_a = page.paired_condition_b_combo.currentData()
    page.paired_condition_a_combo.setCurrentIndex(
        page.paired_condition_b_combo.currentIndex()
    )
    assert page.paired_condition_a_combo.currentData() == requested_a
    assert (
        page.paired_condition_a_combo.currentData()
        != page.paired_condition_b_combo.currentData()
    )
    requested_b = page.paired_condition_a_combo.currentData()
    page.paired_condition_b_combo.setCurrentIndex(
        page.paired_condition_a_combo.currentIndex()
    )
    assert page.paired_condition_b_combo.currentData() == requested_b
    assert (
        page.paired_condition_a_combo.currentData()
        != page.paired_condition_b_combo.currentData()
    )
    assert "positive clusters indicate" in page.direction_label.text()
    assert page._setup_error() is None
    assert page.run_analysis_button.isEnabled()

    page._active_stage = "inspection"
    page._on_operation_cancelled()
    assert page._inspection_failed


def test_provenance_failure_requests_shared_post_processing_without_error_banner(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(qtbot, tmp_path)
    requests: list[tuple[str, str, str]] = []
    page.post_processing_required.connect(
        lambda *args: requests.append(tuple(str(value) for value in args))
    )
    reason = (
        "Neutral FullFFT provenance is missing. Rerun post-processing; "
        "EEG preprocessing is not required."
    )

    page._active_stage = "inspection"
    page._on_post_processing_required(reason)

    assert page._inspection_failed
    assert page._options is None
    assert page.workflow_status.isHidden()
    assert requests == []

    page._on_operation_thread_finished()

    assert requests == [
        (
            "Free Harmonic Clustering Analysis",
            reason,
            str(tmp_path.resolve()),
        )
    ]
    assert page.workflow_status.isHidden()

    page._active_stage = "inspection"
    page._on_operation_failed("The project index could not be read.")
    assert page.workflow_status.isVisible()
    assert page.workflow_status.text() == "The project index could not be read."


def test_worker_preserves_typed_post_processing_failure() -> None:
    class MissingProvenanceWorker(_CancellableWorker):
        def _execute(self) -> object:
            try:
                raise FullFftProvenanceMissingError("missing provenance")
            except FullFftProvenanceMissingError as exc:
                raise FreeHarmonicInputError("Rerun post-processing.") from exc

    worker = MissingProvenanceWorker()
    requests: list[str] = []
    failures: list[str] = []
    worker.post_processing_required.connect(requests.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert requests == ["Rerun post-processing."]
    assert failures == []

    class InvalidProvenanceWorker(_CancellableWorker):
        def _execute(self) -> object:
            try:
                raise FullFftProvenanceError("invalid project state")
            except FullFftProvenanceError as exc:
                raise FreeHarmonicInputError("Invalid FullFFT state.") from exc

    invalid_worker = InvalidProvenanceWorker()
    invalid_requests: list[str] = []
    invalid_failures: list[str] = []
    invalid_worker.post_processing_required.connect(invalid_requests.append)
    invalid_worker.failed.connect(invalid_failures.append)

    invalid_worker.run()

    assert invalid_requests == []
    assert invalid_failures == ["Invalid FullFFT state."]


def test_diagnostics_status_points_to_exclusion_review(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(
        qtbot,
        tmp_path,
        diagnostics=("Two project-QC exclusions are active.",),
    )

    assert "Run Analysis" in page.workflow_status.text()
    assert "cohort and input details" in page.workflow_status.text()
    assert "results workbook" in page.workflow_status.text()


def test_real_qthread_inspection_keeps_gui_responsive_and_shuts_down(
    qtbot,
    tmp_path: Path,
) -> None:
    class ThreadedInspectionBackend(_FakeBackend):
        def __init__(self, results_parent: Path) -> None:
            super().__init__(results_parent)
            self.gui_thread_ident = get_ident()
            self.ran_off_gui_thread = False

        def inspect_project(
            self,
            project_root: Path,
            _frequencies,
            *,
            progress,
            cancel_check,
        ) -> ProjectAnalysisOptions:
            self.ran_off_gui_thread = get_ident() != self.gui_thread_ident
            progress(0, 1, "Inspecting project inputs...")
            deadline = time.monotonic() + 0.08
            while time.monotonic() < deadline:
                if cancel_check():
                    raise RuntimeError("Inspection was cancelled unexpectedly.")
                time.sleep(0.005)
            progress(1, 1, "Project inputs are ready.")
            return _options(project_root)

    results_parent = tmp_path / "3 - Statistical Analysis Results" / (
        "Free Harmonic Clustering Analysis"
    )
    results_parent.mkdir(parents=True)
    backend = ThreadedInspectionBackend(results_parent)
    page = FreeHarmonicClusteringPage(
        project_root=tmp_path,
        frequency_snapshot=ProjectFrequencySnapshot(1.2, 6.0),
        backend=backend,
        auto_discover=False,
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)

    heartbeats: list[bool] = []
    heartbeat = QtCore.QTimer(page)
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: heartbeats.append(True))
    heartbeat.start()
    page._begin_project_inspection()

    qtbot.waitUntil(
        lambda: page._options is not None and not page.has_active_work,
        timeout=3_000,
    )
    heartbeat.stop()
    qtbot.waitUntil(lambda: not has_active_operations(), timeout=1_000)

    assert backend.ran_off_gui_thread
    assert len(heartbeats) >= 2
    assert page.independent_condition_combo.count() == 3
    assert page.independent_group_a_combo.count() == 2
    assert page.fixed_highest_combo.count() == 5
    assert not page.progress_bar.isVisible()
    assert page.run_analysis_button.isEnabled()
    assert "Project inputs loaded" in page.workflow_status.text()


def test_paired_condition_guard_invalidates_prepared_state(
    qtbot,
    tmp_path: Path,
) -> None:
    page = _page(qtbot, tmp_path)
    page._on_preparation_completed(_prepared(tmp_path))
    assert page._prepared is not None

    requested_a = page.paired_condition_b_combo.currentData()
    page.paired_condition_a_combo.setCurrentIndex(
        page.paired_condition_b_combo.currentIndex()
    )

    assert page.paired_condition_a_combo.currentData() == requested_a
    assert (
        page.paired_condition_a_combo.currentData()
        != page.paired_condition_b_combo.currentData()
    )
    assert page._prepared is None
    assert page.setup_panel.isVisible()
    assert page.results_panel.isHidden()
    assert "Setup changed" in page.workflow_status.text()


def test_valid_independent_setup_enables_one_click_analysis(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = _page(qtbot, tmp_path)

    # Windows Qt can round-trip str-backed Enum user data as plain strings.
    page.design_combo.setItemData(
        1,
        GuiAnalysisDesign.INDEPENDENT_GROUPS.value,
    )
    page.harmonic_mode_combo.setItemData(
        0,
        GuiHarmonicMode.AUTOMATIC.value,
    )
    page.design_combo.setCurrentIndex(1)

    setup = page._current_setup()
    assert setup.design is GuiAnalysisDesign.INDEPENDENT_GROUPS
    assert setup.condition_a == "Neutral Happy"
    assert setup.group_ids == ("anxious", "non_anxious")
    assert setup.harmonic_mode is GuiHarmonicMode.AUTOMATIC
    assert page._setup_error() is None
    assert page.run_analysis_button.isEnabled()

    started_stages: list[str] = []

    def _record_start(
        _worker: object,
        *,
        stage: str,
        **_kwargs: object,
    ) -> None:
        started_stages.append(stage)

    monkeypatch.setattr(page, "_start_operation", _record_start)
    qtbot.mouseClick(page.run_analysis_button, QtCore.Qt.LeftButton)

    assert started_stages == ["preparation"]
    assert page._continue_to_permutations


def test_successful_preparation_automatically_starts_permutations(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = _page(qtbot, tmp_path)
    prepared = _prepared(tmp_path)
    permutation_starts: list[bool] = []
    monkeypatch.setattr(
        page,
        "_run_permutations",
        lambda: permutation_starts.append(True),
    )
    page._active_stage = "preparation"
    page._continue_to_permutations = True

    page._on_preparation_completed(prepared)
    page._on_operation_thread_finished()

    assert page.setup_panel.isVisible()
    assert page.results_panel.isHidden()
    assert permutation_starts == [True]
    assert not page._continue_to_permutations

    page._active_stage = "preparation"
    page._continue_to_permutations = True
    page._on_operation_cancelled()
    page._on_operation_thread_finished()

    assert permutation_starts == [True]
    assert not page._continue_to_permutations


def test_results_appear_in_compact_single_screen_without_run_metadata(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = _page(qtbot, tmp_path)
    prepared = _prepared(tmp_path)
    page._on_preparation_completed(prepared)

    assert page.setup_panel.isVisible()
    assert page.results_panel.isHidden()
    assert page.run_analysis_button.isEnabled()
    assert page.run_analysis_button.isVisible()
    assert page.run_analysis_button.text() == "Run Analysis"

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

    assert page.setup_panel.isVisible()
    assert page.results_panel.isVisible()
    assert page.run_analysis_button.isVisible()
    assert page.workflow_actions.isVisible()
    assert page.significant_table.rowCount() == 1
    assert page.significant_table.item(0, 4).text() == "0.0043"
    assert "1 significant cluster found" in page.result_status.text()
    assert "interpret it cautiously" in page.result_status.text()
    visible_text = " ".join(
        label.text() for label in page.findChildren(QtWidgets.QLabel)
    )
    assert "Permutations:" not in visible_text
    assert "cluster-forming" not in visible_text
    assert "seed =" not in visible_text
    assert "df =" not in visible_text

    assert not page.refresh_project_context(
        project_root=tmp_path,
        frequency_snapshot=ProjectFrequencySnapshot(1.2, 6.0),
    )
    assert page.results_panel.isVisible()
    assert not page.has_active_work

    page._inspection_failed = True
    retries: list[bool] = []
    begin_project_inspection = page._begin_project_inspection
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
    monkeypatch.setattr(
        page,
        "_begin_project_inspection",
        begin_project_inspection,
    )

    assert page.refresh_project_context(
        project_root=tmp_path,
        frequency_snapshot=None,
    )
    assert page.results_panel.isHidden()
    assert page.setup_panel.isVisible()
    assert not page.run_analysis_button.isEnabled()
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
