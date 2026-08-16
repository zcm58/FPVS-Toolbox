from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceMissingError,
    FullFftProvenanceStaleError,
)
from Tools.Free_Harmonic_Clustering import api
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    ProjectContrastRequest,
)
from Tools.Free_Harmonic_Clustering.preparation import (
    build_available_frequency_window_plan,
)


@pytest.mark.parametrize(
    ("module_name", "expected_reader_names"),
    [
        ("api.py", {"read_xlsx_sheet_header"}),
        (
            "inputs.py",
            {"read_xlsx_sheet_header", "read_xlsx_sheet_selected_columns"},
        ),
    ],
)
def test_headless_xlsx_inputs_use_shared_main_app_io(
    module_name: str,
    expected_reader_names: set[str],
) -> None:
    module_path = Path(api.__file__).with_name(module_name)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    main_app_reader_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "Main_App.io"
        for alias in node.names
    }
    stats_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("Tools.Stats")
    }

    assert expected_reader_names <= main_app_reader_names
    assert stats_imports == set()


def test_fhc_provenance_import_does_not_load_beta_stats_package() -> None:
    src_root = Path(api.__file__).parents[2]
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(src_root)!r}); "
        "import Tools.Free_Harmonic_Clustering.api; "
        "import Main_App.processing.full_fft_provenance; "
        "loaded = sorted(name for name in sys.modules "
        "if name == 'Tools.Stats' or name.startswith('Tools.Stats.')); "
        "print('\\n'.join(loaded))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""


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
    workbook_b.write_bytes(b"active representative")
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest={},
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

    import Main_App.io
    import Main_App.projects
    import Main_App.processing.full_fft_provenance

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
        Main_App.io,
        "read_xlsx_sheet_header",
        fake_header,
    )
    expected_grid = build_available_frequency_window_plan(
        header,
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
        noise_half_width_hz=0.1,
    ).grid_fingerprint
    monkeypatch.setattr(
        Main_App.processing.full_fft_provenance,
        "validate_project_full_fft_provenance",
        lambda *args, **kwargs: SimpleNamespace(
            grid_fingerprint=expected_grid,
            # The first dataset-index workbook may be excluded by the neutral
            # cohort. Inspection must choose from validated active provenance.
            source_paths=(workbook_b.name,),
            source_workbook_count=1,
        ),
    )
    before = {path.relative_to(project_root) for path in project_root.rglob("*")}

    options = api.inspect_project_analysis_options(
        project_root,
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
    )

    after = {path.relative_to(project_root) for path in project_root.rglob("*")}
    assert header_calls == [workbook_b]
    assert options.workbook_count == 1
    assert options.conditions == ("Neutral Happy", "Neutral Fear")
    assert options.groups == ()
    assert options.grid_compatible is True
    assert options.grid_compatibility_verified is False
    assert "selected cohort" in options.compatibility_message
    assert "FullFFT provenance matched" in options.compatibility_message
    assert options.eligible_orders == (1, 2, 3, 4, 6)
    assert options.eligible_harmonics_hz == pytest.approx(
        (1.2, 2.4, 3.6, 4.8, 7.2)
    )
    assert options.excluded_base_orders == (5,)
    assert options.fft_upper_frequency_hz == pytest.approx(7.3)
    assert before == after


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            FullFftProvenanceMissingError(
                "Neutral FullFFT provenance is missing. Rerun post-processing; "
                "EEG preprocessing is not required."
            ),
            "provenance is missing",
        ),
        (
            FullFftProvenanceStaleError(
                "Neutral FullFFT provenance is stale because the workbook changed."
            ),
            "provenance is stale",
        ),
    ],
)
def test_project_options_surface_neutral_provenance_failures_before_header_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: str,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest={},
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.io
    import Main_App.projects
    import Main_App.processing.full_fft_provenance

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )
    monkeypatch.setattr(
        Main_App.io,
        "read_xlsx_sheet_header",
        lambda *args, **kwargs: pytest.fail(
            "rate mismatch must block before the workbook header is opened"
        ),
    )
    monkeypatch.setattr(
        Main_App.processing.full_fft_provenance,
        "validate_project_full_fft_provenance",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(FreeHarmonicInputError, match=expected):
        api.inspect_project_analysis_options(
            project_root,
            oddball_frequency_hz=1.2,
            base_frequency_hz=6.0,
        )

def test_project_options_ignore_stats_harmonic_cache_when_neutral_record_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    workbook = project_root / "condition-a.xlsx"
    workbook.write_bytes(b"representative")
    conflicting_stats_cache = {
        "tools": {
            "stats": {
                "group_significant_harmonics_cache": {
                    "entries": {
                        "old": {
                            "fingerprint": {
                                "stats_settings": {
                                    "base_frequency_hz": 5.0,
                                    "oddball_frequency_hz": 1.0,
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    dataset = SimpleNamespace(
        project_root=project_root,
        manifest=conflicting_stats_cache,
        workbooks=(SimpleNamespace(path=workbook),),
        conditions=("Condition A",),
        ordered_groups=(),
        diagnostics=(),
    )

    import Main_App.io
    import Main_App.projects
    import Main_App.processing.full_fft_provenance

    monkeypatch.setattr(
        Main_App.projects,
        "load_project_dataset_index",
        lambda _root: dataset,
    )
    frequencies = np.arange(293, dtype=np.float64) * 0.025
    header = ["Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies)]
    expected_grid = build_available_frequency_window_plan(
        header,
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
        noise_half_width_hz=0.1,
    ).grid_fingerprint
    monkeypatch.setattr(
        Main_App.processing.full_fft_provenance,
        "validate_project_full_fft_provenance",
        lambda *args, **kwargs: SimpleNamespace(
            grid_fingerprint=expected_grid,
            source_paths=(workbook.name,),
            source_workbook_count=1,
        ),
    )
    monkeypatch.setattr(
        Main_App.io,
        "read_xlsx_sheet_header",
        lambda *args, **kwargs: header,
    )

    options = api.inspect_project_analysis_options(
        project_root,
        oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
    )

    assert options.grid_compatible is True
