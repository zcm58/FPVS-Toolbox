from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import (
    METHOD_ID_L2_MNE_CORTICAL_SURFACE_BETA,
    SOURCE_KIND_SURFACE_MESH,
    L2MNECorticalForwardModel,
    L2MNEFPVSCondition,
    L2MNEProducerConfig,
    compute_l2_mne_source_values,
    make_l2_mne_cortical_surface_beta_fixture,
    write_l2_mne_cortical_surface_fixture,
    write_l2_mne_cortical_surface_payloads,
)


def test_l2_mne_fixture_writes_valid_surface_manifest_and_payloads(tmp_path) -> None:
    result = write_l2_mne_cortical_surface_fixture(tmp_path)

    manifest = validate_prepared_source_manifest_json(result.manifest_path, require_payload_files=True)

    assert result.method_id == METHOD_ID_L2_MNE_CORTICAL_SURFACE_BETA
    assert result.manifest_validation.label == manifest.label
    assert result.manifest_path.parent == tmp_path
    assert len(result.payloads) == 2
    assert [condition.raw_id for condition in manifest.conditions] == [
        "occipital_oddball_beta",
        "frontal_oddball_beta",
    ]

    raw_manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert raw_manifest["format"] == PREPARED_SOURCE_MANIFEST_FORMAT

    for emitted in result.payloads:
        raw_payload = json.loads(emitted.payload_path.read_text(encoding="utf-8"))
        validated = validate_prepared_source_payload_json(emitted.payload_path)

        assert raw_payload["format"] == PREPARED_SOURCE_PAYLOAD_FORMAT
        assert raw_payload["kind"] == SOURCE_KIND_SURFACE_MESH
        assert raw_payload["source_model"] == METHOD_ID_L2_MNE_CORTICAL_SURFACE_BETA
        assert raw_payload["coordinate_space"] == "fsaverage_surface"
        assert raw_payload["metadata"]["beta"] is True
        assert raw_payload["metadata"]["channel_count"] == 64
        assert raw_payload["metadata"]["deep_source_claim"].startswith("none")
        assert len(raw_payload["points"]) == len(raw_payload["values"])
        assert len(raw_payload["faces"]) > 0
        assert np.all(np.asarray(raw_payload["values"], dtype=float) >= 0.0)
        assert emitted.validation.label == validated.label


def test_l2_mne_fixture_conditions_shift_source_intensity_by_region() -> None:
    forward_model, conditions, config = make_l2_mne_cortical_surface_beta_fixture()
    region_labels = np.asarray(forward_model.metadata["source_regions"])
    occipital_mask = region_labels == "occipital"
    frontal_mask = region_labels == "frontal"

    occipital_values = compute_l2_mne_source_values(
        forward_model=forward_model,
        condition=conditions[0],
        config=config,
    )
    frontal_values = compute_l2_mne_source_values(
        forward_model=forward_model,
        condition=conditions[1],
        config=config,
    )

    assert float(np.mean(occipital_values[occipital_mask])) > float(np.mean(occipital_values[frontal_mask]))
    assert float(np.mean(frontal_values[frontal_mask])) > float(np.mean(frontal_values[occipital_mask]))


def test_l2_mne_writer_can_emit_custom_condition_set(tmp_path) -> None:
    forward_model, conditions, config = make_l2_mne_cortical_surface_beta_fixture()

    result = write_l2_mne_cortical_surface_payloads(
        forward_model=forward_model,
        conditions=conditions[:1],
        config=config,
        output_dir=tmp_path,
    )

    assert len(result.payloads) == 1
    assert result.payloads[0].condition_id == "occipital_oddball_beta"
    assert result.payloads[0].payload_path.is_file()
    assert result.manifest_path.is_file()


def test_l2_mne_condition_requires_exact_selected_harmonics() -> None:
    forward_model, conditions, config = make_l2_mne_cortical_surface_beta_fixture()
    missing_harmonic_condition = L2MNEFPVSCondition(
        condition_id="missing_harmonic",
        label="Missing harmonic",
        harmonic_topographies={
            1.2: conditions[0].harmonic_topographies[1.2],
            2.4: conditions[0].harmonic_topographies[2.4],
        },
    )

    with pytest.raises(ValueError, match="missing selected harmonic 3.6 Hz"):
        compute_l2_mne_source_values(
            forward_model=forward_model,
            condition=missing_harmonic_condition,
            config=config,
        )


def test_l2_mne_uses_estimator_backed_forward_model() -> None:
    calls: list[tuple[np.ndarray, float]] = []

    def source_estimator(topography, *, lambda2: float):  # noqa: ANN001, ANN202
        values = np.asarray(topography, dtype=float)
        calls.append((values.copy(), float(lambda2)))
        return np.asarray([values[0], values[1], values[0] - values[1]], dtype=float)

    forward_model = L2MNECorticalForwardModel(
        channel_names=("A", "B"),
        source_points=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=float,
        ),
        leadfield=np.ones((2, 9), dtype=float),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata={
            "inverse_backend": "mne_python",
            "orientation_constraint": "loose",
            "loose_orientation": 0.2,
        },
        source_estimator=source_estimator,
    )
    condition = L2MNEFPVSCondition(
        condition_id="native_estimator",
        label="Native estimator",
        harmonic_topographies={
            1.0: np.asarray([3.0, 1.0], dtype=float),
            2.0: np.asarray([5.0, 2.0], dtype=float),
        },
    )
    config = L2MNEProducerConfig(
        selected_harmonics_hz=(1.0, 2.0),
        apply_average_reference=False,
        lambda2=0.25,
    )

    values = compute_l2_mne_source_values(forward_model=forward_model, condition=condition, config=config)

    assert np.allclose(values, np.asarray([8.0, 3.0, 5.0]))
    assert len(calls) == 1
    assert np.allclose(calls[0][0], np.asarray([8.0, 3.0]))
    assert calls[0][1] == pytest.approx(0.25)
