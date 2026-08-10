from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import load_workbook

import Main_App.exports.analysis_ready_workbook as export_module
from Main_App.exports.analysis_ready_workbook import (
    ANALYSIS_READY_WORKBOOK_NAME,
    write_analysis_ready_workbook,
)
from Main_App.projects import load_project_dataset_index


def _write_project(root: Path) -> None:
    anxious_raw = root / "Raw" / "Anxious"
    non_anxious_raw = root / "Raw" / "NonAnxious"
    anxious_raw.mkdir(parents=True)
    non_anxious_raw.mkdir(parents=True)
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {
            "anxious": {
                "label": "anxious",
                "folder_name": "Anxious",
                "raw_input_folder": str(anxious_raw),
            },
            "non_anxious": {
                "label": "non-anxious",
                "folder_name": "NonAnxious",
                "raw_input_folder": str(non_anxious_raw),
            },
        },
        "participants": {
            "P1": {"group_id": "anxious"},
            "P2": {"group_id": "non_anxious"},
        },
        "preprocessing": {
            "manual_excluded_participant_conditions": {
                "P2": ["Condition A"],
            }
        },
        "tools": {
            "frequency_domain_qc": {
                "auto_participant_electrode_exclusions": [
                    {
                        "participant_id": "P1",
                        "electrode": "O2",
                        "reason": "test electrode flag",
                        "triggering_conditions": ["Condition A"],
                    }
                ],
                "auto_participant_exclusions": [
                    {
                        "participant_id": "P2",
                        "reason": "test participant flag",
                    }
                ],
            }
        },
    }
    (root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def _write_bca_workbook(
    root: Path,
    *,
    pid: str,
    condition: str,
    group_folder: str,
    values: list[tuple[str, float, float]],
) -> Path:
    folder = root / "1 - Excel Data Files" / condition / group_folder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pid}_{condition}_Results.xlsx"
    frame = pd.DataFrame(
        values,
        columns=["Electrode", "1.2000_Hz", "2.4000_Hz"],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)
    return path


def _selection_metadata() -> dict[str, object]:
    return {
        "harmonic_policy": "group_significant_harmonics",
        "selected_harmonics_hz": [1.2, 2.4],
        "selection_rows": [
            {
                "target_frequency_hz": 1.2,
                "z_score": 3.0,
                "selected": True,
                "included_in_summation": True,
                "excluded_base_rate": False,
            },
            {
                "target_frequency_hz": 2.4,
                "z_score": 2.5,
                "selected": True,
                "included_in_summation": True,
                "excluded_base_rate": False,
            },
        ],
    }


def _build_fixture_project(root: Path) -> None:
    _write_project(root)
    _write_bca_workbook(
        root,
        pid="P1",
        condition="Condition A",
        group_folder="Anxious",
        values=[("O1", 1.0, 2.0), ("O2", 3.0, 4.0), ("Cz", 5.0, 6.0)],
    )
    _write_bca_workbook(
        root,
        pid="P1",
        condition="Condition B",
        group_folder="Anxious",
        values=[("O1", 1.0, 1.0), ("O2", 2.0, 2.0), ("Cz", 3.0, 3.0)],
    )
    _write_bca_workbook(
        root,
        pid="P2",
        condition="Condition A",
        group_folder="NonAnxious",
        values=[("O1", 2.0, 2.0), ("O2", 4.0, 4.0), ("Cz", 6.0, 6.0)],
    )


def test_full_audit_workbook_keeps_excluded_values_and_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "Project"
    _build_fixture_project(root)
    index = load_project_dataset_index(root)
    assert {record.participant_id for record in index.workbooks} == {"P1"}
    assert {record.participant_id for record in index.excluded_workbooks} == {"P2"}
    monkeypatch.setattr(
        export_module,
        "_load_active_rois",
        lambda: {"LOT": ["O1"], "ROT": ["O2"], "Central": ["CZ"]},
    )

    result = write_analysis_ready_workbook(
        root,
        dataset_index=index,
        selection_metadata=_selection_metadata(),
    )

    assert result.workbook_path.name == ANALYSIS_READY_WORKBOOK_NAME
    assert result.roi_row_count == 9
    assert result.participant_count == 2
    assert result.condition_count == 2
    assert result.flag_count >= 3

    roi_long = pd.read_excel(result.workbook_path, sheet_name="ROI Long")
    assert list(roi_long.columns) == [
        "PID",
        "Group",
        "Condition",
        "ROI",
        "Raw Summed BCA",
        "RMS Normalized BCA",
        "Signed Mean Normalized BCA",
        "Current Toolbox Exclusion",
        "QC Flag",
        "QC Notes",
    ]
    excluded = roi_long.loc[roi_long["PID"].eq("P2")]
    assert len(excluded) == 3
    assert set(excluded["Group"]) == {"non-anxious"}
    assert set(excluded["Current Toolbox Exclusion"]) == {"Yes"}
    assert set(excluded["Raw Summed BCA"]) == {4.0, 8.0, 12.0}

    p1_rot = roi_long.loc[
        roi_long["PID"].eq("P1") & roi_long["Condition"].eq("Condition A") & roi_long["ROI"].eq("ROT")
    ].iloc[0]
    assert p1_rot["Group"] == "anxious"
    assert p1_rot["Raw Summed BCA"] == pytest.approx(7.0)
    assert p1_rot["Current Toolbox Exclusion"] == "Yes"
    assert "O2" in p1_rot["QC Notes"]
    assert p1_rot["RMS Normalized BCA"] == pytest.approx(7.0 / math.sqrt((3.0**2 + 7.0**2 + 11.0**2) / 3.0))
    assert p1_rot["Signed Mean Normalized BCA"] == pytest.approx(1.0)

    electrodes = pd.read_excel(result.workbook_path, sheet_name="Electrode Long")
    flagged_o2 = electrodes.loc[
        electrodes["PID"].eq("P1") & electrodes["Condition"].eq("Condition A") & electrodes["Electrode"].eq("O2")
    ].iloc[0]
    assert flagged_o2["Raw Summed BCA"] == pytest.approx(7.0)
    assert flagged_o2["Current Toolbox Exclusion"] == "Yes"

    wide = pd.read_excel(result.workbook_path, sheet_name="Raw BCA Wide")
    p2_wide = wide.loc[wide["PID"].eq("P2")].iloc[0]
    assert pd.isna(p2_wide["Condition B | LOT"])
    assert p2_wide["Condition A | ROT"] == pytest.approx(8.0)

    workbook = load_workbook(result.workbook_path)
    assert workbook.sheetnames == [
        "ROI Long",
        "Raw BCA Wide",
        "RMS Normalized Wide",
        "Signed Mean Normalized Wide",
        "Electrode Long",
        "Whole Scalp Values",
        "QC Flags",
        "ROI Definitions",
        "Selection Summary",
        "Harmonic Selection",
        "Analysis Notes",
    ]
    sheet = workbook["ROI Long"]
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].fill.fgColor.rgb in {"00595959", "FF595959"}
    assert sheet["A2"].fill.fgColor.rgb in {"00F2F2F2", "FFF2F2F2"}
    assert sheet["A2"].alignment.horizontal == "center"
    assert all("path" not in str(cell.value or "").casefold() for cell in sheet[1])


def test_full_audit_export_rejects_index_for_another_project(tmp_path: Path) -> None:
    wrong_index = SimpleNamespace(project_root=tmp_path / "Other Project")

    with pytest.raises(ValueError, match="different project root"):
        write_analysis_ready_workbook(tmp_path, dataset_index=wrong_index)


def test_atomic_writer_preserves_previous_workbook_when_rebuild_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "analysis.xlsx"
    target.write_bytes(b"previous complete workbook")

    class _FailingWriter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise RuntimeError("simulated write failure")

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(export_module.pd, "ExcelWriter", _FailingWriter)

    with pytest.raises(RuntimeError, match="simulated write failure"):
        export_module._write_frames_atomically(
            target,
            {"ROI Long": pd.DataFrame({"PID": ["P1"]})},
        )

    assert target.read_bytes() == b"previous complete workbook"
    assert not list(tmp_path.glob("*.tmp.xlsx"))
