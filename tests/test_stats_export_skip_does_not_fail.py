from pathlib import Path

import pandas as pd


def test_export_skips_rm_anova_none(tmp_path, monkeypatch):
    from Tools.Stats.PySide6 import stats_main_window
    from Tools.Stats.PySide6.stats_core import PipelineId
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(
        stats_main_window, "apply_rois_to_modules", lambda *_a, **_k: None, raising=False
    )
    monkeypatch.setattr(stats_main_window, "set_rois", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(stats_main_window, "load_rois_from_settings", lambda: {}, raising=False)

    _app = QApplication.instance() or QApplication([])
    win = StatsWindow(project_dir=str(tmp_path))

    win.rm_anova_results_data = None
    win.mixed_model_results_data = pd.DataFrame({"value": [1.0]})
    win.posthoc_results_data = None
    win._harmonic_results = {PipelineId.SINGLE: None, PipelineId.BETWEEN: None}

    export_calls: list[tuple[str, object, str]] = []

    def fake_export_results(kind, data_obj, out_dir):
        export_calls.append((kind, data_obj, out_dir))
        return [Path(out_dir) / f"{kind}.xlsx"]

    monkeypatch.setattr(win, "export_results", fake_export_results)
    monkeypatch.setattr(win, "_ensure_results_dir", lambda: str(tmp_path))

    log_calls: list[tuple[str, str, str]] = []

    def fake_append_log(section, message, level="info"):
        log_calls.append((section, message, level))

    monkeypatch.setattr(win, "append_log", fake_append_log)

    result = win._export_single_pipeline()

    assert result is True
    assert any(
        "Skipping export for RM-ANOVA (no data)" in message for _section, message, _level in log_calls
    )
    assert any(kind == "lmm" for kind, _data, _out_dir in export_calls)
