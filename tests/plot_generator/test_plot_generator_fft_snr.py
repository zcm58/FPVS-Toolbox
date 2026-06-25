import importlib.util
import pytest

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)

import pandas as pd

from tests import repo_root


def _import_module():
    path = repo_root() / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"
    spec = importlib.util.spec_from_file_location("plot_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fft_amplitude_workbook_does_not_fallback(tmp_path, monkeypatch):
    module = _import_module()

    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()

    cols = [f"{i}_Hz" for i in range(1, 7)]
    df1 = pd.DataFrame({
        "Electrode": ["Cz", "Pz"],
        cols[0]: [1, 1],
        cols[1]: [1, 1],
        cols[2]: [10, 14],
        cols[3]: [1, 1],
        cols[4]: [1, 1],
        cols[5]: [1, 1],
    })
    df2 = pd.DataFrame({
        "Electrode": ["Cz", "Pz"],
        cols[0]: [1, 1],
        cols[1]: [1, 1],
        cols[2]: [6, 8],
        cols[3]: [1, 1],
        cols[4]: [1, 1],
        cols[5]: [1, 1],
    })
    with pd.ExcelWriter(cond_dir / "sub1.xlsx") as writer:
        df1.to_excel(writer, sheet_name="FFT Amplitude (uV)", index=False)
    with pd.ExcelWriter(cond_dir / "sub2.xlsx") as writer:
        df2.to_excel(writer, sheet_name="FFT Amplitude (uV)", index=False)

    def dummy_plot(self, freqs, roi_data):
        raise AssertionError("FFT-only workbooks must not produce SNR plots")

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
        x_max=6.0,
        y_min=0.0,
        y_max=20.0,
        out_dir=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="FullSNR sheet is required"):
        worker._run()
