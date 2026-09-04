from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.processing.roi_coverage import RoiCoverageGateError
from Tools.Publication_Maps import metrics as publication_metrics
from Tools.Publication_Maps.models import (
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMetric,
    WorkbookEntry,
)
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CanonicalHarmonicSelectionError,
    SharedHarmonicSelection,
)


def test_managed_publication_maps_requires_final_release_before_harmonics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.processing import roi_coverage

    calls: list[str] = []

    def fake_release(project_root: str | Path):
        assert Path(project_root) == tmp_path
        calls.append("release")
        return (
            object(),
            SimpleNamespace(cells=(), fingerprint="coverage-fingerprint"),
            SimpleNamespace(fingerprint="release-fingerprint"),
        )

    def fake_harmonics(**_kwargs):
        calls.append("harmonics")
        return SharedHarmonicSelection(
            source=CANONICAL_HARMONIC_SOURCE,
            selected_harmonics_hz=(1.2,),
            metadata={},
            fingerprint={},
            fingerprint_text="selected: 1.2 Hz",
            output_label=CANONICAL_HARMONIC_SOURCE,
        )

    monkeypatch.setattr(roi_coverage, "require_project_final_release", fake_release)
    monkeypatch.setattr(
        publication_metrics,
        "load_project_processing_harmonics",
        fake_harmonics,
    )
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )

    selected, _metadata = publication_metrics._select_stats_significant_harmonics(
        request=request,
        diagnostics=[],
    )

    assert selected == (1.2,)
    assert calls == ["release", "harmonics"]


def test_managed_publication_maps_reports_stale_release_as_reprocessing_needed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.processing import roi_coverage

    def reject_release(_project_root: str | Path):
        raise RoiCoverageGateError("Final QC release is missing or stale.")

    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        reject_release,
    )
    monkeypatch.setattr(
        publication_metrics,
        "load_project_processing_harmonics",
        lambda **_kwargs: pytest.fail("Harmonics must not load before final release."),
    )
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )

    with pytest.raises(
        CanonicalHarmonicSelectionError,
        match="Final QC release is missing or stale",
    ) as exc_info:
        publication_metrics._select_stats_significant_harmonics(
            request=request,
            diagnostics=[],
        )

    assert exc_info.value.reason == "stale_final_release"


def test_managed_publication_build_checks_release_before_cohort_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from Main_App.processing import roi_coverage

    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        lambda _root: (_ for _ in ()).throw(
            RoiCoverageGateError("Final QC release is stale.")
        ),
    )
    monkeypatch.setattr(
        publication_metrics,
        "active_frequency_domain_exclusions",
        lambda _root: pytest.fail("Cohort reads must follow the release gate."),
    )
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )

    with pytest.raises(CanonicalHarmonicSelectionError, match="release is stale"):
        publication_metrics.build_publication_map_result(request)


def _released_source(path: Path):
    return publication_metrics._ReleasedPublicationSource(
        workbook_path=path.resolve(strict=False),
        retained_scalp_channels=("O1", "O2"),
        allowed_auxiliary_rows=(),
        observed_auxiliary_rows=(),
        source_evidence_fingerprint="source-fingerprint",
    )


def _workbook(path: Path) -> WorkbookEntry:
    return WorkbookEntry(
        condition="Faces",
        subject_id="P1",
        path=path,
    )


def test_managed_publication_maps_rejects_unreleased_selected_workbook(
    tmp_path: Path,
) -> None:
    released = tmp_path / "P1_Faces_Results.xlsx"
    selected = tmp_path / "P2_Faces_Results.xlsx"
    release = publication_metrics._ManagedPublicationRelease(
        sources_by_workbook={released.resolve(strict=False): _released_source(released)},
        final_coverage_fingerprint="coverage-fingerprint",
        final_release_receipt_fingerprint="release-fingerprint",
    )

    with pytest.raises(
        PublicationMapInputError,
        match="not an available QC-20/QC-21 released contributor",
    ):
        publication_metrics._require_released_publication_workbooks(
            (_workbook(selected),),
            release,
        )


@pytest.mark.parametrize(
    ("electrodes", "message"),
    [
        (("O1",), "missing retained scalp channel"),
        (("O1", "O2", "Fp1"), "outside the frozen retained set"),
        (("O1", "O2", "O1"), "repeat.*scalp channel"),
    ],
    ids=("missing-row", "extra-row", "duplicate-row"),
)
def test_managed_publication_maps_requires_exact_frozen_metric_rows(
    tmp_path: Path,
    electrodes: tuple[str, ...],
    message: str,
) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    rows = pd.DataFrame(
        [
            {"Electrode": electrode, "1.2000_Hz": 1.0}
            for electrode in electrodes
        ]
    )

    with pytest.raises(PublicationMapInputError, match=message):
        publication_metrics._validate_released_metric_source_rows(
            rows,
            metric=PublicationMetric.BCA,
            workbook=_workbook(workbook),
            selected_columns=["1.2000_Hz"],
            released_source=_released_source(workbook),
        )


def test_managed_publication_validates_rows_before_electrode_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook_path = tmp_path / "P1_Faces_Results.xlsx"
    workbook = _workbook(workbook_path)
    monkeypatch.setattr(
        publication_metrics,
        "read_metric_sheet_selected_columns",
        lambda *_args, **_kwargs: pd.DataFrame(
            [{"Electrode": "O1", "1.2000_Hz": 1.0}]
        ),
    )

    with pytest.raises(PublicationMapInputError, match="missing retained.*O2"):
        publication_metrics._collect_metric_rows(
            metric=PublicationMetric.BCA,
            workbooks=[workbook],
            harmonics_hz=(1.2,),
            diagnostics=[],
            excluded_electrodes_by_subject={"P1": frozenset({"O2"})},
            managed_sources_by_workbook={
                workbook_path.resolve(strict=False): _released_source(workbook_path)
            },
        )


def test_managed_publication_metadata_retains_release_and_source_fingerprints(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "P1_Faces_Results.xlsx"
    source = _released_source(workbook)
    release = publication_metrics._ManagedPublicationRelease(
        sources_by_workbook={workbook.resolve(strict=False): source},
        final_coverage_fingerprint="coverage-fingerprint",
        final_release_receipt_fingerprint="release-fingerprint",
    )

    metadata = publication_metrics._managed_publication_release_metadata(
        release,
        {workbook.resolve(strict=False): source},
    )

    assert metadata["final_roi_coverage_fingerprint"] == "coverage-fingerprint"
    assert metadata["final_release_receipt_fingerprint"] == "release-fingerprint"
    assert metadata["selected_source_coverage_fingerprints"] == {
        str(workbook.resolve(strict=False)): "source-fingerprint"
    }
