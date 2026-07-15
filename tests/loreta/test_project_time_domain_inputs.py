from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import mne
import numpy as np
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.exports.source_time_domain_export import write_source_ready_time_domain_derivatives
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import (
    ExpectedProjectTimeDomainInput,
    PROJECT_TIME_DOMAIN_INPUT_FOLDER,
    ProjectTimeDomainInputError,
    SOURCE_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT,
    SOURCE_TIME_DOMAIN_SIDECAR_FORMAT,
    load_project_time_domain_inputs,
)

PROCESSING_FINGERPRINT = "processing-fingerprint-123"
PROCESSING_FINGERPRINT_VERSION = "processing_fingerprint_v8_fft_multinotch"
SFREQ = 256.0
N_TIMES = 640
N_STEP = 640


@dataclass(frozen=True)
class _DerivativeFixture:
    project_root: Path
    manifest_path: Path
    fif_paths: dict[str, Path]
    sidecar_paths: dict[str, Path]


def test_load_project_time_domain_inputs_validates_and_lazily_loads_one_raw(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)

    result = _load(fixture.project_root, [_expected()])

    assert result.input_root.name == PROJECT_TIME_DOMAIN_INPUT_FOLDER
    assert result.sfreq_hz == SFREQ
    assert result.n_times == N_TIMES
    assert result.frequency_resolution_hz == pytest.approx(SFREQ / N_TIMES)
    assert [record.key for record in result.records] == [(None, "P01", "condition_a")]
    record = result.records[0]
    assert record.condition_label == "Condition A"
    assert record.channel_names == tuple(DEFAULT_ELECTRODE_NAMES_64)
    assert record.n_step == N_STEP

    yielded = 0
    for loaded in result.iter_loaded_raws():
        yielded += 1
        assert loaded.record is record
        assert loaded.raw.preload is True
        assert loaded.raw.get_data().shape == (64, N_TIMES)
        assert np.all(np.isfinite(loaded.raw.get_data()))
    assert yielded == 1


def test_load_project_time_domain_inputs_accepts_processing_writer_output(tmp_path: Path) -> None:
    info = mne.create_info(list(DEFAULT_ELECTRODE_NAMES_64), sfreq=SFREQ, ch_types="eeg")
    info.set_montage("biosemi64", on_missing="raise")
    data = np.stack(
        [
            _make_raw(tuple(DEFAULT_ELECTRODE_NAMES_64), n_times=N_TIMES, include_nonfinite=False).get_data(),
            np.zeros((len(DEFAULT_ELECTRODE_NAMES_64), N_TIMES), dtype=float),
        ]
    )
    epochs = mne.EpochsArray(data, info, tmin=0.0, baseline=None, verbose=False)
    epochs.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    epochs.apply_proj(verbose=False)

    write_source_ready_time_domain_derivatives(
        project_root=tmp_path,
        participant_id="P01",
        condition_epochs={"Condition A": epochs},
        condition_ids={"Condition A": "condition_a"},
        crop_provenance_by_condition={
            "Condition A": {
                "crop_mode": "55_onbin",
                "N": N_TIMES,
                "N_step": N_STEP,
                "N_mod_step": 0,
            }
        },
        processing_provenance={
            "processing_fingerprint": PROCESSING_FINGERPRINT,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
        },
    )

    result = _load(tmp_path, [_expected()])

    assert len(result.records) == 1
    assert result.records[0].condition_label == "Condition A"
    for loaded in result.iter_loaded_raws():
        assert loaded.raw.get_data().shape == (64, N_TIMES)


def test_load_project_time_domain_inputs_supports_condition_first_group_second_layout(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(
        tmp_path,
        group_id="control",
        group_folder="Control Group",
    )

    result = _load(
        fixture.project_root,
        [
            ExpectedProjectTimeDomainInput(
                participant_id="P01",
                condition_id="condition_a",
                condition_label="Condition A",
                group_id="control",
                group_folder="Control Group",
            )
        ],
    )

    record = result.records[0]
    assert record.group_id == "control"
    assert record.group_folder == "Control Group"
    assert record.fif_path.parent.name == "Control Group"
    assert record.fif_path.parent.parent.name == "Condition A"
    assert fixture.manifest_path.parent.name == "Control Group"


def test_load_project_time_domain_inputs_rejects_missing_expected_condition_without_fallback(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    amplitude_dir = fixture.project_root / "1 - Excel Data Files" / "Condition B"
    amplitude_dir.mkdir(parents=True)
    (amplitude_dir / "P01_Condition_B_Results.xlsx").write_bytes(b"not a fallback")

    with pytest.raises(ProjectTimeDomainInputError, match="amplitude workbooks are not a fallback"):
        _load(
            fixture.project_root,
            [ExpectedProjectTimeDomainInput(participant_id="P01", condition_id="condition_b")],
        )


def test_load_project_time_domain_inputs_rejects_duplicate_expected_key(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    expected = _expected()

    with pytest.raises(ProjectTimeDomainInputError, match="Duplicate expected"):
        _load(fixture.project_root, [expected, expected])


def test_load_project_time_domain_inputs_rejects_project_path_escape(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    manifest = _read_json(fixture.manifest_path)
    manifest["artifacts"][0]["fif_path"] = "../outside_avg-raw.fif"
    _write_json(fixture.manifest_path, manifest)

    with pytest.raises(ProjectTimeDomainInputError, match="safe project-relative POSIX path"):
        _load(fixture.project_root, [_expected()])


def test_load_project_time_domain_inputs_rejects_checksum_mismatch(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    with fixture.fif_paths["condition_a"].open("ab") as handle:
        handle.write(b"corrupt")

    with pytest.raises(ProjectTimeDomainInputError, match="checksum mismatch"):
        _load(fixture.project_root, [_expected()])


@pytest.mark.parametrize(
    ("manifest_change", "match"),
    [
        (lambda payload: payload.__setitem__("format", "unsupported-v0"), "Unsupported participant commit"),
        (
            lambda payload: payload.__setitem__("schema_version", 2),
            "Unsupported participant commit manifest .* schema",
        ),
        (lambda payload: payload.__setitem__("complete", False), "not complete"),
        (lambda payload: payload["artifacts"][0].__setitem__("complete", False), "not committed as complete"),
    ],
)
def test_load_project_time_domain_inputs_rejects_uncommitted_or_wrong_schema(
    tmp_path: Path,
    manifest_change: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    manifest = _read_json(fixture.manifest_path)
    manifest_change(manifest)
    _write_json(fixture.manifest_path, manifest)

    with pytest.raises(ProjectTimeDomainInputError, match=match):
        _load(fixture.project_root, [_expected()])


def test_load_project_time_domain_inputs_rejects_stale_processing_fingerprint(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path)

    with pytest.raises(ProjectTimeDomainInputError, match="Stale source-ready derivative"):
        load_project_time_domain_inputs(
            fixture.project_root,
            expected_inputs=[_expected()],
            expected_processing_fingerprint="new-fingerprint",
            expected_processing_fingerprint_version=PROCESSING_FINGERPRINT_VERSION,
        )


@pytest.mark.parametrize(
    ("sidecar_change", "match"),
    [
        (lambda payload: payload.__setitem__("schema_version", 2), "Unsupported sidecar .* schema"),
        (
            lambda payload: payload["sampling"].__setitem__("frequency_resolution_hz", 0.123),
            "frequency_resolution_hz must equal sfreq / N",
        ),
        (lambda payload: payload["crop"].__setitem__("crop_mode", None), "crop_mode=55_onbin"),
        (lambda payload: payload["crop"].__setitem__("N_mod_step", 1), "crop contract is incompatible"),
        (
            lambda payload: payload["channels"].__setitem__(
                "names",
                list(reversed(DEFAULT_ELECTRODE_NAMES_64)),
            ),
            "exact Toolbox BioSemi64 order",
        ),
        (
            lambda payload: payload["reference"]["projections"][0].__setitem__("active", False),
            "requires an applied Average EEG reference projection",
        ),
        (
            lambda payload: payload["aggregation"].__setitem__("signed_values_preserved", False),
            "does not preserve signed values",
        ),
    ],
)
def test_load_project_time_domain_inputs_rejects_incompatible_sidecar_contracts(
    tmp_path: Path,
    sidecar_change: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    fixture = _write_derivative_fixture(tmp_path)
    _change_sidecar(fixture, "condition_a", sidecar_change)

    with pytest.raises(ProjectTimeDomainInputError, match=match):
        _load(fixture.project_root, [_expected()])


def test_load_project_time_domain_inputs_checks_fif_header_against_sidecar(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(
        tmp_path,
        raw_channel_names=tuple(reversed(DEFAULT_ELECTRODE_NAMES_64)),
        claimed_channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
    )

    with pytest.raises(ProjectTimeDomainInputError, match="FIF channel order does not match"):
        _load(fixture.project_root, [_expected()])


def test_load_project_time_domain_inputs_rejects_cross_record_sampling_incompatibility(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(
        tmp_path,
        conditions=(
            ("condition_a", "Condition A", N_TIMES),
            ("condition_b", "Condition B", N_TIMES * 2),
        ),
    )

    with pytest.raises(ProjectTimeDomainInputError, match="same exact sample count N"):
        _load(
            fixture.project_root,
            [
                _expected(),
                ExpectedProjectTimeDomainInput(
                    participant_id="P01",
                    condition_id="condition_b",
                    condition_label="Condition B",
                ),
            ],
        )


def test_iter_loaded_raws_rejects_nonfinite_data(tmp_path: Path) -> None:
    fixture = _write_derivative_fixture(tmp_path, include_nonfinite=True)
    result = _load(fixture.project_root, [_expected()])

    with pytest.raises(ProjectTimeDomainInputError, match="non-finite"):
        next(result.iter_loaded_raws())


def _load(
    project_root: Path,
    expected: list[ExpectedProjectTimeDomainInput],
):
    return load_project_time_domain_inputs(
        project_root,
        expected_inputs=expected,
        expected_processing_fingerprint=PROCESSING_FINGERPRINT,
        expected_processing_fingerprint_version=PROCESSING_FINGERPRINT_VERSION,
    )


def _expected() -> ExpectedProjectTimeDomainInput:
    return ExpectedProjectTimeDomainInput(
        participant_id="P01",
        condition_id="condition_a",
        condition_label="Condition A",
    )


def _write_derivative_fixture(
    project_root: Path,
    *,
    participant_id: str = "P01",
    group_id: str | None = None,
    group_folder: str | None = None,
    conditions: tuple[tuple[str, str, int], ...] = (("condition_a", "Condition A", N_TIMES),),
    raw_channel_names: tuple[str, ...] | None = None,
    claimed_channel_names: tuple[str, ...] | None = None,
    include_nonfinite: bool = False,
) -> _DerivativeFixture:
    source_root = (
        project_root
        / "6 - Source Localization"
        / PROJECT_TIME_DOMAIN_INPUT_FOLDER
    )
    channel_names = raw_channel_names or tuple(DEFAULT_ELECTRODE_NAMES_64)
    claimed_names = claimed_channel_names or channel_names
    artifacts: list[dict[str, Any]] = []
    fif_paths: dict[str, Path] = {}
    sidecar_paths: dict[str, Path] = {}
    for condition_index, (condition_id, condition_label, n_times) in enumerate(conditions, start=1):
        artifact_dir = source_root / condition_label
        if group_folder is not None:
            artifact_dir /= group_folder
        artifact_dir.mkdir(parents=True, exist_ok=True)
        fif_path = artifact_dir / f"{participant_id}_{condition_id}_avg_raw.fif"
        sidecar_path = artifact_dir / f"{participant_id}_{condition_id}_avg_raw.json"
        raw = _make_raw(channel_names, n_times=n_times, include_nonfinite=include_nonfinite)
        raw.save(fif_path, overwrite=True, verbose=False)
        fif_sha256 = _sha256(fif_path)
        projections = [
            {
                "description": str(projection["desc"]),
                "active": bool(projection["active"]),
                "kind": int(projection["kind"]),
            }
            for projection in raw.info["projs"]
        ]
        n_step = N_STEP
        sidecar = {
            "format": SOURCE_TIME_DOMAIN_SIDECAR_FORMAT,
            "schema_version": 1,
            "complete": True,
            "participant_id": participant_id,
            "group_id": group_id,
            "group_folder": group_folder,
            "condition_id": condition_id,
            "condition_label": condition_label,
            "fif_path": fif_path.relative_to(project_root).as_posix(),
            "fif_sha256": fif_sha256,
            "source_signature": {
                "source_file": f"{participant_id}.bdf",
                "size": 1234,
                "mtime_ns": 5678,
            },
            "processing": {
                "fingerprint": PROCESSING_FINGERPRINT,
                "fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                "provenance": {},
            },
            "sampling": {
                "sfreq_hz": SFREQ,
                "n_times": n_times,
                "duration_sec": n_times / SFREQ,
                "frequency_resolution_hz": SFREQ / n_times,
            },
            "channels": {
                "count": len(claimed_names),
                "names": list(claimed_names),
                "types": ["eeg"] * len(claimed_names),
                "units": ["V"] * len(claimed_names),
                "bads": [],
                "eeg_only": True,
            },
            "reference": {
                "custom_ref_applied": int(raw.info["custom_ref_applied"]),
                "projections": projections,
            },
            "aggregation": {
                "domain": "time",
                "method": "arithmetic_mean",
                "repetition_count": 4,
                "signed_values_preserved": True,
            },
            "crop": {
                "crop_mode": "55_onbin",
                "N": n_times,
                "N_step": n_step,
                "N_mod_step": n_times % n_step,
                "provenance": [{"repetition": 1, "condition_index": condition_index}],
            },
            "resolved_protocol": {
                "presentation_rate_hz": None,
                "oddball_rate_hz": None,
                "contrast_modulation": None,
            },
        }
        _write_json(sidecar_path, sidecar)
        artifacts.append(
            {
                "condition_id": condition_id,
                "condition_label": condition_label,
                "fif_path": fif_path.relative_to(project_root).as_posix(),
                "sidecar_path": sidecar_path.relative_to(project_root).as_posix(),
                "fif_sha256": fif_sha256,
                "sidecar_sha256": _sha256(sidecar_path),
                "complete": True,
            }
        )
        fif_paths[condition_id] = fif_path
        sidecar_paths[condition_id] = sidecar_path

    manifest_dir = source_root / "manifests"
    if group_folder is not None:
        manifest_dir /= group_folder
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{participant_id}.json"
    _write_json(
        manifest_path,
        {
            "format": SOURCE_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT,
            "schema_version": 1,
            "complete": True,
            "participant_id": participant_id,
            "group_id": group_id,
            "group_folder": group_folder,
            "artifacts": artifacts,
        },
    )
    return _DerivativeFixture(
        project_root=project_root,
        manifest_path=manifest_path,
        fif_paths=fif_paths,
        sidecar_paths=sidecar_paths,
    )


def _make_raw(
    channel_names: tuple[str, ...],
    *,
    n_times: int,
    include_nonfinite: bool,
):
    times = np.arange(n_times, dtype=float) / SFREQ
    data = np.vstack(
        [
            (index + 1) * 1e-7 * np.sin(2.0 * np.pi * 1.2 * times + index / 10.0)
            for index in range(len(channel_names))
        ]
    )
    if include_nonfinite:
        data[0, 0] = np.nan
    info = mne.create_info(list(channel_names), sfreq=SFREQ, ch_types=["eeg"] * len(channel_names))
    raw = mne.io.RawArray(data, info, verbose=False)
    raw.set_montage("biosemi64", on_missing="raise", verbose=False)
    raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    raw.apply_proj(verbose=False)
    return raw


def _change_sidecar(
    fixture: _DerivativeFixture,
    condition_id: str,
    change: Callable[[dict[str, Any]], None],
) -> None:
    sidecar_path = fixture.sidecar_paths[condition_id]
    sidecar = _read_json(sidecar_path)
    change(sidecar)
    _write_json(sidecar_path, sidecar)
    manifest = _read_json(fixture.manifest_path)
    artifact = next(item for item in manifest["artifacts"] if item["condition_id"] == condition_id)
    artifact["sidecar_sha256"] = _sha256(sidecar_path)
    _write_json(fixture.manifest_path, manifest)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
