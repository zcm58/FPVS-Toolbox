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
    refresh_helper = next(node for node in tree.body if getattr(node, "name", None) == "_refresh_qc_source_prefetch_exclusions")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), refresh_helper, workflow], type_ignores=[])
    trace = []
    refreshed_exclusions = []
    scan = SimpleNamespace(cancelled=False)

    def refresh_exclusions(values):
        refreshed_exclusions.append(tuple(values or ()))
        trace.append("refresh")

    prefetch = SimpleNamespace(source_prefetch=SimpleNamespace(
        update_participant_exclusions=refresh_exclusions,
    ))
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
        params["manual_excluded_participants"] = ["markers"]
        if stop == "exception":
            raise ValueError("review failed")
        return None if stop == "markers" else scan

    def kurtosis(_host, _infos, current_params, **kwargs):
        trace.append("kurtosis")
        assert current_params is params
        assert kwargs["source_prefetch"] is prefetch.source_prefetch
        assert refreshed_exclusions[-1] == ("hard",)
        return None if stop == "kurtosis" else scan

    def finish(_host, current):
        assert current is prefetch
        trace.append("finish")

    def accept(stage):
        def review(*_args, **kwargs):
            if stage == "other":
                assert kwargs["signal_params"] is params
            else:
                preceding = "markers" if stage == "conditions" else "conditions"
                assert refreshed_exclusions[-1] == (preceding,)
                params["manual_excluded_participants"] = [stage]
            trace.append(stage)
            return stop != stage
        return review

    def hard_exclusions(*_args):
        assert refreshed_exclusions[-1] == ("electrodes",)
        params["manual_excluded_participants"] = ["hard"]
        trace.append("hard")
        return set()

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
        "_confirm_hard_exclusions": hard_exclusions,
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
    assert [entry for entry in trace if entry != "refresh"][:3] == ["scan", "prefetch", "markers"]
    assert trace[-1] == "finish"
    assert trace.count("prefetch") == trace.count("finish") == 1
    stages = ["markers", "conditions", "electrodes", "hard"]
    expected = [] if stop == "exception" else stages[:stages.index(stop)] if stop in stages else stages
    assert all((stage,) in refreshed_exclusions for stage in expected)


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

    worker = next(node for node in tree.body if getattr(node, "name", None) == "_KurtosisReviewWorker")
    status_signal = next(node for node in worker.body if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "status_progress" for target in node.targets))
    assert ast.unparse(status_signal.value) == "Signal(object)"
    scan_call = next(node for node in ast.walk(worker) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "scan_kurtosis_review")
    status_callback = next(keyword.value for keyword in scan_call.keywords if keyword.arg == "status_progress")
    assert ast.unparse(status_callback) == "self.status_progress.emit"
    embedded = next(node for node in tree.body if getattr(node, "name", None) == "_run_kurtosis_review_scan_embedded")
    assert any(
        isinstance(node, ast.Call)
        and ast.unparse(node.func) == "worker.status_progress.connect"
        and [ast.unparse(argument) for argument in node.args] == ["bridge.on_status_progress"]
        for node in ast.walk(embedded)
    )


def test_optional_prefetch_setup_failure_falls_back_without_starting_thread(tmp_path):
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body if getattr(node, "name", None) == "_start_qc_source_prefetch")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper], type_ignores=[])
    warnings = []
    constructor_arguments = []

    def unavailable(*_args):
        constructor_arguments.append(_args)
        raise ValueError("unsupported preload settings")

    namespace = {
        "QcSourcePrefetch": unavailable,
        "QThread": lambda *_args: pytest.fail("Started thread after setup failed"),
        "logger": SimpleNamespace(warning=lambda *_a, **_k: warnings.append(True)),
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    host = SimpleNamespace(currentProject=SimpleNamespace(project_root=tmp_path))
    infos = [object()]
    params = {"reject_thresh": 5, "manual_excluded_participants": ["P03"]}
    assert namespace["_start_qc_source_prefetch"](host, infos, params) is None
    assert warnings == [True]
    assert constructor_arguments == [(tmp_path, infos, params)]
    assert constructor_arguments[0][2] is params


def test_exclusion_refresh_is_optional_and_forwards_cleared_settings():
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body if getattr(node, "name", None) == "_refresh_qc_source_prefetch_exclusions")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), helper], type_ignores=[])
    warnings = []
    namespace = {
        "logger": SimpleNamespace(warning=lambda *args, **kwargs: warnings.append(args)),
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    refresh = namespace["_refresh_qc_source_prefetch_exclusions"]
    refresh(None, {})
    received = []
    bridge = SimpleNamespace(source_prefetch=SimpleNamespace(
        update_participant_exclusions=received.append,
    ))
    refresh(bridge, {"manual_excluded_participants": ["P03"]})
    refresh(bridge, {})
    assert received == [["P03"], None]

    def unavailable(_values):
        raise RuntimeError("Optional preload is no longer available.")

    bridge.source_prefetch.update_participant_exclusions = unavailable
    refresh(bridge, {"manual_excluded_participants": ["P04"]})
    assert warnings == [("qc_source_prefetch_exclusion_refresh_unavailable",)]


@pytest.mark.parametrize(
    ("eligible", "completed", "excluded", "failed", "expected", "percent"),
    [
        (8, 3, 2, 0, "Processed 3 of 8 eligible recordings; 2 excluded.", 38),
        (8, 3, 2, 1, "Processed 2 of 8 eligible recordings; 2 excluded. 1 failed.", 38),
        (0, 0, 12, 0, "Processed 0 of 0 eligible recordings; 12 excluded.", 100),
        (0, 0, 0, 0, "Processed 0 of 0 eligible recordings; 0 excluded.", 100),
    ],
)
def test_kurtosis_status_keeps_eligible_work_separate_from_exclusions(
    eligible, completed, excluded, failed, expected, percent,
):
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if getattr(node, "name", None) in {
        "_kurtosis_scan_progress_text", "_set_progress",
    }]
    bridge = next(node for node in tree.body if getattr(node, "name", None) == "_KurtosisReviewEmbeddedBridge")
    methods = [node for node in bridge.body if isinstance(node, ast.FunctionDef)
               and node.name in {"on_status_progress", "on_progress"}]
    status_method = next(node for node in methods if node.name == "on_status_progress")
    assert [ast.unparse(node) for node in status_method.decorator_list] == ["Slot(object)"]
    for method in methods:
        method.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *helpers, *methods], type_ignores=[])
    labels, ranges, values, formats = {}, [], [], []
    namespace = {
        "KurtosisReviewProgress": SimpleNamespace,
        "_set_label": lambda _host, name, text: labels.update({name: text}),
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKFLOW), "exec"), namespace)
    host = SimpleNamespace(progress_bar=SimpleNamespace(
        setRange=lambda *bounds: ranges.append(bounds),
        setValue=values.append,
        setFormat=formats.append,
    ))
    self = SimpleNamespace(_host=host)
    state = SimpleNamespace(
        eligible_total=eligible, completed_eligible=completed,
        excluded_count=excluded, failed_count=failed,
    )
    namespace["on_status_progress"](self, state)
    assert labels["processing_summary_label"] == expected
    assert ranges[-1] == (0, 100)
    assert values[-1] == percent
    assert formats[-1] == "%p%"

    # Legacy callbacks still provide useful live file text; their inclusive
    # counts must not replace the structured eligible/excluded counters.
    namespace["on_progress"](self, "Loading retained.bdf", 7, 18)
    assert labels["processing_current_file_label"] == "Loading retained.bdf"
    assert labels["processing_summary_label"] == expected
    assert values == [percent]


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
