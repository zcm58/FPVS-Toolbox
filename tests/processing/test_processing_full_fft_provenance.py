"""Processing-owned FullFFT provenance persistence tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
from openpyxl import Workbook
import pytest

from Main_App.processing.full_fft_provenance import (
    validate_project_full_fft_provenance,
    write_project_full_fft_provenance,
)


def _managed_full_fft_project(tmp_path: Path) -> Path:
    root = tmp_path / "Project"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps(
            {
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "participants": {"P1": {}, "P2": {}},
                "preprocessing": {},
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
