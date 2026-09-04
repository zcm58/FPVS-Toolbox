from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.projects import DatasetIndexError
from Tools.Publication_Maps import metrics as publication_map_metrics
from Tools.Publication_Maps.excel_inputs import load_publication_dataset_index
from Tools.Publication_Maps.metrics import build_publication_map_result
from Tools.Publication_Maps.models import (
    PublicationMapCohortError,
    PublicationMapInputError,
    PublicationMapRequest,
)
from Tools.Publication_Maps.scalp_io import normalize_electrode_name


@pytest.fixture(autouse=True)
def _fixed_processing_harmonics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_map_metrics,
        "_select_stats_significant_harmonics",
        lambda **_kwargs: (
            (1.2,),
            {
                "harmonic_selection_profile": "legacy_fpvs_toolbox",
                "harmonic_selection_profile_version": "1.0",
                "selection_fingerprint": "selection-fingerprint",
            },
        ),
    )
    monkeypatch.setattr(
        publication_map_metrics,
        "_require_managed_publication_release",
        _test_managed_release,
    )


def test_ungrouped_project_uses_registered_canonical_participants(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None, "P02": None},
    )
    _write_bca(excel_root / "Faces" / "P01_Faces_Results.xlsx", value=1.0)
    _write_bca(excel_root / "Faces" / "P02_Faces_Results.xlsx", value=3.0)

    result = build_publication_map_result(_request(project_root, excel_root, conditions=("Faces",)))

    assert result.group_id is None
    assert result.group_label is None
    assert result.group_folder is None
    assert {row.participant_id for row in result.included_workbooks} == {"P01", "P02"}
    assert _electrode_value(result, "O1") == pytest.approx(2.0)
    assert set(result.long_values["group_id"].isna()) == {True}


def test_managed_index_rejects_a_descendant_of_the_canonical_excel_root(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    condition_root = excel_root / "Faces"
    _write_bca(condition_root / "P01_Faces_Results.xlsx", value=1.0)

    with pytest.raises(DatasetIndexError, match="exact configured Excel root"):
        load_publication_dataset_index(
            condition_root,
            project_root=project_root,
        )


def test_multigroup_requests_are_explicit_and_never_pool_groups(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={"P01": "control", "P02": "clinical"},
    )
    _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )
    _write_bca(
        excel_root / "Faces" / "Clinical" / "P02_Faces_Results.xlsx",
        value=10.0,
    )

    with pytest.raises(PublicationMapCohortError, match="Select one canonical"):
        build_publication_map_result(_request(project_root, excel_root))

    control = build_publication_map_result(
        _request(
            project_root,
            excel_root,
            group_id="control",
            group_label="Control",
            group_folder="Control",
        )
    )
    clinical = build_publication_map_result(
        _request(
            project_root,
            excel_root,
            group_id="clinical",
            group_label="Clinical",
            group_folder="Clinical",
        )
    )

    assert (control.group_id, control.group_label, control.group_folder) == (
        "control",
        "Control",
        "Control",
    )
    assert (clinical.group_id, clinical.group_label, clinical.group_folder) == (
        "clinical",
        "Clinical",
        "Clinical",
    )
    assert _electrode_value(control, "O1") == pytest.approx(1.0)
    assert _electrode_value(clinical, "O1") == pytest.approx(10.0)
    assert set(control.long_values["subject_id"]) == {"P01"}
    assert set(clinical.long_values["subject_id"]) == {"P02"}


def test_sole_group_is_resolved_when_request_group_fields_are_blank(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )

    result = build_publication_map_result(_request(project_root, excel_root))

    assert (result.group_id, result.group_label, result.group_folder) == (
        "control",
        "Control",
        "Control",
    )
    assert result.included_workbooks[0].group_id == "control"


def test_dataset_exclusions_and_duplicate_preference_are_audited(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={
            "P01": "control",
            "P02": "control",
            "P03": "clinical",
        },
        participant_condition_exclusions={"P02": ["Faces"]},
    )
    grouped = _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )
    _write_bca(excel_root / "Faces" / "P01_Faces_Results.xlsx", value=99.0)
    excluded = _write_bca(
        excel_root / "Faces" / "Control" / "P02_Faces_Results.xlsx",
        value=50.0,
    )
    _write_bca(
        excel_root / "Faces" / "Clinical" / "P03_Faces_Results.xlsx",
        value=10.0,
    )

    result = build_publication_map_result(_request(project_root, excel_root, group_id="control"))

    assert [row.path for row in result.included_workbooks] == [grouped]
    assert _electrode_value(result, "O1") == pytest.approx(1.0)
    assert len(result.excluded_cohort) == 1
    assert result.excluded_cohort[0].path == excluded
    assert result.excluded_cohort[0].reason == "project participant-condition exclusion"
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "duplicate_participant_condition_workbook",
        "excluded_participant_condition",
    }


def test_unassigned_managed_workbook_is_a_fatal_cohort_error(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    _write_bca(excel_root / "Faces" / "P99_Faces_Results.xlsx", value=1.0)

    with pytest.raises(PublicationMapCohortError, match="unassigned_participant"):
        build_publication_map_result(_request(project_root, excel_root))


def test_unassigned_workbook_in_unrequested_condition_does_not_block(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )
    _write_bca(excel_root / "Objects" / "P99_Objects_Results.xlsx", value=20.0)

    result = build_publication_map_result(_request(project_root, excel_root, group_id="control"))

    assert {row.participant_id for row in result.included_workbooks} == {"P01"}
    unrelated = [row for row in result.diagnostics if row.code == "unassigned_participant"]
    assert len(unrelated) == 1
    assert unrelated[0].condition == "Objects"
    assert unrelated[0].level == "warning"


def test_unassigned_workbook_in_requested_condition_remains_fatal(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )
    _write_bca(excel_root / "Faces" / "P99_Faces_Results.xlsx", value=20.0)

    with pytest.raises(
        PublicationMapCohortError,
        match="unassigned_participant",
    ):
        build_publication_map_result(_request(project_root, excel_root, group_id="control"))


def test_unresolved_participant_in_unrequested_condition_does_not_block(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _write_bca(
        excel_root / "Faces" / "Control" / "P01_Faces_Results.xlsx",
        value=1.0,
    )
    _write_bca(excel_root / "Objects" / "unknown.xlsx", value=20.0)

    result = build_publication_map_result(_request(project_root, excel_root, group_id="control"))

    diagnostics = [row for row in result.diagnostics if row.code == "unresolved_participant"]
    assert len(diagnostics) == 1
    assert diagnostics[0].condition == "Objects"
    assert diagnostics[0].level == "warning"
    assert diagnostics[0].detail == ("1 - Excel Data Files/Objects/unknown.xlsx")
    assert str(project_root) not in diagnostics[0].detail


@pytest.mark.parametrize(
    ("failure", "message"),
    (
        ("unreadable", "Unable to read requested BCA"),
        ("missing_sheet", "Worksheet named 'BCA \\(uV\\)' not found"),
        ("missing_column", "Missing exact selected BCA harmonic columns"),
    ),
)
def test_active_workbook_validation_is_fatal(
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    workbook = excel_root / "Faces" / "P01_Faces_Results.xlsx"
    if failure == "unreadable":
        workbook.parent.mkdir(parents=True, exist_ok=True)
        workbook.write_text("not an xlsx archive", encoding="utf-8")
    elif failure == "missing_sheet":
        _write_bca(workbook, value=1.0, sheet_name="SNR")
    else:
        _write_bca(workbook, value=1.0, harmonic_column="1.3000_Hz")

    with pytest.raises(PublicationMapInputError, match=message):
        build_publication_map_result(_request(project_root, excel_root))


def test_duplicate_normalized_electrode_rows_are_fatal(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    workbook = excel_root / "Faces" / "P01_Faces_Results.xlsx"
    _write_bca_frame(
        workbook,
        electrodes=["O1", " o1 ", "O2", "Fz", "F3"],
        values=[1.0, 2.0, 1.0, 1.0, 1.0],
    )

    with pytest.raises(
        PublicationMapInputError,
        match="frozen QC-21 electrode set.*repeat.*O1",
    ):
        build_publication_map_result(_request(project_root, excel_root))


def test_managed_release_rejects_blank_electrode_identity_rows(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    workbook = excel_root / "Faces" / "P01_Faces_Results.xlsx"
    _write_bca_frame(
        workbook,
        electrodes=["O1", "O2", "Fz", "F3", None, pd.NA],
        values=[1.0, 1.0, 1.0, 1.0, 99.0, 99.0],
    )

    with pytest.raises(
        PublicationMapInputError,
        match="frozen QC-21 electrode set.*blank or non-text electrode identity",
    ):
        build_publication_map_result(_request(project_root, excel_root))


@pytest.mark.parametrize("missing_label", [None, float("nan"), pd.NA])
def test_missing_electrode_labels_normalize_to_blank(missing_label: object) -> None:
    assert normalize_electrode_name(missing_label) == ""


def test_workbook_metric_with_no_finite_montage_values_is_fatal(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    workbook = excel_root / "Faces" / "P01_Faces_Results.xlsx"
    _write_bca_frame(
        workbook,
        electrodes=["O1", "O2", "Fz", "F3"],
        values=["bad", None, "", "not-a-number"],
    )

    with pytest.raises(
        PublicationMapInputError,
        match="No finite BioSemi64 values remain",
    ):
        build_publication_map_result(_request(project_root, excel_root))


def test_included_workbook_identity_matches_exact_read_snapshot(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    workbook = _write_bca(
        excel_root / "Faces" / "P01_Faces_Results.xlsx",
        value=1.0,
    )

    result = build_publication_map_result(_request(project_root, excel_root))

    included = result.included_workbooks[0]
    assert included.sha256 == hashlib.sha256(workbook.read_bytes()).hexdigest()
    assert included.size_bytes == workbook.stat().st_size
    assert included.mtime_ns == workbook.stat().st_mtime_ns


def test_backend_cancellation_checkpoint_exception_propagates(tmp_path: Path) -> None:
    project_root, excel_root = _write_project(
        tmp_path,
        groups={},
        participants={"P01": None},
    )
    _write_bca(excel_root / "Faces" / "P01_Faces_Results.xlsx", value=1.0)

    class Cancelled(RuntimeError):
        pass

    calls = 0

    def cancel_check() -> None:
        nonlocal calls
        calls += 1
        if calls >= 4:
            raise Cancelled("cancelled")

    with pytest.raises(Cancelled, match="cancelled"):
        build_publication_map_result(
            _request(project_root, excel_root),
            cancel_check=cancel_check,
        )
    assert calls == 4


def _request(
    project_root: Path,
    excel_root: Path,
    *,
    conditions: tuple[str, ...] = ("Faces",),
    group_id: str | None = None,
    group_label: str | None = None,
    group_folder: str | None = None,
) -> PublicationMapRequest:
    return PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=conditions,
        project_root=project_root,
        group_id=group_id,
        group_label=group_label,
        group_folder=group_folder,
    )


def _write_project(
    tmp_path: Path,
    *,
    groups: dict[str, tuple[str, str]],
    participants: dict[str, str | None],
    participant_condition_exclusions: dict[str, list[str]] | None = None,
) -> tuple[Path, Path]:
    project_root = tmp_path / "Project"
    project_root.mkdir(parents=True)
    manifest_groups = {
        group_id: {
            "label": label,
            "folder_name": folder,
            "raw_input_folder": f"Raw/{folder}",
        }
        for group_id, (label, folder) in groups.items()
    }
    manifest_participants = {
        participant_id: ({} if group_id is None else {"group_id": group_id})
        for participant_id, group_id in participants.items()
    }
    preprocessing: dict[str, object] = {}
    if participant_condition_exclusions is not None:
        preprocessing["manual_excluded_participant_conditions"] = participant_condition_exclusions
    manifest = {
        "schema_version": "2.1.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": manifest_groups,
        "participants": manifest_participants,
        "preprocessing": preprocessing,
    }
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return project_root, project_root / "1 - Excel Data Files"


def _write_bca(
    path: Path,
    *,
    value: float,
    sheet_name: str = "BCA (uV)",
    harmonic_column: str = "1.2000_Hz",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "Electrode": ["O1", "O2", "Fz", "F3"],
            harmonic_column: [value, value, value, value],
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return path


def _write_bca_frame(
    path: Path,
    *,
    electrodes: list[object],
    values: list[object],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "Electrode": electrodes,
            "1.2000_Hz": values,
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)
    return path


def _test_managed_release(project_root: Path | None):
    if project_root is None:
        return None
    excel_root = Path(project_root) / "1 - Excel Data Files"
    sources = {
        path.resolve(strict=False): publication_map_metrics._ReleasedPublicationSource(
            workbook_path=path.resolve(strict=False),
            retained_scalp_channels=("O1", "O2", "FZ", "F3"),
            allowed_auxiliary_rows=(),
            observed_auxiliary_rows=(),
            source_evidence_fingerprint=f"released:{path.name}",
        )
        for path in excel_root.rglob("*.xlsx")
    }
    return publication_map_metrics._ManagedPublicationRelease(
        sources_by_workbook=sources,
        final_coverage_fingerprint="coverage-fingerprint",
        final_release_receipt_fingerprint="release-fingerprint",
    )


def _electrode_value(result, electrode: str) -> float:
    row = result.grand_average_values[result.grand_average_values["electrode"] == electrode].iloc[0]
    return float(row["aggregate_value"])
