from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from Main_App.processing.full_fft_grid_qc import audit_project_full_fft_grids
from Main_App.processing.processing_ledger import save_ledger


def _write_project(root: Path, exclusions: dict[str, list[str]] | None = None) -> Path:
    excel_root = root / "1 - Excel Data Files"
    excel_root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "preprocessing": {
                    "manual_excluded_participant_conditions": exclusions or {},
                },
            }
        ),
        encoding="utf-8",
    )
    return excel_root


def _write_full_fft_header(
    excel_root: Path,
    participant_id: str,
    condition: str,
    *,
    oddball_cycles: int | None,
    frequency_overrides: dict[int, float] | None = None,
) -> Path:
    condition_root = excel_root / condition
    condition_root.mkdir(parents=True, exist_ok=True)
    path = condition_root / f"{participant_id}_{condition}_Results.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("FullFFT Amplitude (uV)")
    if oddball_cycles is None:
        header = ["Electrode", "0.0000_Hz", "0.5000_Hz", "1.0000_Hz"]
    else:
        spacing = 1.2 / oddball_cycles
        overrides = frequency_overrides or {}
        header = [
            "Electrode",
            *[
                f"{overrides.get(index, index * spacing):.4f}_Hz"
                for index in range(oddball_cycles + 12)
            ],
        ]
    sheet.append(header)
    workbook.save(path)
    return path


def test_full_fft_grid_audit_flags_only_strict_majority_mismatches(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    short = _write_full_fft_header(
        excel_root,
        "P3",
        "Negative Valence",
        oddball_cycles=21,
    )

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert audit.reference_duration_s == 120.0
    assert audit.reference_support == 2
    assert audit.reference_total == 3
    assert [
        (row.participant_id, row.condition, row.path, row.duration_s)
        for row in audit.review_candidates
    ] == [("P3", "Negative Valence", short, 17.5)]


def test_full_fft_grid_audit_flags_longer_grid_even_when_columns_overlap(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    longer = _write_full_fft_header(excel_root, "P3", "Faces", oddball_cycles=288)

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert [(row.path, row.oddball_cycles) for row in audit.review_candidates] == [
        (longer, 288)
    ]


def test_full_fft_grid_audit_does_not_guess_when_valid_grids_tie(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=21)

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles is None
    assert audit.has_unresolved_grid_conflict is True
    assert audit.review_candidates == ()
    assert audit.is_compatible_with_exclusions({}) is False
    assert audit.is_compatible_with_exclusions({"P2": ["Faces"]}) is True


def test_full_fft_grid_audit_retains_excluded_workbook_for_review(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(
        tmp_path,
        exclusions={"P3": ["Negative Valence"]},
    )
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    excluded = _write_full_fft_header(
        excel_root,
        "P3",
        "Negative Valence",
        oddball_cycles=21,
    )

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    observation = next(row for row in audit.observations if row.path == excluded)
    assert observation.already_excluded is True
    assert audit.review_candidates == ()


def test_full_fft_grid_audit_always_flags_invalid_active_header(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    invalid = _write_full_fft_header(
        excel_root,
        "P3",
        "Negative Valence",
        oddball_cycles=None,
    )

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert [(row.path, row.oddball_cycles) for row in audit.review_candidates] == [
        (invalid, None)
    ]


def test_full_fft_grid_audit_ignores_noncompleted_ledger_participants(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    for participant_id in ("P3", "P4", "P5"):
        _write_full_fft_header(
            excel_root,
            participant_id,
            "Faces",
            oddball_cycles=21,
        )
    save_ledger(
        tmp_path,
        {
            "schema_version": 1,
            "entries": {
                "P1": {"status": "completed"},
                "P2": {"status": "completed"},
                "P3": {"status": "stale"},
                "P4": {"status": "failed"},
                "P5": {"status": "new"},
            },
        },
    )

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert audit.reference_support == 2
    assert audit.reference_total == 2
    assert {row.participant_id for row in audit.observations} == {"P1", "P2"}


def test_full_fft_grid_audit_ignores_frequency_excluded_participants(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    for participant_id in ("P3", "P4", "P5"):
        _write_full_fft_header(
            excel_root,
            participant_id,
            "Faces",
            oddball_cycles=21,
        )
    manifest_path = tmp_path / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tools"] = {
        "frequency_domain_qc": {
            "manual_participant_exclusions": [
                {"participant_id": participant_id}
                for participant_id in ("P3", "P4", "P5")
            ]
        }
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert audit.reference_support == 2
    assert audit.reference_total == 2
    assert {row.participant_id for row in audit.observations} == {"P1", "P2"}


def test_full_fft_grid_audit_turns_corrupt_workbook_into_review_row(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    corrupt_root = excel_root / "Faces"
    corrupt = corrupt_root / "P3_Faces_Results.xlsx"
    corrupt.write_bytes(b"not an xlsx zip archive")

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert [row.path for row in audit.review_candidates] == [corrupt]
    assert audit.review_candidates[0].issue is not None


def test_full_fft_grid_audit_validates_every_frequency_column(
    tmp_path: Path,
) -> None:
    excel_root = _write_project(tmp_path)
    _write_full_fft_header(excel_root, "P1", "Faces", oddball_cycles=144)
    _write_full_fft_header(excel_root, "P2", "Faces", oddball_cycles=144)
    malformed = _write_full_fft_header(
        excel_root,
        "P3",
        "Faces",
        oddball_cycles=144,
        frequency_overrides={2: 9.9999},
    )

    audit = audit_project_full_fft_grids(tmp_path)

    assert audit.reference_oddball_cycles == 144
    assert [row.path for row in audit.review_candidates] == [malformed]
    assert "uniform" in str(audit.review_candidates[0].issue).casefold()
