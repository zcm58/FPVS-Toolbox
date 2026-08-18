from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.exports.analysis_ready_workbook import ROI_LONG_SHEET
from Tools.Stats.analysis.repeated_session_contracts import (
    FIXED_ORDER_CONFOUNDING,
)
from Tools.Stats.io.repeated_session_project import (
    REPEATED_SESSION_RESULTS_WORKBOOK,
    analyze_repeated_session_project,
    load_repeated_session_project_data,
    write_repeated_session_results_workbook,
)


def _write_project(root: Path) -> Path:
    root.mkdir()
    manifest = {
        "schema_version": "2.2.0",
        "name": "Repeated project",
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {
            "birth_control": {
                "label": "Birth control",
                "folder_name": "Birth Control",
                "raw_input_folder": "Raw/Birth Control",
            },
            "control": {
                "label": "No birth control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
        },
        "sessions": {
            "luteal": {"label": "Luteal (visit 1)", "visit_index": 1},
            "follicular": {
                "label": "Follicular (visit 2)",
                "visit_index": 2,
            },
        },
        "recording_sources": {
            "bc_luteal": {
                "group_id": "birth_control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Birth Control/Luteal",
            },
            "bc_follicular": {
                "group_id": "birth_control",
                "session_id": "follicular",
                "raw_input_folder": "Raw/Birth Control/Follicular",
            },
            "control_luteal": {
                "group_id": "control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Control/Luteal",
            },
            "control_follicular": {
                "group_id": "control",
                "session_id": "follicular",
                "raw_input_folder": "Raw/Control/Follicular",
            },
        },
        "participants": {
            "B1": {"group_id": "birth_control"},
            "B2": {"group_id": "birth_control"},
            "C1": {"group_id": "control"},
            "C2": {"group_id": "control"},
        },
        "recordings": {
            f"{participant}__{session}": {
                "participant_id": participant,
                "session_id": session,
                "source_id": (
                    f"{'bc' if participant.startswith('B') else 'control'}_"
                    f"{session}"
                ),
                "raw_file": (
                    "Raw/"
                    f"{'Birth Control' if participant.startswith('B') else 'Control'}/"
                    f"{'Luteal' if session == 'luteal' else 'Follicular'}/"
                    f"{participant}_{session}.bdf"
                ),
                "visit_index": 1 if session == "luteal" else 2,
            }
            for participant in ("B1", "B2", "C1", "C2")
            for session in ("luteal", "follicular")
        },
    }
    (root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root


def _audit_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        "B1": (1.0, 1.5),
        "B2": (2.0, 2.8),
        "C1": (1.2, 1.3),
        "C2": (1.8, 1.7),
    }
    for participant, (first, second) in values.items():
        group_id = "birth_control" if participant.startswith("B") else "control"
        group_label = "Birth control" if group_id == "birth_control" else "No birth control"
        for session_id, session_label, visit, value in (
            ("luteal", "Luteal (visit 1)", 1, first),
            ("follicular", "Follicular (visit 2)", 2, second),
        ):
            rows.append(
                {
                    "PID": participant,
                    "Recording ID": f"{participant}__{session_id}",
                    "Session ID": session_id,
                    "Session": session_label,
                    "Visit Index": visit,
                    "Days From Baseline": 0 if visit == 1 else 14,
                    "Group ID": group_id,
                    "Group": group_label,
                    "Condition": "Angry",
                    "ROI": "Occipital",
                    "Raw Summed BCA": value,
                    "Current Toolbox Exclusion": "No",
                    "QC Flag": "No",
                    "QC Notes": "",
                }
            )
    return pd.DataFrame(rows)


def test_project_adapter_loads_canonical_audit_and_writes_results(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path / "Project")
    source = project_root / "analysis-ready.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        _audit_rows().to_excel(writer, sheet_name=ROI_LONG_SHEET, index=False)

    project_data = load_repeated_session_project_data(
        project_root,
        analysis_ready_workbook=source,
    )
    assert project_data.contract.group_ids == ("birth_control", "control")
    assert project_data.contract.session_ids == ("luteal", "follicular")
    assert project_data.available_outcomes[0].condition == "Angry"
    assert set(project_data.data["days_from_baseline"]) == {0.0, 14.0}
    coverage = project_data.recording_pair_coverage().set_index("group_id")
    assert coverage.loc["birth_control", "n_complete_recording_pairs"] == 2
    assert coverage.loc["control", "n_complete_recording_pairs"] == 2

    result = analyze_repeated_session_project(
        project_data,
        outcomes=project_data.available_outcomes,
    )
    primary = result.primary_results.iloc[0]
    assert primary["n_pairs_group_a"] == 2
    assert primary["n_pairs_group_b"] == 2
    assert primary["fixed_order_confounding"] == FIXED_ORDER_CONFOUNDING

    destination = project_root / REPEATED_SESSION_RESULTS_WORKBOOK
    written = write_repeated_session_results_workbook(
        result,
        source_data=project_data.data,
        contract=project_data.contract,
        destination=destination,
    )
    assert written == destination
    assert written.is_file()
    sheets = pd.ExcelFile(written).sheet_names
    assert "Repeated Session Primary" in sheets
    assert "Session Pair Coverage" in sheets
    assert "Repeated Session Long" in sheets


def test_project_adapter_rejects_legacy_full_audit_shape(tmp_path: Path) -> None:
    project_root = _write_project(tmp_path / "Project")
    source = project_root / "legacy-audit.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame([{"PID": "B1"}]).to_excel(
            writer,
            sheet_name=ROI_LONG_SHEET,
            index=False,
        )

    with pytest.raises(ValueError, match="not session-aware"):
        load_repeated_session_project_data(
            project_root,
            analysis_ready_workbook=source,
        )


def test_project_adapter_rejects_noncanonical_recording_identity(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path / "Project")
    source = project_root / "foreign-audit.xlsx"
    rows = _audit_rows()
    rows.loc[0, "Recording ID"] = "B1__foreign"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        rows.to_excel(writer, sheet_name=ROI_LONG_SHEET, index=False)

    with pytest.raises(ValueError, match="unknown recording_id 'B1__foreign'"):
        load_repeated_session_project_data(
            project_root,
            analysis_ready_workbook=source,
        )


def test_recording_pair_coverage_keeps_manifest_participants_without_rows(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path / "Project")
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["participants"]["B3"] = {"group_id": "birth_control"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    source = project_root / "analysis-ready.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        _audit_rows().to_excel(writer, sheet_name=ROI_LONG_SHEET, index=False)

    project_data = load_repeated_session_project_data(
        project_root,
        analysis_ready_workbook=source,
    )
    coverage = project_data.recording_pair_coverage().set_index("group_id")

    assert coverage.loc["birth_control", "n_participants"] == 3
    assert coverage.loc["birth_control", "n_complete_recording_pairs"] == 2
    assert coverage.loc["birth_control", "n_missing_visit_1_recording"] == 1
    assert coverage.loc["birth_control", "n_missing_visit_2_recording"] == 1
