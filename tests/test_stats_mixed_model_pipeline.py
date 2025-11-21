import pytest

try:
    import pandas as pd
    from PySide6.QtCore import Qt

    from Tools.Stats.PySide6 import stats_workers
    from Tools.Stats.PySide6.stats_controller import PipelineId
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Stats mixed model tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


def _make_immediate_worker(monkeypatch):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):
        try:
            payload = step.worker_fn(lambda *_a, **_k: None, lambda *_a, **_k: None, **step.kwargs)
        except Exception as exc:  # noqa: BLE001
            error_cb(pipeline_id, step.id, str(exc))
        else:
            finished_cb(pipeline_id, step.id, payload or {})

    monkeypatch.setattr(StatsWindow, "ensure_pipeline_ready", ready_stub, raising=False)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_pipeline_results", lambda self, pid: True, raising=False)
    monkeypatch.setattr(StatsWindow, "build_and_render_summary", lambda self, pid: None, raising=False)


def _prime_between_subjects(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["C1"]
    window.subject_groups = {"S1": "G1", "S2": "G2"}
    window.subject_data = {"S1": {"C1": {"ROI": 1.0}}, "S2": {"C1": {"ROI": 2.0}}}
    window.rois = {"ROI": ["Cz"]}


@pytest.mark.qt
def test_between_mixed_model_valid_payload_advances(monkeypatch, qtbot, tmp_path):
    _make_immediate_worker(monkeypatch)

    dummy_df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})

    monkeypatch.setattr(
        stats_workers,
        "run_between_group_anova",
        lambda *_a, **_k: {"anova_df_results": dummy_df.copy(), "output_text": "anova"},
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_lmm",
        lambda *_a, **_k: {
            "mixed_results_df": dummy_df.copy(),
            "output_text": "ok",
        },
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_group_contrasts",
        lambda *_a, **_k: {"results_df": dummy_df.copy(), "output_text": "contrasts"},
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_harmonic_check",
        lambda *_a, **_k: {"output_text": "harmonic", "findings": []},
        raising=False,
    )

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    qtbot.waitUntil(
        lambda: "Between-Group Analysis finished" in win.output_text.toPlainText(), timeout=2000
    )
    assert "Between-Group Mixed Model completed" in win.output_text.toPlainText()
    assert not win._controller.is_running(PipelineId.BETWEEN)


@pytest.mark.qt
def test_between_mixed_model_invalid_payload_finalizes(monkeypatch, qtbot, tmp_path):
    _make_immediate_worker(monkeypatch)

    dummy_df = pd.DataFrame({"value": [1.0, 2.0]})

    monkeypatch.setattr(
        stats_workers,
        "run_between_group_anova",
        lambda *_a, **_k: {"anova_df_results": dummy_df.copy(), "output_text": "anova"},
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_lmm",
        lambda *_a, **_k: {},
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_group_contrasts",
        lambda *_a, **_k: {"results_df": dummy_df.copy(), "output_text": "contrasts"},
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_harmonic_check",
        lambda *_a, **_k: {"output_text": "harmonic", "findings": []},
        raising=False,
    )

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    assert "Step handler failed" in win.output_text.toPlainText()
    assert not win._controller.is_running(PipelineId.BETWEEN)
