from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Main_App.projects import GroupConfigurationError
from Tools.Publication_Maps.generation_outcome import (
    PublicationMapGenerationCancelled,
)
from Tools.Publication_Maps.models import (
    ExcludedCohortEntry,
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
    SOURCE_WORKBOOK_NAME,
    WorkbookEntry,
)
from Tools.Publication_Maps.output_contract import (
    PublicationArtifactTransaction,
    request_output_root,
)
from Tools.Publication_Maps.rendering import (
    _assert_unique_figure_stems,
    export_source_workbook,
)
from Tools.Publication_Maps.scalp_io import (
    InsufficientSensorCoverageError,
    align_render_values,
)
from Tools.Publication_Maps.source_provenance import SourceProvenanceError


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


def test_source_export_uses_result_group_and_records_complete_provenance(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    input_root = project_root / "1 - Excel Data Files"
    source = input_root / "Faces" / "Control" / "P01_Faces_Results.xlsx"
    excluded = input_root / "Faces" / "Control" / "P02_Faces_Results.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"exact source bytes read by the backend")
    excluded.write_bytes(b"excluded source")
    _write_qc_manifest(project_root)
    request = _request(project_root, project_root / "4 - Scalp Maps")
    result = _result_for_source(
        source,
        group_id="control",
        group_label="Control participants",
        group_folder="Control",
        excluded=excluded,
    )

    workbook_path = export_source_workbook(result, request)

    assert workbook_path == (
        project_root / "4 - Scalp Maps" / "Control" / SOURCE_WORKBOOK_NAME
    ).resolve()
    source_files = pd.read_excel(workbook_path, sheet_name="Source_Files")
    cohort = pd.read_excel(workbook_path, sheet_name="Cohort")
    provenance = pd.read_excel(workbook_path, sheet_name="Provenance")
    coverage = pd.read_excel(workbook_path, sheet_name="Sensor_Coverage")
    long_values = pd.read_excel(workbook_path, sheet_name="Long_Values")
    parameters = pd.read_excel(workbook_path, sheet_name="Parameters")
    provenance_by_key = dict(zip(provenance["key"], provenance["value"]))
    parameters_by_key = dict(zip(parameters["key"], parameters["value"]))

    assert source_files.loc[0, "group_id"] == "control"
    assert source_files.loc[0, "source_workbook"] == (
        "1 - Excel Data Files/Faces/Control/P01_Faces_Results.xlsx"
    )
    assert source_files.loc[0, "sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_files.loc[0, "size_bytes"] == source.stat().st_size
    assert source_files.loc[0, "fingerprint_boundary"] == (
        "verified_against_read_snapshot"
    )
    assert set(cohort["disposition"]) == {"included", "excluded"}
    assert set(cohort["participant_id"]) == {"P01", "P02"}
    assert set(long_values["group_id"]) == {"control"}
    assert provenance_by_key["group_id"] == "control"
    assert provenance_by_key["included_participant_n"] == 1
    assert provenance_by_key[
        "harmonic_selection.harmonic_selection_profile"
    ] == "legacy_fpvs_toolbox"
    assert provenance_by_key[
        "harmonic_selection.selection_fingerprint"
    ] == "selection-fingerprint"
    assert provenance_by_key["qc.last_review.analysis_fingerprint"] == (
        "qc-analysis-fingerprint"
    )
    assert provenance_by_key["qc.last_review.decision_fingerprint"] == (
        "qc-decision-fingerprint"
    )
    assert json.loads(provenance_by_key["qc.excluded_participants"]) == ["P07"]
    assert json.loads(
        provenance_by_key["qc.auto_excluded_electrodes_by_participant"]
    ) == {"P01": ["Pz"]}
    assert provenance_by_key["qc.auto_participant_exclusion_n"] == 1
    assert provenance_by_key["qc.manual_participant_exclusion_n"] == 0
    assert provenance_by_key["qc.auto_participant_electrode_exclusion_n"] == 1
    assert provenance_by_key["qc.applied_snapshot_boundary"] == (
        "analysis_time_result_snapshot"
    )
    assert provenance_by_key["qc.applied_exclusions_sha256"] == (
        "analysis-exclusions-fingerprint"
    )
    assert len(str(provenance_by_key["qc.state_sha256"])) == 64
    assert "never zero-filled" in provenance_by_key["sensor_coverage_rule"]
    assert parameters_by_key["group_folder"] == "Control"
    assert parameters_by_key["selection_fingerprint"] == "selection-fingerprint"
    assert coverage.loc[0, "finite_sensor_count"] == 4
    assert coverage.loc[0, "missing_sensor_count"] == 60
    assert bool(coverage.loc[0, "coverage_sufficient"])


def test_source_export_rejects_request_result_group_identity_mismatch(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    source = project_root / "1 - Excel Data Files" / "Faces" / "P01.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source bytes")
    request = _request(
        project_root,
        project_root / "4 - Scalp Maps",
        group_id="control",
        group_folder="Control",
    )
    result = _result_for_source(
        source,
        group_id="clinical",
        group_label="Clinical",
        group_folder="Clinical",
    )

    with pytest.raises(PublicationMapInputError, match="group identity changed"):
        export_source_workbook(result, request)

    assert not (project_root / "4 - Scalp Maps").exists()


def test_source_export_rejects_source_changed_after_backend_read(
    tmp_path: Path,
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
    result = _result_for_source(source)
    source.write_bytes(b"changed after backend read")
    output_root = project_root / "4 - Scalp Maps"
    output_root.mkdir(parents=True)
    previous = output_root / SOURCE_WORKBOOK_NAME
    previous.write_bytes(b"previous published source workbook")
    request = _request(project_root, output_root)

    with pytest.raises(SourceProvenanceError, match="changed after it was read"):
        export_source_workbook(result, request)

    assert previous.read_bytes() == b"previous published source workbook"
    assert not list(output_root.glob(".scalp-maps-stage-*"))


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


def _result_for_source(
    source: Path,
    *,
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
    excluded: Path | None = None,
) -> PublicationMapResult:
    snapshot = source.stat()
    included = WorkbookEntry(
        condition="Faces",
        subject_id="P01",
        path=source,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        size_bytes=snapshot.st_size,
        mtime_ns=snapshot.st_mtime_ns,
    )
    excluded_rows = (
        (
            ExcludedCohortEntry(
                participant_id="P02",
                condition="Faces",
                reason="project participant-condition exclusion",
                path=excluded,
            ),
        )
        if excluded is not None
        else ()
    )
    electrodes = ["O1", "O2", "Fz", "F3"]
    return PublicationMapResult(
        long_values=pd.DataFrame(
            {
                "condition": ["Faces"] * 4,
                "subject_id": ["P01"] * 4,
                "workbook_path": [str(source)] * 4,
                "electrode": electrodes,
                "metric": [PublicationMetric.BCA.value] * 4,
                "value": [1.0, 2.0, 3.0, 4.0],
            }
        ),
        grand_average_values=pd.DataFrame(
            {
                "condition": ["Faces"] * 4,
                "electrode": electrodes,
                "is_montage_electrode": [True] * 4,
                "metric": [PublicationMetric.BCA.value] * 4,
                "map_label": ["BCA significant-harmonic sum"] * 4,
                "render_value": [1.0, 2.0, 3.0, 4.0],
            }
        ),
        selected_harmonics_hz=(1.2, 2.4),
        selection_metadata={
            "harmonic_selection_profile": "legacy_fpvs_toolbox",
            "harmonic_selection_profile_version": "1.0",
            "selection_fingerprint": "selection-fingerprint",
        },
        group_id=group_id,
        group_label=group_label,
        group_folder=group_folder,
        included_workbooks=(included,),
        excluded_cohort=excluded_rows,
        qc_provenance={
            "method_version": "summed_bca_plausibility_v1",
            "excluded_participants": ["P07"],
            "auto_excluded_participants": ["P07"],
            "manual_excluded_participants": [],
            "auto_excluded_electrodes_by_participant": {"P01": ["Pz"]},
            "downstream_outputs_stale": False,
            "auto_participant_exclusion_n": 1,
            "manual_participant_exclusion_n": 0,
            "auto_participant_electrode_exclusion_n": 1,
            "applied_exclusions_sha256": "analysis-exclusions-fingerprint",
        },
    )


def _write_qc_manifest(project_root: Path) -> None:
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "tools": {
                    "frequency_domain_qc": {
                        "schema_version": 1,
                        "method_version": "summed_bca_plausibility_v1",
                        "downstream_outputs_stale": False,
                        "auto_participant_exclusions": [
                            {"participant_id": "P03"}
                        ],
                        "manual_participant_exclusions": [
                            {
                                "participant_id": "P04",
                                "reason": "Noisy spectrum",
                            }
                        ],
                        "auto_participant_electrode_exclusions": [
                            {"participant_id": "P01", "electrode": "Oz"},
                            {"participant_id": "P01", "electrode": "O2"},
                        ],
                        "last_review": {
                            "reviewed_at": "2026-08-16T12:00:00+00:00",
                            "analysis_fingerprint": "qc-analysis-fingerprint",
                            "decision_fingerprint": "qc-decision-fingerprint",
                            "review_subject_count": 1,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
