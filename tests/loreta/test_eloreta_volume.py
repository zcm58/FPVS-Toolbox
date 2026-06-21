from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_manifest_json
from Tools.LORETA_Visualizer.source_payloads import make_source_payload
from Tools.LORETA_Visualizer.cortical_paint import payload_cluster_mask
from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    ELORETAVolumeForwardModel,
    ELORETAVolumeZScoreConfig,
    compute_eloreta_volume_participant_zscore_source_values,
    compute_eloreta_volume_zscore_source_values,
    summarize_eloreta_volume_participant_zscores,
    write_eloreta_volume_participant_zscore_payloads,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    L2MNEHaukHarmonicBins,
    L2MNEHaukParticipantGroupCondition,
    L2MNEHaukParticipantSourceInput,
    L2MNEHaukZScoreCondition,
)
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
    default_project_eloreta_volume_output_dir,
    write_project_eloreta_volume_hauk_zscore_payloads,
)


def test_eloreta_volume_zscore_matches_participant_first_l2_style_order() -> None:
    result = compute_eloreta_volume_zscore_source_values(
        forward_model=_tiny_eloreta_forward_model(("A", "B", "C")),
        condition=_hauk_condition(),
        config=ELORETAVolumeZScoreConfig(
            selected_harmonics_hz=(1.0, 2.0),
            apply_average_reference=False,
            min_noise_bins=4,
        ),
    )

    expected_source0 = (10.0 - 3.0) / np.std(np.asarray([2.0, 3.0, 4.0]), ddof=0)
    assert result.noise_offsets_used == (-3, -2, 2, 3, 4)
    assert result.values[0] == pytest.approx(expected_source0)
    assert result.values[1] == 0.0
    assert result.zero_noise_sd_source_count >= 1


def test_eloreta_volume_writer_emits_volume_payloads_and_source_index_cluster_metadata(tmp_path) -> None:
    forward_model = _tiny_eloreta_forward_model(("A", "B", "C"))
    config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=(1.0, 2.0),
        apply_average_reference=False,
        min_noise_bins=4,
        cluster_permutation_count=128,
    )

    result = write_eloreta_volume_participant_zscore_payloads(
        forward_model=forward_model,
        conditions=(_participant_group_condition(),),
        config=config,
        output_dir=tmp_path,
        aggregations=(PARTICIPANT_ZSCORE_AGGREGATION_MEAN,),
    )

    assert result.producer_result.manifest_path.is_file()
    assert result.participant_sidecar_path.is_file()
    assert result.producer_result.manifest_validation.label == validate_prepared_source_manifest_json(
        result.producer_result.manifest_path,
        require_payload_files=True,
    ).label
    manifest = json.loads(result.producer_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["metadata"]["source_method"] == "eloreta_volume"
    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    metadata = payload["metadata"]
    assert payload["kind"] == "volume_points"
    assert metadata["source_method"] == "eloreta_volume"
    assert metadata["base_producer_method"] == "eloreta_volume_participant_zscore"
    assert metadata["cluster_mask"] == "source_space_cluster_permutation"
    assert "cluster_mask_source_index_count" in metadata
    assert "cluster_mask_vertex_count" not in metadata


def test_eloreta_volume_project_export_uses_project_fullfft_inputs_and_validation_report(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = write_project_eloreta_volume_hauk_zscore_payloads(
        project_root=project_root,
        forward_model=_tiny_eloreta_forward_model(tuple(DEFAULT_ELECTRODE_NAMES_64)),
        noise_window_bins=3,
        min_noise_bins=4,
        aggregations=(PARTICIPANT_ZSCORE_AGGREGATION_MEAN,),
    )

    assert result.output_dir == default_project_eloreta_volume_output_dir(project_root)
    assert result.manifest_path.is_file()
    assert result.participant_sidecar_path is not None
    assert result.participant_sidecar_path.is_file()
    assert result.validation_report_path is not None
    assert result.validation_report_path.is_file()
    assert len(result.producer_result.payloads) == 2
    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "volume_points"
    assert payload["metadata"]["config_project_integration"] == "project_eloreta_volume_participant_first_hauk_zscore_beta"
    report = json.loads(result.validation_report_path.read_text(encoding="utf-8"))
    assert report["export_model"] == "eloreta_volume_participant_first"
    assert report["validation_checks"]["participant_sidecar_available"] is True
    assert report["validation_checks"]["lateralization_summary_available"] is False
    assert report["payload_summaries"][0]["cluster_mask_source_count"] is not None
    report_markdown = result.validation_report_markdown_path.read_text(encoding="utf-8")
    assert "Cluster sources" in report_markdown


def test_source_index_cluster_masks_are_read_by_display_helpers() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([0.8, 4.0], dtype=float),
        label="cluster masked volume z",
        kind="volume_points",
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_source_indices": [1],
        },
        normalize_values=False,
    )

    assert payload_cluster_mask(payload).tolist() == [False, True]


def test_eloreta_participant_summary_keeps_group_average_over_participant_zscores() -> None:
    config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=(1.0, 2.0),
        apply_average_reference=False,
        min_noise_bins=4,
    )
    participant_values = compute_eloreta_volume_participant_zscore_source_values(
        forward_model=_tiny_eloreta_forward_model(("A", "B", "C")),
        condition=_participant_group_condition(),
        config=config,
    )

    summary = summarize_eloreta_volume_participant_zscores(
        participant_values,
        aggregation=PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    )

    assert summary.method_id == "eloreta_volume_participant_zscore_mean"
    assert np.allclose(summary.values, np.mean(np.vstack([row.values for row in participant_values]), axis=0))


def _tiny_eloreta_forward_model(channel_names: tuple[str, ...]) -> ELORETAVolumeForwardModel:
    source_points = np.asarray(
        [
            [-30.0, -70.0, 20.0],
            [0.0, -70.0, 24.0],
            [30.0, -70.0, 20.0],
            [0.0, -40.0, 40.0],
        ],
        dtype=float,
    )
    channel_count = len(channel_names)
    weights = np.zeros((channel_count, len(source_points)), dtype=float)
    for source_index in range(len(source_points)):
        weights[:, source_index] = np.linspace(0.2, 1.0, channel_count) * (source_index + 1)
    if channel_count == 3:
        weights = np.asarray(
            [
                [1.0, 0.0, 0.0, 0.5],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ],
            dtype=float,
        )

    def source_estimator(topography, *, lambda2: float, method_params: dict | None = None):  # noqa: ANN001, ANN202
        del lambda2, method_params
        return np.asarray(topography, dtype=float) @ weights

    return ELORETAVolumeForwardModel(
        channel_names=channel_names,
        source_points=source_points,
        leadfield=weights,
        source_adjacency=(
            {1, 3},
            {0, 2, 3},
            {1, 3},
            {0, 1, 2},
        ),
        metadata={
            "fixture": True,
            "forward_model_status": "tiny test eLORETA volume model",
            "inverse_backend": "fixture",
            "source_space_kind": "volume",
            "source_count": len(source_points),
        },
        source_estimator=source_estimator,
        source_indices=tuple(range(len(source_points))),
    )


def _participant_group_condition() -> L2MNEHaukParticipantGroupCondition:
    return L2MNEHaukParticipantGroupCondition(
        condition_id="Condition A",
        label="Condition A",
        participants=(
            L2MNEHaukParticipantSourceInput(
                participant_id="P1",
                condition=_hauk_condition(target_boost=0.0, participant_id="P1"),
            ),
            L2MNEHaukParticipantSourceInput(
                participant_id="P2",
                condition=_hauk_condition(target_boost=2.0, participant_id="P2"),
            ),
        ),
    )


def _hauk_condition(
    *,
    target_boost: float = 0.0,
    participant_id: str | None = None,
) -> L2MNEHaukZScoreCondition:
    harmonic_bins = {}
    for harmonic in (1.0, 2.0):
        harmonic_bins[harmonic] = L2MNEHaukHarmonicBins(
            harmonic_hz=harmonic,
            target_topography=np.asarray([5.0 + target_boost, 2.0, 1.0], dtype=float),
            target_frequency_hz=harmonic,
            target_bin_index=int(harmonic * 10),
            target_column=f"{harmonic:.4f}_Hz",
            noise_topographies_by_offset={
                -3: np.asarray([0.5, 1.0, 1.0], dtype=float),
                -2: np.asarray([1.0, 1.0, 1.0], dtype=float),
                2: np.asarray([1.5, 1.0, 1.0], dtype=float),
                3: np.asarray([2.0, 1.0, 1.0], dtype=float),
                4: np.asarray([2.5, 1.0, 1.0], dtype=float),
            },
            noise_frequencies_hz_by_offset={
                -3: harmonic - 0.3,
                -2: harmonic - 0.2,
                2: harmonic + 0.2,
                3: harmonic + 0.3,
                4: harmonic + 0.4,
            },
            noise_bin_indices_by_offset={
                -3: int(harmonic * 10) - 3,
                -2: int(harmonic * 10) - 2,
                2: int(harmonic * 10) + 2,
                3: int(harmonic * 10) + 3,
                4: int(harmonic * 10) + 4,
            },
            noise_columns_by_offset={
                -3: f"{harmonic - 0.3:.4f}_Hz",
                -2: f"{harmonic - 0.2:.4f}_Hz",
                2: f"{harmonic + 0.2:.4f}_Hz",
                3: f"{harmonic + 0.3:.4f}_Hz",
                4: f"{harmonic + 0.4:.4f}_Hz",
            },
        )
    return L2MNEHaukZScoreCondition(
        condition_id="Condition A",
        label="Condition A",
        harmonic_bins=harmonic_bins,
        metadata={"participant_id": participant_id} if participant_id else {},
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
                base=base,
                subject_offset=subject_offset,
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


def _write_participant_workbook(path: Path, *, base: float, subject_offset: int) -> None:
    with pd.ExcelWriter(path) as writer:
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
