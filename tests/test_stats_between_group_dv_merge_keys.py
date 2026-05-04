from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.workers.stats_workers import (
    LMM_DIAGNOSTIC_WORKBOOK,
    run_group_contrasts,
    run_lmm,
)


def _base_kwargs(results_dir: Path | None = None) -> dict:
    kwargs = {
        "subjects": ["P1", "P2"],
        "conditions": ["Face", "House"],
        "conditions_all": ["Face", "House"],
        "subject_data": {},
        "base_freq": 6.0,
        "alpha": 0.05,
        "rois": {"ROI1": ["O1"]},
        "rois_all": {"ROI1": ["O1"]},
        "subject_groups": {"P1": "G1", "P2": "G2"},
        "include_group": True,
        "required_conditions": ["Face", "House"],
        "subject_to_group": {"P1": "G1", "P2": "G2"},
    }
    if results_dir is not None:
        kwargs["results_dir"] = str(results_dir)
    return kwargs


def _results_dir(name: str) -> Path:
    path = Path.cwd() / ".codex-tmp" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_between_group_pid_mismatch_reports_precise_reason_and_writes_diagnostics() -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P100", "P100", "P200", "P200"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    results_dir = _results_dir("between-group-pid-mismatch")

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        fixed_harmonic_dv_table=fixed_dv,
        **_base_kwargs(results_dir=results_dir),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] == "authoritative_prepared_table"
    assert "authoritative prepared multigroup table is empty upstream" in payload["blocked_reason"]
    assert "Aligned lookup subjects did not overlap the selected canonical multigroup participants" in (
        payload["blocked_reason"]
    )

    workbook_path = results_dir / LMM_DIAGNOSTIC_WORKBOOK
    assert workbook_path.is_file()
    with pd.ExcelFile(workbook_path) as workbook:
        assert {"StageCounts", "ConditionSets", "KeyMatchStats", "DVColumnAudit", "FinalBeforeDropna"}.issubset(
            set(workbook.sheet_names)
        )


def test_between_group_condition_mismatch_reports_precise_reason() -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Car", "Chair", "Car", "Chair"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        fixed_harmonic_dv_table=fixed_dv,
        **_base_kwargs(),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "DV merge produced 0 matches: condition mismatch"


def test_between_group_successful_merge_logs_non_nan_before_dropna_and_does_not_block(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    logs: list[str] = []
    captured: dict[str, object] = {}

    def _fake_mixed_effects_model(*, data, dv_col, group_col, fixed_effects, **_kwargs):
        captured["dv_col"] = dv_col
        captured["rows"] = len(data)
        return pd.DataFrame({"Effect": ["condition"], "P-Value": [0.04]}), object()

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.run_mixed_effects_model", _fake_mixed_effects_model)

    kwargs = _base_kwargs()
    kwargs["subjects"] = ["P1BCF", "P2CGL"]
    kwargs["subject_groups"] = {"P1BCF": "G1", "P2CGL": "G2"}
    kwargs["subject_to_group"] = {"P1BCF": "G1", "P2CGL": "G2"}

    payload = run_lmm(
        lambda _progress: None,
        logs.append,
        fixed_harmonic_dv_table=fixed_dv,
        **kwargs,
    )

    assert payload.get("status") != "blocked"
    assert captured["dv_col"] == "value"
    assert captured["rows"] == 4
    assert any("stage=after_merge_before_dropna" in line and "non_nan_count=4" in line for line in logs)


def test_between_group_execution_normalizes_zero_padded_subject_ids(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    captured: dict[str, object] = {}

    def _fake_mixed_effects_model(*, data, dv_col, group_col, fixed_effects, **_kwargs):
        captured["dv_col"] = dv_col
        captured["rows"] = len(data)
        captured["subjects"] = sorted(data["subject"].astype(str).unique().tolist())
        return pd.DataFrame({"Effect": ["condition"], "P-Value": [0.04]}), object()

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.run_mixed_effects_model", _fake_mixed_effects_model)

    kwargs = _base_kwargs()
    kwargs["subjects"] = ["P01", "P02"]
    kwargs["subject_groups"] = {"P01": "G1", "P02": "G2"}
    kwargs["subject_to_group"] = {"P01": "G1", "P02": "G2"}

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        fixed_harmonic_dv_table=fixed_dv,
        **kwargs,
    )

    assert payload.get("status") != "blocked"
    assert captured["dv_col"] == "value"
    assert captured["rows"] == 4
    assert captured["subjects"] == ["P1", "P2"]


def test_between_group_supported_path_aligns_rich_lookup_subjects_without_renaming(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": [
                "ValenceP01",
                "ValenceP01",
                "ValenceP02",
                "ValenceP02",
                "GroupA-ValenceP03-run2",
                "GroupA-ValenceP03-run2",
                "GroupA-ValenceP04-run2",
                "GroupA-ValenceP04-run2",
            ],
            "condition": ["Face", "House", "Face", "House", "Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1", "ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 1.5, 2.5, 3.0, 4.0, 3.5, 4.5],
        }
    )

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

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.run_mixed_effects_model", _capture_lmm)
    monkeypatch.setattr("Tools.Stats.workers.stats_workers.compute_group_contrasts", _capture_contrasts)

    kwargs = _base_kwargs()
    kwargs["subjects"] = ["P1", "P2", "P3", "P4"]
    kwargs["subject_groups"] = {"P1": "G1", "P2": "G1", "P3": "G2", "P4": "G2"}
    kwargs["subject_to_group"] = {"P1": "G1", "P2": "G1", "P3": "G2", "P4": "G2"}
    mixed_payload = run_lmm(
        lambda _progress: None,
        mixed_messages.append,
        fixed_harmonic_dv_table=fixed_dv,
        prepared_multigroup_dv_payload=shared_payload,
        **kwargs,
    )
    contrasts_payload = run_group_contrasts(
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

    prepared_lookup_df = shared_payload["prepared_dv_lookup_df"]
    prepared_df = shared_payload["prepared_dv_table"]

    assert mixed_payload.get("status") != "blocked"
    assert isinstance(prepared_lookup_df, pd.DataFrame)
    assert isinstance(prepared_df, pd.DataFrame)
    assert shared_payload["selected_subjects_after_manual"] == ["P1", "P2", "P3", "P4"]
    assert sorted(prepared_lookup_df["subject"].astype(str).unique().tolist()) == ["P1", "P2", "P3", "P4"]
    assert sorted(prepared_df["subject"].astype(str).unique().tolist()) == ["P1", "P2", "P3", "P4"]
    assert shared_payload["run_report"] is mixed_payload["run_report"]
    assert shared_payload["run_report"] is contrasts_payload["run_report"]
    pd.testing.assert_frame_equal(captured["lmm_input"], captured["contrasts_input"])
    assert any(
        "consumer=between_group_mixed_model" in line
        and "selected_subjects_after_manual_count=4" in line
        and "lookup_unique_subject_count_before_alignment=4" in line
        and "lookup_unique_subject_sample_before_alignment=['ValenceP01', 'ValenceP02', 'GroupA-ValenceP03-run2', 'GroupA-ValenceP04-run2']" in line
        for line in mixed_messages
    )
    assert any(
        "consumer=between_group_mixed_model" in line
        and "lookup_unique_subject_count_after_alignment=4" in line
        and "lookup_unique_subject_sample_after_alignment=['P1', 'P2', 'P3', 'P4']" in line
        and "unmatched_selected_subjects_sample=[]" in line
        and "unmatched_lookup_subjects_sample=[]" in line
        for line in mixed_messages
    )
    assert any(
        "consumer=group_contrasts" in line
        and "prepared_dv_lookup_df_rows=8" in line
        and "prepared_dv_table_rows=8" in line
        and "final_modeled_subject_ids=['P1', 'P2', 'P3', 'P4']" in line
        for line in contrast_messages
    )


def test_between_group_supported_path_shares_prepared_contract_and_keys(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2", "P3", "P3", "P4", "P4"],
            "condition": ["face", "HOUSE", "face", "HOUSE", "face", "HOUSE", "face", "HOUSE"],
            "roi": [" ROI1 ", " ROI1 ", " ROI1 ", " ROI1 ", " ROI1 ", " ROI1 ", " ROI1 ", " ROI1 "],
            "dv_value": [1.0, 2.0, 1.5, 2.5, 3.0, 4.0, 3.5, 4.5],
        }
    )

    shared_payload: dict[str, object] = {}
    captured: dict[str, pd.DataFrame] = {}
    mixed_messages: list[str] = []

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
                    "condition": "face",
                    "roi": "ROI1",
                }
            ]
        )

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.run_mixed_effects_model", _capture_lmm)
    monkeypatch.setattr("Tools.Stats.workers.stats_workers.compute_group_contrasts", _capture_contrasts)

    kwargs = _base_kwargs()
    kwargs["subjects"] = ["P01", "P02", "P03", "P04"]
    kwargs["subject_groups"] = {"P01": "G1", "P02": "G1", "P03": "G2", "P04": "G2"}
    kwargs["subject_to_group"] = {"P01": "G1", "P02": "G1", "P03": "G2", "P04": "G2"}

    mixed_payload = run_lmm(
        lambda _progress: None,
        mixed_messages.append,
        fixed_harmonic_dv_table=fixed_dv,
        prepared_multigroup_dv_payload=shared_payload,
        **kwargs,
    )
    contrasts_payload = run_group_contrasts(
        lambda _progress: None,
        lambda _msg: None,
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

    prepared_df = shared_payload["prepared_dv_table"]
    assert mixed_payload.get("status") != "blocked"
    assert isinstance(prepared_df, pd.DataFrame)
    assert sorted(prepared_df["subject"].astype(str).unique().tolist()) == ["P1", "P2", "P3", "P4"]
    assert sorted(prepared_df["condition"].astype(str).unique().tolist()) == ["face", "house"]
    assert sorted(prepared_df["roi"].astype(str).unique().tolist()) == ["ROI1"]
    pd.testing.assert_frame_equal(captured["lmm_input"], captured["contrasts_input"])
    assert mixed_payload["run_report"] is shared_payload["run_report"]
    assert contrasts_payload["run_report"] is shared_payload["run_report"]
    assert shared_payload["run_report"].final_modeled_pids == ["P1", "P2", "P3", "P4"]
    assert any(
        "consumer=between_group_mixed_model" in line
        and "prepared_dv_lookup_df_rows=8" in line
        and "prepared_dv_table_rows=8" in line
        and "dropped_null_group_rows=0" in line
        and "final_modeled_subject_ids=['P1', 'P2', 'P3', 'P4']" in line
        for line in mixed_messages
    )


def test_between_group_supported_path_reports_subject_alignment_mismatch_samples(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["AlphaSubjectOne", "AlphaSubjectOne", "BetaSubjectTwo", "BetaSubjectTwo"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    messages: list[str] = []

    def _unexpected_run_mixed_effects_model(**_kwargs):
        raise AssertionError(
            "run_mixed_effects_model should not run when aligned lookup subjects do not overlap"
        )

    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers.run_mixed_effects_model",
        _unexpected_run_mixed_effects_model,
    )

    payload = run_lmm(
        lambda _progress: None,
        messages.append,
        fixed_harmonic_dv_table=fixed_dv,
        **_base_kwargs(),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] == "authoritative_prepared_table"
    assert "authoritative prepared multigroup table is empty upstream" in payload["blocked_reason"]
    assert "Aligned lookup subjects did not overlap the selected canonical multigroup participants" in (
        payload["blocked_reason"]
    )
    assert "Source files/manifests were left unchanged." in payload["blocked_reason"]
    assert any(
        "consumer=between_group_mixed_model" in line
        and "selected_subjects_after_manual_count=2" in line
        and "selected_subjects_after_manual_sample=['P1', 'P2']" in line
        and "lookup_unique_subject_count_before_alignment=2" in line
        and "lookup_unique_subject_sample_before_alignment=['AlphaSubjectOne', 'BetaSubjectTwo']" in line
        for line in messages
    )
    assert any(
        "consumer=between_group_mixed_model" in line
        and "lookup_unique_subject_count_after_alignment=2" in line
        and "lookup_unique_subject_sample_after_alignment=['AlphaSubjectOne', 'BetaSubjectTwo']" in line
        and "unmatched_selected_subjects_sample=['P1', 'P2']" in line
        and "unmatched_lookup_subjects_sample=['AlphaSubjectOne', 'BetaSubjectTwo']" in line
        for line in messages
    )
    assert any(
        "consumer=between_group_mixed_model" in line
        and "prepared_dv_lookup_df_rows=4" in line
        and "prepared_dv_table_rows=0" in line
        and "dropped_null_group_rows=0" in line
        and "final_modeled_subject_ids=[]" in line
        for line in messages
    )


def test_between_group_supported_path_blocks_when_authoritative_rows_are_empty_upstream(
    monkeypatch,
) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    messages: list[str] = []

    def _unexpected_run_mixed_effects_model(**_kwargs):
        raise AssertionError(
            "run_mixed_effects_model should not run when the authoritative prepared table is empty"
        )

    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers.run_mixed_effects_model",
        _unexpected_run_mixed_effects_model,
    )

    kwargs = _base_kwargs()
    kwargs["subject_groups"] = {"ValenceSubjectOne": "G1", "ValenceSubjectTwo": "G2"}
    kwargs["subject_to_group"] = {"ValenceSubjectOne": "G1", "ValenceSubjectTwo": "G2"}

    payload = run_lmm(
        lambda _progress: None,
        messages.append,
        fixed_harmonic_dv_table=fixed_dv,
        **kwargs,
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] == "authoritative_prepared_table"
    assert "authoritative prepared multigroup table is empty upstream" in payload["blocked_reason"]
    assert "normalized group assignments" in payload["blocked_reason"]
    assert "participant-token extraction and subject/group assignment mapping" in payload["blocked_reason"]
    assert any(
        "consumer=between_group_mixed_model" in line
        and "prepared_dv_lookup_df_rows=4" in line
        and "prepared_dv_table_rows=0" in line
        and "dropped_null_group_rows=4" in line
        and "final_modeled_subject_ids=[]" in line
        for line in messages
    )
