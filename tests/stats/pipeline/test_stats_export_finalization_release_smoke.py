from __future__ import annotations

import logging
import queue
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

import Main_App.gui.main_window as main_window_module
from Main_App.gui.main_window import MainWindow, _should_show_no_excel_popup
from Tools.Stats.common.stats_core import PipelineId, StepId
from Tools.Stats.ui.stats_window import StatsWindow


@pytest.fixture(autouse=True)
def _stub_default_stats_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        StatsWindow,
        "_load_default_data_folder",
        lambda self: None,
        raising=False,
    )


@pytest.mark.qt
def test_stats_export_finalization_release_smoke(
    tmp_path: Path,
    qtbot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    excel_root = tmp_path / "1 - Excel Data Files"
    excel_root.mkdir()
    existing_excel = excel_root / "P01_results.xlsx"
    existing_excel.write_text("already present", encoding="utf-8")

    assert _should_show_no_excel_popup([], excel_root, [str(existing_excel)]) is False

    app_stub = SimpleNamespace(
        gui_queue=queue.Queue(),
        save_folder_path=SimpleNamespace(get=lambda: str(excel_root)),
        log=lambda _message, level=logging.INFO: None,
        _run_had_successful_export=True,
        _last_job_success=True,
    )

    def fake_no_output(app, _labels):
        app.log("Warning: Post-processing completed, but no Excel files were saved.")

    monkeypatch.setattr(main_window_module, "_shared_post_process", fake_no_output)

    MainWindow._export_with_post_process(app_stub, ["CondA"])

    queued_messages = [
        item.get("message", "")
        for item in list(app_stub.gui_queue.queue)
        if isinstance(item, dict)
    ]
    assert app_stub._last_job_success is True
    assert any("no Excel outputs were detected" in message for message in queued_messages)

    for method in ("critical", "information", "warning", "question"):
        monkeypatch.setattr(
            QMessageBox,
            method,
            staticmethod(lambda *args, **kwargs: QMessageBox.Ok),
            raising=False,
        )

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    win.subjects = ["S1"]
    win.conditions = ["CondA", "CondB"]
    win.subject_data = {
        "S1": {
            "CondA": {"ROI": 1.0},
            "CondB": {"ROI": 2.0},
        }
    }
    win.rois = {"ROI": ["Cz"]}

    monkeypatch.setattr(
        win,
        "_check_for_open_excel_files",
        lambda _folder: False,
        raising=False,
    )
    monkeypatch.setattr(win, "refresh_rois", lambda: None, raising=False)
    monkeypatch.setattr(win, "_get_analysis_settings", lambda: (6.0, 0.05), raising=False)
    monkeypatch.setattr(win, "_get_qc_settings", lambda: (25.0, 50.0), raising=False)

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb, message_cb=None):
        del self, error_cb, message_cb
        payload = {
            "mixed_results_df": pd.DataFrame({"Effect": ["roi"], "Pr > F": [0.5]}),
            "output_text": "mixed model done",
        }
        finished_cb(pipeline_id, step.id, payload)

    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)

    exported_paths: list[Path] = []

    def fake_export_results(kind, data_obj, out_dir):
        save_path = Path(out_dir) / f"{kind}.xlsx"
        pd.DataFrame(data_obj).to_excel(save_path, index=False)
        exported_paths.append(save_path)
        return [save_path]

    monkeypatch.setattr(win, "export_results", fake_export_results)

    def raise_summary(_pipeline_id):
        raise RuntimeError("summary failure")

    monkeypatch.setattr(win, "build_and_render_summary", raise_summary)

    win._controller.run_single_group_analysis(
        step_ids=(StepId.MIXED_MODEL,),
        run_exports=True,
        run_summary=True,
    )

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=2000)

    log_text = win.output_text.toPlainText()
    assert exported_paths and all(path.is_file() for path in exported_paths)
    assert "summary failure" in log_text
    assert not win._controller.is_running(PipelineId.SINGLE)
    assert win.analyze_single_btn.isEnabled()
    assert not win.spinner.isVisible()
