from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
import pytest

from Main_App.projects import GroupConfigurationError
from Tools.Publication_Maps.generation_outcome import (
    PublicationMapGenerationCancelled,
    PublicationMapsOutcomeStatus,
)
from Tools.Publication_Maps.models import (
    ColorBounds,
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
    WorkbookEntry,
)
from Tools.Publication_Maps.output_contract import (
    PublicationArtifactTransaction,
    request_output_root,
)
from Tools.Publication_Maps.rendering import (
    MULTI_GROUP_LAYOUT_STYLE,
    PAIRED_MAP_FIGSIZE,
    _assert_unique_figure_stems,
    _group_comparison_titles,
    _paired_vlim,
    _render_combined_paired_topomap,
    render_group_comparison_figures,
    validate_group_comparison_project_groups,
    validate_group_comparison_requests,
)
from Tools.Publication_Maps.scalp_io import (
    InsufficientSensorCoverageError,
    align_render_values,
)
from Tools.Publication_Maps.worker import PublicationMapsWorker


class Cancelled(RuntimeError):
    pass


@pytest.mark.parametrize("paired", [False, True])
def test_lossy_condition_filename_collision_is_rejected(paired: bool) -> None:
    conditions = (
        ("A B", "X Y", "A+B", "X+Y")
        if paired
        else ("A B", "A+B")
    )
    grand = pd.DataFrame(
        {
            "condition": [*conditions],
            "metric": [PublicationMetric.BCA.value] * len(conditions),
            "map_label": ["BCA significant-harmonic sum"] * len(conditions),
        }
    )
    result = PublicationMapResult(
        long_values=pd.DataFrame(),
        grand_average_values=grand,
    )
    request = PublicationMapRequest(
        input_root=Path("input"),
        output_root=Path("output"),
        conditions=conditions,
        metrics=(PublicationMetric.BCA,),
        export_paired_figures=paired,
        paired_conditions=(),
    )

    with pytest.raises(PublicationMapInputError, match="output names collide"):
        _assert_unique_figure_stems(result, request)


def test_paired_condition_components_cannot_form_the_same_raw_stem() -> None:
    conditions = ("A_and_B", "C", "A", "B_and_C")
    result = PublicationMapResult(
        long_values=pd.DataFrame(),
        grand_average_values=pd.DataFrame(
            {
                "condition": conditions,
                "metric": [PublicationMetric.BCA.value] * len(conditions),
                "map_label": ["BCA significant-harmonic sum"] * len(conditions),
            }
        ),
    )
    request = PublicationMapRequest(
        input_root=Path("input"),
        output_root=Path("output"),
        conditions=conditions,
        metrics=(PublicationMetric.BCA,),
        export_paired_figures=True,
    )

    with pytest.raises(PublicationMapInputError, match="output names collide"):
        _assert_unique_figure_stems(result, request)


@pytest.mark.parametrize("montage", ["biosemi64", "GSN-HydroCel-128", "GSN-HydroCel-256"])
def test_figure_electrodes_are_dots_without_channel_names(montage: str) -> None:
    import matplotlib
    from matplotlib.figure import Figure
    import mne

    from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry
    from Tools.Publication_Maps.rendering import _draw_topomap
    from Tools.Publication_Maps.scalp_io import recorded_map_geometry

    channels = mne.channels.make_standard_montage(montage).ch_names
    geometry = None
    if montage != "biosemi64":
        raw = mne.io.RawArray(np.zeros((len(channels), 4)), mne.create_info(channels, 100, "eeg"), verbose=False)
        identity = attach_raw_recorded_geometry(
            raw, montage_id=montage, template_montage=montage, hardware_platform="egi",
        )
        geometry = recorded_map_geometry(identity, source_id="synthetic-recording")
    values = pd.DataFrame({"electrode": channels, "render_value": np.linspace(0, 1, len(channels))})
    figure = Figure(figsize=(5, 3))
    top, paired = figure.subplots(1, 2)
    for view, ax in (("2d", top), ("3d", paired)):
        _draw_topomap(
            values, geometry=geometry, ax=ax, metric=PublicationMetric.BCA, cmap=matplotlib.colormaps["viridis"],
            bounds=ColorBounds(), scalp_view=view,
        )

    assert len(top.collections[0].get_offsets()) == len(channels)
    assert not top.texts
    assert len(paired.child_axes) == 2
    for child, view in zip(paired.child_axes, ("Front", "Back"), strict=True):
        assert 0 < len(child.collections[0].get_offsets()) < len(channels)
        assert [text.get_text() for text in child.texts] == [view]


def test_alignment_omits_missing_sensors_without_zero_fill() -> None:
    values = pd.DataFrame(
        {
            "electrode": ["O1", "O2", "Fz", "F3", "Cz"],
            "render_value": [1.0, -2.0, 3.0, 4.0, np.nan],
        }
    )

    data, info, missing_count, diagnostics = align_render_values(values)

    assert dict(zip(info.ch_names, data)) == {
        "F3": 4.0,
        "O1": 1.0,
        "Fz": 3.0,
        "O2": -2.0,
    }
    assert 0.0 not in data
    assert missing_count == 60
    assert any("Non-finite" in diagnostic.message for diagnostic in diagnostics)
    assert any("omitted" in diagnostic.message for diagnostic in diagnostics)


@pytest.mark.parametrize("compact", (False, True))
def test_combined_projections_share_electrodes_palette_and_scale(compact, monkeypatch):
    from matplotlib.figure import Figure
    from Tools.Publication_Maps import rendering, scalp_surface

    calls = []
    draw_surface = scalp_surface.draw_scalp_surface
    draw_top = rendering._plot_topomap_compat

    def back(ax, data, info, *, view, cmap, norm):
        calls.append((view, data, info, cmap, (norm.vmin, norm.vmax)))
        draw_surface(ax, data, info, view=view, cmap=cmap, norm=norm)

    def top(*, data, info, ax, cmap, vlim):
        calls.append(("top", data, info, cmap, vlim))
        return draw_top(data=data, info=info, ax=ax, cmap=cmap, vlim=vlim)

    monkeypatch.setattr(scalp_surface, "draw_scalp_surface", back)
    monkeypatch.setattr(rendering, "_plot_topomap_compat", top)
    ax = Figure(figsize=(3, 3)).subplots()
    frame = pd.DataFrame({"electrode": ["O1", "O2", "Pz", "F3", "F4"], "render_value": [1, 2, 1.25, 1.5, .6]})
    cmap = rendering.colormap_for_metric(PublicationMetric.BCA, scalp_view="3d_2d")
    mappable, missing = rendering._draw_topomap(
        frame, ax=ax, metric=PublicationMetric.BCA, cmap=cmap, bounds=ColorBounds(), vlim_override=(0, 3),
        scalp_view="3d_2d", compact=compact,
    )
    assert [call[0] for call in calls] == ["back", "top"]
    assert calls[0][1] is calls[1][1] and calls[0][2] is calls[1][2]
    assert calls[0][3] is calls[1][3] is mappable.cmap
    assert calls[0][4] == calls[1][4] == mappable.get_clim() == (0, 3)
    assert missing == 59
    assert [child.texts[0].get_text() for child in ax.child_axes] == ["3D back · Sibson", "2D top · Cubic"]
    assert len({rendering.figure_stem("Faces", view) for view in ("2d", "3d", "3d_2d")}) == 3


def test_alignment_rejects_fewer_than_four_finite_sensors() -> None:
    values = pd.DataFrame(
        {
            "electrode": ["O1", "O2", "Fz", "F3"],
            "render_value": [1.0, 2.0, 3.0, np.nan],
        }
    )

    with pytest.raises(
        InsufficientSensorCoverageError,
        match="at least 4 finite, non-collinear",
    ):
        align_render_values(values)


def test_group_output_root_requires_canonical_safe_folder(tmp_path: Path) -> None:
    base = tmp_path / "4 - Scalp Maps"
    request = _request(tmp_path, base, group_id="control", group_folder="Control")

    assert request_output_root(request) == (base / "Control").resolve()

    with pytest.raises(ValueError, match="canonical project group folder"):
        request_output_root(_request(tmp_path, base, group_id="control"))
    with pytest.raises(GroupConfigurationError):
        request_output_root(
            _request(
                tmp_path,
                base,
                group_id="control",
                group_folder="../escape",
            )
        )


def test_output_root_cannot_contaminate_processed_excel_tree(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    input_root = project_root / "1 - Excel Data Files"
    input_root.mkdir(parents=True)
    request = PublicationMapRequest(
        input_root=input_root,
        output_root=input_root / "Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
    )

    with pytest.raises(ValueError, match="outside the Excel data tree"):
        PublicationArtifactTransaction(request)


@pytest.mark.parametrize("create_before_render", [False, True])
def test_publication_preserves_directory_named_like_a_figure(tmp_path: Path, create_before_render) -> None:
    base = tmp_path / "maps"
    prior = base / "faces.pdf"
    directory = base / "faces.png"
    base.mkdir()
    def create_directory():
        directory.mkdir()
        (directory / "notes.txt").write_text("keep", encoding="utf-8")

    if create_before_render:
        create_directory()
    prior.write_bytes(b"prior figure")

    with pytest.raises(OSError, match="directory"):
        with PublicationArtifactTransaction(_request(tmp_path, base)) as transaction:
            transaction.stage_path(prior).write_bytes(b"new PDF")
            transaction.stage_path(directory).write_bytes(b"new PNG")
            if not create_before_render:
                create_directory()
            transaction.commit()

    assert (directory / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert prior.read_bytes() == b"prior figure"


def test_failed_restore_preserves_backup_and_reports_recovery_folder(tmp_path, monkeypatch):
    base = tmp_path / "maps"
    base.mkdir()
    prior = base / "faces.pdf"
    prior.write_bytes(b"old PDF")
    replace = os.replace

    def simulate_file_locks(source, destination):
        if destination == base / "faces.png" or (source.parent.name == "previous" and destination == prior):
            raise PermissionError("file locked")
        replace(source, destination)

    with pytest.raises(OSError, match="Recovery files") as error:
        with PublicationArtifactTransaction(_request(tmp_path, base)) as transaction:
            transaction.stage_path(prior).write_bytes(b"new PDF")
            transaction.stage_path(base / "faces.png").write_bytes(b"new PNG")
            monkeypatch.setattr(os, "replace", simulate_file_locks)
            transaction.commit()

    backup, = base.glob(".scalp-maps-stage-*/previous/faces.pdf")
    assert backup.read_bytes() == b"old PDF"
    assert str(backup.parent.parent) in str(error.value)


@pytest.mark.parametrize("cancel_on_call", (3, 4))
def test_all_group_transaction_rolls_back_on_commit_cancellation(
    tmp_path: Path,
    cancel_on_call: int,
) -> None:
    base = tmp_path / "4 - Scalp Maps"
    control = _request(
        tmp_path,
        base,
        group_id="control",
        group_folder="Control",
    )
    clinical = _request(
        tmp_path,
        base,
        group_id="clinical",
        group_folder="Clinical",
    )
    control_final = request_output_root(control) / "artifact.txt"
    clinical_final = request_output_root(clinical) / "artifact.txt"
    control_final.parent.mkdir(parents=True)
    control_final.write_text("previous-control", encoding="utf-8")
    calls = 0

    def cancel_check() -> None:
        nonlocal calls
        calls += 1
        if calls == cancel_on_call:
            raise Cancelled("cancelled")

    with pytest.raises(Cancelled, match="cancelled"):
        with PublicationArtifactTransaction(control) as transaction:
            transaction.stage_path(control_final).write_text(
                "new-control",
                encoding="utf-8",
            )
            transaction.stage_path(clinical_final).write_text(
                "new-clinical",
                encoding="utf-8",
            )
            transaction.commit(cancel_check=cancel_check)

    assert control_final.read_text(encoding="utf-8") == "previous-control"
    assert not clinical_final.exists()
    assert not list(base.glob(".scalp-maps-stage-*"))


def test_all_group_transaction_publishes_one_complete_batch(tmp_path: Path) -> None:
    base = tmp_path / "4 - Scalp Maps"
    control = _request(
        tmp_path,
        base,
        group_id="control",
        group_folder="Control",
    )
    clinical = _request(
        tmp_path,
        base,
        group_id="clinical",
        group_folder="Clinical",
    )
    control_final = request_output_root(control) / "artifact.txt"
    clinical_final = request_output_root(clinical) / "artifact.txt"

    with PublicationArtifactTransaction(control) as transaction:
        transaction.stage_path(control_final).write_text("control", encoding="utf-8")
        transaction.stage_path(clinical_final).write_text("clinical", encoding="utf-8")
        published = transaction.commit()

    assert set(published) == {control_final, clinical_final}
    assert control_final.read_text(encoding="utf-8") == "control"
    assert clinical_final.read_text(encoding="utf-8") == "clinical"
    assert not list(base.glob(".scalp-maps-stage-*"))


def test_committed_outputs_survive_nonfatal_stage_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = tmp_path / "4 - Scalp Maps"
    request = _request(tmp_path, base)
    final = base / "artifact.txt"
    transaction = PublicationArtifactTransaction(request)
    transaction.stage_path(final).write_text("published", encoding="utf-8")
    real_cleanup = transaction._cleanup_stage

    def fail_cleanup() -> None:
        raise PermissionError("stage directory is temporarily locked")

    monkeypatch.setattr(transaction, "_cleanup_stage", fail_cleanup)
    with caplog.at_level(
        logging.WARNING,
        logger="Tools.Publication_Maps.output_contract",
    ):
        published = transaction.commit()
    monkeypatch.setattr(transaction, "_cleanup_stage", real_cleanup)
    transaction._cleanup_stage()

    assert published == (final.resolve(),)
    assert final.read_text(encoding="utf-8") == "published"
    assert "could not remove staging directory" in caplog.text


def test_abort_cleanup_failure_does_not_mask_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = tmp_path / "4 - Scalp Maps"
    request = _request(tmp_path, base)
    transaction = PublicationArtifactTransaction(request)
    staged = transaction.stage_path(base / "artifact.txt")
    staged.write_text("not-published", encoding="utf-8")
    real_cleanup = transaction._cleanup_stage

    def fail_cleanup() -> None:
        raise PermissionError("stage directory is temporarily locked")

    monkeypatch.setattr(transaction, "_cleanup_stage", fail_cleanup)
    with (
        caplog.at_level(
            logging.WARNING,
            logger="Tools.Publication_Maps.output_contract",
        ),
        pytest.raises(PublicationMapGenerationCancelled, match="cancel now"),
    ):
        with transaction:
            raise PublicationMapGenerationCancelled("cancel now")

    monkeypatch.setattr(transaction, "_cleanup_stage", real_cleanup)
    transaction._cleanup_stage()

    assert not (base / "artifact.txt").exists()
    assert "could not remove staging directory" in caplog.text
    assert "after abort" in caplog.text


def test_worker_rejects_source_changed_after_render_and_aborts_figure_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    source = (
        project_root
        / "1 - Excel Data Files"
        / "Faces"
        / "P01_Faces_Results.xlsx"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bytes read by backend")
    result = _result_with_workbook_snapshot(source)
    output_root = project_root / "4 - Scalp Maps"
    request = _request(project_root, output_root)
    final_figure = output_root / "Faces_bca.png"

    def fake_build(_request, *, cancel_check):
        cancel_check()
        return result

    def fake_render(_result, _request, *, cancel_check, transaction):
        cancel_check()
        staged = transaction.stage_path(final_figure)
        staged.write_bytes(b"complete staged PNG")
        source.write_bytes(b"changed after backend read and rendering")
        return [final_figure]

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.render_publication_figures",
        fake_render,
    )
    worker = PublicationMapsWorker(request)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.ERROR
    assert "changed while Scalp Maps data were being read" in finished[0].message
    assert not final_figure.exists()
    assert not list(output_root.glob(".scalp-maps-stage-*"))


def test_two_group_comparison_renders_at_base_with_shared_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    output_root = project_root / "4 - Scalp Maps"
    requests = _group_comparison_requests(project_root, output_root)
    clinical = _comparison_result("clinical", "Clinical", scale=10.0)
    control = _comparison_result("control", "Control", scale=1.0)
    captured_vlim: list[tuple[float, float]] = []
    captured_titles: list[tuple[str, str, str]] = []
    captured_layout_styles: list[object] = []

    from Tools.Publication_Maps import rendering as publication_rendering

    real_render = publication_rendering._render_paired_topomap

    def capture_render(first_values, second_values, **kwargs) -> None:
        captured_titles.append(
            (
                kwargs["first_title"],
                kwargs["second_title"],
                kwargs["figure_title"],
            )
        )
        captured_vlim.append(
            _paired_vlim(
                first_values,
                second_values,
                metric=kwargs["metric"],
                bounds=kwargs["bounds"],
            )
        )
        captured_layout_styles.append(kwargs["layout_style"])
        real_render(first_values, second_values, **kwargs)

    monkeypatch.setattr(
        publication_rendering,
        "_render_paired_topomap",
        capture_render,
    )

    paths = render_group_comparison_figures(
        (clinical, control),
        requests,
    )

    assert paths == [
        (output_root / "Faces_clinical_and_control_bca_group_comparison.png").resolve()
    ]
    assert captured_vlim == [(0.0, 40.0)]
    assert captured_titles == [("Clinical", "Control", "Faces")]
    assert captured_layout_styles == [MULTI_GROUP_LAYOUT_STYLE]
    assert not (output_root / "Control").exists()
    assert not (output_root / "Clinical").exists()
    with Image.open(paths[0]) as image:
        assert image.width == int(PAIRED_MAP_FIGSIZE[0] * requests[0].png_dpi)
        assert image.height == int(PAIRED_MAP_FIGSIZE[1] * requests[0].png_dpi)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("one_request", "exactly two"),
        ("two_conditions", "exactly one selected condition"),
        ("duplicate_id", "two distinct canonical group IDs"),
        ("mismatched_ids", "must match the ordered canonical"),
        ("paired", "cannot be combined with paired-condition"),
    ),
)
def test_two_group_comparison_rejects_non_exact_batch_modes(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    requests = list(
        _group_comparison_requests(
            tmp_path / "Project",
            tmp_path / "Project" / "4 - Scalp Maps",
        )
    )
    if mutation == "one_request":
        requests = requests[:1]
    elif mutation == "two_conditions":
        requests = [
            dataclasses.replace(request, conditions=("Faces", "Objects"))
            for request in requests
        ]
    elif mutation == "duplicate_id":
        requests[1] = dataclasses.replace(
            requests[1],
            group_id="clinical",
        )
    elif mutation == "mismatched_ids":
        requests = [
            dataclasses.replace(
                request,
                group_comparison_ids=("control", "clinical"),
            )
            for request in requests
        ]
    else:
        requests = [
            dataclasses.replace(
                request,
                export_paired_figures=True,
                paired_conditions=("Faces", "Objects"),
            )
            for request in requests
        ]

    with pytest.raises(ValueError, match=message):
        validate_group_comparison_requests(requests)


def test_two_group_comparison_rejects_project_with_third_canonical_group(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    requests = _group_comparison_requests(
        project_root,
        project_root / "4 - Scalp Maps",
    )
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["pilot"] = {
        "label": "Pilot",
        "folder_name": "Pilot",
        "raw_input_folder": "Raw/Pilot",
    }
    manifest["participants"]["P03"] = {"group_id": "pilot"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        PublicationMapInputError,
        match="exactly two canonical groups",
    ):
        validate_group_comparison_project_groups(requests)


def test_worker_comparison_mode_publishes_only_batch_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    output_root = project_root / "4 - Scalp Maps"
    requests = _group_comparison_requests(project_root, output_root)
    results = {
        "clinical": _comparison_result("clinical", "Clinical", scale=10.0),
        "control": _comparison_result("control", "Control", scale=1.0),
    }
    comparison_figure = (
        output_root / "Faces_clinical_and_control_bca_group_comparison.png"
    ).resolve()
    calls: list[str] = []

    def fake_build(request, *, cancel_check):
        cancel_check()
        calls.append(f"build:{request.group_id}")
        return results[str(request.group_id)]

    def reject_individual_artifact(*_args, **_kwargs):
        pytest.fail("Comparison-only mode must not publish per-group artifacts.")

    def fake_comparison_render(
        seen_results,
        seen_requests,
        *,
        cancel_check,
        transaction,
        _project_groups_validated,
    ):
        cancel_check()
        assert tuple(seen_results) == (
            results["clinical"],
            results["control"],
        )
        assert tuple(request.group_id for request in seen_requests) == (
            "clinical",
            "control",
        )
        assert transaction is not None
        assert _project_groups_validated
        calls.append("comparison:figure")
        return [comparison_figure]

    def fake_verify(workbooks, *, cancel_check):
        cancel_check()
        assert workbooks == ()
        calls.append("verify")

    class FakeTransaction:
        def __init__(self, request) -> None:
            assert request is requests[0]

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def ensure_request_target(self, _request) -> None:
            return None

        def commit(self, *, cancel_check) -> None:
            cancel_check()
            calls.append("commit")

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.render_publication_figures",
        reject_individual_artifact,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.render_group_comparison_figures",
        fake_comparison_render,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.verify_publication_workbooks_unchanged",
        fake_verify,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.PublicationArtifactTransaction",
        FakeTransaction,
    )
    worker = PublicationMapsWorker(requests)
    progress: list[int] = []
    finished: list[object] = []
    worker.progress.connect(progress.append)
    worker.finished.connect(finished.append)

    worker.run()

    assert calls == [
        "build:clinical",
        "build:control",
        "comparison:figure",
        "verify",
        "verify",
        "commit",
    ]
    assert progress == sorted(progress)
    assert progress[-1] == 100
    assert len(finished) == 1
    outcome = finished[0]
    assert outcome.status is PublicationMapsOutcomeStatus.SUCCESS
    assert outcome.batch_figure_paths == (comparison_figure,)
    assert all(not result.figure_paths for result in outcome.results)
    assert not list(output_root.rglob("*.xlsx"))


def test_two_group_comparison_disambiguates_duplicate_display_labels(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    requests = _group_comparison_requests(
        project_root,
        project_root / "4 - Scalp Maps",
    )
    duplicate_labels = tuple(
        dataclasses.replace(request, group_label="Participants") for request in requests
    )

    assert _group_comparison_titles(duplicate_labels) == (
        "Participants (clinical)",
        "Participants (control)",
    )


def test_combined_group_comparison_displays_condition_above_group_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = pd.DataFrame(
        {
            "electrode": ["O1", "O2", "Fz", "F3"],
            "render_value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    captured: dict[str, object] = {}

    def capture_figure(fig, _output_path, **_kwargs) -> None:
        captured["figure_title"] = fig._suptitle.get_text()
        captured["axes_titles"] = [axis.get_title() for axis in fig.axes]
        captured["map_tops"] = [
            axis.get_position().y1 for axis in fig.axes if axis.get_title()
        ]

    monkeypatch.setattr(
        "Tools.Publication_Maps.rendering._save_figure",
        capture_figure,
    )
    _render_combined_paired_topomap(
        {
            PublicationMetric.BCA: (values, values),
            PublicationMetric.SNR: (values, values),
        },
        metrics=(PublicationMetric.BCA, PublicationMetric.SNR),
        first_title="Clinical",
        second_title="Control",
        output_path=tmp_path / "comparison.png",
        bounds_by_metric={
            PublicationMetric.BCA: ColorBounds(),
            PublicationMetric.SNR: ColorBounds(),
        },
        dpi=100,
        cancel_check=None,
        figure_title="Faces",
    )

    assert captured["figure_title"] == "Faces"
    assert captured["axes_titles"][:2] == ["Clinical", "Control"]
    assert max(captured["map_tops"]) <= 0.87


@pytest.mark.parametrize("field", ("group_label", "group_folder"))
def test_two_group_comparison_rejects_request_result_identity_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    project_root = tmp_path / "Project"
    requests = _group_comparison_requests(
        project_root,
        project_root / "4 - Scalp Maps",
    )
    results = [
        _comparison_result("clinical", "Clinical", scale=10.0),
        _comparison_result("control", "Control", scale=1.0),
    ]
    setattr(results[0], field, "Mismatched")

    with pytest.raises(PublicationMapInputError, match="group identity changed"):
        render_group_comparison_figures(results, requests)


@pytest.mark.parametrize("use_recorded", [False, True])
def test_group_surface_preview_and_export_share_limits_and_preserve_flat_figure(
    tmp_path, monkeypatch, use_recorded, hydrocel_geometry,
):
    from Tools.Publication_Maps import scalp_scene, scalp_surface, worker

    root = tmp_path / "Project"
    output = root / "4 - Scalp Maps"
    requests = tuple(dataclasses.replace(request, scalp_view="3d", export_pdf=True)
                     for request in _group_comparison_requests(root, output))
    cohorts = {key: _comparison_result(key, title, scale=scale) for key, title, scale in (
        ("clinical", "Clinical", 10.0), ("control", "Control", 1.0),
    )}
    first_electrode = hydrocel_geometry.channel_names[0] if use_recorded else "O1"
    for group_id, cohort in cohorts.items():
        if use_recorded:
            cohort.geometry = hydrocel_geometry
            cohort.grand_average_values["electrode"] = hydrocel_geometry.channel_names
        source = tmp_path / f"{group_id}.xlsx"
        source.write_bytes(b"original")
        cohort.included_workbooks = _result_with_workbook_snapshot(source).included_workbooks
        cohort.selection_metadata["final_release_receipt_fingerprint"] = "current-release"
    monkeypatch.setattr(worker, "build_publication_map_result",
                        lambda request, **_: cohorts[request.group_id])
    with monkeypatch.context() as preview_guard:
        def unexpected_destination_access(*_, **__):
            pytest.fail("Read-only preview touched an export destination")
        preview_guard.setattr(worker, "request_output_root", unexpected_destination_access)
        preview_guard.setattr(worker, "PublicationArtifactTransaction", unexpected_destination_access)
        preview = PublicationMapsWorker(requests, preview_only=True)
        preview.run()
    assert preview.outcome.status is PublicationMapsOutcomeStatus.SUCCESS
    assert not output.exists()
    assert preview.outcome.batch_figure_paths == ()
    panels = preview.outcome.viewer_panels
    assert [p.title for p in panels] == ["Faces · Clinical", "Faces · Control"]
    assert [(p.norm.vmin, p.norm.vmax) for p in panels] == [(0.0, 40.0)] * 2
    assert [dict(zip(p.info.ch_names, p.data, strict=True))[first_electrode] for p in panels] == [10.0, 1.0]
    assert all(p.output_root == output and p.input_root == requests[0].input_root for p in panels)
    assert all(p.output_base_root == output and p.project_root == root for p in panels)
    assert all(p.release_fingerprint == "current-release" for p in panels)
    assert panels[0].source_workbooks is panels[1].source_workbooks
    assert panels[0].source_workbooks == tuple(c.included_workbooks[0] for c in cohorts.values())

    output.mkdir()
    flat = output / "Faces_clinical_and_control_bca_group_comparison.png"
    flat.write_bytes(b"prior flat figure")
    draw_surface = scalp_surface.draw_scalp_surface
    rendered = []
    def capture_export(ax, data, info, *, view, cmap, norm):
        if view == "front":
            rendered.append((data, info.ch_names, (norm.vmin, norm.vmax), cmap))
        draw_surface(ax, data, info, view=view, cmap=cmap, norm=norm)

    with monkeypatch.context() as export_guard:
        export_guard.setattr(scalp_surface, "draw_scalp_surface", capture_export)
        export_guard.setattr(scalp_scene, "build_surface_panels",
                             lambda *_, **__: pytest.fail("File export prepared unused interactive panels"))
        batch = PublicationMapsWorker(requests)
        batch.run()
    assert batch.outcome.status is PublicationMapsOutcomeStatus.SUCCESS
    assert not batch.outcome.viewer_panels
    assert flat.read_bytes() == b"prior flat figure"
    assert {path.suffix for path in batch.outcome.batch_figure_paths} == {".pdf", ".png"}
    for path in batch.outcome.batch_figure_paths:
        assert path.stem == flat.stem + "_3d" and path.stat().st_size > 1000
    # PNG and PDF save the same figure; build each group's surface only once.
    for surface, (data, names, limits, cmap) in zip(panels, rendered, strict=True):
        np.testing.assert_array_equal(surface.data, data)
        assert surface.info.ch_names == names
        assert (surface.norm.vmin, surface.norm.vmax) == limits
        assert cmap.name == surface.cmap.name == "FpvsPublicationScalp3D"
        np.testing.assert_array_equal(cmap(np.linspace(0, 1, 256)), surface.cmap(np.linspace(0, 1, 256)))

    panels[0].source_workbooks[1].path.write_bytes(b"edited after analysis")
    stale = PublicationMapsWorker(requests, preview_only=True)
    stale.run()
    assert stale.outcome.status is PublicationMapsOutcomeStatus.ERROR
    assert not stale.outcome.viewer_panels and not stale.outcome.batch_figure_paths


@pytest.mark.parametrize(("view", "paired", "multi_metric"), [
    ("2d", False, False), ("2d", True, True), ("3d", True, False), ("3d", True, True),
    ("stacked_pair", True, True), ("stacked_pair", True, False),
    ("3d_2d", False, False), ("3d_2d", True, False), ("3d_2d", True, True),
])
def test_named_montage_reaches_each_ordinary_and_paired_figure(
    tmp_path, monkeypatch, hydrocel_geometry, view, paired, multi_metric,
):
    from Tools.Publication_Maps import rendering, scalp_surface
    from Tools.Publication_Maps.scalp_scene import build_surface_panels

    result = _comparison_result("clinical", "Clinical", scale=1.0)
    result.geometry = hydrocel_geometry
    names = hydrocel_geometry.channel_names
    frame = result.grand_average_values.assign(electrode=names)
    conditions = ("Faces", "Objects") if paired else ("Faces",)
    metrics = (PublicationMetric.BCA, PublicationMetric.SNR) if multi_metric else (PublicationMetric.BCA,)
    result.grand_average_values = pd.concat([
        frame.assign(condition=condition, metric=metric.value) for condition in conditions for metric in metrics
    ])
    request = PublicationMapRequest(
        input_root=tmp_path / "inputs", output_root=tmp_path / "maps", conditions=conditions,
        metrics=metrics, export_pdf=False, png_dpi=72, scalp_view=view,
        export_paired_figures=paired, paired_conditions=conditions if paired else (),
    )
    seen = []
    if view == "2d":
        draw = rendering._plot_topomap_compat

        def capture(*, data, info, **kwargs):
            seen.append(tuple(info.ch_names))
            return draw(data=data, info=info, **kwargs)

        monkeypatch.setattr(rendering, "_plot_topomap_compat", capture)
    else:
        draw = scalp_surface.draw_scalp_surface

        def capture(ax, data, info, **kwargs):
            seen.append(tuple(info.ch_names))
            return draw(ax, data, info, **kwargs)

        monkeypatch.setattr(scalp_surface, "draw_scalp_surface", capture)
    paths = rendering.render_publication_figures(result, request)
    assert paths and all(path.is_file() and path.parent.name == "Clinical" for path in paths)
    if view == "stacked_pair":
        assert len(paths) == len(metrics)
        assert all(path.stem.endswith("_paired_stacked_pair") for path in paths)
        assert len(seen) == 4 * len(metrics)
    assert seen and all(channels == names for channels in seen)
    panels = build_surface_panels([result], [dataclasses.replace(request, scalp_view="3d")], cancel_check=lambda: None)
    assert len(panels) == len(conditions) * len(metrics)
    for panel in panels:
        assert tuple(panel.info.ch_names) == names
        np.testing.assert_array_equal(panel.data, [1.0, 2.0, 3.0, 4.0])


def test_stacked_pair_has_ordered_columns_and_one_bottom_scale(tmp_path, monkeypatch):
    from Tools.Publication_Maps import rendering

    result = _comparison_result("clinical", "Clinical", scale=1.0)
    frame = result.grand_average_values
    captured = []
    monkeypatch.setattr(rendering, "_save_figure", lambda fig, *a, **kw: captured.append(fig))
    rendering._render_stacked_pair(
        (frame, frame), ("Left", "Right"), result.geometry, PublicationMetric.BCA,
        ColorBounds(auto_scale=False, vmin=-0.1, vmax=0.7), tmp_path / "figure.png", 72, None,
    )
    fig, = captured
    assert [t.get_text().splitlines()[0] for t in fig.texts] == ["Left", "Right"]
    assert all(t.get_fontweight() == "bold" for t in fig.texts)
    assert len(fig.axes) == 7
    for top, front, back in (fig.axes[:3], fig.axes[3:6]):
        assert top.get_position().y0 > front.get_position().y0 > back.get_position().y0
        assert top.images[0].get_clim() == (-0.1, 0.7)
    scale = fig.axes[-1]
    assert scale.get_xlabel() == "µV"
    assert scale.get_position().x0 + scale.get_position().width / 2 == pytest.approx(.5)
    assert scale.get_position().y1 < min(ax.get_position().y0 for ax in fig.axes[:-1])
    np.testing.assert_allclose(scale.get_xticks(), [-.1, .1, .3, .5, .7])


def test_group_comparison_rejects_incompatible_caps_before_output_or_preview(tmp_path, hydrocel_geometry):
    from Tools.Publication_Maps.scalp_scene import build_surface_panels

    root = tmp_path / "Project"
    requests = _group_comparison_requests(root, tmp_path / "figures")
    results = [_comparison_result(r.group_id, r.group_label, scale=1.) for r in requests]
    results[0].geometry = hydrocel_geometry
    results[1].geometry = dataclasses.replace(hydrocel_geometry, montage_id="different-layout")
    for result in results:
        result.grand_average_values["electrode"] = hydrocel_geometry.channel_names
    with pytest.raises(PublicationMapInputError, match="(?i)montage|geometry|layout"):
        render_group_comparison_figures(results, requests)
    with pytest.raises(PublicationMapInputError, match="(?i)montage|geometry|layout"):
        build_surface_panels(results, requests, cancel_check=lambda: None)
    assert not requests[0].output_root.exists()


def test_paired_surface_viewer_keeps_group_folder_and_selected_pair_order(tmp_path):
    from Tools.Publication_Maps.scalp_scene import build_surface_panels

    request = PublicationMapRequest(
        input_root=tmp_path / "input", output_root=tmp_path / "output",
        conditions=("Faces", "Objects", "Extra"), export_paired_figures=True,
        paired_conditions=("Objects", "Faces"), scalp_view="3d",
    )
    result = _comparison_result("clinical", "Clinical", scale=1.0)
    frame = result.grand_average_values
    result.grand_average_values = pd.concat([
        frame, frame.assign(condition="Objects", render_value=2.0), frame.assign(condition="Extra", render_value=100.0),
    ])
    panels = build_surface_panels([result], [request], cancel_check=lambda: None)
    assert [p.title for p in panels] == ["Objects · Clinical", "Faces · Clinical"]
    assert all(p.output_root == request.output_root / "Clinical" for p in panels)
    assert all(p.norm.vmax == 4.0 for p in panels)


def _group_comparison_requests(
    project_root: Path,
    output_root: Path,
) -> tuple[PublicationMapRequest, PublicationMapRequest]:
    _write_two_group_manifest(project_root)
    common = PublicationMapRequest(
        input_root=project_root / "1 - Excel Data Files",
        output_root=output_root,
        conditions=("Faces",),
        project_root=project_root,
        metrics=(PublicationMetric.BCA,),
        export_png=True,
        export_pdf=False,
        export_group_comparison_figure=True,
        group_comparison_ids=("clinical", "control"),
        png_dpi=100,
    )
    return (
        dataclasses.replace(
            common,
            group_id="clinical",
            group_label="Clinical",
            group_folder="Clinical",
        ),
        dataclasses.replace(
            common,
            group_id="control",
            group_label="Control",
            group_folder="Control",
        ),
    )


def _comparison_result(
    group_id: str,
    group_label: str,
    *,
    scale: float,
) -> PublicationMapResult:
    electrodes = ["O1", "O2", "Fz", "F3"]
    values = [scale, 2.0 * scale, 3.0 * scale, 4.0 * scale]
    return PublicationMapResult(
        long_values=pd.DataFrame(),
        grand_average_values=pd.DataFrame(
            {
                "condition": ["Faces"] * 4,
                "group_id": [group_id] * 4,
                "group_label": [group_label] * 4,
                "group_folder": [group_label] * 4,
                "electrode": electrodes,
                "is_montage_electrode": [True] * 4,
                "metric": [PublicationMetric.BCA.value] * 4,
                "map_label": ["BCA significant-harmonic sum"] * 4,
                "render_value": values,
            }
        ),
        selected_harmonics_hz=(1.2,),
        selection_metadata={"selection_fingerprint": "selection-fingerprint"},
        group_id=group_id,
        group_label=group_label,
        group_folder=group_label,
        qc_provenance={
            "applied_exclusions_sha256": "qc-exclusions-fingerprint",
        },
    )


def _write_two_group_manifest(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    excel_root = project_root / "1 - Excel Data Files"
    excel_root.mkdir(parents=True, exist_ok=True)
    manifest_path = project_root / "project.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    manifest.update(
        {
            "schema_version": "2.1.0",
            "subfolders": {"excel": "1 - Excel Data Files"},
            "groups": {
                "clinical": {
                    "label": "Clinical",
                    "folder_name": "Clinical",
                    "raw_input_folder": "Raw/Clinical",
                },
                "control": {
                    "label": "Control",
                    "folder_name": "Control",
                    "raw_input_folder": "Raw/Control",
                },
            },
            "participants": {
                "P01": {"group_id": "control"},
                "P02": {"group_id": "clinical"},
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _request(
    project_root: Path,
    output_root: Path,
    *,
    group_id: str | None = None,
    group_folder: str | None = None,
) -> PublicationMapRequest:
    return PublicationMapRequest(
        input_root=project_root / "1 - Excel Data Files",
        output_root=output_root,
        conditions=("Faces",),
        project_root=project_root,
        group_id=group_id,
        group_label=group_folder,
        group_folder=group_folder,
        export_png=False,
        export_pdf=False,
    )


def _result_with_workbook_snapshot(source: Path) -> PublicationMapResult:
    snapshot = source.stat()
    included = WorkbookEntry(
        condition="Faces",
        subject_id="P01",
        path=source,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        size_bytes=snapshot.st_size,
        mtime_ns=snapshot.st_mtime_ns,
    )
    return PublicationMapResult(
        long_values=pd.DataFrame(),
        grand_average_values=pd.DataFrame(),
        included_workbooks=(included,),
    )
