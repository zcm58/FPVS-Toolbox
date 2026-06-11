from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    PARTICIPANT_SOURCE_MAP_SIDECAR_FORMAT,
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN,
    PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN,
    L2MNEHaukHarmonicBins,
    L2MNEHaukParticipantGroupCondition,
    L2MNEHaukParticipantSourceInput,
    L2MNEHaukParticipantZScoreValues,
    L2MNEHaukZScoreCondition,
    L2MNEHaukZScoreConfig,
    build_l2_mne_hauk_zscore_surface_payload,
    compute_l2_mne_hauk_participant_zscore_source_values,
    compute_l2_mne_hauk_source_cluster_mask,
    compute_l2_mne_hauk_zscore_source_values,
    summarize_l2_mne_hauk_participant_zscores,
    write_l2_mne_hauk_participant_zscore_surface_payloads,
    write_l2_mne_hauk_zscore_surface_payloads,
)


def test_hauk_zscore_computes_source_space_noise_corrected_values() -> None:
    forward_model = _identity_forward_model()
    condition = _hauk_condition()
    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=(1.0, 2.0),
        apply_average_reference=False,
        min_noise_bins=4,
    )

    result = compute_l2_mne_hauk_zscore_source_values(
        forward_model=forward_model,
        condition=condition,
        config=config,
    )

    assert result.noise_offsets_used == (-3, -2, 2, 3, 4)
    expected_source0 = (10.0 - 3.0) / np.std(np.asarray([2.0, 3.0, 4.0]), ddof=0)
    assert result.values[0] == pytest.approx(expected_source0)
    assert result.values[1] == 0.0
    assert result.zero_noise_sd_source_count == 2


def test_hauk_zscore_payload_metadata_declares_zscore_units() -> None:
    payload = build_l2_mne_hauk_zscore_surface_payload(
        forward_model=_identity_forward_model(),
        condition=_hauk_condition(),
        config=L2MNEHaukZScoreConfig(
            selected_harmonics_hz=(1.0, 2.0),
            apply_average_reference=False,
            min_noise_bins=4,
        ),
    )

    assert payload["source_model"] == "l2_mne_cortical_surface_hauk_zscore_beta"
    assert payload["value_label"] == "source-space z-score"
    assert payload["metadata"]["source_value_unit"] == "z-score"
    assert payload["metadata"]["hauk_2021_frequency_domain_zscore_aligned"] is True
    assert payload["metadata"]["neighboring_bin_policy"]["common_offsets_used"] == [-3, -2, 2, 3, 4]


def test_hauk_zscore_uses_estimator_backed_forward_model() -> None:
    calls: list[tuple[np.ndarray, float]] = []

    def source_estimator(topography, *, lambda2: float):  # noqa: ANN001, ANN202
        values = np.asarray(topography, dtype=float)
        calls.append((values.copy(), float(lambda2)))
        return values

    payload = build_l2_mne_hauk_zscore_surface_payload(
        forward_model=_identity_forward_model(
            metadata={
                "inverse_backend": "mne_python",
                "orientation_constraint": "loose",
                "loose_orientation": 0.2,
                "fixed_orientation": False,
                "depth_weighting": "none",
                "noise_normalization": "none",
            },
            source_estimator=source_estimator,
        ),
        condition=_hauk_condition(),
        config=L2MNEHaukZScoreConfig(
            selected_harmonics_hz=(1.0, 2.0),
            apply_average_reference=False,
            lambda2=0.25,
            min_noise_bins=4,
        ),
    )

    metadata = payload["metadata"]
    assert metadata["inverse_backend"] == "mne_python"
    assert metadata["orientation_constraint"] == "loose"
    assert metadata["loose_orientation"] == 0.2
    assert metadata["fixed_orientation"] is False
    assert metadata["depth_weighting"] == "none"
    assert metadata["noise_normalization"] == "none"
    assert len(calls) == 1
    assert calls[0][0].shape == (6, 3)
    assert np.allclose(calls[0][0][0], np.asarray([10.0, 4.0, 2.0]))
    assert calls[0][1] == pytest.approx(0.25)


def test_participant_first_zscore_computes_each_participant_before_aggregation() -> None:
    calls: list[np.ndarray] = []

    def source_estimator(topography, *, lambda2: float):  # noqa: ANN001, ANN202
        del lambda2
        values = np.asarray(topography, dtype=float)
        calls.append(values.copy())
        return values

    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=(1.0, 2.0),
        apply_average_reference=False,
        min_noise_bins=4,
    )
    participant_values = compute_l2_mne_hauk_participant_zscore_source_values(
        forward_model=_identity_forward_model(source_estimator=source_estimator),
        condition=_participant_group_condition(),
        config=config,
    )
    mean_summary = summarize_l2_mne_hauk_participant_zscores(
        participant_values,
        aggregation=PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
    )
    median_summary = summarize_l2_mne_hauk_participant_zscores(
        participant_values,
        aggregation=PARTICIPANT_ZSCORE_AGGREGATION_MEDIAN,
    )

    assert len(participant_values) == 2
    assert [row.participant_id for row in participant_values] == ["P1", "P2"]
    assert len(calls) == 2
    assert calls[0].shape == (6, 3)
    expected_mean = np.mean(np.vstack([row.values for row in participant_values]), axis=0)
    assert np.allclose(mean_summary.values, expected_mean)
    assert np.allclose(median_summary.values, np.median(np.vstack([row.values for row in participant_values]), axis=0))
    assert mean_summary.method_id == "l2_mne_fsaverage_participant_zscore_mean"


def test_participant_zscore_trimmed_mean_drops_each_tail_per_source() -> None:
    participant_values = tuple(
        L2MNEHaukParticipantZScoreValues(
            participant_id=f"P{index}",
            values=np.asarray([value, value * 2.0], dtype=float),
            target_source_values=np.zeros(2, dtype=float),
            noise_mean_values=np.zeros(2, dtype=float),
            noise_std_values=np.ones(2, dtype=float),
            noise_offsets_used=(-2, 2),
            zero_noise_sd_source_count=0,
        )
        for index, value in enumerate((-100.0, 1.0, 2.0, 3.0, 100.0), start=1)
    )

    summary = summarize_l2_mne_hauk_participant_zscores(
        participant_values,
        aggregation=PARTICIPANT_ZSCORE_AGGREGATION_TRIMMED_MEAN,
        trim_fraction=0.2,
    )

    assert summary.trim_fraction == pytest.approx(0.2)
    assert np.allclose(summary.values, np.asarray([2.0, 4.0]))


def test_cluster_permutation_mask_keeps_significant_connected_positive_cluster() -> None:
    participant_values = _cluster_participant_values()
    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=(1.0,),
        apply_average_reference=False,
        min_noise_bins=4,
        cluster_permutation_count=128,
    )

    result = compute_l2_mne_hauk_source_cluster_mask(
        participant_values,
        faces=np.asarray([[0, 1, 2], [2, 3, 4]], dtype=np.int64),
        config=config,
    )

    assert result.cluster_forming_p_value == pytest.approx(0.05)
    assert result.cluster_alpha == pytest.approx(0.05)
    assert result.tail == "two-sided"
    assert result.cluster_forming_threshold > 2.0
    assert result.permutation_count == 64
    assert result.mask.tolist() == [True, True, True, False, False]
    assert len(result.significant_clusters) == 1
    assert result.significant_clusters[0].tail == "positive"
    assert result.significant_clusters[0].p_value <= 0.05


def test_two_tailed_cluster_permutation_keeps_positive_and_negative_clusters_separate() -> None:
    participant_values = _two_tailed_cluster_participant_values()
    config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=(1.0,),
        apply_average_reference=False,
        min_noise_bins=4,
        cluster_permutation_count=128,
    )

    result = compute_l2_mne_hauk_source_cluster_mask(
        participant_values,
        faces=np.asarray([[0, 1, 2], [2, 3, 4]], dtype=np.int64),
        config=config,
    )

    assert result.tail == "two-sided"
    assert result.permutation_count == 64
    assert result.mask.tolist() == [True, True, True, True, False]
    assert [cluster.tail for cluster in result.significant_clusters] == ["positive", "negative"]
    assert all(cluster.p_value <= 0.05 for cluster in result.significant_clusters)


def test_participant_first_writer_emits_group_summaries_and_sidecar(tmp_path) -> None:
    result = write_l2_mne_hauk_participant_zscore_surface_payloads(
        forward_model=_identity_forward_model(),
        conditions=(_participant_group_condition(),),
        config=L2MNEHaukZScoreConfig(
            selected_harmonics_hz=(1.0, 2.0),
            apply_average_reference=False,
            min_noise_bins=4,
        ),
        output_dir=tmp_path,
    )

    assert result.producer_result.method_id == "l2_mne_fsaverage_participant_zscore"
    assert len(result.producer_result.payloads) == 3
    assert result.participant_sidecar_path.is_file()
    assert result.lateralization_summary_path is not None
    assert result.lateralization_summary_path.is_file()
    assert result.lateralization_summary_csv_path is not None
    assert result.lateralization_summary_csv_path.is_file()
    manifest = json.loads(result.producer_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["label"] == "L2-MNE participant-first source-space z-score maps"
    assert [entry["metadata"]["participant_zscore_aggregation"] for entry in manifest["conditions"]] == [
        "mean",
        "median",
        "trimmed_mean",
    ]
    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    assert payload["source_model"] == "l2_mne_fsaverage_participant_zscore_mean"
    assert payload["metadata"]["source_map_model"] == "participant_first"
    assert payload["metadata"]["participant_count"] == 2
    assert payload["metadata"]["cluster_mask"] == "source_space_cluster_permutation"
    assert payload["metadata"]["cluster_mask_method"] == "one_sample_sign_flip_max_cluster_mass_two_tailed"
    assert payload["metadata"]["cluster_forming_tail"] == "two-sided"
    assert payload["metadata"]["cluster_mask_vertex_count"] == 0
    sidecar = json.loads(result.participant_sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["format"] == PARTICIPANT_SOURCE_MAP_SIDECAR_FORMAT
    assert sidecar["conditions"][0]["participant_count"] == 2
    lateralization = json.loads(result.lateralization_summary_path.read_text(encoding="utf-8"))
    assert lateralization["format"] == "fpvs_loreta_source_lateralization_summary_v1"
    assert lateralization["metadata"]["positive_lateralization_index"] == "right_lateralized"
    assert "occipitotemporal_lot_rot" in lateralization["metadata"]["roi_definitions"]
    assert len(lateralization["rows"]) == 10


def test_hauk_zscore_writer_emits_manifest_importer_contract(tmp_path) -> None:
    result = write_l2_mne_hauk_zscore_surface_payloads(
        forward_model=_identity_forward_model(),
        conditions=(_hauk_condition(),),
        config=L2MNEHaukZScoreConfig(
            selected_harmonics_hz=(1.0, 2.0),
            apply_average_reference=False,
            min_noise_bins=4,
        ),
        output_dir=tmp_path,
    )

    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["label"] == "L2-MNE Hauk-style source-space z-score beta maps"
    assert manifest["conditions"][0]["metadata"]["source_value_unit"] == "z-score"


def _identity_forward_model(
    *,
    metadata: dict[str, object] | None = None,
    source_estimator=None,  # noqa: ANN001
) -> L2MNECorticalForwardModel:
    return L2MNECorticalForwardModel(
        channel_names=("A", "B", "C"),
        source_points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=float,
        ),
        leadfield=np.eye(3, dtype=float),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata={"fixture": True, **(metadata or {})},
        source_estimator=source_estimator,
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


def _cluster_participant_values() -> tuple[L2MNEHaukParticipantZScoreValues, ...]:
    rows = []
    for index, scale in enumerate((0.92, 0.96, 1.0, 1.04, 1.08, 1.12), start=1):
        noise_value = 0.35 if index % 2 else -0.35
        values = np.asarray([4.2 * scale, 4.0 * scale, 3.8 * scale, noise_value, -0.04], dtype=float)
        rows.append(
            L2MNEHaukParticipantZScoreValues(
                participant_id=f"P{index}",
                values=values,
                target_source_values=np.zeros(5, dtype=float),
                noise_mean_values=np.zeros(5, dtype=float),
                noise_std_values=np.ones(5, dtype=float),
                noise_offsets_used=(-2, 2),
                zero_noise_sd_source_count=0,
            )
        )
    return tuple(rows)


def _two_tailed_cluster_participant_values() -> tuple[L2MNEHaukParticipantZScoreValues, ...]:
    rows = []
    for index, scale in enumerate((0.92, 0.96, 1.0, 1.04, 1.08, 1.12), start=1):
        values = np.asarray([4.2 * scale, 4.0 * scale, -4.2 * scale, -4.0 * scale, 0.02], dtype=float)
        rows.append(
            L2MNEHaukParticipantZScoreValues(
                participant_id=f"P{index}",
                values=values,
                target_source_values=np.zeros(5, dtype=float),
                noise_mean_values=np.zeros(5, dtype=float),
                noise_std_values=np.ones(5, dtype=float),
                noise_offsets_used=(-2, 2),
                zero_noise_sd_source_count=0,
            )
        )
    return tuple(rows)


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
