from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mne
import numpy as np
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.exports.source_time_domain_export import (
    write_source_ready_time_domain_derivatives,
)
from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION
from Main_App.projects.project import Project
from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    ELORETAVolumeForwardModel,
    METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
)
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
)
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
    MneFsaverageELORETAVolumeSourcePsdModel,
)
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_hauk_source_psd_export import (
    DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS,
    DEFAULT_PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_MANIFEST_NAME,
    default_project_eloreta_volume_hauk_source_psd_output_dir,
    write_project_eloreta_volume_hauk_source_psd_payloads,
)


SFREQ = 200.0
N_TIMES = 200
PROCESSING_FINGERPRINT = "f" * 64


def test_project_eloreta_source_psd_uses_signed_fif_exact_method_and_cache(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(tmp_path, participants=("P01",))
    _write_time_domain_derivative(project.project_root, participant_id="P01")
    assert not tuple(project.project_root.rglob("*.xlsx"))

    model = _source_psd_model()
    calls: list[dict[str, Any]] = []
    first = write_project_eloreta_volume_hauk_source_psd_payloads(
        project=project,
        project_root=project.project_root,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        apply_inverse_func=_apply_inverse_callable(calls),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "eLORETA"
    assert call["method_params"] == dict(DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS)
    assert call["prepared"] is True
    assert call["lambda2"] == pytest.approx(DEFAULT_HAUK_SOURCE_PSD_LAMBDA2)
    assert call["pick_ori"] == "vector"
    assert call["return_residual"] is False
    sensor_coefficients = np.asarray(call["evoked"].data)
    assert sensor_coefficients.shape == (len(DEFAULT_ELECTRODE_NAMES_64), 19)
    assert np.iscomplexobj(sensor_coefficients)

    assert first.manifest_path.name == (
        DEFAULT_PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_MANIFEST_NAME
    )
    assert first.output_dir == default_project_eloreta_volume_hauk_source_psd_output_dir(
        project.project_root
    )
    assert first.producer_result.method_id == (
        METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1
    )
    assert first.included_participants == ("P01",)
    assert first.cache_hit_count == 0
    assert first.cache_miss_count == 1
    assert first.participant_sidecar_path.is_file()
    assert first.validation_report_path is not None
    assert first.validation_report_path.is_file()
    assert not tuple(project.project_root.rglob("*.xlsx"))

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["metadata"]["producer_method"] == (
        METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1
    )
    assert manifest["metadata"]["input_domain"] == (
        "signed_repetition_averaged_eeg_time_series"
    )
    method_metadata = manifest["metadata"]["source_psd_method"]
    assert method_metadata["inverse_method"] == "eLORETA"
    assert method_metadata["method_params"] == dict(
        DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS
    )
    assert method_metadata["prepared"] is True
    assert method_metadata["source_orientation_mode"] == "vector_norm"
    assert method_metadata["source_orientation_contract"]["rotation_invariant_amplitude"] is True

    payload = json.loads(
        (first.output_dir / manifest["conditions"][0]["file"]).read_text(
            encoding="utf-8"
        )
    )
    assert payload["kind"] == "volume_points"
    assert payload["source_model"] == (
        f"{METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1}_mean"
    )
    assert payload["metadata"]["input_domain"] == (
        "signed_repetition_averaged_eeg_time_series"
    )
    assert payload["metadata"]["inverse_method"] == "eLORETA"
    assert payload["metadata"]["legacy_amplitude_topography_input"] is False
    assert payload["metadata"]["condition_source_input"] == (
        "signed_time_domain_derivative"
    )
    assert payload["metadata"]["renderer_dependency"] == "none"

    validation = json.loads(first.validation_report_path.read_text(encoding="utf-8"))
    assert validation["export_model"] == (
        METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1
    )
    assert validation["input_summary"]["condition_summaries"][0]["workbook_count"] == 0
    assert validation["input_summary"]["candidate_noise_offsets"] == [
        *range(-10, -1),
        *range(2, 11),
    ]
    assert validation["input_summary"][
        "required_candidate_noise_bin_count"
    ] == 18
    assert validation["input_summary"][
        "retained_noise_bin_count_after_extreme_drop"
    ] == 16
    assert validation["input_summary"]["min_noise_bins"] == 18
    assert "legacy_fullfft_fallback=forbidden" in validation["input_summary"][
        "diagnostics"
    ]

    def fail_if_recomputed(**_kwargs: Any) -> Any:
        raise AssertionError("valid eLORETA source-PSD cache entry should be reused")

    second = write_project_eloreta_volume_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        apply_inverse_func=fail_if_recomputed,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )
    assert second.cache_hit_count == 1
    assert second.cache_miss_count == 0

    alternate_params = {**DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS, "eps": 2e-6}
    alternate_calls: list[dict[str, Any]] = []
    separated = write_project_eloreta_volume_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(method_params=alternate_params),
        selected_harmonics_hz=(20.0,),
        apply_inverse_func=_apply_inverse_callable(alternate_calls),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )
    assert separated.cache_hit_count == 0
    assert separated.cache_miss_count == 1
    assert len(alternate_calls) == 1
    assert alternate_calls[0]["method_params"] == alternate_params
    cache_metadata_files = tuple(
        (project.project_root / ".fpvs_processing" / "source_psd_cache" / "v1").rglob(
            "*.json"
        )
    )
    assert len(cache_metadata_files) == 2
    cache_metadata = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in cache_metadata_files
    ]
    assert {
        payload["key_payload"]["numerical_model_metadata"]["model_kind"]
        for payload in cache_metadata
    } == {"mne_fsaverage_biosemi64_eloreta_volume_source_psd"}
    assert {
        payload["key_payload"]["method_metadata"]["inverse_method"]
        for payload in cache_metadata
    } == {"eLORETA"}
    assert {
        payload["key_payload"]["method_metadata"]["method_params"]["eps"]
        for payload in cache_metadata
    } == {1e-6, 2e-6}
    assert {
        payload["result_metadata"]["method_id"] for payload in cache_metadata
    } == {METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1}


def test_project_eloreta_source_psd_uses_complete_case_group_splits(
    tmp_path: Path,
) -> None:
    conditions = {"Condition A": 21, "Condition B": 22}
    participant_groups = {
        "P01": ("control", "Control Group"),
        "P02": ("patient", "Patient Group"),
        "P03": ("control", "Control Group"),
    }
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02", "P03"),
        participant_groups=participant_groups,
        event_map=conditions,
        entry_changes={
            "P01": {"source_derivative_status": "complete"},
            "P02": {"source_derivative_status": "complete"},
            "P03": {
                "condition_completeness": "partial",
                "missing_condition_labels": ["Condition B"],
                "source_derivative_status": "incomplete",
                "source_derivative_warning": "Missing source epoch condition(s): Condition B",
            },
        },
    )
    for participant_id in ("P01", "P02"):
        group_id, group_folder = participant_groups[participant_id]
        _write_time_domain_derivative(
            project.project_root,
            participant_id=participant_id,
            group_id=group_id,
            group_folder=group_folder,
            conditions=conditions,
        )
    progress: list[str] = []

    result = write_project_eloreta_volume_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        apply_inverse_func=_apply_inverse_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
        progress_callback=progress.append,
    )

    assert result.included_participants == ("P01", "P02")
    assert [item.participant_id for item in result.source_ineligible_participants] == [
        "P03"
    ]
    assert result.source_ineligible_participants[0].reason_code == (
        "incomplete_condition_set"
    )
    assert [record.participant_id for record in result.project_inputs.records] == [
        "P01",
        "P01",
        "P02",
        "P02",
    ]
    assert any("omitting P03 from every source condition" in item for item in progress)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["metadata"]["group_summary_policy"] == (
        "separate_canonical_project_groups"
    )
    assert [condition["id"] for condition in manifest["conditions"]] == [
        "control_21_mean",
        "patient_21_mean",
        "control_22_mean",
        "patient_22_mean",
    ]
    expected_participants = {"control": ["P01"], "patient": ["P02"]}
    for condition in manifest["conditions"]:
        group = condition["metadata"]["project_group"]
        assert group["group_split_applied"] is True
        assert group["participant_ids"] == expected_participants[group["group_id"]]
        payload = json.loads(
            (result.output_dir / condition["file"]).read_text(encoding="utf-8")
        )
        assert payload["metadata"]["participant_ids"] == expected_participants[
            group["group_id"]
        ]
        assert payload["metadata"]["condition_group_id"] == group["group_id"]

    sidecar = json.loads(result.participant_sidecar_path.read_text(encoding="utf-8"))
    assert [row["condition_id"] for row in sidecar["conditions"]] == [
        "control_21",
        "patient_21",
        "control_22",
        "patient_22",
    ]
    assert sidecar["metadata"]["included_participants"] == ["P01", "P02"]
    assert [
        item["participant_id"]
        for item in sidecar["metadata"]["source_ineligible_participants"]
    ] == ["P03"]

    validation = json.loads(result.validation_report_path.read_text(encoding="utf-8"))
    assert validation["input_summary"]["source_cohort_status"] == (
        "complete_with_warnings"
    )
    assert validation["input_summary"]["condition_count"] == 4
    assert [
        item["participant_id"]
        for item in validation["input_summary"]["source_ineligible_participants"]
    ] == ["P03"]


def test_project_eloreta_source_psd_confines_root_and_output(tmp_path: Path) -> None:
    project = _project_with_ledger(tmp_path / "project", participants=("P01",))
    other_root = tmp_path / "other"
    other_root.mkdir()

    with pytest.raises(ValueError, match="must match the active project"):
        write_project_eloreta_volume_hauk_source_psd_payloads(
            project=project,
            project_root=other_root,
            selected_harmonics_hz=(20.0,),
        )
    with pytest.raises(ValueError, match="must stay inside the project root"):
        write_project_eloreta_volume_hauk_source_psd_payloads(
            project=project,
            output_dir=tmp_path / "outside",
            selected_harmonics_hz=(20.0,),
        )

    default_output = default_project_eloreta_volume_hauk_source_psd_output_dir(
        project.project_root
    )
    assert default_output.is_relative_to(project.project_root)
    assert "eLORETA Hauk Source PSD" in default_output.name


def _project_with_ledger(
    root: Path,
    *,
    participants: tuple[str, ...],
    entry_changes: dict[str, dict[str, Any]] | None = None,
    participant_groups: dict[str, tuple[str, str]] | None = None,
    event_map: dict[str, int] | None = None,
) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    canonical_event_map = event_map or {"Condition A": 21}
    groups: dict[str, Any] = {}
    project_participants: dict[str, Any] = {}
    if participant_groups is not None:
        for participant_id in participants:
            group_id, group_label = participant_groups[participant_id]
            groups.setdefault(
                group_id,
                {
                    "label": group_label,
                    "folder_name": group_label,
                    "raw_input_folder": str(root / "Raw" / group_id),
                },
            )
            project_participants[participant_id] = {"group_id": group_id}
    project = Project.load(
        root,
        manifest={
            "name": "eLORETA Source PSD Test",
            "event_map": canonical_event_map,
            "groups": groups,
            "participants": project_participants,
        },
    )
    entries: dict[str, dict[str, Any]] = {}
    for participant_id in participants:
        group_id = (
            participant_groups[participant_id][0]
            if participant_groups is not None
            else None
        )
        entries[participant_id] = {
            "participant_id": participant_id,
            "group_id": group_id,
            "status": "completed",
            "condition_completeness": "complete",
            "missing_condition_labels": [],
            "processing_fingerprint": PROCESSING_FINGERPRINT,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "expected_outputs": [
                str(
                    root
                    / "1 - Excel Data Files"
                    / condition_label
                    / f"{participant_id}_{condition_label}_Results.xlsx"
                )
                for condition_label in canonical_event_map
            ],
        }
    for participant_id, changes in (entry_changes or {}).items():
        entries[participant_id].update(changes)
    ledger_path = root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps({"schema_version": 1, "entries": entries}, indent=2),
        encoding="utf-8",
    )
    return project


def _write_time_domain_derivative(
    root: Path,
    *,
    participant_id: str,
    group_id: str | None = None,
    group_folder: str | None = None,
    conditions: dict[str, int] | None = None,
) -> None:
    canonical_conditions = conditions or {"Condition A": 21}
    times = np.arange(N_TIMES, dtype=float) / SFREQ
    repetitions = np.stack(
        [
            np.vstack(
                [
                    (channel + 1)
                    * 1e-8
                    * np.sin(
                        2.0 * np.pi * 5.0 * times
                        + channel * 0.03
                        + repetition * 0.1
                    )
                    for channel in range(len(DEFAULT_ELECTRODE_NAMES_64))
                ]
            )
            for repetition in range(2)
        ]
    )
    info = mne.create_info(
        list(DEFAULT_ELECTRODE_NAMES_64),
        sfreq=SFREQ,
        ch_types="eeg",
    )
    info.set_montage("biosemi64", on_missing="raise")
    epochs = mne.EpochsArray(
        repetitions,
        info,
        tmin=0.0,
        baseline=None,
        verbose=False,
    )
    epochs.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    epochs.apply_proj(verbose=False)
    write_source_ready_time_domain_derivatives(
        project_root=root,
        participant_id=participant_id,
        group_id=group_id,
        group_folder=group_folder,
        condition_epochs={label: epochs for label in canonical_conditions},
        condition_ids=canonical_conditions,
        crop_provenance_by_condition={
            label: {
                "crop_mode": "55_onbin",
                "N": N_TIMES,
                "N_step": N_TIMES,
                "N_mod_step": 0,
            }
            for label in canonical_conditions
        },
        processing_provenance={
            "processing_fingerprint": PROCESSING_FINGERPRINT,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
        },
    )


def _source_psd_model(
    *,
    method_params: dict[str, Any] | None = None,
) -> MneFsaverageELORETAVolumeSourcePsdModel:
    points = np.asarray(
        [
            [-20.0, -20.0, 0.0],
            [0.0, -20.0, 10.0],
            [20.0, -20.0, 0.0],
            [0.0, 0.0, 20.0],
        ],
        dtype=float,
    )
    leadfield = np.arange(64 * 4, dtype=float).reshape(64, 4) / 1000.0 + 0.01

    def legacy_topography_estimator(*_args: Any, **_kwargs: Any) -> np.ndarray:
        raise AssertionError(
            "time-domain eLORETA export must not call the legacy FullFFT estimator"
        )

    forward_model = ELORETAVolumeForwardModel(
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        source_points=points,
        leadfield=leadfield,
        source_adjacency=(
            {1, 3},
            {0, 2, 3},
            {1, 3},
            {0, 1, 2},
        ),
        metadata={
            "inverse_backend": "test_injected_mne",
            "source_space_kind": "volume",
            "volume_pos_mm": 10.0,
            "model_sfreq_hz": SFREQ,
        },
        source_estimator=legacy_topography_estimator,
        source_indices=tuple(range(len(points))),
    )
    info = mne.create_info(
        list(DEFAULT_ELECTRODE_NAMES_64),
        sfreq=SFREQ,
        ch_types="eeg",
    )
    info.set_montage("biosemi64", on_missing="raise")
    return MneFsaverageELORETAVolumeSourcePsdModel(
        forward_model=forward_model,
        info=info,
        inverse_operator={"source_count": len(points)},
        prepared=True,
        lambda2=DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
        method_params=(
            dict(DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS)
            if method_params is None
            else dict(method_params)
        ),
    )


def _apply_inverse_callable(calls: list[dict[str, Any]]):
    def apply_inverse(**kwargs: Any) -> SimpleNamespace:
        calls.append(dict(kwargs))
        frequency_count = int(kwargs["evoked"].data.shape[1])
        source_count = int(kwargs["inverse_operator"]["source_count"])
        amplitudes = (
            1.0
            + np.arange(source_count, dtype=float)[:, None] * 0.05
            + np.arange(frequency_count, dtype=float)[None, :] * 0.02
        )
        amplitudes[:, frequency_count // 2] += 1.5
        vector_coefficients = np.zeros(
            (source_count, 3, frequency_count),
            dtype=np.complex128,
        )
        vector_coefficients[:, 0, :] = amplitudes * np.exp(0.25j)
        return SimpleNamespace(data=vector_coefficients)

    return apply_inverse
