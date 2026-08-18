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
            captured["title"] = args[4]
            captured["out_dir"] = args[11]
            captured["prepared_dataset_index"] = kwargs.get(
                "prepared_dataset_index"
            )
            self.progress = _DummySignal()
            self.finished = _DummySignal()

        def moveToThread(self, *a, **k):
            pass

        def run(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(module, "_Worker", DummyWorker)
    monkeypatch.setattr(module, "QThread", _DummyThread)

    win._conditions_queue = ["Fruit vs Veg"]
    win._gen_params = (str(tmp_path), str(tmp_path), 0.0, 1.0, 0.0, 1.0)
    win._all_conditions = True
    prepared_dataset_index = object()
    win._batch_dataset_index = prepared_dataset_index
    win._total_conditions = 1
    win._current_condition = 0

    win._start_next_condition()

    assert captured.get("title") == "Fruit vs Veg"
    assert captured.get("out_dir") == str(tmp_path)
    assert captured.get("prepared_dataset_index") is prepared_dataset_index
    assert win.title_edit.text() == "Fruit vs Veg"

    app.quit()
