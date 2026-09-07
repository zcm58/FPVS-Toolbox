"""Execute QC orchestration with inert UI doubles; never import or run Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


WORKFLOW = Path(__file__).resolve().parents[2] / "src/Main_App/gui/preprocessing_qc_workflow.py"


@pytest.mark.parametrize("stop", [None, "markers", "conditions", "electrodes", "kurtosis", "other", "exception"])
def test_prefetch_starts_with_step_two_and_finishes_on_every_review_exit(tmp_path, stop):
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    workflow = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_preprocessing_qc_workflow")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), workflow], type_ignores=[])
    trace = []
    scan = SimpleNamespace(cancelled=False)
    prefetch = SimpleNamespace(source_prefetch=object())
    params = {"event_id_map": {"Faces": 1}, "reject_thresh": 5}
    infos = [SimpleNamespace(path=tmp_path / "source.bdf")]

    def initial_scan(*_args, **_kwargs):
        trace.append("scan")
        return scan

    def start(*_args):
        trace.append("prefetch")
        return prefetch

    def markers(*_args):
        trace.append("markers")
        if stop == "exception":
            raise ValueError("review failed")
        return None if stop == "markers" else scan

    def kurtosis(_host, _infos, current_params, **kwargs):
        trace.append("kurtosis")
        assert current_params is params
        assert kwargs["source_prefetch"] is prefetch.source_prefetch
        return None if stop == "kurtosis" else scan

    def finish(_host, current):
        assert current is prefetch
        trace.append("finish")

    def accept(stage):
        def review(*_args, **kwargs):
            if stage == "other":
                assert kwargs["signal_params"] is params
            trace.append(stage)
            return stop != stage
        return review

    namespace = {
        "Mapping": dict, "Sequence": (list, tuple), "Path": Path,
        "_DATA_QUALITY_SCAN_WAIT_MESSAGE": "Scanning",
        "_project_group_labels": lambda *_a: {},
        "_show_data_quality_notice": lambda *_a: None,
        "_begin_preflight_page": lambda *_a, **_k: None,
        "_set_label": lambda *_a: None,
        "scan_recording_not_started_files": lambda *_a: [],
        "_path_strings": lambda *_a: [], "_path_key": str,
        "_condition_review_scan_identity": lambda *_a: "unchanged",
        "_run_scan_embedded": initial_scan,
        "_start_qc_source_prefetch": start,
        "_finish_qc_source_prefetch": finish,
        "_review_marker_occurrences": markers,
        "_confirm_condition_crop_exclusions": accept("conditions"),
        "_review_removed_electrodes": accept("electrodes"),
        "_confirm_hard_exclusions": lambda *_a: set(),
        "canonical_event_plans_by_file": lambda *_a: {},
        "_raw_channel_qc_by_recording": lambda *_a: {},
        "_run_kurtosis_review_scan_embedded": kurtosis,
        "_review_kurtosis_findings": lambda *_a: True,
        "_show_suspicious_remainder": accept("other"),
        "MarkerOccurrenceReviewError": ValueError,
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    if stop == "exception":
        with pytest.raises(ValueError, match="review failed"):
            namespace["run_preprocessing_qc_workflow"](object(), infos, params)
    else:
        assert namespace["run_preprocessing_qc_workflow"](object(), infos, params) is (stop is None)
    assert trace[:3] == ["scan", "prefetch", "markers"]
    assert trace[-1] == "finish"
    assert trace.count("prefetch") == trace.count("finish") == 1


def test_gui_worker_and_embedded_scan_forward_run_owned_prefetch():
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    expected = {
        "_KurtosisReviewWorker": "scan_kurtosis_review",
        "_run_kurtosis_review_scan_embedded": "_KurtosisReviewWorker",
    }
    for owner, callee in expected.items():
        node = next(node for node in tree.body if getattr(node, "name", None) == owner)
        call = next(child for child in ast.walk(node) if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name) and child.func.id == callee)
        assert "source_prefetch" in {keyword.arg for keyword in call.keywords}


def test_optional_prefetch_setup_failure_falls_back_without_starting_thread(tmp_path):
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body if getattr(node, "name", None) == "_start_qc_source_prefetch")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper], type_ignores=[])
    warnings = []

    def unavailable(*_args):
        raise ValueError("unsupported preload settings")

    namespace = {
        "QcSourcePrefetch": unavailable,
        "QThread": lambda *_args: pytest.fail("Started thread after setup failed"),
        "logger": SimpleNamespace(warning=lambda *_a, **_k: warnings.append(True)),
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    host = SimpleNamespace(currentProject=SimpleNamespace(project_root=tmp_path))
    assert namespace["_start_qc_source_prefetch"](host, [object()], {"reject_thresh": 5}) is None
    assert warnings == [True]


def test_main_window_cannot_destroy_a_live_prefetch_thread():
    path = WORKFLOW.with_name("main_window.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    shell = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    close = next(node for node in shell.body if isinstance(node, ast.FunctionDef) and node.name == "closeEvent")
    guard = next(node for node in close.body if isinstance(node, ast.If)
                 and any(isinstance(child, ast.Constant) and child.value == "_qc_source_prefetch_bridge"
                         for child in ast.walk(node.test)))
    wrapper = ast.parse("def close_window(self, event):\n    pass\n")
    wrapper.body[0].body = [guard]
    ignored, notices = [], []
    namespace = {"QMessageBox": SimpleNamespace(information=lambda *_args: notices.append(True))}
    exec(compile(ast.fix_missing_locations(wrapper), str(path), "exec"), namespace)
    host = SimpleNamespace(_qc_source_prefetch_bridge=object())
    event = SimpleNamespace(ignore=lambda: ignored.append(True))
    namespace["close_window"](host, event)
    assert ignored == notices == [True]
    host._qc_source_prefetch_bridge = None
    namespace["close_window"](host, event)
    assert ignored == notices == [True]
