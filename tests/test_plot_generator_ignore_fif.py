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


def test_populate_conditions_skips_fif(tmp_path):
    module = _import_module()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    (tmp_path / "CondA").mkdir()
    (tmp_path / "skip.fif.data").mkdir()

    win = module.PlotGeneratorWindow()
    win._populate_conditions(str(tmp_path))
    items = [win.condition_combo.itemText(i) for i in range(win.condition_combo.count())]
    assert "CondA" in items
    assert all(".fif" not in item for item in items)

    app.quit()
