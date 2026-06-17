import importlib.util
import pytest
from tests import repo_root

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)

import pandas as pd

from Tools.Plot_Generator import data_collection as plot_data_collection
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION


def _import_module():
    path = repo_root() / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"
    spec = importlib.util.spec_from_file_location("plot_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_snr_roi_averaging(tmp_path, monkeypatch):
    module = _import_module()

    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()

    df1 = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz"],
            "1.0000_Hz": [1, 3],
            "1.0001_Hz": [2, 4],
            "2.0000_Hz": [4, 6],
            "2.0001_Hz": [5, 7],
        }
    )
    df2 = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz"],
            "1.0000_Hz": [5, 7],
            "1.0001_Hz": [6, 8],
            "2.0000_Hz": [7, 9],
            "2.0001_Hz": [8, 10],
        }
    )
    with pd.ExcelWriter(cond_dir / "sub1.xlsx") as writer:
        df1.to_excel(writer, sheet_name="FullSNR", index=False)
    with pd.ExcelWriter(cond_dir / "sub2.xlsx") as writer:
        df2.to_excel(writer, sheet_name="FullSNR", index=False)

    captured = {}

    def dummy_plot(self, freqs, roi_data):
        captured["freqs"] = freqs
        captured["roi_data"] = roi_data

    monkeypatch.setattr(module._Worker, "_plot", dummy_plot)
    monkeypatch.setattr(module._Worker, "_emit", lambda *a, **k: None)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"All": ["Cz", "Pz"]},
        selected_roi="All",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=2.0,
        y_min=-1.0,
        y_max=1.0,
        out_dir=str(tmp_path),
    )

    worker._run()

    freqs = captured["freqs"]
    data = captured["roi_data"]["All"]

    assert freqs == [1.0, 1.0001, 2.0, 2.0001]
    assert data == [4.0, 5.0, 6.5, 7.5]


def test_full_snr_all_roi_and_group_aggregation(tmp_path, monkeypatch):
    module = _import_module()

    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()

    def write_subject(name, rows):
        df = pd.DataFrame(
            rows,
            columns=["Electrode", "0.5000_Hz", "1.0000_Hz", "2.0000_Hz", "3.0000_Hz"],
        )
        with pd.ExcelWriter(cond_dir / name) as writer:
            df.to_excel(writer, sheet_name="FullSNR", index=False)

    write_subject(
        "P01_Cond_Results.xlsx",
        [
            ("cz", 1, 10, 20, 2),
            ("Pz", 1, 30, 40, 2),
            ("Oz", 1, 50, 60, 2),
            ("O1", 1, 70, 80, 2),
            ("Fz", 1, 900, 900, 2),
        ],
    )
    write_subject(
        "P02_Cond_Results.xlsx",
        [
            ("Cz", 1, 20, 30, 2),
            ("Pz", 1, 40, 50, 2),
            ("OZ", 1, 60, 70, 2),
            ("O1", 1, 80, 90, 2),
        ],
    )
    write_subject(
        "P03_Cond_Results.xlsx",
        [
            ("Cz", 1, 100, 200, 2),
            ("Pz", 1, 300, 400, 2),
            ("Oz", 1, 500, 600, 2),
            ("O1", 1, 700, 800, 2),
        ],
    )

    captured = {}

    def dummy_plot(self, freqs, roi_data, group_curves=None, scalp_inputs=None):
        captured["freqs"] = freqs
        captured["roi_data"] = roi_data
        captured["group_curves"] = group_curves or {}

    monkeypatch.setattr(module._Worker, "_plot", dummy_plot)
    monkeypatch.setattr(module._Worker, "_emit", lambda *a, **k: None)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={
            "Central": ["Cz", "Pz"],
            "Posterior": ["Oz", "O1"],
        },
        selected_roi=ALL_ROIS_OPTION,
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=2.0,
        y_min=0.0,
        y_max=900.0,
        out_dir=str(tmp_path),
        subject_groups={
            "P01": "Group A",
            "P02": "Group A",
            "P03": "Group B",
        },
        selected_groups=["Group A", "Group B"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )

    worker._run()

    assert captured["freqs"] == [1.0, 2.0]
    assert captured["roi_data"] == {
        "Central": pytest.approx([250 / 3, 370 / 3]),
        "Posterior": pytest.approx([730 / 3, 850 / 3]),
    }
    assert captured["group_curves"] == {
        "Group A": {
            "Central": pytest.approx([25.0, 35.0]),
            "Posterior": pytest.approx([65.0, 75.0]),
        },
        "Group B": {
            "Central": pytest.approx([200.0, 300.0]),
            "Posterior": pytest.approx([600.0, 700.0]),
        },
    }


def test_full_snr_without_scalp_uses_direct_sheet_read(tmp_path, monkeypatch):
    module = _import_module()

    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()
    df = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz"],
            "0.5000_Hz": [100, 100],
            "1.0000_Hz": [1, 3],
            "2.0000_Hz": [5, 7],
            "3.0000_Hz": [100, 100],
        }
    )
    with pd.ExcelWriter(cond_dir / "P01_Cond_Results.xlsx") as writer:
        df.to_excel(writer, sheet_name="FullSNR", index=False)

    def fail_pandas_excel(*args, **kwargs):
        raise AssertionError("FullSNR fast path should not use Pandas Excel readers")

    monkeypatch.setattr(plot_data_collection.pd, "read_excel", fail_pandas_excel)
    monkeypatch.setattr(plot_data_collection.pd, "ExcelFile", fail_pandas_excel)
    monkeypatch.setattr(module._Worker, "_emit", lambda *a, **k: None)

    captured = {}

    def dummy_plot(self, freqs, roi_data):
        captured["freqs"] = freqs
        captured["roi_data"] = roi_data

    monkeypatch.setattr(module._Worker, "_plot", dummy_plot)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"All": ["Cz", "Pz"]},
        selected_roi="All",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=2.0,
        y_min=0.0,
        y_max=10.0,
        out_dir=str(tmp_path),
    )

    worker._run()

    assert captured["freqs"] == [1.0, 2.0]
    assert captured["roi_data"] == {"All": [2.0, 6.0]}
