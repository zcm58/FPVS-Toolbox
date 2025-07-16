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


class _DummySignal:
    def connect(self, *a, **k):
        pass


class _DummyThread:
    def __init__(self):
        self.started = _DummySignal()
        self.finished = _DummySignal()

    def start(self):
        pass

    def quit(self):
        pass

    def deleteLater(self):
        pass


def test_all_conditions_titles(tmp_path, monkeypatch):
    module = _import_module()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    (tmp_path / "Fruit vs Veg").mkdir()
    (tmp_path / "Veg vs Fruit").mkdir()

    win = module.PlotGeneratorWindow()
    win._populate_conditions(str(tmp_path))
    win.condition_combo.setCurrentText(module.ALL_CONDITIONS_OPTION)

    captured = {}

    class DummyWorker:
        def __init__(self, *args, **kwargs):
            captured["title"] = args[5]
            self.progress = _DummySignal()
            self.finished = _DummySignal()

        def moveToThread(self, *a, **k):
            pass

    monkeypatch.setattr(module, "_Worker", DummyWorker)
    monkeypatch.setattr(module, "QThread", _DummyThread)

    win._conditions_queue = ["Fruit vs Veg"]
    win._gen_params = (str(tmp_path), str(tmp_path), 0.0, 1.0, 0.0, 1.0)
    win._all_conditions = True
    win._total_conditions = 1
    win._current_condition = 0

    win._start_next_condition()

    assert captured.get("title") == "Fruit vs Veg"
    assert win.title_edit.text() == "Fruit vs Veg"

    app.quit()
