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


def test_plot_title_is_omitted_and_title_roi_names_output(tmp_path, monkeypatch):
    module = _import_module()

    captured = {}
    saved_paths = []

    def dummy_close(fig):
        captured["fig"] = fig

    monkeypatch.setattr(module.plt, "close", dummy_close)

    def fake_savefig(self, path, *args, **kwargs):
        saved_paths.append(path)

    monkeypatch.setattr(module.matplotlib.figure.Figure, "savefig", fake_savefig)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"Occipital": ["Cz"]},
        selected_roi="Occipital",
        title="Cond",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=2.0,
        y_min=-1.0,
        y_max=1.0,
        out_dir=str(tmp_path),
    )

    worker._emit = lambda *a, **k: None
    worker._plot([1.0], {"Occipital": [0.5]})

    fig = captured.get("fig")
    assert fig is not None
    ax = fig.axes[0]
    assert getattr(fig, "_suptitle", None) is None
    assert ax.get_title() == ""
    assert {path.name for path in saved_paths} == {
        "Cond - Occipital.png",
        "Cond - Occipital.pdf",
    }


def test_overlay_plot_uses_title_and_roi_for_output_name(tmp_path, monkeypatch):
    module = _import_module()

    captured = {}
    saved_paths = []

    def dummy_close(fig):
        captured["fig"] = fig

    def fake_savefig(self, path, *args, **kwargs):
        saved_paths.append(path)

    monkeypatch.setattr(module.plt, "close", dummy_close)
    monkeypatch.setattr(module.matplotlib.figure.Figure, "savefig", fake_savefig)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="CondA",
        roi_map={"Occipital": ["Cz"]},
        selected_roi="Occipital",
        title="Condition A vs Condition B",
        xlabel="x",
        ylabel="y",
        x_min=0.0,
        x_max=2.0,
        y_min=-1.0,
        y_max=1.0,
        out_dir=str(tmp_path),
        condition_b="CondB",
        overlay=True,
    )

    worker._emit = lambda *a, **k: None
    worker._plot_overlay([1.0], {"Occipital": [0.5]}, {"Occipital": [0.4]})

    fig = captured.get("fig")
    assert fig is not None
    assert getattr(fig, "_suptitle", None) is None
    assert {path.name for path in saved_paths} == {
        "Condition A vs Condition B - Occipital.png",
        "Condition A vs Condition B - Occipital.pdf",
    }
