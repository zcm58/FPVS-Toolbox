import importlib.util
import pytest
from tests import repo_root

if importlib.util.find_spec("matplotlib") is None:
    pytest.skip("matplotlib not available", allow_module_level=True)


def _import_module():
    path = repo_root() / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"
    spec = importlib.util.spec_from_file_location("plot_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gridlines_added(tmp_path, monkeypatch):
    module = _import_module()

    captured = {}

    def dummy_close(fig):
        captured["fig"] = fig

    monkeypatch.setattr(module.plt, "close", dummy_close)
    monkeypatch.setattr(module.matplotlib.figure.Figure, "savefig", lambda self, *a, **k: None)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"roi": ["Cz"]},
        selected_roi="roi",
        oddballs=[1.0, 2.0],
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=3.0,
        y_min=0.0,
        y_max=3.0,
        use_matlab_style=False,
        out_dir=str(tmp_path),
    )

    worker._emit = lambda *a, **k: None
    worker._plot([1.0, 2.0], {"roi": [1.5, 2.5]})

    fig = captured.get("fig")
    assert fig is not None
    ax = fig.axes[0]
    segments = [
        segment
        for collection in ax.collections
        if hasattr(collection, "get_segments")
        for segment in collection.get_segments()
    ]
    v_lines = {
        float(segment[0][0])
        for segment in segments
        if segment[0][0] == segment[1][0]
    }
    h_lines = {
        float(segment[0][1])
        for segment in segments
        if segment[0][1] == segment[1][1]
    }
    assert v_lines == {1.0, 2.0, 3.0}
    assert h_lines == {0.0, 1.0, 2.0, 3.0}
