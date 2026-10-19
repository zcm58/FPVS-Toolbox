"""Exercise real worker boundaries with signal doubles and no Qt import."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceMissingError,
    FullFftProvenanceStaleError,
)
from Tools.Free_Harmonic_Clustering.models import FreeHarmonicCancelledError


@pytest.fixture
def worker_functions():
    path = Path(__file__).resolve().parents[2] / "src/Tools/Free_Harmonic_Clustering/gui/workers.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    shell = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_CancellableWorker")
    run = next(node for node in shell.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    run.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *helpers, run,
    ], type_ignores=[])
    namespace = {
        "logger": logging.getLogger("fhc_worker_boundary_test"),
        "perf_counter": perf_counter,
        "FullFftProvenanceMissingError": FullFftProvenanceMissingError,
        "FullFftProvenanceStaleError": FullFftProvenanceStaleError,
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _worker(operation, *, cancelled=False):
    signals = {
        name: SimpleNamespace(emit=Mock())
        for name in ("completed", "failed", "cancelled", "post_processing_required", "finished")
    }
    return SimpleNamespace(_execute=operation, _should_cancel=lambda: cancelled, **signals)


@pytest.mark.parametrize("error", [ValueError("invalid map"), RuntimeError("unexpected renderer fault")])
def test_published_analysis_preview_failure_retains_saved_success(worker_functions, caplog, error):
    def build():
        raise error

    with caplog.at_level(logging.ERROR):
        maps, warning = worker_functions._map_snapshots_after_publish(build, worker_type="PlannedAnalysisWorker")

    assert maps == ()
    assert "were saved" in warning
    record = next(row for row in caplog.records if row.msg == "free_harmonic_map_preview_failed_after_publication")
    assert record.worker == "PlannedAnalysisWorker"
    assert record.exc_info[1] is error


def test_published_analysis_preview_preserves_maps(worker_functions):
    maps = (object(),)
    result, warning = worker_functions._map_snapshots_after_publish(lambda: maps, worker_type="AnalysisWorker")
    assert result is maps
    assert warning == ""


def test_published_analysis_preview_does_not_swallow_process_interrupt(worker_functions):
    def build():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        worker_functions._map_snapshots_after_publish(build, worker_type="AnalysisWorker")


@pytest.mark.parametrize("error", [RuntimeError("backend failed"), TypeError("unexpected backend fault")])
def test_worker_reports_unexpected_failure_and_always_finishes(worker_functions, caplog, error):
    worker = _worker(Mock(side_effect=error))
    with caplog.at_level(logging.ERROR):
        worker_functions.run(worker)

    worker.failed.emit.assert_called_once_with(str(error))
    worker.finished.emit.assert_called_once_with()
    worker.completed.emit.assert_not_called()
    worker.cancelled.emit.assert_not_called()
    worker.post_processing_required.emit.assert_not_called()
    record = next(row for row in caplog.records if row.msg == "free_harmonic_gui_worker_failed")
    assert record.worker == type(worker).__name__
    assert record.exc_info[1] is error


@pytest.mark.parametrize("explicit_cancel", [False, True])
def test_worker_cancellation_finishes_without_failure(worker_functions, explicit_cancel):
    error = RuntimeError("stopped") if explicit_cancel else FreeHarmonicCancelledError("stopped")
    worker = _worker(Mock(side_effect=error), cancelled=explicit_cancel)
    worker_functions.run(worker)
    worker.cancelled.emit.assert_called_once_with()
    worker.finished.emit.assert_called_once_with()
    worker.failed.emit.assert_not_called()
    worker.completed.emit.assert_not_called()


@pytest.mark.parametrize("error_type", [FullFftProvenanceMissingError, FullFftProvenanceStaleError])
def test_worker_preserves_chained_post_processing_remedy(worker_functions, error_type):
    error = ValueError("cannot prepare")
    error.__cause__ = error_type("rebuild provenance")
    worker = _worker(Mock(side_effect=error))
    worker_functions.run(worker)
    worker.post_processing_required.emit.assert_called_once_with(str(error))
    worker.finished.emit.assert_called_once_with()
    worker.failed.emit.assert_not_called()
    worker.cancelled.emit.assert_not_called()


def test_worker_keeps_success_when_cancellation_arrives_after_publication(worker_functions):
    receipt = object()
    worker = _worker(lambda: receipt, cancelled=True)
    worker_functions.run(worker)
    worker.completed.emit.assert_called_once_with(receipt)
    worker.finished.emit.assert_called_once_with()
    worker.failed.emit.assert_not_called()
    worker.cancelled.emit.assert_not_called()
