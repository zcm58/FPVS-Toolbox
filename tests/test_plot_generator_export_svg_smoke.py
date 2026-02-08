import importlib.util

import pandas as pd
import pytest

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.worker import _Worker


if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)


def test_snr_export_svg_smoke(qtbot, tmp_path, monkeypatch):
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)

    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()
    df = pd.DataFrame(
        {
            "Electrode": ["Cz"],
            "1_Hz": [1.0],
            "2_Hz": [2.0],
        }
    )
    with pd.ExcelWriter(cond_dir / "sub1.xlsx") as writer:
        df.to_excel(writer, sheet_name="FullSNR", index=False)

    out_dir = tmp_path / "out"
    worker = _Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"All": ["Cz"]},
        selected_roi="All",
        title="SNR Plot",
        xlabel="Hz",
        ylabel="SNR",
        x_min=0.0,
        x_max=2.0,
        y_min=0.0,
        y_max=3.0,
        out_dir=str(out_dir),
    )
    monkeypatch.setattr(worker, "_emit", lambda *args, **kwargs: None)

    worker._run()

    assert list(out_dir.rglob("*.svg"))
    assert not list(out_dir.rglob("*.png"))
