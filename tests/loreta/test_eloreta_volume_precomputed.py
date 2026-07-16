from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
)
from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    HARMONIC_STRATEGY_SUM_SOURCE_PSD_AMPLITUDES_THEN_ZSCORE,
    METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1,
    ELORETAVolumeForwardModel,
    ELORETAVolumeParticipantZScoreValues,
    ELORETAVolumePrecomputedParticipantGroupCondition,
    ELORETAVolumeZScoreConfig,
    write_eloreta_volume_precomputed_participant_zscore_payloads,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    PARTICIPANT_ZSCORE_AGGREGATION_MEAN,
)


def test_precomputed_eloreta_writer_keeps_volume_statistics_and_time_domain_provenance(
    tmp_path,
) -> None:
    estimator_calls: list[object] = []
    forward_model = _volume_forward_model(estimator_calls)
    participant_rows = (
        _participant_row("P01", [1.0, 2.0, 3.0, 4.0]),
        _participant_row("P02", [2.0, 3.0, 4.0, 5.0]),
        _participant_row("P03", [3.0, 4.0, 5.0, 6.0]),
    )
    condition = ELORETAVolumePrecomputedParticipantGroupCondition(
        condition_id="Oddball Faces",
        label="Oddball Faces",
        participant_values=participant_rows,
        metadata={"group_id": "all"},
    )
    config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=(1.2, 2.4),
        method_id=METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1,
        cluster_permutation_count=32,
        metadata={"project_integration": "time_domain_eloreta_source_psd"},
    )

    result = write_eloreta_volume_precomputed_participant_zscore_payloads(
        forward_model=forward_model,
        conditions=(condition,),
        config=config,
        output_dir=tmp_path,
        aggregations=(PARTICIPANT_ZSCORE_AGGREGATION_MEAN,),
    )

    assert estimator_calls == []
    assert result.producer_result.method_id == METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1
    validate_prepared_source_manifest_json(result.producer_result.manifest_path, require_payload_files=True)

    manifest = json.loads(result.producer_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["label"] == "eLORETA volume Hauk-informed source-PSD participant z-score maps"
    assert manifest["metadata"]["producer_method"] == METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1
    assert manifest["metadata"]["input_domain"] == "signed_repetition_averaged_eeg_time_series"
    entry = manifest["conditions"][0]
    assert entry["metadata"]["base_producer_method"] == METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1
    assert entry["metadata"]["producer_method"] == (
        f"{METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1}_mean"
    )
    assert entry["metadata"]["cluster_mask_source_count"] == 4

    payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "volume_points"
    assert "faces" not in payload
    assert payload["source_model"] == f"{METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1}_mean"
    assert payload["values"] == pytest.approx([2.0, 3.0, 4.0, 5.0])
    metadata = payload["metadata"]
    assert metadata["source_method"] == "eloreta_volume"
    assert metadata["inverse_method"] == "eLORETA"
    assert metadata["source_space"] == "volume"
    assert metadata["input_domain"] == "signed_repetition_averaged_eeg_time_series"
    assert metadata["harmonic_strategy"] == HARMONIC_STRATEGY_SUM_SOURCE_PSD_AMPLITUDES_THEN_ZSCORE
    assert metadata["legacy_amplitude_topography_input"] is False
    assert metadata["participant_zscore_order"][0] == (
        "load signed repetition-averaged participant EEG time series"
    )
    assert metadata["participant_zscore_order"][1].startswith(
        "compute participant eLORETA volume source PSD"
    )
    assert metadata["renderer_dependency"] == "none"

    sidecar = json.loads(result.participant_sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["source_model"] == METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1
    assert sidecar["source_method"] == "eloreta_volume"
    assert sidecar["metadata"]["input_domain"] == "signed_repetition_averaged_eeg_time_series"
    assert sidecar["metadata"]["harmonic_strategy"] == (
        HARMONIC_STRATEGY_SUM_SOURCE_PSD_AMPLITUDES_THEN_ZSCORE
    )
    assert [row["participant_id"] for row in sidecar["conditions"][0]["participants"]] == [
        "P01",
        "P02",
        "P03",
    ]


def test_precomputed_eloreta_writer_rejects_maps_outside_volume_source_space(tmp_path) -> None:
    condition = ELORETAVolumePrecomputedParticipantGroupCondition(
        condition_id="Oddball",
        label="Oddball",
        participant_values=(
            _participant_row("P01", [1.0, 2.0, 3.0]),
            _participant_row("P02", [2.0, 3.0, 4.0]),
        ),
    )
    config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=(1.2,),
        method_id=METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_V1,
    )

    with pytest.raises(ValueError, match="has 3 sources; 4 expected"):
        write_eloreta_volume_precomputed_participant_zscore_payloads(
            forward_model=_volume_forward_model([]),
            conditions=(condition,),
            config=config,
            output_dir=tmp_path,
            aggregations=(PARTICIPANT_ZSCORE_AGGREGATION_MEAN,),
        )


def test_precomputed_eloreta_writer_requires_time_domain_method_id(tmp_path) -> None:
    condition = ELORETAVolumePrecomputedParticipantGroupCondition(
        condition_id="Oddball",
        label="Oddball",
        participant_values=(
            _participant_row("P01", [1.0, 2.0, 3.0, 4.0]),
            _participant_row("P02", [2.0, 3.0, 4.0, 5.0]),
        ),
    )

    with pytest.raises(ValueError, match="Precomputed time-domain eLORETA maps require method_id"):
        write_eloreta_volume_precomputed_participant_zscore_payloads(
            forward_model=_volume_forward_model([]),
            conditions=(condition,),
            config=ELORETAVolumeZScoreConfig(selected_harmonics_hz=(1.2,)),
            output_dir=tmp_path,
        )


def _participant_row(
    participant_id: str,
    values: list[float],
) -> ELORETAVolumeParticipantZScoreValues:
    vector = np.asarray(values, dtype=float)
    return ELORETAVolumeParticipantZScoreValues(
        participant_id=participant_id,
        values=vector,
        target_source_values=vector + 10.0,
        noise_mean_values=vector + 1.0,
        noise_std_values=np.ones_like(vector),
        noise_offsets_used=tuple(range(-10, -1)) + tuple(range(2, 11)),
        zero_noise_sd_source_count=0,
    )


def _volume_forward_model(estimator_calls: list[object]) -> ELORETAVolumeForwardModel:
    points = np.asarray(
        [
            [-20.0, -60.0, 10.0],
            [0.0, -60.0, 10.0],
            [20.0, -60.0, 10.0],
            [0.0, -30.0, 30.0],
        ],
        dtype=float,
    )

    def source_estimator(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        estimator_calls.append((args, kwargs))
        raise AssertionError("The precomputed writer must not run the legacy source estimator.")

    return ELORETAVolumeForwardModel(
        channel_names=("A", "B", "C"),
        source_points=points,
        leadfield=np.ones((3, len(points)), dtype=float),
        source_adjacency=(
            {1, 3},
            {0, 2, 3},
            {1, 3},
            {0, 1, 2},
        ),
        metadata={
            "inverse_backend": "fixture",
            "orientation_constraint": "volume_free",
            "source_space_kind": "volume",
        },
        source_estimator=source_estimator,
        source_indices=tuple(range(len(points))),
    )
