from __future__ import annotations

import pandas as pd

from Main_App.processing.frequency_domain_qc import (
    WARNING_REASON_UNUSUAL_VALUES,
    active_frequency_domain_exclusions,
    apply_frequency_domain_qc_decision,
    clear_manual_frequency_domain_participant_exclusions,
    mark_frequency_domain_outputs_current,
    run_frequency_domain_qc_review,
    sync_frequency_domain_qc_automatic_state,
)
from Main_App.projects.project import Project
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME
from Tools.Stats.analysis.dv_policies import prepare_summed_bca_data


def test_frequency_domain_qc_persists_hard_electrode_and_reuses_review(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)

    assert report["review_required"] is True
    assert report["review_reused"] is False
    assert report["auto_participant_exclusions"] == []
    assert report["auto_participant_electrode_exclusions"] == [
        {
            "participant_id": "P1",
            "electrode": "O2",
            "reason": "abs summed BCA exceeded hard electrode threshold",
            "threshold_uv": 250.0,
            "max_abs_summed_bca_uv": 300.0,
            "triggering_conditions": ["CondA"],
            "source": "automatic_frequency_domain_qc",
        }
    ]

    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        manual_participant_reasons={"P1": WARNING_REASON_UNUSUAL_VALUES},
    )
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.auto_excluded_electrodes_by_participant["P1"] == frozenset({"O2"})
    assert exclusions.manual_excluded_participants == frozenset({"P1"})
    assert exclusions.downstream_outputs_stale is True

    reviewed = run_frequency_domain_qc_review(project)
    assert reviewed["review_required"] is False
    assert reviewed["review_reused"] is True
    assert (project.project_root / "Quality Check" / "Frequency_Domain_QC_Review.txt").is_file()


def test_frequency_domain_qc_clear_manual_marks_outputs_stale(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        manual_participant_reasons={"P1": WARNING_REASON_UNUSUAL_VALUES},
    )

    cleared = clear_manual_frequency_domain_participant_exclusions(
        project.project_root,
        ["P1"],
    )

    assert cleared == ["P1"]
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.manual_excluded_participants == frozenset()
    assert exclusions.downstream_outputs_stale is True


def test_frequency_domain_qc_sync_clears_stale_automatic_exclusions(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(project.project_root, report)
    mark_frequency_domain_outputs_current(project.project_root)

    _write_bca_workbook(
        project.project_root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    clean_report = run_frequency_domain_qc_review(project)

    assert clean_report["review_required"] is False
    assert clean_report["auto_participant_electrode_exclusions"] == []

    sync_frequency_domain_qc_automatic_state(project.project_root, clean_report)

    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.auto_excluded_electrodes_by_participant == {}
    assert exclusions.auto_excluded_participants == frozenset()
    assert exclusions.downstream_outputs_stale is True


def test_summed_bca_drops_frequency_domain_excluded_electrode(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(project.project_root, report)

    subject_data = {
        "P1": {
            "CondA": str(
                project.project_root
                / "1 - Excel Data Files"
                / "CondA"
                / "P1_CondA_Results.xlsx"
            )
        },
        "P2": {
            "CondA": str(
                project.project_root
                / "1 - Excel Data Files"
                / "CondA"
                / "P2_CondA_Results.xlsx"
            )
        },
    }
    data = prepare_summed_bca_data(
        subjects=["P1", "P2"],
        conditions=["CondA"],
        subject_data=subject_data,
        base_freq=6.0,
        log_func=lambda _message: None,
        rois={"Right OT": ["O2", "PZ"]},
        dv_policy={
            "name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            "fixed_harmonic_auto_exclude_base": True,
        },
        project_root=str(project.project_root),
    )

    assert data is not None
    assert data["P1"]["CondA"]["Right OT"] == 2.0
    assert data["P2"]["CondA"]["Right OT"] == 2.0


def _make_project(tmp_path):
    root = tmp_path / "Project"
    project = Project.load(root)
    project.event_map = {"CondA": 1, "CondB": 2}
    payload = dict(project.preprocessing)
    payload.update(
        {
            "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            "fixed_harmonic_auto_exclude_base": True,
        }
    )
    project.update_preprocessing(payload)
    project.save()

    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx",
        {"O2": (150.0, 150.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondB" / "P1_CondB_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondA" / "P2_CondA_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondB" / "P2_CondB_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    return project


def _write_bca_workbook(path, electrode_values):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
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
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)
