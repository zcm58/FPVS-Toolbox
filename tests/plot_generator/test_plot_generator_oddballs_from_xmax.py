import importlib.util

import pytest

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)

from Tools.Plot_Generator import worker as worker_module
from Tools.Plot_Generator.worker import _Worker


def _worker(tmp_path, *, x_max: float, oddballs=None):
    return _Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"roi": ["Cz"]},
        selected_roi="roi",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=x_max,
        y_min=0.0,
        y_max=3.0,
        out_dir=str(tmp_path),
        oddballs=oddballs,
    )


def test_oddballs_derive_from_xmax_and_analysis_freq(monkeypatch, tmp_path):
    def fake_read(self, option, fallback):
        if option == "base_freq":
            return 6.0
        if option == "oddball_freq":
            return 1.2
        return fallback

    monkeypatch.setattr(_Worker, "_read_analysis_float", fake_read)
    worker = _worker(tmp_path, x_max=10.0)

    assert worker.oddballs == [1.2, 2.4, 3.6, 4.8, 7.2, 8.4, 9.6]


def test_explicit_oddballs_override_auto_derived(monkeypatch, tmp_path):
    monkeypatch.setattr(_Worker, "_read_analysis_float", lambda self, option, fallback: fallback)
    worker = _worker(tmp_path, x_max=10.0, oddballs=[1.0, 2.0])

    assert worker.oddballs == [1.0, 2.0]


def test_analysis_frequency_reads_share_one_successful_settings_snapshot(
    monkeypatch,
    tmp_path,
):
    constructions = 0

    class FakeSettingsManager:
        def __init__(self):
            nonlocal constructions
            constructions += 1

        def get(self, _section, option, _fallback):
            return {"base_freq": "6.0", "oddball_freq": "1.2"}[option]

    monkeypatch.setattr(worker_module, "SettingsManager", FakeSettingsManager)

    worker = _worker(tmp_path, x_max=10.0)

    assert constructions == 1
    assert worker._analysis_base_freq == 6.0
    assert worker._analysis_oddball_freq == 1.2


def test_analysis_frequency_fallback_survives_settings_construction_failure(
    monkeypatch,
    tmp_path,
):
    constructions = 0

    class FailingSettingsManager:
        def __init__(self):
            nonlocal constructions
            constructions += 1
            raise OSError("settings unavailable")

    monkeypatch.setattr(worker_module, "SettingsManager", FailingSettingsManager)

    worker = _worker(tmp_path, x_max=10.0)

    assert constructions == 2
    assert worker._analysis_base_freq == 6.0
    assert worker._analysis_oddball_freq == 1.2


def test_invalid_analysis_frequency_does_not_cache_failed_settings_read(
    monkeypatch,
    tmp_path,
):
    constructions = 0

    class PartiallyInvalidSettingsManager:
        def __init__(self):
            nonlocal constructions
            constructions += 1

        def get(self, _section, option, _fallback):
            return {"base_freq": "nan", "oddball_freq": "1.2"}[option]

    monkeypatch.setattr(
        worker_module,
        "SettingsManager",
        PartiallyInvalidSettingsManager,
    )

    worker = _worker(tmp_path, x_max=10.0)

    assert constructions == 2
    assert worker._analysis_base_freq == 6.0
    assert worker._analysis_oddball_freq == 1.2
