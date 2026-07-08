from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from Main_App.gui import preprocessing_qc_workflow as workflow  # noqa: E402


def _hard_candidate(raw_payload: dict[str, object]) -> workflow.PreflightQcFileResult:
    return workflow.PreflightQcFileResult(
        path=Path("p34.bdf"),
        participant_id="P34",
        load_error=None,
        raw_channel_qc=raw_payload,
        raw_spectral_qc=None,
    )


def test_removed_electrode_review_scope_preserves_unreviewed_participants() -> None:
    existing = {"P01": ["P9"], "P02": ["Oz"]}
    review_participants = ["P03"]

    visible = workflow._filter_removed_map_for_participants(
        existing,
        review_participants,
    )
    assert visible == {}

    updated = workflow._replace_removed_map_for_participants(
        existing,
        {"P03": ["PO8"]},
        review_participants,
    )

    assert updated == {"P01": ["P9"], "P02": ["Oz"], "P03": ["PO8"]}


def test_removed_electrode_review_rows_split_auto_and_manual_sources() -> None:
    rows = workflow._removed_review_row_values(
        ["P34"],
        {"P34": ["FT7"]},
        {"P34": ["FT7", "P9"]},
    )

    assert rows == [("P34", "FT7", "P9", "FT7, P9")]


def test_removed_electrode_review_parser_moves_auto_field_additions_to_manual() -> None:
    records, final_confirmed, warnings = workflow._removed_review_records_from_rows(
        [("P34", "FT7, P9", "", "FT7, P9")],
        {"P34": ["FT7"]},
    )

    assert final_confirmed == {"P34": ["FT7", "P9"]}
    assert records["P34"]["accepted_auto_flagged"] == ["FT7"]
    assert records["P34"]["manual_additions"] == ["P9"]
    assert records["P34"]["manual_only_missed_by_auto"] == ["P9"]
    assert "P34: moved to Manual additions: P9" in warnings


def test_removed_electrode_review_parser_tracks_rejected_auto_flags() -> None:
    records, final_confirmed, warnings = workflow._removed_review_records_from_rows(
        [("P36", "FT7", "", "FT7")],
        {"P36": ["FT7", "P9"]},
    )

    assert final_confirmed == {"P36": ["FT7"]}
    assert records["P36"]["accepted_auto_flagged"] == ["FT7"]
    assert records["P36"]["rejected_auto_flagged"] == ["P9"]
    assert records["P36"]["manual_additions"] == []
    assert warnings == []


def test_hard_participant_exclusion_reason_is_condensed_with_details() -> None:
    result = _hard_candidate(
        {
            "excluded": True,
            "message": (
                "p34.bdf excluded by raw channel-health QC: participant-level raw "
                "amplitude baseline was excessively noisy."
            ),
            "triggered_rules": ["raw_amplitude_baseline_failure"],
            "raw_baseline_median_std_uv": 32193.4,
            "raw_baseline_median_p2p_99_uv": 260426.5,
            "bad_channels": ["CPz", "FT7"],
            "thresholds": {
                "baseline_exclusion_median_std_uv": 10000.0,
                "baseline_exclusion_median_p2p_99_uv": 100000.0,
            },
        }
    )

    assert workflow._hard_candidate_flag(result) == "Hard raw QC"
    assert workflow._hard_candidate_reason(result) == "Extremely noisy baseline"
    assert workflow._hard_candidate_row_values([result]) == [
        ("P34", "Hard raw QC", "Extremely noisy baseline", "")
    ]
    assert "far outside the expected range" in workflow._hard_candidate_plain_explanation(result)

    details = workflow._hard_candidate_detail_text(result)
    assert "Median STD: 32193.4 uV (hard exclusion >= 10000.0 uV)" in details
    assert "Median P2P99: 260426.5 uV (hard exclusion >= 100000.0 uV)" in details
    assert "raw_amplitude_baseline_failure" in details
    assert "Original raw QC message" in details
