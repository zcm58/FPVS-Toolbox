from __future__ import annotations

import pandas as pd

from Tools.Stats.workers import stats_workers


def test_rm_worker_excludes_incomplete_condition_without_dropping_participants(
    monkeypatch,
) -> None:
    subjects = ["P1", "P2", "P3"]
    complete_conditions = ["Shared A", "Shared B"]
    nested: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, object]] = []
    for participant_index, participant in enumerate(subjects):
        nested[participant] = {}
        for condition_index, condition in enumerate(complete_conditions):
            value = 1.0 + participant_index * 0.1 + condition_index * 0.2
            nested[participant][condition] = {"R1": value}
            rows.append(
                {
                    "subject": participant,
                    "condition": condition,
                    "roi": "R1",
                    "value": value,
                }
            )
    for participant in ("P1", "P2"):
        nested[participant]["Optional"] = {"R1": 2.0}
        rows.append(
            {
                "subject": participant,
                "condition": "Optional",
                "roi": "R1",
                "value": 2.0,
            }
        )
    long_data = pd.DataFrame(rows)
    captured: dict[str, object] = {}

    monkeypatch.setattr(stats_workers, "set_rois", lambda _rois: None)
    monkeypatch.setattr(
        stats_workers,
        "_prepare_single_group_data",
        lambda **_kwargs: (
            subjects,
            {},
            nested,
            long_data,
            {},
            None,
            None,
            [],
            [],
        ),
    )
    monkeypatch.setattr(
        stats_workers,
        "_diag_subject_data_structure",
        lambda *_args, **_kwargs: None,
    )

    def _fake_analysis(data, _log, **kwargs):
        captured["data"] = data
        captured["conditions"] = kwargs["conditions"]
        return (
            "ok",
            pd.DataFrame(
                {
                    "Effect": ["condition * roi"],
                    "p_reported": [0.2],
                    "reportable": [True],
                }
            ),
        )

    monkeypatch.setattr(stats_workers, "analysis_run_rm_anova", _fake_analysis)

    result = stats_workers.run_rm_anova(
        lambda _progress: None,
        lambda _message: None,
        subjects=subjects,
        conditions=["Shared A", "Shared B", "Optional"],
        conditions_all=["Shared A", "Shared B", "Optional"],
        subject_data={},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
    )

    assert captured["conditions"] == complete_conditions
    assert set(captured["data"]) == set(subjects)
    assert all(
        set(participant_data) == set(complete_conditions)
        for participant_data in captured["data"].values()
    )
    assert result["design_audit"].complete_conditions == tuple(complete_conditions)
    assert result["design_audit"].excluded_conditions == ("Optional",)
    assert result["run_report"].final_modeled_pids == subjects
