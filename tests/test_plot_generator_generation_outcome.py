from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.worker import _infer_subject_id_from_path


def test_infer_subject_id_is_case_insensitive() -> None:
    assert _infer_subject_id_from_path(Path("p10.bdf")) == "P10"
    assert _infer_subject_id_from_path(Path("P01.bdf")) == "P01"
    assert _infer_subject_id_from_path(Path("=p17.bdf")) == "P17"


def test_finish_all_uses_generated_paths(qtbot, monkeypatch) -> None:
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)

    called: dict[str, int] = {"question": 0}

    def _fake_question(*_args, **_kwargs):
        called["question"] += 1
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", _fake_question)

    window._generated_paths = ["C:/tmp/plot.png"]
    window._failed_items = []
    window._finish_all()

    assert called["question"] == 1


def test_finish_all_reports_no_plots_when_generated_paths_empty(qtbot, monkeypatch) -> None:
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)

    def _fail_question(*_args, **_kwargs):
        raise AssertionError("question dialog should not be shown when no plots are generated")

    monkeypatch.setattr(QMessageBox, "question", _fail_question)

    window._generated_paths = []
    window._failed_items = [{"item": "p10.xlsx", "error": "No frequency columns found"}]
    window._finish_all()

    assert "No plots were generated" in window.log.toPlainText()
