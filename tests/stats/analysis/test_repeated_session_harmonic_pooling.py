from __future__ import annotations

import pandas as pd
import pytest

from Tools.Stats.analysis.harmonic_pooling import (
    pool_group_session_condition_spectra,
    session_condition_cell_id,
)


def _spectrum(value: float) -> pd.Series:
    return pd.Series([value, value + 1.0], index=[1.2, 1.5], dtype=float)


def test_repeated_pool_is_participant_first_and_equal_across_declared_cells() -> None:
    spectra = {
        ("P1_S1_A", "Faces"): _spectrum(0.0),
        ("P1_S1_B", "Faces"): _spectrum(10.0),
        ("P2_S1", "Faces"): _spectrum(9.0),
        ("P1_S2", "Faces"): _spectrum(1.0),
        ("P2_S2", "Faces"): _spectrum(5.0),
        ("P3_S1", "Faces"): _spectrum(3.0),
        ("P3_S2", "Faces"): _spectrum(7.0),
    }
    recording_ids = tuple(recording_id for recording_id, _condition in spectra)
    participant_ids = {
        "P1_S1_A": "P1",
        "P1_S1_B": "P1",
        "P2_S1": "P2",
        "P1_S2": "P1",
        "P2_S2": "P2",
        "P3_S1": "P3",
        "P3_S2": "P3",
    }
    session_ids = {
        recording_id: "visit_1" if "S1" in recording_id else "visit_2"
        for recording_id in recording_ids
    }

    pool = pool_group_session_condition_spectra(
        spectra=spectra,
        recording_ids=recording_ids,
        conditions=("Faces",),
        recording_participant_ids=participant_ids,
        recording_session_ids=session_ids,
        participant_group_ids={"P1": "treated", "P2": "treated", "P3": "control"},
        declared_group_ids=("treated", "control"),
        declared_session_ids=("visit_1", "visit_2"),
    )

    visit_1 = pool.condition_spectra[
        session_condition_cell_id("visit_1", "Faces")
    ]
    # P1 is first averaged across its duplicate recordings: (0 + 10) / 2 = 5.
    # Treated is then (P1=5 + P2=9) / 2 = 7, and the two groups are equal:
    # (treated=7 + control=3) / 2 = 5.
    assert visit_1.loc[1.2] == pytest.approx(5.0)
    assert pool.analysis_condition_ids == (
        "visit_1::Faces",
        "visit_2::Faces",
    )
    assert len(pool.cells) == 4
    treated_visit_1 = next(
        cell
        for cell in pool.cells
        if cell.group_id == "treated" and cell.session_id == "visit_1"
    )
    assert treated_visit_1.participant_ids == ("P1", "P2")
    assert treated_visit_1.recording_ids == ("P1_S1_A", "P1_S1_B", "P2_S1")
    assert treated_visit_1.participant_weight_within_cell == pytest.approx(0.5)
    assert treated_visit_1.group_weight_within_condition == pytest.approx(0.5)
    assert treated_visit_1.session_weight == pytest.approx(0.5)
    assert treated_visit_1.task_condition_weight == pytest.approx(1.0)
    assert treated_visit_1.cell_weight == pytest.approx(0.25)
    assert treated_visit_1.effective_participant_weight == pytest.approx(0.125)


def test_repeated_pool_hard_fails_only_an_entirely_missing_declared_cell() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"control x visit_2 x Faces",
    ):
        pool_group_session_condition_spectra(
            spectra={
                ("P1_S1", "Faces"): _spectrum(1.0),
                ("P1_S2", "Faces"): _spectrum(2.0),
                ("P2_S1", "Faces"): _spectrum(3.0),
            },
            recording_ids=("P1_S1", "P1_S2", "P2_S1"),
            conditions=("Faces",),
            recording_participant_ids={
                "P1_S1": "P1",
                "P1_S2": "P1",
                "P2_S1": "P2",
            },
            recording_session_ids={
                "P1_S1": "visit_1",
                "P1_S2": "visit_2",
                "P2_S1": "visit_1",
            },
            participant_group_ids={"P1": "treated", "P2": "control"},
            declared_group_ids=("treated", "control"),
            declared_session_ids=("visit_1", "visit_2"),
        )
