from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.projects import (
    GroupInfo,
    ProjectDatasetIndex,
    SessionInfo,
    WorkbookRecord,
)
from Tools.Publication_Maps.excel_inputs import select_publication_workbooks
from Tools.Publication_Maps.models import (
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps import session_workflow
from Tools.Publication_Maps import session_rendering
from Tools.Publication_Maps import worker as publication_worker
from Tools.Publication_Maps.generation_outcome import PublicationMapsOutcomeStatus
from Tools.Publication_Maps.session_controls import (
    FIXED_ORDER_CAVEAT,
    PublicationSessionControlError,
    SESSION_MODE_COMPARISON,
    publication_session_state,
)
from Tools.Publication_Maps.session_workflow import (
    build_session_panel_sets,
    validate_session_grid_project,
    validate_session_grid_requests,
)


def _repeated_index(
    tmp_path: Path,
    *,
    conditions: tuple[str, ...] = ("Faces",),
) -> ProjectDatasetIndex:
    groups = {
        "birth_control": GroupInfo(
            "birth_control",
            "Birth control",
            "Birth Control",
            tmp_path / "raw-bc",
        ),
        "no_birth_control": GroupInfo(
            "no_birth_control",
            "No birth control",
            "No Birth Control",
            tmp_path / "raw-no-bc",
        ),
    }
    sessions = {
        "luteal": SessionInfo("luteal", "Luteal phase", 1),
        "follicular": SessionInfo("follicular", "Follicular phase", 2),
    }
    records = tuple(
        WorkbookRecord(
            participant_id=participant_id,
            condition=condition,
            path=(
                tmp_path
                / "excel"
                / condition
                / groups[group_id].folder_name
                / session.session_id
                / f"{participant_id}.xlsx"
            ),
            group_id=group_id,
            group_label=groups[group_id].label,
            observed_layout="condition_group_session",
            observed_group_folder=groups[group_id].folder_name,
            recording_id=f"{participant_id}_{session.session_id}",
            session_id=session.session_id,
            session_label=session.label,
            visit_index=session.visit_index,
        )
        for condition in conditions
        for participant_id, group_id in (
            ("P01", "birth_control"),
            ("P02", "no_birth_control"),
        )
        for session in sessions.values()
    )
    return ProjectDatasetIndex(
        project_root=tmp_path,
        excel_root=tmp_path / "excel",
        scan_root=tmp_path / "excel",
        manifest={"name": "Repeated"},
        groups=groups,
        participants={},
        workbooks=records,
        excluded_workbooks=(),
        diagnostics=(),
        sessions=sessions,
    )


def _session_requests(
    tmp_path: Path,
    *,
    conditions: tuple[str, ...] = ("Faces",),
) -> tuple[PublicationMapRequest, ...]:
    return tuple(
        PublicationMapRequest(
            input_root=tmp_path / "excel",
            output_root=tmp_path / "maps",
            conditions=conditions,
            project_root=tmp_path,
            group_id=group_id,
            group_label=group_label,
            group_folder=group_folder,
            session_ids=("luteal", "follicular"),
            export_session_grid_figure=True,
            session_comparison_ids=("luteal", "follicular"),
            export_paired_session_difference=True,
        )
        for group_id, group_label, group_folder in (
            ("birth_control", "Birth control", "Birth Control"),
            ("no_birth_control", "No birth control", "No Birth Control"),
        )
    )


def test_publication_session_state_and_exact_session_filter(tmp_path: Path) -> None:
    index = _repeated_index(tmp_path)
    state = publication_session_state(index)

    assert state.default_mode == SESSION_MODE_COMPARISON
    assert [choice.display_label for choice in state.sessions] == [
        "Luteal phase — Visit 1",
        "Follicular phase — Visit 2",
    ]
    assert state.caveat == FIXED_ORDER_CAVEAT

    entries, group = select_publication_workbooks(
        index,
        ("Faces",),
        group_id="birth_control",
        session_ids=("follicular",),
    )
    assert group is not None and group.group_id == "birth_control"
    assert len(entries) == 1
    assert entries[0].path.name == "P01.xlsx"
    assert "follicular" in entries[0].path.parts


def test_publication_session_state_rejects_unstable_group(tmp_path: Path) -> None:
    index = _repeated_index(tmp_path)
    changed = replace(
        index.workbooks[1],
        group_id="no_birth_control",
        group_label="No birth control",
    )
    index = replace(index, workbooks=(index.workbooks[0], changed, *index.workbooks[2:]))

    with pytest.raises(PublicationSessionControlError, match="changes group"):
        publication_session_state(index)


def test_session_grid_request_contract_is_explicit_and_legacy_defaults_are_off(
    tmp_path: Path,
) -> None:
    requests = _session_requests(tmp_path)

    assert validate_session_grid_requests(requests) is True
    all_condition_requests = tuple(
        replace(request, conditions=("Faces", "Objects"))
        for request in requests
    )
    assert validate_session_grid_requests(all_condition_requests) is True
    assert PublicationMapRequest(
        input_root=tmp_path / "excel",
        output_root=tmp_path / "maps",
        conditions=("Faces",),
    ).export_session_grid_figure is False

    duplicate_sessions = tuple(
        replace(
            request,
            session_ids=("luteal", "luteal"),
            session_comparison_ids=("luteal", "luteal"),
        )
        for request in requests
    )
    with pytest.raises(ValueError, match="distinct canonical session"):
        validate_session_grid_requests(duplicate_sessions)

    mismatched_conditions = (
        all_condition_requests[0],
        replace(all_condition_requests[1], conditions=("Faces",)),
    )
    with pytest.raises(ValueError, match="same ordered conditions"):
        validate_session_grid_requests(mismatched_conditions)


def test_session_panel_workflow_combines_group_results_without_pooling_visits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conditions = ("Faces", "Objects")
    index = _repeated_index(tmp_path, conditions=conditions)
    requests = _session_requests(tmp_path, conditions=conditions)
    monkeypatch.setattr(
        session_workflow,
        "load_publication_dataset_index",
        lambda *_args, **_kwargs: index,
    )
    totals = {
        "P01_luteal": 1.0,
        "P01_follicular": 3.0,
        "P02_luteal": 10.0,
        "P02_follicular": 14.0,
    }
    results = []
    for request in requests:
        rows = []
        for record in index.workbooks:
            if record.group_id != request.group_id:
                continue
            for harmonic in (1.2, 2.4):
                rows.append(
                    {
                        "condition": record.condition,
                        "group_id": record.group_id,
                        "subject_id": record.participant_id,
                        "workbook_path": str(record.path),
                        "electrode": "Cz",
                        "is_montage_electrode": True,
                        "metric": PublicationMetric.BCA.value,
                        "harmonic_hz": harmonic,
                        "value": (
                            totals[str(record.recording_id)]
                            * (10.0 if record.condition == "Objects" else 1.0)
                            / 2.0
                        ),
                    }
                )
        results.append(
            PublicationMapResult(
                long_values=pd.DataFrame(rows),
                grand_average_values=pd.DataFrame(),
                selected_harmonics_hz=(1.2, 2.4),
                selection_metadata={"selection_fingerprint": "same-selection"},
                qc_provenance={"applied_exclusions_sha256": "same-qc"},
                group_id=request.group_id,
                group_label=request.group_label,
                group_folder=request.group_folder,
            )
        )

    cancellation_checkpoints: list[None] = []
    panel_sets = build_session_panel_sets(
        results,
        requests,
        cancel_check=lambda: cancellation_checkpoints.append(None),
    )

    assert [panel_set.condition for panel_set in panel_sets] == [
        "Faces",
        "Objects",
    ]
    panel_set = panel_sets[0]
    assert panel_set.group_ids == ("birth_control", "no_birth_control")
    assert panel_set.session_ids == ("luteal", "follicular")
    assert panel_set.panel("birth_control", "luteal").participant_n == 1
    difference = panel_set.paired_difference("no_birth_control")
    assert difference.paired_n == 1
    assert difference.values[0].aggregate_difference == pytest.approx(4.0)
    objects_panel_set = panel_sets[1]
    assert objects_panel_set.common_vmin == pytest.approx(10.0)
    assert objects_panel_set.common_vmax == pytest.approx(140.0)
    assert objects_panel_set.difference_vmin == pytest.approx(-40.0)
    assert objects_panel_set.difference_vmax == pytest.approx(40.0)
    assert len(cancellation_checkpoints) >= 4


def test_session_grid_project_requires_every_selected_condition_cell(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conditions = ("Faces", "Objects")
    index = _repeated_index(tmp_path, conditions=conditions)
    incomplete = replace(
        index,
        workbooks=tuple(
            record
            for record in index.workbooks
            if not (
                record.condition == "Objects"
                and record.group_id == "no_birth_control"
                and record.session_id == "follicular"
            )
        ),
    )
    monkeypatch.setattr(
        session_workflow,
        "load_publication_dataset_index",
        lambda *_args, **_kwargs: incomplete,
    )

    with pytest.raises(
        PublicationMapInputError,
        match="Objects × no_birth_control × follicular",
    ):
        validate_session_grid_project(
            _session_requests(tmp_path, conditions=conditions)
        )


def test_session_renderer_queues_each_selected_condition_output_pair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requests = _session_requests(
        tmp_path,
        conditions=("Faces", "Objects"),
    )
    panel_sets = tuple(
        SimpleNamespace(
            condition=condition,
            metric=PublicationMetric.BCA,
            group_ids=("birth_control", "no_birth_control"),
        )
        for condition in ("Faces", "Objects")
    )
    rendered: list[tuple[str, str]] = []

    class FakeTransaction:
        def ensure_request_target(self, _request) -> None:
            return None

        def stage_path(self, final_path: Path) -> Path:
            return tmp_path / "staged" / final_path.name

    monkeypatch.setattr(
        session_rendering,
        "build_session_panel_sets",
        lambda *_args, **_kwargs: panel_sets,
    )
    monkeypatch.setattr(
        session_rendering,
        "_render_session_panel_set",
        lambda panel_set, _request, *, output_path, cancel_check: rendered.append(
            (panel_set.condition, output_path.suffix)
        ),
    )

    paths = session_rendering.render_session_grid_figures(
        (),
        requests,
        transaction=FakeTransaction(),
    )

    assert rendered == [
        ("Faces", ".png"),
        ("Faces", ".pdf"),
        ("Objects", ".png"),
        ("Objects", ".pdf"),
    ]
    assert [path.name for path in paths] == [
        "Faces_birth_control_and_no_birth_control_bca_session_grid.png",
        "Faces_birth_control_and_no_birth_control_bca_session_grid.pdf",
        "Objects_birth_control_and_no_birth_control_bca_session_grid.png",
        "Objects_birth_control_and_no_birth_control_bca_session_grid.pdf",
    ]


def test_worker_stages_all_selected_session_grids_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requests = _session_requests(
        tmp_path,
        conditions=("Faces", "Objects"),
    )
    built_results = [
        PublicationMapResult(
            long_values=pd.DataFrame(),
            grand_average_values=pd.DataFrame(),
            group_id=request.group_id,
            group_label=request.group_label,
            group_folder=request.group_folder,
        )
        for request in requests
    ]
    result_iter = iter(built_results)

    class FakeTransaction:
        def __init__(self, _request) -> None:
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return None

        def ensure_request_target(self, _request) -> None:
            return None

        def commit(self, *, cancel_check) -> None:
            cancel_check()
            self.committed = True

    monkeypatch.setattr(
        publication_worker,
        "validate_session_grid_project",
        lambda _requests: None,
    )
    monkeypatch.setattr(
        publication_worker,
        "PublicationArtifactTransaction",
        FakeTransaction,
    )
    monkeypatch.setattr(
        publication_worker,
        "build_publication_map_result",
        lambda _request, **_kwargs: next(result_iter),
    )
    monkeypatch.setattr(
        publication_worker,
        "render_publication_figures",
        lambda *_args, **_kwargs: pytest.fail(
            "ordinary group figures must not render in session-grid mode"
        ),
    )
    rendered_conditions: list[tuple[tuple[str, ...], ...]] = []
    monkeypatch.setattr(
        publication_worker,
        "render_session_grid_figures",
        lambda _results, rendered_requests, **_kwargs: (
            rendered_conditions.append(
                tuple(request.conditions for request in rendered_requests)
            )
            or [
                tmp_path / "maps" / "Faces_bca_session_grid.png",
                tmp_path / "maps" / "Faces_bca_session_grid.pdf",
                tmp_path / "maps" / "Objects_bca_session_grid.png",
                tmp_path / "maps" / "Objects_bca_session_grid.pdf",
            ]
        ),
    )
    monkeypatch.setattr(
        publication_worker,
        "verify_publication_workbooks_unchanged",
        lambda *_args, **_kwargs: None,
    )

    worker = publication_worker.PublicationMapsWorker(requests)
    worker.run()

    assert worker.outcome is not None
    assert worker.outcome.status is PublicationMapsOutcomeStatus.SUCCESS
    assert worker.outcome.results[0] is built_results[0]
    assert worker.outcome.results[1] is built_results[1]
    assert rendered_conditions == [
        (("Faces", "Objects"), ("Faces", "Objects")),
    ]
    assert [path.suffix for path in worker.outcome.batch_figure_paths] == [
        ".png",
        ".pdf",
        ".png",
        ".pdf",
    ]
