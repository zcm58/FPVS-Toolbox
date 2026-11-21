"""Execute real GUI crop-routing functions without creating or importing Qt."""
from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from Main_App import gui
from Main_App.processing.preflight_qc import PreflightQcScan
from Main_App.processing.processing_ledger import additional_preflight_infos_for_chosen_scope


class _Signal:
    def __init__(self, *_types):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *values):
        for callback in self.callbacks:
            callback(*values)


def _native_functions(monkeypatch):
    module = ModuleType("native_crop_wiring")
    module.Path = Path
    module.Mapping = Mapping
    module.Sequence = Sequence
    module.PreflightQcScan = PreflightQcScan
    module.additional_preflight_infos_for_chosen_scope = additional_preflight_infos_for_chosen_scope
    module.logging = logging
    module.QObject = object
    module.Signal = _Signal
    module.logger = logging.getLogger(__name__)
    module._DATA_QUALITY_SCAN_WAIT_MESSAGE = "Scanning"
    monkeypatch.setattr(gui, "processing_inputs", SimpleNamespace(), raising=False)
    root = Path(__file__).resolve().parents[2] / "src/Main_App/gui"
    for name, functions in {
        "preprocessing_qc_workflow": {"_path_key", "_identity_id", "_extended_review_inputs",
                                      "_PreflightQcWorker", "run_preprocessing_qc_workflow"},
        "processing_workflows": {"_run_additional_preflight_for_chosen_scope"},
    }.items():
        file = root / (name + ".py")
        tree = ast.parse(file.read_text(encoding="utf-8"))
        tree.body = [*ast.parse("from __future__ import annotations").body,
                     *(node for node in tree.body if getattr(node, "name", None) in functions)]
        exec(compile(tree, str(file), "exec"), module.__dict__)
    return module


def test_additional_crop_review_restores_global_events_and_keeps_all_current_votes(
    monkeypatch, tmp_path,
):
    workflow = _native_functions(monkeypatch)
    from Main_App.processing.processing_controller import RawFileInfo
    from Main_App.processing.processing_ledger import ProcessingInputState, ProcessingPlan

    infos = [RawFileInfo(tmp_path / f"P{i}.bdf", f"P{i}") for i in range(1, 71)]
    # 65 historical recordings, four new with reviewed marker plans, and an
    # earlier technical exclusion. The crop choice changed for historical P2.
    statuses = {2: "changed_settings", 70: "excluded"}
    statuses.update(dict.fromkeys(range(66, 70), "new"))
    states = tuple(
        ProcessingInputState(info, info.subject_id, statuses.get(index, "completed"), "", ())
        for index, info in enumerate(infos, 1)
    )
    plan = ProcessingPlan(states, "fingerprint", ("Faces",))
    settings = {
        "_fpvs_preflight_event_plans_by_file": {
            "P66": {}, **{str(info.path): {} for info in infos[66:69]},
        },
        "_fpvs_preflight_recording_not_started_files": [str(infos[69].path)],
    }
    source_map = {"Faces": 22}
    host = SimpleNamespace(
        _processing_raw_file_infos=infos,
        run_preprocessing_qc_workflow=workflow.run_preprocessing_qc_workflow,
    )
    captured = []

    class ReachedRawReview(Exception):
        pass

    def start_raw_review(values):
        assert settings["event_id_map"] == source_map
        settings["observed_review_edit"] = True
        captured.extend(info.subject_id for info in values)
        raise ReachedRawReview

    for name in ("_project_group_labels", "_show_data_quality_notice", "_begin_preflight_page", "_set_label"):
        monkeypatch.setattr(workflow, name, lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(workflow, "scan_recording_not_started_files", start_raw_review, raising=False)
    with pytest.raises(ReachedRawReview):
        workflow._run_additional_preflight_for_chosen_scope(host, plan, settings, source_map)
    assert captured == ["P2", "P66", "P67", "P68", "P69", "P70"]
    assert "event_id_map" not in settings and settings["observed_review_edit"]
    with pytest.raises(ValueError, match="no longer registered"):
        workflow._extended_review_inputs([infos[1]], infos, [str(tmp_path / "unregistered.bdf")])


@pytest.mark.parametrize("raw_protocol", ["original", ""])
def test_preflight_worker_rejects_changed_or_missing_protocol_for_header_review(monkeypatch, tmp_path, raw_protocol):
    workflow = _native_functions(monkeypatch)
    scan = workflow.PreflightQcScan(results=(), frequency_protocol_fingerprint=raw_protocol)
    captured = {}
    monkeypatch.setattr(workflow, "scan_preprocessing_qc", lambda *args, **kwargs: scan, raising=False)

    def headers(root, *, superseded_recordings):
        captured["superseded"] = superseded_recordings
        return SimpleNamespace(frequency_protocol_fingerprint="changed", observations=(object(),))

    monkeypatch.setattr(workflow, "audit_project_full_fft_grids", headers, raising=False)
    infos = [SimpleNamespace(subject_id="P", recording_id="visit-2"), SimpleNamespace(subject_id="Q")]
    worker = workflow._PreflightQcWorker(infos, {}, [], 1, tmp_path, {"Faces": 22})
    failures, finished = [], []
    worker.failed.connect(failures.append)
    worker.finished.connect(finished.append)
    worker.run()
    assert captured["superseded"] == ("visit-2", "Q")
    assert len(failures) == 1 and "same confirmed frequency protocol" in failures[0]
    assert not finished
