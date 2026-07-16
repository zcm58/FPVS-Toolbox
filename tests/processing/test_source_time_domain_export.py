from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import mne
import numpy as np
import pandas as pd
import pytest

from Main_App.exports import source_time_domain_export as export_module
from Main_App.exports.source_time_domain_export import (
    SOURCE_READY_TIME_DOMAIN_FORMAT,
    SOURCE_READY_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT,
    SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT,
    write_source_ready_time_domain_derivatives,
)


def _epochs(*, scale: float = 1.0) -> mne.EpochsArray:
    info = mne.create_info(
        ["Fz", "Cz", "Status"],
        sfreq=8.0,
        ch_types=["eeg", "eeg", "stim"],
    )
    info.set_montage(mne.channels.make_standard_montage("standard_1020"))
    data = np.asarray(
        [
            [
                [-4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0],
                [4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0],
                [21.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            [
                [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0],
                [2.0, 1.5, 1.0, 0.5, -0.5, -1.0, -1.5, -2.0],
                [21.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ],
        ],
        dtype=float,
    )
    events = np.asarray([[0, 0, 21], [8, 0, 21]], dtype=int)
    epochs = mne.EpochsArray(
        data * scale,
        info,
        events=events,
        event_id={"Condition A": 21},
        tmin=0.0,
        baseline=None,
        verbose=False,
    )
    epochs.metadata = pd.DataFrame(
        [
            {
                "crop_mode": "55_onbin",
                "N_step": 4,
                "N_mod_step": 0,
                "oddball_id": 55,
            },
            {
                "crop_mode": "55_onbin",
                "N_step": 4,
                "N_mod_step": 0,
                "oddball_id": 55,
            },
        ]
    )
    epochs.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    epochs.apply_proj(verbose=False)
    return epochs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_writes_signed_eeg_mean_sidecar_and_commit_manifest(tmp_path: Path) -> None:
    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()
    epochs = _epochs(scale=1e-6)
    eeg_picks = mne.pick_types(epochs.info, eeg=True, meg=False, exclude=[])
    expected = epochs.get_data(picks=eeg_picks, copy=True).mean(axis=0)

    result = write_source_ready_time_domain_derivatives(
        project_root=project_root,
        participant_id="P01",
        group_id="control",
        group_folder="Control",
        condition_epochs={"Condition A": [epochs]},
        condition_ids={"Condition A": "condition-a"},
        crop_provenance_by_condition={
            "Condition A": {
                "crop_mode": "55_onbin",
                "N": 8,
                "N_step": 4,
                "N_mod_step": 0,
                "fs": 8.0,
            }
        },
        processing_provenance={
            "processing_fingerprint": "processing-hash",
            "processing_fingerprint_version": "processing-v1",
            "preprocessing_order": "locked",
        },
        source_signature={"raw_file": "Input/P01.bdf", "raw_size": 1234},
        resolved_protocol_by_condition={
            "Condition A": {
                "presentation_rate_hz": 6.0,
                "oddball_rate_hz": 1.2,
                "contrast_modulation": {"kind": "sinusoidal", "phase_deg": 0.0},
            }
        },
    )

    expected_root = project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    artifact = result.artifacts[0]
    assert result.output_root == expected_root
    assert artifact.fif_path == (
        expected_root / "Condition A" / "Control" / "P01_condition-a_avg_raw.fif"
    )
    assert artifact.sidecar_path == (
        expected_root / "Condition A" / "Control" / "P01_condition-a_avg_raw.json"
    )
    assert result.manifest_path == (
        expected_root
        / "manifests"
        / "Control"
        / "P01.json"
    )

    exported_raw = mne.io.read_raw_fif(artifact.fif_path, preload=True, verbose=False)
    assert exported_raw.ch_names == ["Fz", "Cz"]
    assert exported_raw.get_channel_types() == ["eeg", "eeg"]
    np.testing.assert_allclose(exported_raw.get_data(), expected, rtol=0.0, atol=1e-12)
    assert np.any(exported_raw.get_data() < 0.0)
    assert np.any(exported_raw.get_data() > 0.0)
    assert exported_raw.get_montage() is not None
    assert any(projection["desc"] == "Average EEG reference" for projection in exported_raw.info["projs"])

    sidecar = json.loads(artifact.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["format"] == SOURCE_READY_TIME_DOMAIN_FORMAT
    assert sidecar["schema_version"] == 1
    assert sidecar["writer"]["mne_version"] == mne.__version__
    assert sidecar["writer"]["numpy_version"] == np.__version__
    assert sidecar["complete"] is True
    assert sidecar["participant_id"] == "P01"
    assert sidecar["group_id"] == "control"
    assert sidecar["condition_id"] == "condition-a"
    assert sidecar["fif_path"] == artifact.fif_path.relative_to(project_root).as_posix()
    assert sidecar["fif_sha256"] == _sha256(artifact.fif_path)
    assert sidecar["sampling"] == {
        "duration_sec": 1.0,
        "frequency_resolution_hz": 1.0,
        "n_times": 8,
        "sfreq_hz": 8.0,
    }
    assert sidecar["channels"] == {
        "bads": [],
        "count": 2,
        "eeg_only": True,
        "names": ["Fz", "Cz"],
        "types": ["eeg", "eeg"],
        "units": ["V", "V"],
    }
    assert sidecar["aggregation"] == {
        "domain": "time",
        "method": "arithmetic_mean",
        "repetition_count": 2,
        "signed_values_preserved": True,
    }
    assert sidecar["crop"]["crop_mode"] == "55_onbin"
    assert sidecar["crop"]["N"] == 8
    assert sidecar["crop"]["N_step"] == 4
    assert sidecar["crop"]["N_mod_step"] == 0
    assert sidecar["processing"]["fingerprint"] == "processing-hash"
    assert sidecar["processing"]["fingerprint_version"] == "processing-v1"
    assert sidecar["source_signature"] == {"raw_file": "Input/P01.bdf", "raw_size": 1234}
    assert sidecar["resolved_protocol"] == {
        "contrast_modulation": {"kind": "sinusoidal", "phase_deg": 0.0},
        "oddball_rate_hz": 1.2,
        "presentation_rate_hz": 6.0,
    }
    assert sidecar["reference"]["projections"] == [
        {"active": True, "description": "Average EEG reference", "kind": 10}
    ]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == SOURCE_READY_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT
    assert manifest["schema_version"] == 1
    assert manifest["complete"] is True
    assert manifest["artifact_count"] == 1
    assert manifest["artifacts"] == [
        {
            "complete": True,
            "condition_id": "condition-a",
            "condition_label": "Condition A",
            "fif_path": artifact.fif_path.relative_to(project_root).as_posix(),
            "sidecar_path": artifact.sidecar_path.relative_to(project_root).as_posix(),
            "fif_sha256": _sha256(artifact.fif_path),
            "sidecar_sha256": _sha256(artifact.sidecar_path),
        }
    ]


def test_export_defaults_future_protocol_fields_to_null(tmp_path: Path) -> None:
    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()

    result = write_source_ready_time_domain_derivatives(
        project_root=project_root,
        participant_id="P02",
        condition_epochs={"Condition A": _epochs(scale=1e-6)},
        condition_ids={"Condition A": "condition-a"},
    )

    sidecar = json.loads(result.artifacts[0].sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["group_id"] is None
    assert sidecar["group_folder"] is None
    assert sidecar["resolved_protocol"] == {
        "contrast_modulation": None,
        "oddball_rate_hz": None,
        "presentation_rate_hz": None,
    }
    assert sidecar["crop"]["crop_mode"] == "55_onbin"
    assert sidecar["crop"]["N_step"] == 4
    assert sidecar["crop"]["N_mod_step"] == 0


def test_export_rejects_relative_root_and_unsafe_components(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit absolute path"):
        write_source_ready_time_domain_derivatives(
            project_root=Path("relative-project"),
            participant_id="P01",
            condition_epochs={"Condition A": _epochs()},
        )

    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()
    with pytest.raises(ValueError, match="unsafe in a project path"):
        write_source_ready_time_domain_derivatives(
            project_root=project_root,
            participant_id="../outside",
            condition_epochs={"Condition A": _epochs()},
        )
    assert not (tmp_path / "outside").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path namespace regression")
def test_project_relative_paths_accept_equivalent_windows_extended_prefix(
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()
    normal_inside = project_root / "nested" / "source.fif"
    extended_inside = Path("\\\\?\\" + str(normal_inside))

    assert export_module._canonical_resolved_path(extended_inside) == normal_inside
    assert export_module.source_ready_project_relative_path(
        project_root,
        extended_inside,
    ) == "nested/source.fif"
    assert export_module._project_path(
        project_root,
        str(extended_inside.parent),
    ) == normal_inside.parent

    extended_outside = Path("\\\\?\\" + str(tmp_path / "outside" / "source.fif"))
    with pytest.raises(ValueError, match="outside the project root"):
        export_module.source_ready_project_relative_path(
            project_root,
            extended_outside,
        )


def test_atomic_replace_retries_a_transient_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def _flaky_replace(source: str, destination: str) -> None:
        calls.append((source, destination))
        if len(calls) == 1:
            raise PermissionError("transient scanner lock")

    monkeypatch.setattr(export_module.os, "replace", _flaky_replace)
    monkeypatch.setattr(export_module.time, "sleep", lambda _seconds: None)

    export_module._replace_file(Path("source.tmp"), Path("destination.json"))

    assert len(calls) == 2


def test_crop_mismatch_fails_before_any_artifact_is_committed(tmp_path: Path) -> None:
    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()

    with pytest.raises(ValueError, match="does not match Epochs N"):
        write_source_ready_time_domain_derivatives(
            project_root=project_root,
            participant_id="P01",
            condition_epochs={"Condition A": _epochs()},
            crop_provenance_by_condition={"Condition A": {"N": 12}},
        )

    output_root = project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    assert not list(output_root.rglob("*.fif"))
    assert not list(output_root.rglob("*.json"))


def test_partial_condition_failure_removes_artifacts_and_never_commits_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / "Project").resolve()
    project_root.mkdir()
    original_write_json = export_module._atomic_write_json
    sidecar_calls = 0

    def _fail_second_sidecar(path: Path, payload: dict) -> None:
        nonlocal sidecar_calls
        if payload.get("format") == SOURCE_READY_TIME_DOMAIN_FORMAT:
            sidecar_calls += 1
            if sidecar_calls == 2:
                raise OSError("simulated sidecar failure")
        original_write_json(path, payload)

    monkeypatch.setattr(export_module, "_atomic_write_json", _fail_second_sidecar)

    with pytest.raises(OSError, match="simulated sidecar failure"):
        write_source_ready_time_domain_derivatives(
            project_root=project_root,
            participant_id="P01",
            condition_epochs={
                "Condition A": _epochs(scale=1e-6),
                "Condition B": _epochs(scale=2e-6),
            },
            condition_ids={"Condition A": "a", "Condition B": "b"},
        )

    output_root = project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    assert not list(output_root.rglob("*.fif"))
    assert not list(output_root.rglob("*.json"))
    assert not list(output_root.rglob("*.tmp"))
