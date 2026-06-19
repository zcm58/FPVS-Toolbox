from PySide6.QtWidgets import QMessageBox

from Tools.Plot_Generator.gui import PlotGeneratorWindow
from Tools.Plot_Generator.worker import _Worker


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


def test_worker_timing_summary_emits_without_mutating_results(tmp_path, monkeypatch) -> None:
    worker = _Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"ROI": ["Cz"]},
        selected_roi="ROI",
        title="Title",
        xlabel="Hz",
        ylabel="SNR",
        x_min=0.0,
        x_max=2.0,
        y_min=0.0,
        y_max=2.0,
        out_dir=str(tmp_path),
    )
    messages: list[str] = []
    worker.generated_paths.append(str(tmp_path / "plot.png"))
    worker.failed_items.append({"item": "p01.xlsx", "error": "example"})
    worker._timings["excel_load"] = 0.25
    worker._timings["plot_render"] = 0.5

    monkeypatch.setattr(worker, "_emit", lambda msg, *_args: messages.append(msg))

    worker._emit_timing_summary()

    assert messages == [
        "Timing summary: excel load=0.25s, plot render=0.50s, total=0.75s"
    ]
    assert worker.generated_paths == [str(tmp_path / "plot.png")]
    assert worker.failed_items == [{"item": "p01.xlsx", "error": "example"}]


def test_worker_timing_summary_emits_excel_load_details_separately(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"ROI": ["Cz"]},
        selected_roi="ROI",
        title="Title",
        xlabel="Hz",
        ylabel="SNR",
        x_min=0.0,
        x_max=2.0,
        y_min=0.0,
        y_max=2.0,
        out_dir=str(tmp_path),
    )
    messages: list[str] = []
    worker._timings["excel_load"] = 1.0
    worker._timings["plot_render"] = 0.5
    worker._timing_details["fullsnr_workbook_open"] = 0.25
    worker._timing_details["fullsnr_row_stream"] = 0.75

    monkeypatch.setattr(worker, "_emit", lambda msg, *_args: messages.append(msg))

    worker._emit_timing_summary()

    assert messages == [
        "Timing summary: excel load=1.00s, plot render=0.50s, total=1.50s",
        "Excel load details: FullSNR workbook open=0.25s, FullSNR row stream=0.75s",
    ]
