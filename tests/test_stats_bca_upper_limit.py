from __future__ import annotations

import pandas as pd
import pytest

from Tools.Stats.analysis import stats_analysis
from Tools.Stats.analysis import dv_policies
from Tools.Stats.analysis import dv_policy_settings


def _make_bca_df() -> pd.DataFrame:
    data = {
        "1.2_Hz": [0.1, 0.1],
        "2.4_Hz": [0.1, 0.1],
        "3.6_Hz": [0.1, 0.1],
        "4.8_Hz": [0.1, 0.1],
        "7.2_Hz": [0.1, 0.1],
        "16.8_Hz": [0.1, 0.1],
        "19.2_Hz": [4.0, 4.0],
    }
    df = pd.DataFrame(data, index=["O1", "O2"])
    df.index.name = "Electrode"
    return df


def _make_z_df() -> pd.DataFrame:
    df = _make_bca_df()
    return df.map(lambda _value: 2.0)


def _common_kwargs() -> dict[str, object]:
    return {
        "subjects": ["P1"],
        "conditions": ["A"],
        "subject_data": {"P1": {"A": "P1_A.xlsx"}},
        "base_freq": 6.0,
        "log_func": lambda _m: None,
        "rois": {"Occipital": ["O1", "O2"]},
        "dv_policy": None,
    }


def test_prepare_summed_bca_data_respects_explicit_max_freq(monkeypatch) -> None:
    df = _make_bca_df()
    z_df = _make_z_df()

    def _fake_read_excel(path, sheet_name, *, index_col=None, use_cache=True):
        _ = path, index_col, use_cache
        if sheet_name == stats_analysis.SUMMED_BCA_Z_SHEET_NAME:
            return z_df.copy()
        assert sheet_name == "BCA (uV)"
        return df.copy()

    monkeypatch.setattr(stats_analysis, "safe_read_excel", _fake_read_excel)
    monkeypatch.setattr(stats_analysis.os.path, "exists", lambda _path: True)
    dv_policies._DV_DATA_CACHE.clear()

    low = dv_policies.prepare_summed_bca_data(
        **_common_kwargs(),
        max_freq=16.8,
    )
    high = dv_policies.prepare_summed_bca_data(
        **_common_kwargs(),
        max_freq=19.2,
    )

    assert low is not None
    assert high is not None
    low_val = float(low["P1"]["A"]["Occipital"])
    high_val = float(high["P1"]["A"]["Occipital"])
    assert high_val > low_val
    assert high_val - low_val == pytest.approx(4.0)


def test_prepare_summed_bca_data_uses_settings_upper_limit_when_missing_max_freq(
    monkeypatch,
) -> None:
    df = _make_bca_df()
    z_df = _make_z_df()

    def _fake_read_excel(path, sheet_name, *, index_col=None, use_cache=True):
        _ = path, index_col, use_cache
        if sheet_name == stats_analysis.SUMMED_BCA_Z_SHEET_NAME:
            return z_df.copy()
        assert sheet_name == "BCA (uV)"
        return df.copy()

    class _FakeSettingsManager:
        def get(self, section, option, fallback=None):
            _ = fallback
            if section == "analysis" and option == "bca_upper_limit":
                return "19.2"
            return fallback

    monkeypatch.setattr(stats_analysis, "safe_read_excel", _fake_read_excel)
    monkeypatch.setattr(stats_analysis.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(dv_policy_settings, "SettingsManager", _FakeSettingsManager)
    dv_policies._DV_DATA_CACHE.clear()

    meta: dict[str, object] = {}
    data = dv_policies.prepare_summed_bca_data(
        **_common_kwargs(),
        max_freq=None,
        dv_metadata=meta,
    )

    assert data is not None
    val = float(data["P1"]["A"]["Occipital"])
    assert val == pytest.approx(4.6)
    assert float(meta["max_frequency_hz"]) == pytest.approx(19.2)
