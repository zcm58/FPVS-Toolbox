from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from openpyxl import Workbook
import pytest

from Main_App.processing.full_fft_provenance import (
    FULL_FFT_PROVENANCE_METHOD_VERSION,
    FullFftProvenanceError,
    FullFftProvenanceMissingError,
    FullFftProvenanceStaleError,
    mark_project_full_fft_provenance_stale,
    validate_project_full_fft_provenance,
    write_project_full_fft_provenance,
)
from Tools.Free_Harmonic_Clustering.preparation import (
    build_available_frequency_window_plan,
)


def _header(*, spacing_hz: float = 0.025, upper_hz: float = 3.75) -> list[str]:
    frequencies = np.arange(
        int(round(upper_hz / spacing_hz)) + 1,
        dtype=np.float64,
    ) * spacing_hz
    return ["Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies)]


def _write_full_fft_workbook(path: Path, header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("FullFFT Amplitude (uV)")
    sheet.append(header)
    sheet.append(["Fp1", *(1.0 for _ in header[1:])])
    workbook.save(path)


def _write_project(
    tmp_path: Path,
    *,
    second_header: list[str] | None = None,
) -> tuple[Path, tuple[Path, ...]]:
    root = tmp_path / "Project"
    root.mkdir()
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "participants": {"P1": {}, "P2": {}},
        "preprocessing": {},
    }
    (root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    paths = (
        root / "1 - Excel Data Files" / "Faces" / "P1_Faces_Results.xlsx",
        root / "1 - Excel Data Files" / "Faces" / "P2_Faces_Results.xlsx",
    )
    _write_full_fft_workbook(paths[0], _header())
    _write_full_fft_workbook(paths[1], second_header or _header())
    return root, paths


def test_neutral_provenance_round_trip_is_stats_independent_and_project_relative(
    tmp_path: Path,
) -> None:
    root, paths = _write_project(tmp_path)

    written = write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest["tools"]["processing"]["full_fft_provenance"]
    metadata_paths = tuple(row["path"] for row in metadata["source_workbooks"])

    assert metadata["method_version"] == FULL_FFT_PROVENANCE_METHOD_VERSION
    assert "stats" not in manifest["tools"]
    assert metadata["cohort_state"]["ledger_filter_applied"] is False
    assert metadata["frequency_qc_state"]["excluded_participants"] == []
    assert metadata["processing_export_state"] == []
    assert written.source_workbook_count == 2
    assert written.source_paths == metadata_paths
    assert all(not Path(value).is_absolute() for value in metadata_paths)
    assert set(metadata_paths) == {
        path.relative_to(root).as_posix() for path in paths
    }

    # A standard Summed-BCA-only stale marker must not participate in FullFFT
    # freshness or prevent sibling FHC use.
    manifest["tools"]["stats"] = {
        "summed_bca_derivatives_stale": True,
        "group_significant_harmonics_cache": {},
    }
    manifest["tools"]["post_processing"] = {
        "artifact_freshness": {
            "artifacts": {
                "stats_ready_summed_bca": {"status": "stale"},
                "analysis_ready_full_audit": {"status": "stale"},
            }
        }
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    validated = validate_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )

    assert validated.grid_fingerprint == written.grid_fingerprint
    fhc_plan = build_available_frequency_window_plan(
        _header(),
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
        noise_half_width_hz=0.1,
    )
    assert validated.grid_fingerprint == fhc_plan.grid_fingerprint


def test_missing_record_requests_postprocessing_not_eeg_preprocessing(
    tmp_path: Path,
) -> None:
    root, _paths = _write_project(tmp_path)

    with pytest.raises(FullFftProvenanceMissingError) as captured:
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )

    message = str(captured.value)
    assert "Rerun post-processing" in message
    assert "EEG preprocessing is not required" in message


def test_changed_full_fft_file_is_stale_but_can_be_rebuilt_without_raw_data(
    tmp_path: Path,
) -> None:
    root, paths = _write_project(tmp_path)
    write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    with paths[0].open("ab") as stream:
        stream.write(b"changed-after-provenance")

    with pytest.raises(FullFftProvenanceStaleError, match="workbook path, size"):
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def test_changed_canonical_cohort_is_stale_even_when_workbook_bytes_do_not_change(
    tmp_path: Path,
) -> None:
    root, _paths = _write_project(tmp_path)
    write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["manual_excluded_participants"] = ["P2"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(FullFftProvenanceStaleError, match="cohort"):
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def test_rate_mismatch_and_explicit_stale_status_block_validation(
    tmp_path: Path,
) -> None:
    root, _paths = _write_project(tmp_path)
    write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )

    with pytest.raises(FullFftProvenanceStaleError, match="do not match"):
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=7.5,
            oddball_frequency_hz=1.2,
        )

    mark_project_full_fft_provenance_stale(root, reason="FullFFT export changed")
    with pytest.raises(FullFftProvenanceStaleError, match="FullFFT export changed"):
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def test_record_creation_rejects_mixed_full_fft_grids(tmp_path: Path) -> None:
    root, _paths = _write_project(
        tmp_path,
        second_header=_header(spacing_hz=0.02),
    )

    with pytest.raises(FullFftProvenanceError, match="one exact FullFFT grid"):
        write_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )
