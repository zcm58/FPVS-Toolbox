from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import pytest

from Main_App.processing import full_fft_provenance
from Main_App.processing.frequency_domain_qc import (
    FrequencyDomainQcIntegrityError,
    apply_frequency_domain_qc_decision,
    load_frequency_domain_qc_state,
    run_frequency_domain_qc_review,
    sync_frequency_domain_qc_automatic_state,
)
from Main_App.projects.preprocessing_settings import (
    FIXED_HARMONIC_SELECTION_PROFILE,
    HARMONIC_SELECTION_PROFILE_VERSION,
)
from Main_App.projects.project import Project
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME


@pytest.fixture(autouse=True)
def _current_workbook_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda _root, *, dataset_index=None: object(),
    )


def test_invalid_selected_cell_blocks_partial_sum_exclusions_and_finalization(
    tmp_path,
) -> None:
    project, workbook_path = _make_project(
        tmp_path,
        {"O2": (300.0, "damaged"), "PZ": (1.0, 1.0)},
    )

    report = run_frequency_domain_qc_review(project)

    assert report["qc_complete"] is False
    assert report["result_status"] == "technical_output_integrity_failed"
    assert report["technical_integrity_failed"] is True
    assert report["review_required"] is False
    assert report["review_reused"] is False
    assert report["flags"] == []
    assert report["auto_participant_electrode_exclusions"] == []
    assert report["auto_participant_exclusions"] == []
    assert report["finite_input_status"]["technical_integrity_failure_count"] == 1
    assert len(report["finite_input_status"]["fingerprint"]) == 64
    assert report["technical_integrity_failures"] == [
        {
            "participant_id": "P1",
            "condition": "CondA",
            "workbook_path": str(workbook_path),
            "electrode": "O2",
            "worksheet_row": 2,
            "harmonic_hz": 2.4,
            "harmonic_column": "2.4000_Hz",
            "failure_type": "invalid_selected_bca_cell",
            "value_category": "text",
            "reason_codes": [],
        }
    ]

    with pytest.raises(FrequencyDomainQcIntegrityError, match="P1/CondA/O2/2.4000_Hz"):
        sync_frequency_domain_qc_automatic_state(project.project_root, report)
    with pytest.raises(FrequencyDomainQcIntegrityError, match="Reprocess"):
        apply_frequency_domain_qc_decision(project.project_root, report)
    assert load_frequency_domain_qc_state(project.project_root) == {}

    _write_workbook(
        workbook_path,
        {"O2": (300.0, 0.0), "PZ": (1.0, 1.0)},
    )
    regenerated = run_frequency_domain_qc_review(project)
    assert regenerated["technical_integrity_failed"] is False
    assert regenerated["qc_complete"] is True
    assert regenerated["technical_integrity_failures"] == []
    assert regenerated["flags"][0]["summed_bca_uv"] == 300.0


@pytest.mark.parametrize(
    ("invalid_value", "expected_category"),
    (
        (None, "blank"),
        ("NaN", "nan"),
        ("INF", "positive_infinity"),
        ("-INF", "negative_infinity"),
    ),
)
def test_selected_cell_invalid_categories_are_diagnostic(
    tmp_path,
    invalid_value: object,
    expected_category: str,
) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": (1.0, invalid_value), "PZ": (1.0, 1.0)},
    )

    report = run_frequency_domain_qc_review(project)

    assert report["technical_integrity_failed"] is True
    assert report["technical_integrity_failures"][0]["value_category"] == (
        expected_category
    )


def test_all_invalid_selected_cells_produce_no_partial_score(tmp_path) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": ("bad", "NaN"), "PZ": (1.0, 1.0)},
    )

    report = run_frequency_domain_qc_review(project)

    failures = report["technical_integrity_failures"]
    assert [item["harmonic_column"] for item in failures] == [
        "1.2000_Hz",
        "2.4000_Hz",
    ]
    assert report["flags"] == []
    assert report["auto_participant_electrode_exclusions"] == []


def test_fixed_selected_method_unavailability_does_not_partial_sum_or_fail_qc10(
    tmp_path,
) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": (300.0, None), "PZ": (1.0, 1.0)},
        audit_rows=[
            {
                "Electrode": "O2",
                "Target Frequency Exact (Hz)": "12/5",
                "BCA Status": "unavailable",
                "Reason Codes": "target_inside_applied_notch",
            }
        ],
    )

    report = run_frequency_domain_qc_review(project)

    assert report["qc_complete"] is True
    assert report["technical_integrity_failed"] is False
    assert report["technical_integrity_failures"] == []
    assert report["flags"] == []
    assert report["unavailable_by_method"] == [
        {
            "participant_id": "P1",
            "condition": "CondA",
            "workbook_path": str(
                project.project_root
                / "1 - Excel Data Files"
                / "CondA"
                / "P1_CondA_Results.xlsx"
            ),
            "electrode": "O2",
            "worksheet_row": 2,
            "harmonic_hz": 2.4,
            "harmonic_column": "2.4000_Hz",
            "status": "unavailable_by_method",
            "reason_codes": ["target_inside_applied_notch"],
        }
    ]


def test_nonfinite_spectral_audit_reason_is_qc10_failure(tmp_path) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": (1.0, None), "PZ": (1.0, 1.0)},
        audit_rows=[
            {
                "Electrode": "O2",
                "Target Frequency Exact (Hz)": "12/5",
                "BCA Status": "unavailable",
                "Reason Codes": "nonfinite_noise_support",
            }
        ],
    )

    report = run_frequency_domain_qc_review(project)

    assert report["technical_integrity_failed"] is True
    assert report["unavailable_by_method"] == []
    failure = report["technical_integrity_failures"][0]
    assert failure["failure_type"] == "spectral_metric_input_nonfinite"
    assert failure["reason_codes"] == ["nonfinite_noise_support"]


def test_local_z_only_unavailability_does_not_invalidate_finite_bca(tmp_path) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": (300.0, -300.0), "PZ": (1.0, 1.0)},
        audit_rows=[
            {
                "Electrode": "O2",
                "Target Frequency Exact (Hz)": "12/5",
                "BCA Status": "available",
                "Reason Codes": "nonfinite_noise_population_sd",
            }
        ],
    )

    report = run_frequency_domain_qc_review(project)

    assert report["qc_complete"] is True
    assert report["technical_integrity_failures"] == []
    assert report["unavailable_by_method"] == []
    assert report["flags"] == []


def test_complete_signed_cancellation_remains_a_finite_score(tmp_path) -> None:
    project, _ = _make_project(
        tmp_path,
        {"O2": (300.0, -300.0), "PZ": (1.0, 1.0)},
    )

    report = run_frequency_domain_qc_review(project)

    assert report["qc_complete"] is True
    assert report["technical_integrity_failures"] == []
    assert report["flags"] == []


def test_integrity_failure_cannot_reuse_prior_scientific_review(tmp_path) -> None:
    project, workbook_path = _make_project(
        tmp_path,
        {"O2": (150.0, 150.0), "PZ": (1.0, 1.0)},
    )
    initial = run_frequency_domain_qc_review(project)
    assert initial["review_required"] is True
    apply_frequency_domain_qc_decision(project.project_root, initial)

    _write_workbook(
        workbook_path,
        {"O2": (150.0, "bad"), "PZ": (1.0, 1.0)},
    )
    damaged = run_frequency_domain_qc_review(project)

    assert damaged["technical_integrity_failed"] is True
    assert damaged["review_reused"] is False
    assert damaged["review_required"] is False
    assert damaged["auto_participant_electrode_exclusions"] == []


def _make_project(
    tmp_path,
    electrode_values: Mapping[str, Sequence[object]],
    *,
    audit_rows: Sequence[Mapping[str, object]] = (),
) -> tuple[Project, object]:
    root = tmp_path / "Project"
    project = Project.load(root)
    project.event_map = {"CondA": 1}
    preprocessing = dict(project.preprocessing)
    preprocessing.update(
        {
            "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
            "harmonic_selection_profile": FIXED_HARMONIC_SELECTION_PROFILE,
            "harmonic_selection_profile_version": HARMONIC_SELECTION_PROFILE_VERSION,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            "fixed_harmonic_auto_exclude_base": True,
        }
    )
    project.update_preprocessing(preprocessing)
    project.save()
    workbook_path = (
        root
        / "1 - Excel Data Files"
        / "CondA"
        / "P1_CondA_Results.xlsx"
    )
    _write_workbook(workbook_path, electrode_values, audit_rows=audit_rows)
    return project, workbook_path


def _write_workbook(
    path,
    electrode_values: Mapping[str, Sequence[object]],
    *,
    audit_rows: Sequence[Mapping[str, object]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bca = pd.DataFrame(
        [
            {
                "Electrode": electrode,
                "1.2000_Hz": values[0],
                "2.4000_Hz": values[1],
            }
            for electrode, values in electrode_values.items()
        ]
    )
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        if audit_rows:
            pd.DataFrame(audit_rows).to_excel(
                writer,
                sheet_name="Spectral Metric QC",
                index=False,
            )
