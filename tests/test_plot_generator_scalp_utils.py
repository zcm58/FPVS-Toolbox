from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("mne")

from Tools.Plot_Generator.scalp_utils import (  # noqa: E402
    prepare_scalp_inputs,
    summarize_subject_scalp,
)


def test_summarize_subject_scalp_indexes_electrodes_once() -> None:
    df_bca = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz"],
            "1.0_Hz": [1.0, 5.0],
            "2.0_Hz": [2.0, 7.0],
        }
    )
    df_z = pd.DataFrame(
        {
            "Electrode": ["cz", "pz"],
            "1.0_Hz": [2.0, 1.7],
            "2.0_Hz": [1.0, 2.0],
        }
    )

    values = summarize_subject_scalp(df_bca, df_z, [1.0, 2.0])

    assert values == {"CZ": 1.0, "PZ": 12.0}


def test_prepare_scalp_inputs_reuses_cached_info_without_shared_mutation() -> None:
    subject_maps = {
        "P01": {"Cz": 1.0, "Pz": 3.0},
        "P02": {"Cz": 5.0, "Pz": 7.0},
    }

    first = prepare_scalp_inputs(subject_maps, ["Cz", "Pz"])
    second = prepare_scalp_inputs(subject_maps, ["Cz", "Pz"])

    assert first is not None
    assert second is not None
    assert first.info is not second.info
    np.testing.assert_allclose(first.data, second.data)
