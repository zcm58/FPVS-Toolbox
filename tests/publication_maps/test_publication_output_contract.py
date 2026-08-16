from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
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
