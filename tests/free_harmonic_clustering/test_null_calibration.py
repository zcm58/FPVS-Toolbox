from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.manual_diagnostics import run_free_harmonic_clustering_null_calibration as calibration_runner
from Tools.Free_Harmonic_Clustering.models import AnalysisDesign
from Tools.Free_Harmonic_Clustering.null_calibration import (
    CALIBRATION_DETERMINISM_BATCH_SIZE,
    CALIBRATION_DETERMINISM_PERMUTATIONS,
    CALIBRATION_DETERMINISM_PROTOCOL_ID,
    CALIBRATION_SCENARIOS,
    DEFAULT_NULL_CALIBRATION_PROTOCOL,
    NullCalibrationReplicate,
    NullCalibrationScenario,
    NullCalibrationTask,
    _correlated_standard_field,
    build_calibration_receipt,
    calibration_tasks,
    clopper_pearson_upper,
    critical_rejection_count,
    determinism_tasks,
    ordered_results_fingerprint,
    pending_calibration_receipt_template,
    protocol_fingerprint,
    replicate_from_payload,
    replicate_payload,
    run_null_calibration_replicate,
    summarize_null_calibration,
    task_seeds,
    validate_calibration_receipt,
    validate_replicate_for_task,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_TEMPLATE_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "agent"
    / "quality"
    / "free-harmonic-clustering-null-calibration-v1-receipt-template.json"
)


def _passing_determinism_check() -> dict[str, object]:
    fingerprint = "d" * 64
    return {
        "protocol_id": CALIBRATION_DETERMINISM_PROTOCOL_ID,
        "task_ids": [task.task_id for task in determinism_tasks()],
        "permutations_per_replicate": CALIBRATION_DETERMINISM_PERMUTATIONS,
        "permutation_batch_size": CALIBRATION_DETERMINISM_BATCH_SIZE,
        "serial_results_sha256": fingerprint,
        "resumed_results_sha256": fingerprint,
        "parallel_results_sha256": fingerprint,
        "status": "pass",
    }


def test_powered_protocol_and_exact_binomial_guardrails_are_frozen() -> None:
    protocol = DEFAULT_NULL_CALIBRATION_PROTOCOL

    assert protocol.total_replicates == 4_000
    assert protocol.replicates_per_design == 2_000
    assert protocol.replicates_per_scenario == 500
    assert protocol.permutations_per_replicate == 10_000
    assert protocol_fingerprint() == "178739203fc5fd32702681546cae9ad50d153b79c850921531aee8410a585936"
    assert critical_rejection_count(replicates=2_000, confidence=0.975, error_bound=0.070) == 117
    assert clopper_pearson_upper(117, 2_000, confidence=0.975) < 0.070
    assert clopper_pearson_upper(118, 2_000, confidence=0.975) >= 0.070
    assert critical_rejection_count(replicates=500, confidence=0.950, error_bound=0.100) == 38
    assert clopper_pearson_upper(38, 500, confidence=0.950) < 0.100
    assert clopper_pearson_upper(39, 500, confidence=0.950) >= 0.100


def test_task_schedule_and_seed_streams_are_deterministic_and_unique() -> None:
    tasks = calibration_tasks()

    assert len(tasks) == 4_000
    assert tasks[0].task_id == "independent_groups:iid_two_harmonic_lognormal:0000"
    assert task_seeds(tasks[0]) == (1_886_657_657, 3_093_921_092)
    assert tasks[-1].task_id == "paired_conditions:heavy_tail_two_harmonic:0499"
    assert task_seeds(tasks[-1]) == (139_188_401, 2_546_528_640)
    assert len({task_seeds(task) for task in tasks}) == len(tasks)
    data_seeds = [task_seeds(task)[0] for task in tasks]
    permutation_seeds = [task_seeds(task)[1] for task in tasks]
    assert len(set(data_seeds)) == len(tasks)
    assert len(set(permutation_seeds)) == len(tasks)
    assert set(data_seeds).isdisjoint(permutation_seeds)


def test_pending_receipt_template_matches_the_frozen_protocol() -> None:
    committed = json.loads(RECEIPT_TEMPLATE_PATH.read_text(encoding="utf-8"))

    assert committed == pending_calibration_receipt_template()
    validate_calibration_receipt(committed, allow_pending=True)


def test_checkpoint_row_round_trip_preserves_scientific_result() -> None:
    result = NullCalibrationReplicate(
        task_id="paired_conditions:iid_two_harmonic_lognormal:0000",
        design="paired_conditions",
        scenario_id="iid_two_harmonic_lognormal",
        replicate_index=0,
        data_seed=1,
        permutation_seed=2,
        status="complete",
        selected_orders=(1, 2),
        positive_rejection=True,
        global_rejection=True,
        permutation_assignment_hash="a" * 64,
        elapsed_seconds=1.25,
    )

    assert replicate_from_payload(replicate_payload(result)) == result
    later_timing = replace(result, elapsed_seconds=99.0)
    assert ordered_results_fingerprint((result,)) == ordered_results_fingerprint((later_timing,))


@pytest.mark.parametrize("design", tuple(AnalysisDesign))
@pytest.mark.parametrize("scenario", CALIBRATION_SCENARIOS, ids=lambda value: value.scenario_id)
def test_tiny_replicate_uses_each_frozen_generator_without_powered_cost(
    design: AnalysisDesign,
    scenario: NullCalibrationScenario,
) -> None:
    protocol = replace(
        DEFAULT_NULL_CALIBRATION_PROTOCOL,
        scenarios=(scenario,),
        replicates_per_scenario=1,
        permutations_per_replicate=19,
        permutation_batch_size=7,
    )
    task = NullCalibrationTask(
        design=design,
        scenario_id=scenario.scenario_id,
        replicate_index=0,
    )

    result = run_null_calibration_replicate(task, protocol)

    assert result.status == "complete"
    assert result.selected_orders
    assert result.permutation_assignment_hash
    assert result.error == ""


def test_summary_and_receipt_apply_every_design_and_scenario_guardrail() -> None:
    protocol = replace(
        DEFAULT_NULL_CALIBRATION_PROTOCOL,
        replicates_per_scenario=2,
        permutations_per_replicate=19,
        design_upper_confidence=0.5,
        design_error_bound=0.9,
        scenario_upper_confidence=0.5,
        scenario_error_bound=0.9,
    )
    results = []
    for task in calibration_tasks(protocol):
        selected_orders = (1,) if task.replicate_index == 0 else (1, 2)
        data_seed, permutation_seed = task_seeds(task)
        results.append(
            NullCalibrationReplicate(
                task_id=task.task_id,
                design=task.design.value,
                scenario_id=task.scenario_id,
                replicate_index=task.replicate_index,
                data_seed=data_seed,
                permutation_seed=permutation_seed,
                status="complete",
                selected_orders=selected_orders,
                permutation_assignment_hash=f"{task.replicate_index:064d}",
            )
        )

    summary = summarize_null_calibration(results, protocol)
    receipt = build_calibration_receipt(
        results,
        determinism_check=_passing_determinism_check(),
        protocol=protocol,
        runtime={"workers": 1},
    )

    assert summary["status"] == "pass"
    assert len(summary["designs"]) == 2
    assert len(summary["scenarios"]) == 8
    assert receipt["assessment"]["powered_null_status"] == summary["status"]
    assert receipt["assessment"]["determinism_check"] == _passing_determinism_check()
    assert receipt["assessment"]["status"] == "pass"
    validate_calibration_receipt(receipt, protocol=protocol)


def test_frequency_correlation_uses_physical_fft_bin_distance() -> None:
    scenario = replace(CALIBRATION_SCENARIOS[1], sensor_smoothing=0.0)
    field = _correlated_standard_field(
        np.random.default_rng(8127),
        participant_count=30_000,
        sensor_count=1,
        selected_frequencies_hz=np.asarray([0.0, 0.025, 1.025]),
        frequency_step_hz=0.025,
        scenario=scenario,
    )[:, 0, :]
    correlation = np.corrcoef(field, rowvar=False)

    assert correlation[0, 1] == pytest.approx(scenario.frequency_correlation, abs=0.02)
    assert abs(correlation[1, 2]) < 0.03


def test_checkpoint_row_must_match_task_metadata_and_seed_streams() -> None:
    task = calibration_tasks()[0]
    data_seed, permutation_seed = task_seeds(task)
    valid = NullCalibrationReplicate(
        task_id=task.task_id,
        design=task.design.value,
        scenario_id=task.scenario_id,
        replicate_index=task.replicate_index,
        data_seed=data_seed,
        permutation_seed=permutation_seed,
        status="complete",
        selected_orders=(1, 2),
        permutation_assignment_hash="a" * 64,
    )

    validate_replicate_for_task(valid, task)
    with pytest.raises(ValueError, match="data_seed"):
        validate_replicate_for_task(replace(valid, data_seed=data_seed + 1), task)


def test_runner_protocol_document_rejects_environment_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_path = tmp_path / "protocol.json"
    calibration_runner._ensure_protocol(protocol_path)
    identity = calibration_runner._execution_identity()
    assert json.loads(protocol_path.read_text(encoding="utf-8"))["execution_identity"] == identity

    monkeypatch.setattr(
        calibration_runner,
        "_execution_identity",
        lambda: {**identity, "numpy": "mismatched-version"},
    )
    with pytest.raises(RuntimeError, match="different calibration protocol"):
        calibration_runner._ensure_protocol(protocol_path)


def test_runner_nonofficial_determinism_check_matches_all_execution_modes() -> None:
    report = calibration_runner._run_determinism_check()

    assert report["status"] == "pass"
    assert report["serial_results_sha256"] == report["resumed_results_sha256"]
    assert report["serial_results_sha256"] == report["parallel_results_sha256"]
    official_ids = {task.task_id for task in calibration_tasks()}
    assert official_ids.isdisjoint(report["task_ids"])


def test_runner_checkpoint_is_atomic_resumable_and_protocol_guarded(tmp_path: Path) -> None:
    protocol_path = tmp_path / "protocol.json"
    checkpoint_path = tmp_path / "results.jsonl"
    first_task, second_task = calibration_tasks()[:2]
    first_data_seed, first_permutation_seed = task_seeds(first_task)
    second_data_seed, second_permutation_seed = task_seeds(second_task)
    first = NullCalibrationReplicate(
        task_id=first_task.task_id,
        design=first_task.design.value,
        scenario_id=first_task.scenario_id,
        replicate_index=first_task.replicate_index,
        data_seed=first_data_seed,
        permutation_seed=first_permutation_seed,
        status="complete",
        selected_orders=(1, 2),
        permutation_assignment_hash="a" * 64,
    )
    second = NullCalibrationReplicate(
        task_id=second_task.task_id,
        design=second_task.design.value,
        scenario_id=second_task.scenario_id,
        replicate_index=second_task.replicate_index,
        data_seed=second_data_seed,
        permutation_seed=second_permutation_seed,
        status="complete",
        selected_orders=(1, 2, 3),
        permutation_assignment_hash="b" * 64,
    )

    calibration_runner._ensure_protocol(protocol_path)
    calibration_runner._ensure_protocol(protocol_path)
    calibration_runner._write_checkpoint(checkpoint_path, {second.task_id: second, first.task_id: first})

    assert calibration_runner._load_checkpoint(checkpoint_path) == {
        first.task_id: first,
        second.task_id: second,
    }
    lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["task_id"] == first.task_id
    assert json.loads(lines[1])["task_id"] == second.task_id

    protocol_path.write_text('{"protocol": "different"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="different calibration protocol"):
        calibration_runner._ensure_protocol(protocol_path)


def test_runner_refuses_an_orphan_checkpoint_before_scheduling(tmp_path: Path) -> None:
    output_dir = tmp_path / "orphaned"
    output_dir.mkdir()
    (output_dir / "results.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Checkpoint exists without its protocol"):
        calibration_runner.run(
            [
                "--output-dir",
                str(output_dir),
                "--max-new-replicates",
                "1",
            ]
        )

    assert not (output_dir / "protocol.json").exists()
