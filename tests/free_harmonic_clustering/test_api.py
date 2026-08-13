from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering import api
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicInputError,
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


def _frequency_cache_entry(
    project_root: Path,
    workbook: Path,
    *,
    base_hz: float = 6.0,
    oddball_hz: float = 1.2,
    selection_base_hz: float | None = 6.0,
    selection_oddball_hz: float | None = 1.2,
    source_path: str | None = None,
    source_size: int | None = None,
    source_mtime_ns: int | None = None,
) -> dict[str, object]:
    stat = workbook.stat()
    selection: dict[str, object] = {}
    if selection_base_hz is not None:
        selection["base_frequency_hz"] = selection_base_hz
    if selection_oddball_hz is not None:
        selection["oddball_frequency_hz"] = selection_oddball_hz
    return {
        "fingerprint": {
            "stats_settings": {
                "base_frequency_hz": base_hz,
                "oddball_frequency_hz": oddball_hz,
            },
            "source_workbooks": [
                {
                    "path": source_path
                    or workbook.relative_to(project_root).as_posix(),
                    "size_bytes": stat.st_size
                    if source_size is None
                    else source_size,
                    "mtime_ns": stat.st_mtime_ns
                    if source_mtime_ns is None
                    else source_mtime_ns,
                }
            ],
        },
        "selection_metadata": selection,
    }


def _frequency_manifest(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "tools": {
            "stats": {
                "group_significant_harmonics_cache": {
                    "entries": {
                        f"entry-{index}": entry
                        for index, entry in enumerate(entries)
                    }
                }
            }
        }
    }


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


def test_project_options_use_one_header_and_allow_ungrouped_paired_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook_a = project_root / "condition-a.xlsx"
    workbook_b = project_root / "condition-b.xlsx"
    workbook_a.write_bytes(b"representative")
    workbook_b.write_bytes(b"must not be opened")
    manifest = _frequency_manifest(
        _frequency_cache_entry(project_root, workbook_a)
    )
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=manifest,
        workbooks=(
            SimpleNamespace(path=workbook_a),
            SimpleNamespace(path=workbook_b),
        ),
        conditions=("Neutral Happy", "Neutral Fear"),
        ordered_groups=(),
        diagnostics=(),
    )
    header_calls: list[Path] = []
    frequencies = np.arange(293, dtype=np.float64) * 0.025
    header = [
        "Electrode",
        *(f"{frequency:.6f}_Hz" for frequency in frequencies),
    ]

    import Main_App.projects
    import Tools.Stats.io.xlsx_selected_reader

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )

    def fake_header(path: Path, *, sheet_name: str) -> list[str]:
        header_calls.append(path)
        assert sheet_name == "FullFFT Amplitude (uV)"
        return header

    monkeypatch.setattr(
        Tools.Stats.io.xlsx_selected_reader,
        "read_xlsx_sheet_header",
        fake_header,
    )
    before = {path.relative_to(project_root) for path in project_root.rglob("*")}

    options = api.inspect_project_analysis_options(
        project_root,
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
    )

    after = {path.relative_to(project_root) for path in project_root.rglob("*")}
    assert header_calls == [workbook_a]
    assert options.conditions == ("Neutral Happy", "Neutral Fear")
    assert options.groups == ()
    assert options.grid_compatible is True
    assert options.grid_compatibility_verified is False
    assert "selected cohort" in options.compatibility_message
    assert "frequency provenance matched" in options.compatibility_message
    assert options.eligible_orders == (1, 2, 3, 4, 6)
    assert options.eligible_harmonics_hz == pytest.approx(
        (1.2, 2.4, 3.6, 4.8, 7.2)
    )
    assert options.excluded_base_orders == (5,)
    assert options.fft_upper_frequency_hz == pytest.approx(7.3)
    assert before == after


def test_project_options_reject_current_rates_that_differ_from_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=_frequency_manifest(
            _frequency_cache_entry(project_root, workbook)
        ),
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.projects
    import Tools.Stats.io.xlsx_selected_reader

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )
    monkeypatch.setattr(
        Tools.Stats.io.xlsx_selected_reader,
        "read_xlsx_sheet_header",
        lambda *args, **kwargs: pytest.fail(
            "rate mismatch must block before the workbook header is opened"
        ),
    )

    with pytest.raises(
        FreeHarmonicInputError,
        match="do not match the processed-project provenance",
    ) as captured:
        api.inspect_project_analysis_options(
            project_root,
            oddball_frequency_hz=1.2,
            base_frequency_hz=7.5,
        )

    assert "processed base=6 Hz" in str(captured.value)
    assert "Restore the rates" in str(captured.value)


def test_project_options_reject_conflicting_frequency_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=_frequency_manifest(
            _frequency_cache_entry(project_root, workbook),
            _frequency_cache_entry(
                project_root,
                workbook,
                base_hz=5.0,
                selection_base_hz=5.0,
            ),
        ),
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.projects

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )

    with pytest.raises(
        FreeHarmonicInputError,
        match="Conflicting processed-project frequency rates",
    ):
        api.inspect_project_analysis_options(
            project_root,
            oddball_frequency_hz=1.2,
            base_frequency_hz=6.0,
        )


def test_project_options_reject_selection_metadata_rate_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=_frequency_manifest(
            _frequency_cache_entry(
                project_root,
                workbook,
                selection_oddball_hz=1.0,
            )
        ),
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.projects

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )

    with pytest.raises(
        FreeHarmonicInputError,
        match="selection_metadata oddball_frequency_hz=1 conflicts",
    ):
        api.inspect_project_analysis_options(
            project_root,
            oddball_frequency_hz=1.2,
            base_frequency_hz=6.0,
        )


@pytest.mark.parametrize("missing_kind", ["empty", "different_path", "stale"])
def test_project_options_conservatively_reject_missing_matching_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_kind: str,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    if missing_kind == "empty":
        manifest = _frequency_manifest()
        expected = "No matching processed-project"
    elif missing_kind == "different_path":
        manifest = _frequency_manifest(
            _frequency_cache_entry(
                project_root,
                workbook,
                source_path="different.xlsx",
            )
        )
        expected = "No cache entry contains"
    else:
        manifest = _frequency_manifest(
            _frequency_cache_entry(
                project_root,
                workbook,
                source_size=workbook.stat().st_size + 1,
            )
        )
        expected = "size or modification time is stale"
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=manifest,
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.projects

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )

    with pytest.raises(FreeHarmonicInputError, match=expected) as captured:
        api.inspect_project_analysis_options(
            project_root,
            oddball_frequency_hz=1.2,
            base_frequency_hz=6.0,
        )

    assert "regenerate the post-processing/Stats frequency provenance" in str(
        captured.value
    )
