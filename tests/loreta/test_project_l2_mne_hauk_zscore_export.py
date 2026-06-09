from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_manifest_json
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
    ProjectFullFftInputError,
    build_l2_mne_hauk_participant_zscore_conditions_from_project,
    build_l2_mne_hauk_zscore_conditions_from_project,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
    PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
    PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST,
    default_project_l2_mne_hauk_zscore_output_dir,
    write_project_l2_mne_hauk_zscore_payloads,
)


def test_project_fullfft_assembler_reads_neighboring_bins(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_hauk_zscore_conditions_from_project(
        project_root,
        conditions=["Condition A"],
        noise_window_bins=3,
        min_noise_bins=4,
    )

    assert result.sheet_name == "FullFFT Amplitude (uV)"
    assert result.selected_harmonics_hz == (2.4, 4.8)
    assert result.bin_plan.noise_window_bins == 3
    assert [condition.label for condition in result.conditions] == ["Condition A"]
    condition = result.conditions[0]
    harmonic = condition.harmonic_bins[2.4]
    assert harmonic.target_column == "2.4000_Hz"
    assert tuple(harmonic.noise_topographies_by_offset) == (-3, -2, 2, 3)
    expected_target = _expected_fullfft_values(condition_base=10.0, frequency_hz=2.4, subject_mean=0.5)
    assert np.allclose(harmonic.target_topography, expected_target)
    expected_noise = _expected_fullfft_values(condition_base=10.0, frequency_hz=2.2, subject_mean=0.5)
    assert np.allclose(harmonic.noise_topographies_by_offset[-2], expected_noise)


def test_project_fullfft_participant_assembler_preserves_subject_maps(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_hauk_participant_zscore_conditions_from_project(
        project_root,
        conditions=["Condition A"],
        noise_window_bins=3,
        min_noise_bins=4,
    )

    assert [condition.label for condition in result.conditions] == ["Condition A"]
    condition = result.conditions[0]
    assert [participant.participant_id for participant in condition.participants] == ["P1", "P2"]
    first_harmonic = condition.participants[0].condition.harmonic_bins[2.4]
    second_harmonic = condition.participants[1].condition.harmonic_bins[2.4]
    assert np.allclose(
        first_harmonic.target_topography,
        _expected_fullfft_values(condition_base=10.0, frequency_hz=2.4, subject_mean=0.0),
    )
    assert np.allclose(
        second_harmonic.target_topography,
        _expected_fullfft_values(condition_base=10.0, frequency_hz=2.4, subject_mean=1.0),
    )
    assert condition.metadata["project_input_assembly"] == "phase_6h_a2_fullfft_participant_neighbor_bins_read_only"


def test_project_hauk_zscore_export_writes_manifest_under_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = write_project_l2_mne_hauk_zscore_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
        noise_window_bins=3,
        min_noise_bins=4,
    )

    assert result.output_dir == default_project_l2_mne_hauk_zscore_output_dir(project_root)
    assert result.manifest_path.is_file()
    assert result.export_model == PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST
    assert result.participant_sidecar_path is not None
    assert result.participant_sidecar_path.is_file()
    assert result.producer_result.manifest_validation.label == validate_prepared_source_manifest_json(
        result.manifest_path,
        require_payload_files=True,
    ).label
    assert len(result.producer_result.payloads) == 6

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["label"] == "L2-MNE participant-first source-space z-score maps"
    assert manifest["metadata"]["participant_sidecar_file"] == result.participant_sidecar_path.name
    assert [entry["metadata"]["participant_zscore_aggregation"] for entry in manifest["conditions"][:3]] == [
        "mean",
        "median",
        "trimmed_mean",
    ]
    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    metadata = payload["metadata"]
    assert payload["source_model"] == "l2_mne_fsaverage_participant_zscore_mean"
    assert metadata["source_value_unit"] == "z-score"
    assert metadata["source_map_model"] == "participant_first"
    assert metadata["participant_zscore_aggregation"] == "mean"
    assert metadata["config_project_integration"] == "phase_6h_a2_project_l2_mne_participant_first_hauk_zscore"
    assert metadata["condition_project_input_assembly"] == "phase_6h_a2_fullfft_participant_neighbor_bins_read_only"
    assert metadata["cluster_mask"] == "none"
    sidecar = json.loads(result.participant_sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["conditions"][0]["participant_count"] == 2


def test_project_hauk_zscore_export_keeps_deprecated_group_first_opt_in(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = write_project_l2_mne_hauk_zscore_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
        noise_window_bins=3,
        min_noise_bins=4,
        zscore_model=PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
    )

    assert result.export_model == PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST
    assert result.participant_sidecar_path is None
    assert len(result.producer_result.payloads) == 2
    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    assert payload["source_model"] == "l2_mne_cortical_surface_hauk_zscore_beta"
    assert payload["metadata"]["source_map_model"] == "deprecated_group_first"
    assert payload["metadata"]["deprecated_model"] is True


def test_project_hauk_zscore_export_reports_progress(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)
    messages: list[str] = []

    write_project_l2_mne_hauk_zscore_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
        noise_window_bins=3,
        min_noise_bins=4,
        progress_callback=messages.append,
    )

    assert any("Reading participant FullFFT workbooks" in message for message in messages)
    assert any("Prepared participant-level source inputs for 2 condition" in message for message in messages)
    assert any("Using supplied L2-MNE inverse model" in message for message in messages)
    assert any("L2-MNE inverse model is ready" in message for message in messages)
    assert any("Computing participant source z-scores for condition 1/2" in message for message in messages)
    assert any("Writing participant source-map sidecar" in message for message in messages)
    assert any("Writing source-map manifest" in message for message in messages)
    assert any("Source-map JSON export complete" in message for message in messages)


def test_project_hauk_zscore_export_reads_group_subfolder_workbooks(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, group_subfolders=True)

    result = write_project_l2_mne_hauk_zscore_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
        noise_window_bins=3,
        min_noise_bins=4,
    )

    assert result.manifest_path.is_file()
    assert len(result.producer_result.payloads) == 6
    assert result.project_inputs.summaries[0].workbook_count == 2


def test_project_hauk_zscore_rejects_outputs_outside_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    with pytest.raises(ValueError, match="inside the project root"):
        write_project_l2_mne_hauk_zscore_payloads(
            project_root=project_root,
            output_dir=tmp_path / "outside",
            forward_model=_tiny_forward_model(),
            noise_window_bins=3,
            min_noise_bins=4,
        )


def test_project_hauk_zscore_rejects_bca_only_workbooks(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, include_fullfft=False)

    with pytest.raises(ProjectFullFftInputError, match="requires the 'FullFFT Amplitude"):
        build_l2_mne_hauk_zscore_conditions_from_project(
            project_root,
            noise_window_bins=3,
            min_noise_bins=4,
        )


def _tiny_forward_model() -> L2MNECorticalForwardModel:
    leadfield = np.vstack(
        [
            np.asarray([0.1 + channel * 0.01, 0.3 + channel * 0.02, 0.5 + channel * 0.03], dtype=float)
            for channel in range(len(DEFAULT_ELECTRODE_NAMES_64))
        ]
    )
    return L2MNECorticalForwardModel(
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        source_points=np.asarray(
            [
                [-40.0, -80.0, 20.0],
                [0.0, -90.0, 32.0],
                [40.0, -80.0, 20.0],
            ],
            dtype=float,
        ),
        leadfield=leadfield,
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata={"fixture": True, "forward_model_status": "tiny test model"},
    )


def _build_project_fixture(
    tmp_path: Path,
    *,
    include_fullfft: bool = True,
    group_subfolders: bool = False,
) -> Path:
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
        workbook_dir = condition_dir / "Default" if group_subfolders else condition_dir
        workbook_dir.mkdir(exist_ok=True)
        for subject_offset, subject in enumerate(("SCP1", "SCP2")):
            _write_participant_workbook(
                workbook_dir / f"{subject}_{condition}_Results.xlsx",
                base=base,
                subject_offset=subject_offset,
                include_fullfft=include_fullfft,
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


def _write_participant_workbook(
    path: Path,
    *,
    base: float,
    subject_offset: int,
    include_fullfft: bool,
) -> None:
    bca = pd.DataFrame(
        {
            "Electrode": DEFAULT_ELECTRODE_NAMES_64,
            "2.4000_Hz": [base + index for index in range(64)],
            "4.8000_Hz": [base + 10.0 + index for index in range(64)],
        }
    )
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        if include_fullfft:
            fullfft = pd.DataFrame({"Electrode": DEFAULT_ELECTRODE_NAMES_64})
            for frequency in (2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 4.5, 4.6, 4.7, 4.8, 4.9, 5.0, 5.1):
                fullfft[f"{frequency:.4f}_Hz"] = _expected_fullfft_values(
                    condition_base=base,
                    frequency_hz=frequency,
                    subject_mean=float(subject_offset),
                )
            fullfft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)


def _expected_fullfft_values(
    *,
    condition_base: float,
    frequency_hz: float,
    subject_mean: float,
) -> np.ndarray:
    electrode_index = np.arange(64, dtype=float)
    return condition_base + subject_mean + electrode_index * (1.0 + frequency_hz / 10.0)
