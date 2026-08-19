from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Tools.Free_Harmonic_Clustering import __main__ as cli
from Tools.Free_Harmonic_Clustering.api import (
    FreeHarmonicRun,
    RepeatedSessionBatchRun,
)
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicInputError,
    NoHarmonicsSelectedError,
)


def _prepared(request: object) -> SimpleNamespace:
    return SimpleNamespace(
        request=request,
        arm_a_label="arm a",
        arm_b_label="arm b",
        participant_ids_a=("P1", "P2"),
        participant_ids_b=("P3", "P4"),
        sensor_names=("Fp1", "Fp2"),
        harmonics_hz=(1.2, 2.4),
    )


def test_independent_cli_builds_ordered_group_request_and_prepare_only_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run(request: object, method: object, **kwargs: object) -> FreeHarmonicRun:
        captured.update(request=request, method=method, kwargs=kwargs)
        return FreeHarmonicRun(
            prepared=_prepared(request),
            result=None,
            receipt=None,
        )

    monkeypatch.setattr(cli, "run_free_harmonic_clustering", fake_run)
    destination = tmp_path / "project" / "would-not-be-written"

    exit_code = cli.main(
        [
            "independent",
            "--project-root",
            str(tmp_path / "project"),
            "--condition",
            "Neutral Angry",
            "--group-a",
            "anxious",
            "--group-b",
            "non_anxious",
            "--prepare-only",
            "--destination",
            str(destination),
            "--n-permutations",
            "99",
            "--seed",
            "8",
            "--oddball-frequency-hz",
            "1.5",
            "--base-frequency-hz",
            "7.5",
            "--max-harmonic-hz",
            "45",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.design is AnalysisDesign.INDEPENDENT_GROUPS
    assert request.condition_a == "Neutral Angry"
    assert request.group_ids == ("anxious", "non_anxious")
    assert captured["method"].n_permutations == 99
    assert captured["method"].seed == 8
    assert captured["method"].oddball_frequency_hz == 1.5
    assert captured["method"].base_frequency_hz == 7.5
    assert captured["method"].max_harmonic_hz == 45.0
    assert captured["kwargs"]["prepare_only"] is True
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "prepared"
    assert summary["write_performed"] is False
    assert summary["familywise_error_control"] == "weak-FWER"
    assert not destination.exists()


def test_paired_cli_builds_condition_request_with_optional_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "project" / "results" / "paired-run"
    manifest = output / "manifest.json"

    def fake_run(request: object, method: object, **kwargs: object) -> FreeHarmonicRun:
        captured.update(request=request, method=method, kwargs=kwargs)
        receipt = SimpleNamespace(output_directory=output, manifest_path=manifest)
        return FreeHarmonicRun(
            prepared=_prepared(request),
            result=object(),
            receipt=receipt,
        )

    monkeypatch.setattr(cli, "run_free_harmonic_clustering", fake_run)

    exit_code = cli.main(
        [
            "paired",
            "--project-root",
            str(tmp_path / "project"),
            "--condition-a",
            "Positive Valence",
            "--condition-b",
            "Negative Valence",
            "--group",
            "anxious",
            "--run-id",
            "paired-run",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.design is AnalysisDesign.PAIRED_CONDITIONS
    assert request.condition_a == "Positive Valence"
    assert request.condition_b == "Negative Valence"
    assert request.group_ids == ("anxious",)
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "complete"
    assert summary["output_directory"] == str(output)


def test_repeated_session_cli_builds_ordered_batch_and_recording_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        request: object,
        method: object,
        **kwargs: object,
    ) -> RepeatedSessionBatchRun:
        captured.update(request=request, method=method, kwargs=kwargs)
        prepared = SimpleNamespace(
            request=request,
            conditions=request.conditions,
            contrast_runs=(object(),) * (len(request.conditions) * 4),
            shared_selection=SimpleNamespace(selected_harmonics_hz=(1.2, 2.4)),
            shared_domain_fingerprint="shared-sha",
        )
        return RepeatedSessionBatchRun(
            prepared=prepared,
            result=None,
            receipt=None,
        )

    monkeypatch.setattr(cli, "run_repeated_session_fhc_batch", fake_run)

    exit_code = cli.main(
        [
            "repeated-session",
            "--project-root",
            str(tmp_path / "project"),
            "--condition",
            "Neutral Angry",
            "--condition",
            "Angry Control",
            "--group-a",
            "bc_group",
            "--group-b",
            "control_group",
            "--session-a",
            "follicular_phase",
            "--session-b",
            "luteal_phase",
            "--exclude-recording",
            "P18_BC_F=Declared outlier",
            "--prepare-only",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.conditions == ("Neutral Angry", "Angry Control")
    assert request.group_ids == ("bc_group", "control_group")
    assert request.session_ids == ("follicular_phase", "luteal_phase")
    assert request.recording_exclusions[0].recording_id == "P18_BC_F"
    assert request.recording_exclusions[0].reason == "Declared outlier"
    summary = json.loads(capsys.readouterr().out)
    assert summary["analysis_kind"] == "repeated_session_batch"
    assert summary["contrast_run_count"] == 8
    assert summary["write_performed"] is False


def test_cli_returns_nonzero_and_writes_error_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise FreeHarmonicInputError("synthetic input failure")

    monkeypatch.setattr(cli, "run_free_harmonic_clustering", fail)

    exit_code = cli.main(
        [
            "paired",
            "--project-root",
            str(tmp_path / "project"),
            "--condition-a",
            "A",
            "--condition-b",
            "B",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "synthetic input failure" in captured.err


def test_cli_emits_structured_no_harmonics_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise NoHarmonicsSelectedError(
            candidate_orders=[1, 2, 3],
            candidate_harmonics_hz=[1.2, 2.4, 3.6],
            arm_a_z=[1.0, 2.0, 1.5],
            arm_b_z=[3.0, 2.5, 2.0],
            z_threshold=3.29,
        )

    monkeypatch.setattr(cli, "run_free_harmonic_clustering", fail)

    exit_code = cli.main(
        [
            "paired",
            "--project-root",
            str(tmp_path / "project"),
            "--condition-a",
            "A",
            "--condition-b",
            "B",
            "--prepare-only",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    diagnostic = json.loads(captured.err)
    assert diagnostic == {
        "code": "NO_HARMONICS_SELECTED",
        "threshold": 3.29,
        "arm_a_max": {"z": 2.0, "harmonic_order": 2, "harmonic_hz": 2.4},
        "arm_b_max": {"z": 3.0, "harmonic_order": 1, "harmonic_hz": 1.2},
    }
