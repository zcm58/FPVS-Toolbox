"""Processing-owned FullFFT provenance persistence tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
from openpyxl import Workbook
import pytest

from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceError,
    FullFftProvenanceStaleError,
    require_current_project_workbook_geometry,
    require_current_project_full_fft_provenance,
    validate_project_full_fft_provenance,
    write_project_full_fft_provenance,
)
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    biosemi64_geometry_identity,
)
from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION
from Main_App.projects import FrequencyProtocol


def _write_geometry_ledger(
    root: Path,
    geometry_by_participant: dict[str, dict[str, object]],
) -> None:
    path = root / ".fpvs_processing" / "processing_ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = {
        participant: {
            "participant_id": participant,
            "status": "completed",
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": "fixture-processing-fingerprint",
            "condition_completeness": "complete",
            "geometry": geometry,
        }
        for participant, geometry in geometry_by_participant.items()
    }
    path.write_text(
        json.dumps({"schema_version": 1, "entries": entries}, indent=2),
        encoding="utf-8",
    )


def _managed_full_fft_project(
    tmp_path: Path,
    *,
    presentation_rate_hz: float = 6.0,
    oddball_every_n: int = 5,
) -> Path:
    root = tmp_path / "Project"
    root.mkdir()
    protocol = FrequencyProtocol.from_recurrence(
        presentation_rate_hz,
        oddball_every_n,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    (root / "project.json").write_text(
        json.dumps(
            {
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "participants": {"P1": {}, "P2": {}},
                "preprocessing": {},
                "frequency_protocol": protocol.to_manifest(),
                "tools": {"unrelated": {"preserved": True}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    frequencies = np.arange(151, dtype=np.float64) * 0.025
    header = ["Electrode", *(f"{value:.6f}_Hz" for value in frequencies)]
    for participant in ("P1", "P2"):
        path = (
            root
            / "1 - Excel Data Files"
            / "Faces"
            / f"{participant}_Faces_Results.xlsx"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("FullFFT Amplitude (uV)")
        sheet.append(header)
        sheet.append(["Fp1", *(1.0 for _ in frequencies)])
        workbook.save(path)
    geometry = biosemi64_geometry_identity()
    _write_geometry_ledger(root, {"P1": geometry, "P2": geometry})
    return root


def test_full_fft_provenance_rebases_when_managed_project_is_copied(
    tmp_path: Path,
) -> None:
    source = _managed_full_fft_project(tmp_path)
    written = write_project_full_fft_provenance(
        source,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    copied = tmp_path / "Copied Project"
    shutil.copytree(source, copied, copy_function=shutil.copy2)

    validated = validate_project_full_fft_provenance(
        copied,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    copied_manifest = json.loads(
        (copied / "project.json").read_text(encoding="utf-8")
    )

    assert validated.project_root == copied.resolve()
    assert validated.source_fingerprint == written.source_fingerprint
    assert copied_manifest["tools"]["unrelated"] == {"preserved": True}
    assert written.geometry_identity == biosemi64_geometry_identity()
    assert written.geometry_fingerprint == written.geometry_identity[
        "geometry_identity_fingerprint"
    ]
    assert all(not Path(value).is_absolute() for value in validated.source_paths)


def test_failed_manifest_replace_preserves_project_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    manifest_path = root / "project.json"
    before = manifest_path.read_bytes()
    original_replace = Path.replace

    def fail_provenance_replace(path: Path, target: Path) -> Path:
        if path.name == ".project.json.full-fft-provenance.tmp":
            raise PermissionError("simulated manifest replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_provenance_replace)

    with pytest.raises(PermissionError, match="simulated"):
        write_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )

    assert manifest_path.read_bytes() == before
    assert not (root / ".project.json.full-fft-provenance.tmp").exists()


def test_require_current_full_fft_provenance_uses_saved_rates_and_checks_inputs(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(
        tmp_path,
        presentation_rate_hz=7.5,
        oddball_every_n=6,
    )
    written = write_project_full_fft_provenance(
        root,
        base_frequency_hz=7.5,
        oddball_frequency_hz=1.25,
    )

    current = require_current_project_full_fft_provenance(root)

    assert current == written
    assert current.base_frequency_hz == 7.5
    assert current.oddball_frequency_hz == 1.25
    assert current.frequency_protocol_fingerprint

    workbook_path = root / Path(current.source_paths[0])
    workbook_path.touch()
    with pytest.raises(FullFftProvenanceStaleError, match="workbook path, size"):
        require_current_project_full_fft_provenance(root)


def test_rate_mismatch_wins_when_saved_full_fft_inputs_are_also_stale(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    record = write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    (root / Path(record.source_paths[0])).touch()

    with pytest.raises(
        FullFftProvenanceStaleError,
        match="Current Project Settings rates do not match",
    ):
        validate_project_full_fft_provenance(
            root,
            base_frequency_hz=7.5,
            oddball_frequency_hz=1.2,
        )


def test_current_full_fft_provenance_rejects_changed_project_protocol(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    record = write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source="manual",
    )
    manifest["frequency_protocol"] = changed_protocol.to_manifest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(
        FullFftProvenanceStaleError,
        match="project frequency protocol changed",
    ):
        require_current_project_full_fft_provenance(root)

    assert record.frequency_protocol_fingerprint != changed_protocol.fingerprint


def test_full_fft_provenance_rejects_unknown_legacy_geometry(tmp_path: Path) -> None:
    root = _managed_full_fft_project(tmp_path)
    (root / ".fpvs_processing" / "processing_ledger.json").unlink()

    with pytest.raises(FullFftProvenanceError, match="Legacy or unknown geometry"):
        write_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def test_processing_time_geometry_gate_accepts_current_geometry_without_saved_record(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)

    geometry = require_current_project_workbook_geometry(root)

    assert geometry == biosemi64_geometry_identity()
    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert "processing" not in manifest.get("tools", {})


def test_processing_time_geometry_gate_rejects_missing_geometry_ledger(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    (root / ".fpvs_processing" / "processing_ledger.json").unlink()

    with pytest.raises(FullFftProvenanceError, match="Legacy or unknown geometry"):
        require_current_project_workbook_geometry(root)


def test_processing_time_geometry_gate_rejects_standard_1005_identity(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    legacy = biosemi64_geometry_identity()
    legacy["montage_id"] = "standard_1005"
    _write_geometry_ledger(root, {"P1": legacy, "P2": legacy})

    with pytest.raises(FullFftProvenanceError, match="unknown or legacy"):
        require_current_project_workbook_geometry(root)


def test_full_fft_provenance_rejects_mixed_retained_geometry(tmp_path: Path) -> None:
    root = _managed_full_fft_project(tmp_path)
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["max_chan_idx_keep"] = 63
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_geometry_ledger(
        root,
        {
            "P1": biosemi64_geometry_identity(
                retained_channels=BIOSEMI64_CHANNELS[:63]
            ),
            "P2": biosemi64_geometry_identity(
                retained_channels=BIOSEMI64_CHANNELS[1:]
            ),
        },
    )

    with pytest.raises(FullFftProvenanceError, match="mixed electrode geometries"):
        write_project_full_fft_provenance(
            root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def test_geometry_gate_rejects_uniform_wrong_subset_with_expected_count(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["max_chan_idx_keep"] = 63
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    wrong_subset = biosemi64_geometry_identity(
        retained_channels=BIOSEMI64_CHANNELS[1:]
    )
    _write_geometry_ledger(root, {"P1": wrong_subset, "P2": wrong_subset})

    with pytest.raises(FullFftProvenanceError, match="exact retained scalp set"):
        require_current_project_workbook_geometry(root)


def test_saved_legacy_full_fft_schema_requires_eeg_reprocessing(
    tmp_path: Path,
) -> None:
    root = _managed_full_fft_project(tmp_path)
    write_project_full_fft_provenance(
        root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tools"]["processing"]["full_fft_provenance"]["schema_version"] = 1
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(
        FullFftProvenanceStaleError,
        match="predates the current BioSemi64 and project-frequency-protocol contract",
    ):
        require_current_project_full_fft_provenance(root)
