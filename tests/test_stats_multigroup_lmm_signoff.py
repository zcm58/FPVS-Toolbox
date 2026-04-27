from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtCore import Qt

    from Tools.Stats.PySide6 import stats_workers
    from Tools.Stats.PySide6.reporting_summary import (
        ReportingSummaryContext,
        build_reporting_summary,
    )
    from Tools.Stats.PySide6.stats_controller import (
        PipelineId,
        StepId,
        WORKER_FN_BY_STEP,
    )
    from Tools.Stats.PySide6.stats_run_report import StatsRunReport
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
    from Tools.Stats.PySide6.summary_utils import (
        StatsSummaryFrames,
        SummaryConfig,
        build_summary_from_frames,
    )
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for multigroup LMM signoff tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


class _FakeMixedModelResult:
    def __init__(self, formula: str, *, converged: bool = True) -> None:
        self.converged = converged
        self.model = type("_FormulaModel", (), {"formula": formula})()
        self.hist = [{"gopt": 0.0}]


def _prepared_multigroup_payload() -> dict[str, object]:
    prepared_df = pd.DataFrame(
        [
            {"subject": "P1", "condition": "A", "roi": "ROI1", "value": 1.0, "group": "Control"},
            {"subject": "P1", "condition": "A", "roi": "ROI2", "value": 1.1, "group": "Control"},
            {"subject": "P1", "condition": "B", "roi": "ROI1", "value": 1.2, "group": "Control"},
            {"subject": "P1", "condition": "B", "roi": "ROI2", "value": 1.3, "group": "Control"},
            {"subject": "P2", "condition": "A", "roi": "ROI1", "value": 2.0, "group": "Patient"},
            {"subject": "P2", "condition": "A", "roi": "ROI2", "value": 2.1, "group": "Patient"},
            {"subject": "P2", "condition": "B", "roi": "ROI1", "value": 2.2, "group": "Patient"},
            {"subject": "P2", "condition": "B", "roi": "ROI2", "value": 2.3, "group": "Patient"},
        ]
    )
    return {
        "selected_subjects_after_manual": ["P1", "P2"],
        "subject_data_after_manual": {},
        "subject_groups_after_manual": {"P1": "Control", "P2": "Patient"},
        "qc_report": None,
        "manual_excluded": [],
        "exclusion_rows": [],
        "normalized_subject_group_map": {"P1": "Control", "P2": "Patient"},
        "dv_metadata": {},
        "all_subject_bca_data": {},
        "model_input_columns_df": pd.DataFrame(),
        "prepared_dv_lookup_df": prepared_df.copy(),
        "prepared_dv_table": prepared_df.copy(),
        "dv_report": None,
        "required_exclusions": [],
        "run_report": StatsRunReport([], None, None, [], ["P1", "P2"]),
        "mapped_source_col": "value",
        "tried_columns": ["value"],
    }


def _call_supported_between_run(monkeypatch, mixed_results_df: pd.DataFrame, *, converged: bool = True):
    formula = "value ~ group * C(condition, Sum) * C(roi, Sum)"
    payload = _prepared_multigroup_payload()
    captured: dict[str, object] = {}
    messages: list[str] = []

    monkeypatch.setattr(
        stats_workers,
        "_prepare_supported_multigroup_dv_contract",
        lambda **_kwargs: payload,
    )
    monkeypatch.setattr(stats_workers, "set_rois", lambda _rois: None)
    monkeypatch.setattr(stats_workers, "compute_missingness", lambda **_kwargs: [])

    def _fake_run_mixed_effects_model(**kwargs):
        captured["kwargs"] = kwargs
        return mixed_results_df.copy(), _FakeMixedModelResult(formula, converged=converged)

    monkeypatch.setattr(
        stats_workers,
        "run_mixed_effects_model",
        _fake_run_mixed_effects_model,
    )

    result = stats_workers.run_lmm(
        lambda *_args, **_kwargs: None,
        messages.append,
        subjects=["P1", "P2"],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"], "ROI2": ["O2"]},
        rois_all={"ROI1": ["O1"], "ROI2": ["O2"]},
        subject_groups={"P1": "Control", "P2": "Patient"},
        include_group=True,
        required_conditions=["A", "B"],
        prepared_multigroup_dv_payload={},
        results_dir=None,
    )
    return result, captured, messages


def _unsupported_between_lmm_df() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "Effect (raw)": ["Intercept", "group[T.Patient]"],
            "Coef.": [1.0, 0.25],
            "SE": [0.1, float("nan")],
            "Z": [10.0, 1.5],
            "P>|z|": [1.0e-6, 0.13],
            "Note": ["", "Model did not converge"],
        }
    )
    df.attrs["lmm_fit_supported"] = False
    df.attrs["lmm_fit_status_label"] = "UNSUPPORTED"
    df.attrs["lmm_fit_status_message"] = (
        "Supported multigroup LMM blocked: optimizer reported non-convergence."
    )
    return df


def _make_immediate_worker(monkeypatch, seen_steps=None):
    def ready_stub(self, pipeline_id, *, require_anova=False):
        del pipeline_id, require_anova
        self._current_base_freq = 6.0
        self._current_alpha = 0.05
        return True

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb, message_cb=None):
        if isinstance(seen_steps, list):
            seen_steps.append(step.id)
        try:
            payload = step.worker_fn(
                lambda *_a, **_k: None,
                message_cb or (lambda *_a, **_k: None),
                **step.kwargs,
            )
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


def test_supported_multigroup_lmm_contract_is_truthful(monkeypatch) -> None:
    mixed_results_df = pd.DataFrame(
        {
            "Effect": ["Intercept", "group[T.Patient]", "C(condition, Sum)[S.B]"],
            "Coef.": [1.0, 0.25, 0.4],
            "SE": [0.1, 0.2, 0.2],
            "Z": [10.0, 1.25, 2.0],
            "P>|z|": [1.0e-6, 0.21, 0.045],
            "Note": ["", "", ""],
        }
    )

    result, captured, messages = _call_supported_between_run(monkeypatch, mixed_results_df, converged=True)

    attrs = result["mixed_results_df"].attrs
    assert captured["kwargs"]["contrast_map"] == {"condition": "Sum", "roi": "Sum"}
    assert result["status"] == "supported"
    assert result["fit_status"]["supported"] is True
    assert attrs["lmm_formula"] == "value ~ group * C(condition, Sum) * C(roi, Sum)"
    assert attrs["lmm_fixed_effects_summary"] == "Group, condition, ROI, and all interactions"
    assert attrs["lmm_random_effects_summary"] == "Random intercept for subject only (re_formula=1)"
    assert attrs["lmm_estimation_summary"] == "REML via statsmodels MixedLM"
    assert attrs["lmm_coding_summary"] == (
        "group: Default/implicit (not explicitly set by FPVS wrapper); "
        "condition: Sum; roi: Sum"
    )
    assert "Fit status: SUPPORTED" in result["output_text"]
    assert not any("blocked" in message.lower() for message in messages)


def test_unsupported_multigroup_lmm_is_classified_and_summarized_honestly(monkeypatch) -> None:
    mixed_results_df = pd.DataFrame(
        {
            "Effect": ["Intercept", "group[T.Patient]"],
            "Coef.": [1.0, 0.25],
            "SE": [0.1, float("nan")],
            "Z": [10.0, 1.5],
            "P>|z|": [1.0e-6, 0.13],
            "Note": ["", "Model did not converge"],
        }
    )

    result, _captured, messages = _call_supported_between_run(monkeypatch, mixed_results_df, converged=False)

    assert result["status"] == "unsupported"
    assert result["fit_status"]["supported"] is False
    assert "Diagnostic Output (Unsupported Fit)" in result["output_text"]
    assert any("blocked" in message.lower() for message in messages)

    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name=PipelineId.BETWEEN.name,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=100,
        timezone_label="UTC",
        total_participants=2,
        included_participants=["P1", "P2"],
        excluded_reasons={},
        selected_conditions=["A", "B"],
        selected_rois=["ROI1", "ROI2"],
    )
    reporting_text = build_reporting_summary(
        context,
        anova_df=None,
        lmm_df=result["mixed_results_df"],
        posthoc_df=None,
    )
    assert "Supported multigroup fit status: UNSUPPORTED" in reporting_text
    assert "Coding summary: group: Default/implicit" in reporting_text

    summary_text = build_summary_from_frames(
        StatsSummaryFrames(
            mixed_model_terms=result["mixed_results_df"],
            pipeline_id=PipelineId.BETWEEN,
        ),
        SummaryConfig(alpha=0.05),
    )
    assert "Supported multigroup LMM blocked" in summary_text
    assert "Attempted contract: Group, condition, ROI, and all interactions" in summary_text


@pytest.mark.qt
def test_between_pipeline_stops_on_unsupported_multigroup_lmm(monkeypatch, qtbot, tmp_path) -> None:
    seen_steps: list[StepId] = []
    _make_immediate_worker(monkeypatch, seen_steps)

    unsupported_df = _unsupported_between_lmm_df()

    monkeypatch.setattr(
        stats_workers,
        "run_lmm",
        lambda *_a, **_k: {
            "status": "unsupported",
            "fit_status": {
                "status": "unsupported",
                "label": "UNSUPPORTED",
                "supported": False,
                "message": unsupported_df.attrs["lmm_fit_status_message"],
                "issues": ["optimizer reported non-convergence"],
            },
            "mixed_results_df": unsupported_df.copy(),
            "output_text": "blocked",
            "missingness": {},
        },
        raising=False,
    )
    monkeypatch.setattr(
        stats_workers,
        "run_group_contrasts",
        lambda *_a, **_k: {"results_df": pd.DataFrame({"value": [1.0]}), "output_text": "contrasts"},
        raising=False,
    )
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.BETWEEN_GROUP_MIXED_MODEL, stats_workers.run_lmm)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.GROUP_CONTRASTS, stats_workers.run_group_contrasts)

    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    _prime_between_subjects(win)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=2000)
    assert "Supported multigroup LMM blocked" in win.output_text.toPlainText()
    assert "Step handler failed" in win.output_text.toPlainText()
    assert seen_steps == [StepId.BETWEEN_GROUP_MIXED_MODEL]
    assert not win._controller.is_running(PipelineId.BETWEEN)
    assert not win._can_export_between_mixed_model()


def test_supported_multigroup_contract_retains_finite_rows_after_required_exclusions(monkeypatch) -> None:
    fixed_rows: list[dict[str, object]] = []
    groups = {
        "P1": "G1",
        "P2": "G1",
        "P3": "G1",
        "P4": "G2",
        "P5": "G2",
        "P6": "G2",
    }
    nan_cells = {
        "P1": ("Face", "ROI1"),
        "P2": ("Face", "ROI2"),
        "P3": ("House", "ROI1"),
        "P4": ("House", "ROI2"),
        "P5": ("Face", "ROI1"),
        "P6": ("House", "ROI1"),
    }
    for idx, subject in enumerate(sorted(groups), start=1):
        for condition in ("Face", "House"):
            for roi in ("ROI1", "ROI2"):
                value = float(idx)
                if nan_cells[subject] == (condition, roi):
                    value = float("nan")
                fixed_rows.append(
                    {
                        "subject": subject,
                        "condition": condition,
                        "roi": roi,
                        "dv_value": value,
                    }
                )

    fixed_dv = pd.DataFrame(fixed_rows)
    shared_payload: dict[str, object] = {}
    captured: dict[str, pd.DataFrame] = {}
    mixed_messages: list[str] = []
    contrast_messages: list[str] = []

    def _capture_lmm(*, data, dv_col, group_col, fixed_effects, **_kwargs):
        _ = group_col, fixed_effects
        captured["lmm_input"] = (
            data.loc[:, ["subject", "condition", "roi", "group", dv_col]]
            .rename(columns={dv_col: "value"})
            .sort_values(["subject", "condition", "roi"], kind="mergesort")
            .reset_index(drop=True)
        )
        return pd.DataFrame({"Effect": ["group"], "P-Value": [0.04]}), object()

    def _capture_contrasts(data, **_kwargs):
        captured["contrasts_input"] = (
            data.loc[:, ["subject", "condition", "roi", "group", "value"]]
            .sort_values(["subject", "condition", "roi"], kind="mergesort")
            .reset_index(drop=True)
        )
        return pd.DataFrame(
            [
                {
                    "group_1": "G1",
                    "group_2": "G2",
                    "difference": -2.0,
                    "t_stat": -3.0,
                    "p_value": 0.04,
                    "condition": "Face",
                    "roi": "ROI1",
                }
            ]
        )

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.run_mixed_effects_model", _capture_lmm)
    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.compute_group_contrasts", _capture_contrasts)

    kwargs = {
        "subjects": ["P1", "P2", "P3", "P4", "P5", "P6"],
        "conditions": ["Face", "House"],
        "conditions_all": ["Face", "House"],
        "subject_data": {},
        "base_freq": 6.0,
        "alpha": 0.05,
        "rois": {"ROI1": ["O1"], "ROI2": ["O2"]},
        "rois_all": {"ROI1": ["O1"], "ROI2": ["O2"]},
        "subject_groups": groups,
        "include_group": True,
        "required_conditions": ["Face", "House"],
        "subject_to_group": groups,
    }

    mixed_payload = stats_workers.run_lmm(
        lambda _progress: None,
        mixed_messages.append,
        fixed_harmonic_dv_table=fixed_dv,
        prepared_multigroup_dv_payload=shared_payload,
        **kwargs,
    )
    contrasts_payload = stats_workers.run_group_contrasts(
        lambda _progress: None,
        contrast_messages.append,
        subjects=kwargs["subjects"],
        conditions=kwargs["conditions"],
        conditions_all=kwargs["conditions_all"],
        subject_data=kwargs["subject_data"],
        base_freq=kwargs["base_freq"],
        alpha=kwargs["alpha"],
        rois=kwargs["rois"],
        rois_all=kwargs["rois_all"],
        subject_groups=kwargs["subject_groups"],
        fixed_harmonic_dv_table=fixed_dv,
        required_conditions=kwargs["required_conditions"],
        subject_to_group=kwargs["subject_to_group"],
        prepared_multigroup_dv_payload=shared_payload,
    )

    assert mixed_payload.get("status") != "blocked"
    assert isinstance(shared_payload.get("prepared_dv_table"), pd.DataFrame)
    assert shared_payload["selected_lookup_rows_before_exclusions"] == 24
    assert shared_payload["rows_after_outlier_filter"] == 0
    assert shared_payload["required_exclusion_count"] == 6
    assert shared_payload["required_pids_sample"] == ["P1", "P2", "P3", "P4", "P5"]
    assert shared_payload["exclusion_reason_counts"] == {"REQUIRED_EXCLUSION_NONFINITE": 6}
    assert shared_payload["rows_after_required_exclusions"] == 18
    assert shared_payload["prepared_dv_table_rows"] == 18
    assert shared_payload["final_modeled_subject_ids"] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert shared_payload["run_report"].final_modeled_pids == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert contrasts_payload["run_report"] is shared_payload["run_report"]
    assert captured["lmm_input"].shape[0] == 18
    pd.testing.assert_frame_equal(captured["lmm_input"], captured["contrasts_input"])
    assert any(
        "selected_lookup_rows_before_exclusions=24" in line
        and "rows_after_outlier_filter=0" in line
        and "required_exclusion_count=6" in line
        for line in mixed_messages
    )
    assert any(
        "exclusion_reason_counts={'REQUIRED_EXCLUSION_NONFINITE': 6}" in line
        and "rows_after_required_exclusions=18" in line
        and "prepared_dv_table_rows=18" in line
        and "final_modeled_subject_ids=['P1', 'P2', 'P3', 'P4', 'P5', 'P6']" in line
        for line in contrast_messages
    )
