from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import dv_policy_group_significant as group_policy


@pytest.fixture
def released_sources(tmp_path: Path) -> dict:
    """One incomplete participant can leave every declared group cell populated."""
    values = {
        ("P13", "Erotic"): 2.0,
        ("P13", "Neg Val"): 4.0,
        ("P47", "Erotic"): 6.0,
        ("P47", "Neg Val"): 1000.0,
        ("P9", "Erotic"): 20.0,
        ("P9", "Neg Val"): 30.0,
    }
    subject_data: dict[str, dict[str, str]] = {}
    expected: dict[tuple[str, str], tuple[str, ...]] = {}
    for (participant, condition), value in values.items():
        path = tmp_path / f"{participant}_{condition}.xlsx"
        pd.DataFrame(
            {"Electrode": ["O1"], "1.2000_Hz": [value], "2.4000_Hz": [value + 2.0]},
        ).to_excel(path, sheet_name="FullFFT Amplitude (uV)", index=False)
        subject_data.setdefault(participant, {})[condition] = str(path)
        expected[(participant, condition.casefold())] = ("O1",)
    return {
        "subjects": ["P13", "P47", "P9"],
        "conditions": ["Erotic", "Neg Val"],
        "subject_data": subject_data,
        "expected_scalp_channels_by_subject_condition": expected,
        "rois": {"Posterior": ["O1"]},
        "electrode_scope": "all_scalp_electrodes",
        "selection_electrodes": (),
        "log_func": lambda _message: None,
        "frequency_columns": [(1.2, "1.2000_Hz", 0), (2.4, "2.4000_Hz", 1)],
        "required_indices": [0, 1],
    }


def _pool(kind: str, inputs: dict):
    if kind == "legacy":
        return group_policy._build_grand_average_amplitude(**inputs)
    return group_policy._build_balanced_condition_amplitudes(
        **inputs,
        participant_group_ids={"P13": "A", "P47": "A", "P9": "B"},
        declared_group_ids=["A", "B"],
    )


@pytest.mark.parametrize("kind", ["legacy", "balanced"])
def test_reviewed_condition_omission_keeps_other_participant_observations(
    kind: str, released_sources: dict,
) -> None:
    omitted_path = released_sources["subject_data"]["P47"].pop("Neg Val")
    released_sources["expected_scalp_channels_by_subject_condition"].pop(
        ("P47", "neg val"),
    )
    # Exclusion changes the trusted cohort, not the existing exported workbook.
    assert Path(omitted_path).is_file()

    result = _pool(kind, released_sources)

    if kind == "legacy":
        spectrum, columns, bins, count, electrodes = result
        assert count == 5
        assert electrodes == 1
        assert columns == ["1.2000_Hz", "2.4000_Hz"]
        assert bins == [0, 1]
        # Legacy retains equal available-workbook weighting without imputation.
        np.testing.assert_array_equal(spectrum.to_numpy(), [12.4, 14.4])
        return

    pool, columns, bins, electrodes, used_electrodes = result
    assert pool.workbook_count == 5
    assert columns == ["1.2000_Hz", "2.4000_Hz"]
    assert bins == [0, 1]
    assert electrodes == 1
    assert used_electrodes == {"O1"}
    # Erotic: mean A participants [2, 6], then average A and B equally.
    np.testing.assert_array_equal(pool.condition_spectra["Erotic"], [12.0, 14.0])
    # Neg Val: P13 remains, P47 is absent, and B retains its equal group weight.
    np.testing.assert_array_equal(pool.condition_spectra["Neg Val"], [17.0, 19.0])
    cells = {(cell.group_id, cell.condition): cell for cell in pool.cells}
    assert cells[("A", "Erotic")].participant_ids == ("P13", "P47")
    assert cells[("A", "Neg Val")].participant_ids == ("P13",)
    assert cells[("A", "Erotic")].participant_count == 2
    assert cells[("A", "Neg Val")].participant_count == 1
    assert cells[("A", "Neg Val")].participant_weight_within_cell == 1.0
    assert cells[("A", "Erotic")].effective_participant_weight == 0.125
    assert cells[("A", "Neg Val")].effective_participant_weight == 0.25
    assert all(cell.group_weight_within_condition == 0.5 for cell in pool.cells)
    assert all(cell.condition_weight == 0.5 for cell in pool.cells)


@pytest.mark.parametrize("kind", ["legacy", "balanced"])
@pytest.mark.parametrize("missing", ["subject_data_entry", "workbook"])
def test_expected_released_source_cannot_silently_become_missing(
    kind: str, missing: str, released_sources: dict,
) -> None:
    if missing == "subject_data_entry":
        released_sources["subject_data"]["P47"].pop("Neg Val")
    else:
        Path(released_sources["subject_data"]["P47"]["Neg Val"]).unlink()

    with pytest.raises(
        RuntimeError,
        match="Released harmonic-selection workbook is missing for P47/Neg Val",
    ):
        _pool(kind, released_sources)


@pytest.mark.parametrize("kind", ["legacy", "balanced"])
def test_present_workbook_without_released_membership_is_rejected(
    kind: str, released_sources: dict,
) -> None:
    released_sources["expected_scalp_channels_by_subject_condition"].pop(
        ("P47", "neg val"),
    )
    with pytest.raises(RuntimeError, match="lacks released QC-21 source membership"):
        _pool(kind, released_sources)


def test_reviewed_exclusion_cannot_remove_an_entire_declared_group_condition(
    released_sources: dict,
) -> None:
    released_sources["subject_data"]["P9"].pop("Neg Val")
    released_sources["expected_scalp_channels_by_subject_condition"].pop(
        ("P9", "neg val"),
    )

    with pytest.raises(RuntimeError, match="B x Neg Val"):
        _pool("balanced", released_sources)
