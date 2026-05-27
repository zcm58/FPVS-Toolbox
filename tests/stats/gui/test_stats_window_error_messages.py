from __future__ import annotations

from Tools.Stats.ui.stats_window_error_messages import build_worker_error_guidance


def test_group_fullfft_grid_error_gets_user_guidance() -> None:
    raw = (
        "Group-level significant harmonic selection requires matching FullFFT "
        "candidate and neighboring-noise columns in every included workbook before "
        "reading amplitude or BCA data. Missing columns in "
        r"C:\Project\ACR\1 - Excel Data Files\Negative Valence\Default"
        r"\P1_Negative Valence_Results.xlsx: "
        "['1.1167_Hz', '1.1250_Hz']"
    )

    guidance = build_worker_error_guidance(raw)

    assert guidance is not None
    assert guidance.title == "Stats-Ready Export Needs Matching FullFFT Grids"
    assert "different FullFFT grid" in guidance.message
    assert "P1_Negative Valence_Results.xlsx" in guidance.message
    assert "1.1167_Hz, 1.1250_Hz" in guidance.message
    assert "Reprocess that participant-condition" in guidance.message


def test_unrecognized_worker_error_has_no_guidance() -> None:
    assert build_worker_error_guidance("simulated failure") is None
