from __future__ import annotations

from pathlib import Path

import pytest

import Main_App.processing.project_processing_cache as cache_module
from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    classify_processing_inputs,
    ledger_path,
    record_processing_results,
    runs_path,
)
from Main_App.processing.project_processing_cache import (
    clear_project_processing_cache,
    inspect_project_processing_cache,
    preprocessed_cache_directory,
)
from Main_App.projects.project import Project


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_clear_project_processing_cache_removes_only_cold_run_state(
    tmp_path: Path,
) -> None:
    preprocessed_files = (
        _write(preprocessed_cache_directory(tmp_path) / "P01_raw.fif", b"raw-cache"),
        _write(preprocessed_cache_directory(tmp_path) / "P01.json", b"metadata"),
    )
    preflight_files = (
        _write(preflight_qc_cache_directory(tmp_path) / "one.json", b"qc-one"),
        _write(
            preflight_qc_cache_directory(tmp_path) / "nested" / "two.tmp",
            b"qc-two",
        ),
    )
    ledger = _write(ledger_path(tmp_path), b'{"entries":{"P01":{}}}')
    ledger_temporary = _write(ledger.with_suffix(".json.tmp"), b"partial-ledger")

    preserved_paths = (
        _write(tmp_path / "project.json", b'{"name":"Valence"}'),
        _write(tmp_path / "Raw Data" / "P01.bdf", b"bdf-data"),
        _write(
            tmp_path / "1 - Excel Data Files" / "Condition" / "P01_Results.xlsx",
            b"processed-output",
        ),
        _write(runs_path(tmp_path), b'{"run":"historical"}\n'),
        _write(
            tmp_path / ".fpvs_processing" / "preflight_qc" / "v3" / "future.json",
            b"future-cache-version",
        ),
        _write(
            tmp_path / ".fpvs_cache" / "mne" / "MNE-fsaverage-data" / "marker",
            b"local-dependency-cache",
        ),
        _write(
            tmp_path / "Quality Check" / "Data_Quality_Check_Review_Flags.xlsx",
            b"review-decisions",
        ),
    )
    preserved_payloads = {path: path.read_bytes() for path in preserved_paths}
    removable_paths = (*preprocessed_files, *preflight_files, ledger, ledger_temporary)

    usage = inspect_project_processing_cache(tmp_path)

    assert usage.file_count == len(removable_paths)
    assert usage.total_bytes == sum(path.stat().st_size for path in removable_paths)
    assert usage.targets == (
        "preprocessed Raw cache",
        "preflight QC cache",
        "processing ledger temporary file",
        "processing ledger",
    )

    removed = clear_project_processing_cache(tmp_path)

    assert removed == usage
    assert not preprocessed_cache_directory(tmp_path).exists()
    assert not preflight_qc_cache_directory(tmp_path).exists()
    assert not ledger.exists()
    assert not ledger_temporary.exists()
    assert {path: path.read_bytes() for path in preserved_paths} == preserved_payloads
    assert inspect_project_processing_cache(tmp_path).is_empty


def test_clear_project_processing_cache_is_repeatable_without_creating_state(
    tmp_path: Path,
) -> None:
    assert inspect_project_processing_cache(tmp_path).is_empty
    assert clear_project_processing_cache(tmp_path).is_empty
    assert clear_project_processing_cache(tmp_path).is_empty
    assert not (tmp_path / ".fpvs_cache").exists()
    assert not (tmp_path / ".fpvs_processing").exists()


def test_cache_reset_makes_completed_inputs_new_without_removing_outputs_or_history(
    tmp_path: Path,
) -> None:
    project = Project.load(tmp_path / "project")
    raw_file = _write(tmp_path / "raw" / "P01.bdf", b"raw")
    info = RawFileInfo(raw_file.resolve(), "P01")
    project.input_folder = raw_file.parent
    project.event_map = {"Condition A": 1}
    project.save()
    settings = {
        "high_pass": 0.1,
        "low_pass": 50.0,
        "downsample": 256,
        "epoch_start": -1.0,
        "epoch_end": 125.0,
    }
    initial = classify_processing_inputs(
        project,
        [info],
        settings,
        project.event_map,
    )
    for output in initial.states[0].expected_outputs:
        _write(output, b"existing-output")
    record_processing_results(
        project,
        initial,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    completed = classify_processing_inputs(
        project,
        [info],
        settings,
        project.event_map,
    )
    assert completed.states[0].status == "completed"
    output_payloads = {
        output: output.read_bytes() for output in initial.states[0].expected_outputs
    }
    history = runs_path(project.project_root).read_bytes()
    _write(preprocessed_cache_directory(project.project_root) / "P01_raw.fif", b"fif")
    _write(preflight_qc_cache_directory(project.project_root) / "P01.json", b"qc")

    clear_project_processing_cache(project.project_root)

    cold = classify_processing_inputs(
        project,
        [info],
        settings,
        project.event_map,
    )
    assert cold.states[0].status == "new"
    assert cold.incremental_files == (info.path,)
    assert {output: output.read_bytes() for output in output_payloads} == output_payloads
    assert runs_path(project.project_root).read_bytes() == history


@pytest.mark.parametrize(
    "operation",
    [inspect_project_processing_cache, clear_project_processing_cache],
)
def test_project_processing_cache_requires_an_absolute_project_root(operation) -> None:
    with pytest.raises(ValueError, match="absolute path"):
        operation(Path("relative-project"))


def test_cache_directory_failure_preserves_incremental_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preprocessed = preprocessed_cache_directory(tmp_path)
    _write(preprocessed / "P01_raw.fif", b"locked")
    preflight = _write(
        preflight_qc_cache_directory(tmp_path) / "one.json",
        b"preflight",
    )
    ledger = _write(ledger_path(tmp_path), b'{"entries":{"P01":{}}}')
    real_rmtree = cache_module.shutil.rmtree

    def fail_preprocessed_cache(path: Path) -> None:
        if Path(path) == preprocessed:
            raise PermissionError("simulated locked cache")
        real_rmtree(path)

    monkeypatch.setattr(cache_module.shutil, "rmtree", fail_preprocessed_cache)

    with pytest.raises(PermissionError, match="simulated locked cache"):
        clear_project_processing_cache(tmp_path)

    assert preprocessed.exists()
    assert preflight.exists()
    assert ledger.exists()


def test_dangling_cache_link_is_not_silently_reported_empty(tmp_path: Path) -> None:
    preprocessed = preprocessed_cache_directory(tmp_path)
    preprocessed.parent.mkdir(parents=True)
    try:
        preprocessed.symlink_to(tmp_path / "missing-cache-target", target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links unavailable in this environment: {exc}")

    usage = inspect_project_processing_cache(tmp_path)

    assert not usage.is_empty
    assert usage.targets == ("preprocessed Raw cache",)
    with pytest.raises(OSError, match="redirected cache target"):
        clear_project_processing_cache(tmp_path)
    assert preprocessed.is_symlink()
