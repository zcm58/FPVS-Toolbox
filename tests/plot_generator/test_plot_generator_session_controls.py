from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from Main_App.projects import (
    GroupInfo,
    ProjectDatasetIndex,
    SessionInfo,
    WorkbookRecord,
)
from Tools.Plot_Generator.session_controls import (
    FIXED_ORDER_CAVEAT,
    RepeatedSessionControlError,
    SESSION_MODE_COMPARISON,
    SESSION_MODE_CONDITION,
    repeated_session_control_state,
)
from Tools.Plot_Generator.session_workflow import (
    SessionPlotConfigurationError,
    SessionPlotWorkflowMixin,
    validate_session_plot_selection,
)


def _repeated_index(tmp_path: Path) -> ProjectDatasetIndex:
    groups = {
        "birth_control": GroupInfo(
            group_id="birth_control",
            label="Birth control",
            folder_name="Birth Control",
            raw_input_folder=tmp_path / "raw-bc",
        ),
        "no_birth_control": GroupInfo(
            group_id="no_birth_control",
            label="No birth control",
            folder_name="No Birth Control",
            raw_input_folder=tmp_path / "raw-no-bc",
        ),
    }
    sessions = {
        "luteal": SessionInfo("luteal", "Luteal phase", 1),
        "follicular": SessionInfo("follicular", "Follicular phase", 2),
    }
    records = []
    for participant_id, group_id in (
        ("P01", "birth_control"),
        ("P02", "no_birth_control"),
    ):
        group = groups[group_id]
        for session in sessions.values():
            records.append(
                WorkbookRecord(
                    participant_id=participant_id,
                    condition="Faces",
                    path=(
                        tmp_path
                        / "excel"
                        / "Faces"
                        / group.folder_name
                        / session.session_id
                        / f"{participant_id}.xlsx"
                    ),
                    group_id=group_id,
                    group_label=group.label,
                    observed_layout="condition_group_session",
                    observed_group_folder=group.folder_name,
                    recording_id=f"{participant_id}_{session.session_id}",
                    session_id=session.session_id,
                    session_label=session.label,
                    visit_index=session.visit_index,
                )
            )
    return ProjectDatasetIndex(
        project_root=tmp_path,
        excel_root=tmp_path / "excel",
        scan_root=tmp_path / "excel",
        manifest={"name": "Repeated"},
        groups=groups,
        participants={},
        workbooks=tuple(records),
        excluded_workbooks=(),
        diagnostics=(),
        sessions=sessions,
    )


def test_repeated_session_controls_use_labels_and_visit_order(tmp_path: Path) -> None:
    state = repeated_session_control_state(_repeated_index(tmp_path))

    assert state.repeated is True
    assert state.default_mode == SESSION_MODE_COMPARISON
    assert [choice.display_label for choice in state.sessions] == [
        "Luteal phase — Visit 1",
        "Follicular phase — Visit 2",
    ]
    assert state.caveat == FIXED_ORDER_CAVEAT
    assert state.validate_selection(
        mode=SESSION_MODE_CONDITION,
        single_session_id="luteal",
    ) == ("luteal",)
    assert state.validate_selection(
        mode=SESSION_MODE_COMPARISON,
        reference_session_id="luteal",
        comparison_session_id="follicular",
    ) == ("luteal", "follicular")


def test_repeated_session_controls_reject_missing_recording_identity(
    tmp_path: Path,
) -> None:
    index = _repeated_index(tmp_path)
    broken = replace(index.workbooks[0], recording_id=None)
    index = replace(index, workbooks=(broken, *index.workbooks[1:]))

    with pytest.raises(RepeatedSessionControlError, match="recording_id"):
        repeated_session_control_state(index)


def test_session_worker_selection_requires_complete_group_by_session_cells(
    tmp_path: Path,
) -> None:
    index = _repeated_index(tmp_path)
    selection = validate_session_plot_selection(
        index,
        condition="Faces",
        session_ids=("luteal", "follicular"),
        group_ids=("birth_control", "no_birth_control"),
    )

    assert selection.session_ids == ("luteal", "follicular")
    assert selection.group_ids == ("birth_control", "no_birth_control")
    assert len(selection.records) == 4

    incomplete = replace(
        index,
        workbooks=tuple(
            record
            for record in index.workbooks
            if not (
                record.group_id == "no_birth_control"
                and record.session_id == "follicular"
            )
        ),
    )
    with pytest.raises(SessionPlotConfigurationError, match="missing"):
        validate_session_plot_selection(
            incomplete,
            condition="Faces",
            session_ids=("luteal", "follicular"),
            group_ids=("birth_control", "no_birth_control"),
        )


def test_session_workflow_collects_visits_separately_before_aggregation(
    tmp_path: Path,
) -> None:
    index = _repeated_index(tmp_path)

    class FakeWorker(SessionPlotWorkflowMixin):
        condition = "Faces"
        session_comparison_ids = ("luteal", "follicular")
        session_group_ids = ("birth_control", "no_birth_control")

        def __init__(self) -> None:
            self.collection_sessions: list[str] = []
            self.prepared = None
            self.rendered = None

        def _load_dataset_index(self):
            return index

        def _collect_data(
            self,
            _condition,
            *,
            excel_files,
            offset,
            total_override,
        ):
            assert total_override == 4
            records = [
                record for record in index.workbooks if record.path in excel_files
            ]
            session_id = str(records[0].session_id)
            assert all(record.session_id == session_id for record in records)
            self.collection_sessions.append(session_id)
            values = {
                ("luteal", "P01"): [1.0, 2.0],
                ("follicular", "P01"): [3.0, 5.0],
                ("luteal", "P02"): [10.0, 20.0],
                ("follicular", "P02"): [14.0, 26.0],
            }
            return [1.0, 2.0], {
                record.participant_id.upper(): {
                    "Posterior": values[(session_id, record.participant_id)]
                }
                for record in records
            }

        def _cancellation_checkpoint(self):
            return False

        def _selected_roi_names(self):
            return ("Posterior",)

        def _revalidate_analysis_context_for_output(self):
            return None

        def _prepare_session_source_curves(self, *, frequencies_hz, aggregation):
            self.prepared = (tuple(frequencies_hz), aggregation)

        def _plot_session_comparison(
            self,
            frequencies,
            aggregation,
        ):
            self.rendered = (
                tuple(frequencies),
                aggregation,
            )

    worker = FakeWorker()
    worker._run_session_comparison()

    assert worker.collection_sessions == ["luteal", "follicular"]
    assert worker.prepared is not None
    aggregation = worker.prepared[1]
    assert aggregation.cell(
        "birth_control", "follicular", "Posterior"
    ).plotted_values == pytest.approx((3.0, 5.0))
    assert aggregation.paired_difference(
        "no_birth_control", "Posterior"
    ).plotted_values == pytest.approx((4.0, 6.0))
    assert worker.rendered[:1] == ((1.0, 2.0),)
