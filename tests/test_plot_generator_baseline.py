import importlib.util
import os
import pytest

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)


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


def test_plot_contains_baseline_line(tmp_path, monkeypatch):
    module = _import_module()

    captured = {}

    def dummy_close(fig):
        captured["fig"] = fig

    monkeypatch.setattr(module.plt, "close", dummy_close)
    monkeypatch.setattr(module.matplotlib.figure.Figure, "savefig", lambda self, *a, **k: None)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        metric="SNR",
        roi_map={"roi": ["Cz"]},
        selected_roi="roi",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=2.0,
        y_min=0.0,
        y_max=2.0,
        out_dir=str(tmp_path),
    )

    worker._emit = lambda *a, **k: None
    worker._plot([1.0], {"roi": [0.5]})

    fig = captured.get("fig")
    assert fig is not None
    ax = fig.axes[0]
    assert any(
        getattr(line, "get_ydata", lambda: [])() == [1.0, 1.0] for line in ax.lines
    )
