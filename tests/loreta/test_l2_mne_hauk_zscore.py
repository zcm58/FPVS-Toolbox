from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    L2MNEHaukHarmonicBins,
    L2MNEHaukZScoreCondition,
    L2MNEHaukZScoreConfig,
    build_l2_mne_hauk_zscore_surface_payload,
    compute_l2_mne_hauk_zscore_source_values,
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
    assert len(calls) == 6
    assert np.allclose(calls[0][0], np.asarray([10.0, 4.0, 2.0]))
    assert calls[0][1] == pytest.approx(0.25)


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


def _hauk_condition() -> L2MNEHaukZScoreCondition:
    harmonic_bins = {}
    for harmonic in (1.0, 2.0):
        harmonic_bins[harmonic] = L2MNEHaukHarmonicBins(
            harmonic_hz=harmonic,
            target_topography=np.asarray([5.0, 2.0, 1.0], dtype=float),
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
    )
