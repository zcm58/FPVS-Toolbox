from __future__ import annotations

from pathlib import Path

import pytest

from Tools.Free_Harmonic_Clustering import api
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicMethodSpec,
    ProjectContrastRequest,
)


def _request(tmp_path: Path) -> ProjectContrastRequest:
    return ProjectContrastRequest(
        project_root=tmp_path / "project",
        design=AnalysisDesign.INDEPENDENT_GROUPS,
        condition_a="Neutral Angry",
        group_ids=("anxious", "non_anxious"),
    )


def test_prepare_only_is_strict_no_analysis_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    prepared = object()
    calls: list[tuple[str, object]] = []

    def fake_prepare(request_arg: object, spec_arg: object, **kwargs: object) -> object:
        calls.append(("prepare", (request_arg, spec_arg, kwargs)))
        return prepared

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("prepare-only must not analyze or export")

    monkeypatch.setattr(api, "prepare_project_contrast", fake_prepare)
    monkeypatch.setattr(api, "analyze_prepared_contrast", forbidden)
    monkeypatch.setattr(api, "export_free_harmonic_run", forbidden)
    destination = tmp_path / "outside" / "ignored-run"

    run = api.run_free_harmonic_clustering(
        request,
        prepare_only=True,
        run_id="ignored-run",
        destination=destination,
    )

    assert run.prepared is prepared
    assert run.result is None
    assert run.receipt is None
    assert run.prepare_only is True
    assert [name for name, _ in calls] == ["prepare"]
    assert not destination.exists()


def test_full_run_prepares_analyzes_then_exports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    method = FreeHarmonicMethodSpec(n_permutations=11, seed=4)
    prepared = object()
    result = object()
    receipt = object()
    calls: list[tuple[str, object]] = []

    def progress(complete: int, total: int) -> None:
        return None

    def cancel() -> bool:
        return False

    def fake_prepare(request_arg: object, spec_arg: object, **kwargs: object) -> object:
        calls.append(("prepare", (request_arg, spec_arg, kwargs)))
        return prepared

    def fake_analyze(prepared_arg: object, **kwargs: object) -> object:
        calls.append(("analyze", (prepared_arg, kwargs)))
        return result

    def fake_export(prepared_arg: object, result_arg: object, **kwargs: object) -> object:
        calls.append(("export", (prepared_arg, result_arg, kwargs)))
        return receipt

    monkeypatch.setattr(api, "prepare_project_contrast", fake_prepare)
    monkeypatch.setattr(api, "analyze_prepared_contrast", fake_analyze)
    monkeypatch.setattr(api, "export_free_harmonic_run", fake_export)

    run = api.run_free_harmonic_clustering(
        request,
        method,
        run_id="run-002",
        destination=Path("relative/output/run-002"),
        batch_size=17,
        progress_callback=progress,
        cancel_check=cancel,
    )

    assert run.prepared is prepared
    assert run.result is result
    assert run.receipt is receipt
    assert run.prepare_only is False
    assert [name for name, _ in calls] == ["prepare", "analyze", "export"]
    prepare_kwargs = calls[0][1][2]
    assert prepare_kwargs == {"progress_callback": progress, "cancel_check": cancel}
    analyze_kwargs = calls[1][1][1]
    assert analyze_kwargs == {
        "batch_size": 17,
        "progress": progress,
        "cancel_check": cancel,
    }
    export_kwargs = calls[2][1][2]
    assert export_kwargs == {
        "run_id": "run-002",
        "destination": Path("relative/output/run-002"),
    }


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_run_rejects_invalid_batch_size_before_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    batch_size: object,
) -> None:
    monkeypatch.setattr(
        api,
        "prepare_project_contrast",
        lambda *args, **kwargs: pytest.fail("preparation should not run"),
    )

    with pytest.raises(ValueError, match="batch_size"):
        api.run_free_harmonic_clustering(
            _request(tmp_path),
            batch_size=batch_size,
        )
