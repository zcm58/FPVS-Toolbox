"""Exercise output completion with real functions and no Qt imports or event loop."""

from __future__ import annotations

import ast
from collections import deque
import logging
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest

from Main_App.io.result_outputs import result_output_paths, result_output_snapshot


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_functions(relative_path, namespace, *, class_name=None):
    source = REPO_ROOT / relative_path
    tree = ast.parse(source.read_text(encoding="utf-8"))
    owner = tree if class_name is None else next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    functions = [node for node in owner.body if isinstance(node, ast.FunctionDef)]
    for function in functions:
        function.decorator_list = []
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture
def workflows():
    return _load_functions("src/Main_App/gui/post_export_workflows.py", {
        "Path": Path, "logging": logging, "logger": logging.getLogger(__name__),
        "result_output_paths": result_output_paths,
        "result_output_snapshot": result_output_snapshot,
    })


def _host(output_root):
    return SimpleNamespace(
        _run_excel_output_root=str(output_root),
        _run_excel_snapshot_before=result_output_snapshot(output_root),
        _run_had_successful_export=False, _last_job_success=False,
        save_folder_path=SimpleNamespace(get=lambda: str(output_root)),
        gui_queue=Queue(), log=Mock(), _post_backlog=deque(),
    )


def test_output_snapshot_counts_anchors_and_ignores_companions_and_temporary_files(tmp_path):
    accepted = ["P01.fpvs", "P02.FPVS", "P03.xlsx", "P04.XLSX", "P05.xlsm"]
    ignored = ["._P06.fpvs", "~$P07.fpvs", "._P08.xlsx", "~$P09.xlsx",
               "P10.spectra.npz", "P10.metrics.npz", ".P10.tmp", "P11.fpvs.tmp"]
    nested = tmp_path / "Condition"
    nested.mkdir()
    for name in accepted + ignored:
        (nested / name).write_bytes(b"published or temporary test data")
    (nested / "directory.fpvs").mkdir()
    assert {path.name for path in result_output_paths(tmp_path)} == set(accepted)
    assert {Path(path).name for path in result_output_snapshot(tmp_path)} == set(accepted)


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx", ".FPVS", ".XLSX"])
@pytest.mark.parametrize("overwrite", [False, True])
def test_current_run_detects_new_and_overwritten_native_or_legacy_anchors(
    tmp_path, workflows, suffix, overwrite,
):
    anchor = tmp_path / f"P01{suffix}"
    if overwrite:
        anchor.write_bytes(b"old")
    host = _host(tmp_path)
    anchor.write_bytes(b"new result data of a different size")
    workflows.refresh_run_excel_success_from_disk(host)
    assert host._last_job_success is True
    assert host._run_had_successful_export is True


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_old_unchanged_outputs_do_not_count_as_current_run_writes(tmp_path, workflows, suffix):
    (tmp_path / f"P01{suffix}").write_bytes(b"old")
    host = _host(tmp_path)
    workflows.refresh_run_excel_success_from_disk(host)
    assert host._last_job_success is False


def test_orphan_companions_do_not_mask_a_run_with_no_outputs(tmp_path, workflows):
    host = _host(tmp_path)
    (tmp_path / "P01.spectra.npz").write_bytes(b"incomplete export")
    workflows.refresh_run_excel_success_from_disk(host)
    assert host._last_job_success is False
    assert workflows.should_show_no_excel_popup([], tmp_path) is True


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_wrapper_native_or_legacy_write_and_later_no_output_preserves_success(
    tmp_path, workflows, suffix,
):
    host = _host(tmp_path)
    workflows.export_with_post_process(
        host, ["Faces"], lambda _host, _labels: (tmp_path / f"P01{suffix}").write_bytes(b"data"),
    )
    assert host._last_job_success is True
    workflows.export_with_post_process(
        host, ["Objects"],
        lambda app, _labels: app.log("Warning: Post-processing completed, but no result files were saved."),
    )
    assert host._last_job_success is True


@pytest.mark.parametrize("no_output_word", ["result", "Excel"])
@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_explicit_no_output_warning_cannot_reuse_old_files_as_success(
    tmp_path, workflows, no_output_word, suffix,
):
    (tmp_path / f"P01{suffix}").write_bytes(b"old")
    host = _host(tmp_path)
    workflows.export_with_post_process(
        host, ["Faces"],
        lambda app, _labels: app.log(
            f"Warning: Post-processing completed, but no {no_output_word} files were saved."
        ),
    )
    assert host._last_job_success is False


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_wrapper_export_exception_does_not_promote_old_outputs(tmp_path, workflows, suffix):
    (tmp_path / f"P01{suffix}").write_bytes(b"old")
    host = _host(tmp_path)

    def fail_export(_host, _labels):
        raise ValueError("write failed")

    workflows.export_with_post_process(host, ["Faces"], fail_export)
    assert host._last_job_success is False
    assert host.gui_queue.get_nowait() == {"type": "error", "message": "write failed"}


@pytest.mark.parametrize("suffix", [".fpvs", ".xlsx"])
def test_worker_reports_both_formats_through_compatible_payload(tmp_path, suffix):
    anchor = tmp_path / f"P01{suffix}"
    worker_functions = _load_functions(
        "src/Main_App/workers/processing_worker.py", {
            "Path": Path, "SimpleNamespace": SimpleNamespace, "time": time,
            "logger": logging.getLogger(__name__), "LegacyCtx": SimpleNamespace,
            "result_output_snapshot": result_output_snapshot,
            "run_post_export": lambda _ctx, _labels: anchor.write_bytes(b"result data"),
        }, class_name="PostProcessWorker",
    )
    worker = SimpleNamespace(
        _cancelled=False, _file="P01.bdf", _epochs={}, _labels=["Faces"],
        _save_folder=tmp_path, _data_paths=["P01.bdf"], _settings={}, _log=Mock(),
        progress=SimpleNamespace(emit=Mock()), finished=SimpleNamespace(emit=Mock()),
        error=SimpleNamespace(emit=Mock()),
    )
    worker_functions.run(worker)
    worker.error.emit.assert_not_called()
    payload = worker.finished.emit.call_args.args[0]
    assert payload["generated_excel_paths"] == [str(anchor.resolve())]
    assert payload["existing_excel_paths"] == [str(anchor.resolve())]


