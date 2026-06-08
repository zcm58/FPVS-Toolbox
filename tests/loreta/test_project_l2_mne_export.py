from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.gui import resolve_loreta_import_start_dir
from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_manifest_json
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    PROJECT_L2_MNE_BETA_OUTPUT_FOLDER,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    _surface_source_points_and_faces,
    default_project_l2_mne_output_dir,
    write_project_l2_mne_cortical_surface_payloads,
)


def test_project_l2_mne_export_writes_manifest_and_payloads_under_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = write_project_l2_mne_cortical_surface_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
    )

    assert result.output_dir == default_project_l2_mne_output_dir(project_root)
    assert result.manifest_path.is_file()
    assert result.producer_result.manifest_validation.label == validate_prepared_source_manifest_json(
        result.manifest_path,
        require_payload_files=True,
    ).label
    assert len(result.producer_result.payloads) == 2
    assert result.project_inputs.selected_harmonics_hz == (2.4, 4.8)

    raw_manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert raw_manifest["label"] == "L2-MNE cortical-surface beta source maps"
    assert [entry["label"] for entry in raw_manifest["conditions"]] == ["Condition A", "Condition B"]

    first_payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    metadata = first_payload["metadata"]
    assert first_payload["coordinate_space"] == "fsaverage_surface"
    assert metadata["config_project_integration"] == "phase_6c_project_l2_mne_beta"
    assert metadata["config_project_root_name"] == "Project"
    assert metadata["config_source_topography_metric"] == "bca"
    assert metadata["condition_project_input_assembly"] == "phase_6b_read_only"


def test_project_l2_mne_export_rejects_outputs_outside_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    with pytest.raises(ValueError, match="inside the project root"):
        write_project_l2_mne_cortical_surface_payloads(
            project_root=project_root,
            output_dir=tmp_path / "outside",
            forward_model=_tiny_forward_model(),
        )


def test_loreta_import_dialog_prefers_last_dir_then_project_source_dir(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    source_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_BETA_OUTPUT_FOLDER
    source_dir.mkdir(parents=True)
    last_dir = tmp_path / "last"
    last_dir.mkdir()

    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=last_dir) == str(last_dir)
    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=None) == str(source_dir)

    source_dir.rmdir()
    source_dir.parent.rmdir()
    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=None) == str(project_root)
    assert resolve_loreta_import_start_dir(project_root=None, last_import_dir=None) == ""


def test_source_points_use_native_coordinate_source_space_not_forward_head_space() -> None:
    forward_space = {
        "vertno": np.asarray([0, 1, 2], dtype=np.int64),
        "rr": np.asarray(
            [
                [10.0, 10.0, 10.0],
                [20.0, 20.0, 20.0],
                [30.0, 30.0, 30.0],
            ],
            dtype=float,
        ),
        "use_tris": np.asarray([[0, 1, 2]], dtype=np.int64),
    }
    native_space = {
        "vertno": np.asarray([0, 1, 2], dtype=np.int64),
        "rr": np.asarray(
            [
                [-0.040, -0.090, 0.020],
                [0.000, -0.100, 0.030],
                [0.040, -0.090, 0.020],
            ],
            dtype=float,
        ),
    }

    points, faces, counts = _surface_source_points_and_faces(
        [forward_space],
        coordinate_source_spaces=[native_space],
    )

    assert np.allclose(
        points,
        np.asarray(
            [
                [-40.0, -90.0, 20.0],
                [0.0, -100.0, 30.0],
                [40.0, -90.0, 20.0],
            ]
        ),
    )
    assert np.array_equal(faces, np.asarray([[0, 1, 2]], dtype=np.int64))
    assert counts == (3,)


def _tiny_forward_model() -> L2MNECorticalForwardModel:
    leadfield = np.vstack(
        [
            np.linspace(0.1 + channel * 0.01, 0.4 + channel * 0.01, 4)
            for channel in range(len(DEFAULT_ELECTRODE_NAMES_64))
        ]
    )
    return L2MNECorticalForwardModel(
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        source_points=np.asarray(
            [
                [-40.0, -80.0, 20.0],
                [-10.0, -90.0, 32.0],
                [10.0, -90.0, 32.0],
                [40.0, -80.0, 20.0],
            ],
            dtype=float,
        ),
        leadfield=leadfield,
        faces=np.asarray([[0, 1, 2], [1, 3, 2]], dtype=np.int64),
        metadata={"fixture": True, "forward_model_status": "tiny test model"},
    )


def _build_project_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "Project"
    stats_dir = project_root / "3 - Statistical Analysis Results"
    excel_root = project_root / "1 - Excel Data Files"
    stats_dir.mkdir(parents=True)
    excel_root.mkdir(parents=True)
    _write_stats_ready(stats_dir / "Stats_Ready_Summed_BCA.xlsx")
    pd.DataFrame({"participant_id": [], "exclusion_reason": []}).to_excel(
        stats_dir / "Excluded Participants.xlsx",
        sheet_name="Excluded Participants",
        index=False,
    )
    pd.DataFrame({"participant_id": [], "flag_types": []}).to_excel(
        stats_dir / "Flagged Participants.xlsx",
        sheet_name="Flag Summary",
        index=False,
    )
    for condition, base in (("Condition A", 10.0), ("Condition B", 100.0)):
        condition_dir = excel_root / condition
        condition_dir.mkdir()
        for subject_offset, subject in enumerate(("SCP1", "SCP2")):
            _write_participant_workbook(
                condition_dir / f"{subject}_{condition}_Results.xlsx",
                base=base + subject_offset,
            )
    return project_root


def _write_stats_ready(path: Path) -> None:
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            {
                "condition": ["Condition A", "Condition A", "Condition B", "Condition B"],
                "subject_id": ["P1", "P2", "P1", "P2"],
                "roi": ["ROI"] * 4,
                "summed_bca_uv": [1.0, 2.0, 3.0, 4.0],
            }
        ).to_excel(writer, sheet_name="Long_Format", index=False)
        pd.DataFrame(
            {
                "harmonic_hz": [1.2, 2.4, 4.8],
                "selected": [False, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)


def _write_participant_workbook(path: Path, *, base: float) -> None:
    bca = pd.DataFrame(
        {
            "Electrode": DEFAULT_ELECTRODE_NAMES_64,
            "2.4000_Hz": [base + index for index in range(64)],
            "4.8000_Hz": [base + 10.0 + index for index in range(64)],
        }
    )
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
