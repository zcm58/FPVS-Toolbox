import importlib.util
import os
import pytest

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)

import pandas as pd


def _import_module():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "Tools",
        "Plot_Generator",
        "plot_generator.py",
    )
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
        metric="SNR",
        roi_map={"All": ["Cz", "Pz"]},
        selected_roi="All",
        oddballs=[],
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

    assert pytest.approx(freqs[0], 0.0001) == 0.5
    assert pytest.approx(freqs[-1], 0.0001) == 20.01
    assert len(freqs) > 1000
    assert len(data) == len(freqs)

    idx1 = min(range(len(freqs)), key=lambda i: abs(freqs[i] - 1.0))
    idx2 = min(range(len(freqs)), key=lambda i: abs(freqs[i] - 2.0))
    assert pytest.approx(data[idx1], 1e-6) == 4.0
    assert pytest.approx(data[idx2], 1e-6) == 6.5
