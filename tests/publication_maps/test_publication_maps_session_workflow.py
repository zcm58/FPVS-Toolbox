from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image

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
    PublicationSessionControlError,
    SESSION_MODE_COMPARISON,
    publication_session_state,
)
from Tools.Publication_Maps.session_workflow import (
    build_session_panel_sets,
    validate_session_grid_project,
    validate_session_grid_requests,
)
from Tools.Publication_Maps.tool_info import SCALP_MAPS_TOOL_INFO_HTML


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


def _renderable_session_panel_set() -> SimpleNamespace:
    group_ids = ("group_a", "group_b")
    group_labels = {
        "group_a": "Longitudinal Intervention Cohort Group Alpha",
        "group_b": "Longitudinal Matched Comparison Cohort Group Beta",
    }
    session_ids = ("session_a", "session_b")
    session_labels = {
        "session_a": "Baseline Assessment Session With Extended Label",
        "session_b": "Follow-Up Assessment Session With Extended Label",
    }
    panels = {
        (group_id, session_id): SimpleNamespace(
            group_label=group_labels[group_id],
            session_label=session_labels[session_id],
            visit_index=session_index,
            participant_n=3,
            values=(
                SimpleNamespace(
                    electrode="Cz",
                    render_value=float(session_index),
                    is_montage_electrode=True,
                ),
            ),
        )
        for group_id in group_ids
        for session_index, session_id in enumerate(session_ids, start=1)
    }
    differences = {
        group_id: SimpleNamespace(
            group_label=group_labels[group_id],
            comparison_session_label=session_labels["session_b"],
            reference_session_label=session_labels["session_a"],
            paired_n=2,
            values=(
                SimpleNamespace(
                    electrode="Cz",
                    aggregate_difference=1.0,
                    is_montage_electrode=True,
                ),
            ),
        )
        for group_id in group_ids
    }
    return SimpleNamespace(
        condition="Extended Visual Recognition and Attention Condition",
        metric=PublicationMetric.BCA,
        group_ids=group_ids,
        session_ids=session_ids,
        common_vmin=0.0,
        common_vmax=2.0,
        difference_vmin=-1.0,
        difference_vmax=1.0,
        panel=lambda group_id, session_id: panels[(group_id, session_id)],
        paired_difference=lambda group_id: differences[group_id],
    )


def _pdf_media_box_points(path: Path) -> tuple[float, float]:
    match = re.search(
        rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+"
        rb"([0-9.]+)\s+([0-9.]+)\s*\]",
        path.read_bytes(),
    )
    assert match is not None
    x0, y0, x1, y1 = (float(value) for value in match.groups())
    return x1 - x0, y1 - y0


def test_publication_session_state_and_exact_session_filter(tmp_path: Path) -> None:
    index = _repeated_index(tmp_path)
    state = publication_session_state(index)

    assert state.default_mode == SESSION_MODE_COMPARISON
    assert [choice.display_label for choice in state.sessions] == [
        "Luteal phase — Visit 1",
        "Follicular phase — Visit 2",
    ]
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


def test_repeated_session_help_omits_fixed_order_caveat() -> None:
    help_text = " ".join(SCALP_MAPS_TOOL_INFO_HTML.split())

    assert "Descriptive view only" not in help_text
    assert "confounds phase with visit order" not in help_text


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
    default_request = PublicationMapRequest(
        input_root=tmp_path / "excel",
        output_root=tmp_path / "maps",
        conditions=("Faces",),
    )
    assert default_request.export_session_grid_figure is False
    assert default_request.export_paired_session_difference is False

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


@pytest.mark.parametrize(
    ("include_difference", "expected_height_in"),
    ((False, 4.2), (True, 5.9)),
)
def test_session_renderer_repeated_layout_artifact_contract(
    tmp_path: Path,
    monkeypatch,
    include_difference: bool,
    expected_height_in: float,
) -> None:
    test_dpi = 50
    requests = tuple(
        replace(
            request,
            export_paired_session_difference=include_difference,
            export_png=True,
            export_pdf=True,
            png_dpi=test_dpi,
        )
        for request in _session_requests(tmp_path)
    )
    panel_set = _renderable_session_panel_set()
    monkeypatch.setattr(
        session_rendering,
        "build_session_panel_sets",
        lambda *_args, **_kwargs: (panel_set,),
    )

    def draw_test_map(_frame, *, ax, cmap, vlim_override, **_kwargs):
        image = ax.imshow(
            ((0.0, 1.0), (1.0, 0.0)),
            cmap=cmap,
            vmin=vlim_override[0],
            vmax=vlim_override[1],
        )
        ax.set_axis_off()
        return image, ()

    monkeypatch.setattr(session_rendering, "_draw_topomap", draw_test_map)
    real_save = session_rendering._save_figure
    captured_layout: dict[str, object] = {}

    def capture_save(fig, output_path, *, dpi, cancel_check=None) -> None:
        if output_path.suffix.lower() == ".png":
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            map_prefix = session_rendering.REPEATED_SESSION_LAYOUT.map_axis_gid_prefix
            map_axes = sorted(
                (
                    ax
                    for ax in fig.axes
                    if (ax.get_gid() or "").startswith(map_prefix)
                ),
                key=lambda ax: ax.get_gid(),
            )
            header_prefix = (
                session_rendering.REPEATED_SESSION_LAYOUT.column_header_gid_prefix
            )
            headers = sorted(
                (
                    text
                    for text in fig.texts
                    if (text.get_gid() or "").startswith(header_prefix)
                ),
                key=lambda text: text.get_gid(),
            )
            row_label_prefix = (
                session_rendering.REPEATED_SESSION_LAYOUT.row_label_gid_prefix
            )
            row_labels = sorted(
                (
                    text
                    for ax in fig.axes
                    for text in ax.texts
                    if (text.get_gid() or "").startswith(row_label_prefix)
                ),
                key=lambda text: text.get_gid(),
            )
            colorbar_prefix = (
                session_rendering.REPEATED_SESSION_LAYOUT.colorbar_axis_gid_prefix
            )
            colorbar_axes = sorted(
                (
                    ax
                    for ax in fig.axes
                    if (ax.get_gid() or "").startswith(colorbar_prefix)
                ),
                key=lambda ax: ax.get_position().y0,
            )
            dividers = [
                artist
                for artist in fig.artists
                if artist.get_gid()
                == session_rendering.REPEATED_SESSION_LAYOUT.divider_gid
            ]
            grid_frames = [
                artist
                for artist in fig.artists
                if artist.get_gid()
                == session_rendering.REPEATED_SESSION_LAYOUT.grid_frame_gid
            ]
            row_divider_prefix = (
                session_rendering.REPEATED_SESSION_LAYOUT.row_divider_gid_prefix
            )
            row_dividers = sorted(
                (
                    artist
                    for artist in fig.artists
                    if (artist.get_gid() or "").startswith(row_divider_prefix)
                ),
                key=lambda artist: artist.get_gid(),
            )
            divider_x = (
                float(dividers[0].get_xdata()[0]) if len(dividers) == 1 else None
            )
            figure_box = fig.bbox

            def box_tuple(text) -> tuple[float, float, float, float]:
                box = text.get_window_extent(renderer)
                return box.x0, box.y0, box.x1, box.y1

            captured_layout.update(
                texts=tuple(text.get_text() for text in fig.texts),
                has_suptitle=fig._suptitle is not None,
                divider_count=len(dividers),
                divider_x=divider_x,
                divider_y=(
                    tuple(float(value) for value in dividers[0].get_ydata())
                    if len(dividers) == 1
                    else ()
                ),
                grid_frame_count=len(grid_frames),
                grid_frame_bounds=(
                    tuple(float(value) for value in grid_frames[0].get_bbox().bounds)
                    if len(grid_frames) == 1
                    else ()
                ),
                row_divider_count=len(row_dividers),
                row_divider_lines=tuple(
                    (
                        tuple(float(value) for value in divider.get_xdata()),
                        tuple(float(value) for value in divider.get_ydata()),
                    )
                    for divider in row_dividers
                ),
                gutter_left=map_axes[0].get_position().x1,
                gutter_right=map_axes[1].get_position().x0,
                map_axis_count=len(map_axes),
                map_boxes=tuple(
                    (
                        ax.get_window_extent(renderer).x0,
                        ax.get_window_extent(renderer).y0,
                        ax.get_window_extent(renderer).x1,
                        ax.get_window_extent(renderer).y1,
                    )
                    for ax in map_axes
                ),
                colorbar_axis_count=len(colorbar_axes),
                colorbar_left=min(ax.get_position().x0 for ax in colorbar_axes),
                colorbar_boxes=tuple(
                    (
                        ax.get_tightbbox(renderer).x0,
                        ax.get_tightbbox(renderer).y0,
                        ax.get_tightbbox(renderer).x1,
                        ax.get_tightbbox(renderer).y1,
                    )
                    for ax in colorbar_axes
                ),
                canvas=(
                    figure_box.x0,
                    figure_box.y0,
                    figure_box.x1,
                    figure_box.y1,
                ),
                header_boxes=tuple(box_tuple(header) for header in headers),
                header_texts=tuple(header.get_text() for header in headers),
                panel_texts=tuple(ax.title.get_text() for ax in map_axes),
                row_label_boxes=tuple(box_tuple(label) for label in row_labels),
                row_label_texts=tuple(label.get_text() for label in row_labels),
            )
        real_save(
            fig,
            output_path,
            dpi=dpi,
            cancel_check=cancel_check,
        )

    monkeypatch.setattr(session_rendering, "_save_figure", capture_save)

    paths = session_rendering.render_session_grid_figures((), requests)

    png_path = next(path for path in paths if path.suffix == ".png")
    pdf_path = next(path for path in paths if path.suffix == ".pdf")
    with Image.open(png_path) as image:
        assert image.size == (int(6.5 * test_dpi), int(expected_height_in * test_dpi))
        assert image.info["dpi"] == pytest.approx((test_dpi, test_dpi), abs=0.1)
    pdf_width, pdf_height = _pdf_media_box_points(pdf_path)
    assert pdf_width == pytest.approx(6.5 * 72.0)
    assert pdf_height == pytest.approx(expected_height_in * 72.0)
    assert captured_layout["has_suptitle"] is False
    assert captured_layout["map_axis_count"] == (6 if include_difference else 4)
    assert captured_layout["colorbar_axis_count"] == (
        2 if include_difference else 1
    )
    if include_difference:
        lower_colorbar, upper_colorbar = captured_layout["colorbar_boxes"]
        assert lower_colorbar[3] < upper_colorbar[1]
    assert captured_layout["divider_count"] == 1
    assert captured_layout["grid_frame_count"] == 1
    assert captured_layout["row_divider_count"] == (
        2 if include_difference else 1
    )
    assert (
        captured_layout["gutter_left"]
        < captured_layout["divider_x"]
        < captured_layout["gutter_right"]
    )
    assert len(captured_layout["header_boxes"]) == 2
    canvas_left, canvas_bottom, canvas_right, canvas_top = captured_layout["canvas"]
    canvas_width = canvas_right - canvas_left
    canvas_height = canvas_top - canvas_bottom
    frame_x, frame_y, frame_width, frame_height = captured_layout[
        "grid_frame_bounds"
    ]
    frame_left = canvas_left + (frame_x * canvas_width)
    frame_right = frame_left + (frame_width * canvas_width)
    frame_bottom = canvas_bottom + (frame_y * canvas_height)
    frame_top = frame_bottom + (frame_height * canvas_height)
    for box in (*captured_layout["map_boxes"], *captured_layout["colorbar_boxes"]):
        assert canvas_left <= box[0] < box[2] <= canvas_right
        assert canvas_bottom <= box[1] < box[3] <= canvas_top
    assert canvas_left < frame_left < frame_right < canvas_right
    assert canvas_bottom < frame_bottom < frame_top < canvas_top
    assert captured_layout["divider_y"] == pytest.approx(
        (frame_y, frame_y + frame_height)
    )
    divider_pixels = canvas_left + (captured_layout["divider_x"] * canvas_width)
    map_boxes = captured_layout["map_boxes"]
    assert min(box[0] for box in map_boxes) == pytest.approx(frame_left)
    assert max(box[2] for box in map_boxes) == pytest.approx(frame_right)
    assert min(box[1] for box in map_boxes) == pytest.approx(frame_bottom)
    assert max(box[3] for box in map_boxes) == pytest.approx(frame_top)
    assert max(box[2] for box in captured_layout["row_label_boxes"]) < frame_left
    assert min(box[1] for box in captured_layout["header_boxes"]) > frame_top
    colorbar_left = canvas_left + (
        captured_layout["colorbar_left"] * canvas_width
    )
    assert frame_right < colorbar_left
    row_divider_lines = captured_layout["row_divider_lines"]
    for row, (x_values, y_values) in enumerate(row_divider_lines):
        assert x_values == pytest.approx((frame_x, frame_x + frame_width))
        assert y_values[0] == pytest.approx(y_values[1])
        divider_y_pixels = canvas_bottom + (y_values[0] * canvas_height)
        upper_row_boxes = map_boxes[row * 2 : (row + 1) * 2]
        lower_row_boxes = map_boxes[(row + 1) * 2 : (row + 2) * 2]
        assert max(box[3] for box in lower_row_boxes) < divider_y_pixels
        assert divider_y_pixels < min(box[1] for box in upper_row_boxes)
    column_bounds = (
        (frame_left, divider_pixels),
        (divider_pixels, frame_right),
    )
    all_title_boxes = (
        *captured_layout["header_boxes"],
        *captured_layout["row_label_boxes"],
    )
    for left, bottom, right, top in all_title_boxes:
        assert canvas_left <= left < right <= canvas_right
        assert canvas_bottom <= bottom < top <= canvas_top
    for column, header_box in enumerate(captured_layout["header_boxes"]):
        assert column_bounds[column][0] <= header_box[0]
        assert header_box[2] <= column_bounds[column][1]
    def overlaps(first, second) -> bool:
        return (
            min(first[2], second[2]) > max(first[0], second[0])
            and min(first[3], second[3]) > max(first[1], second[1])
        )

    for index, first in enumerate(all_title_boxes):
        for second in all_title_boxes[index + 1 :]:
            assert not overlaps(first, second)
    expected_group_labels = tuple(
        panel_set.panel(group_id, panel_set.session_ids[0]).group_label
        for group_id in panel_set.group_ids
    )
    assert tuple(" ".join(text.split()) for text in captured_layout["header_texts"]) == (
        f"(A) {expected_group_labels[0]}",
        f"(B) {expected_group_labels[1]}",
    )
    normalized_panel_texts = tuple(
        " ".join(text.split()) for text in captured_layout["panel_texts"]
    )
    assert normalized_panel_texts == ("",) * (6 if include_difference else 4)
    expected_row_labels = [
        panel_set.panel(panel_set.group_ids[0], session_id).session_label
        for session_id in panel_set.session_ids
    ]
    if include_difference:
        difference = panel_set.paired_difference(panel_set.group_ids[0])
        expected_row_labels.append(
            f"{difference.comparison_session_label} − "
            f"{difference.reference_session_label}"
        )
    assert tuple(
        " ".join(text.split()) for text in captured_layout["row_label_texts"]
    ) == tuple(" ".join(text.split()) for text in expected_row_labels)
    assert panel_set.condition not in captured_layout["texts"]
    assert panel_set.metric.display_name not in captured_layout["texts"]


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
