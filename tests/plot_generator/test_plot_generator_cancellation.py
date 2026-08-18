from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from Main_App.processing.full_fft_provenance import FullFftProvenanceStaleError
from Main_App.projects import ProjectDatasetIndex
from Tools.Plot_Generator.analysis_context import SNRAnalysisContext
from Tools.Plot_Generator.generation_outcome import (
    managed_analysis_matches_active_project,
    normalize_worker_outcome,
)
from Tools.Plot_Generator.generation_workflow import (
    QMessageBox,
    PlotGeneratorWorkflowMixin,
)
from Tools.Plot_Generator.worker import _Worker


def _worker(tmp_path: Path, **kwargs) -> _Worker:
    return _Worker(
        folder=str(tmp_path),
        condition="Condition A",
        roi_map={"ROI": ["Cz"]},
        selected_roi="ROI",
        title="SNR",
        xlabel="Frequency (Hz)",
        ylabel="SNR",
        x_min=0.0,
        x_max=2.0,
        y_min=0.0,
        y_max=3.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=False,
        **kwargs,
    )


def _empty_dataset_index(root: Path) -> ProjectDatasetIndex:
    return ProjectDatasetIndex(
        project_root=root,
        excel_root=root,
        scan_root=root,
        manifest=None,
        groups={},
        participants={},
        workbooks=(),
        excluded_workbooks=(),
        diagnostics=(),
    )


def test_worker_outcome_normalizes_explicit_cancelled_state() -> None:
    assert normalize_worker_outcome({"cancelled": True}).cancelled is True
    assert normalize_worker_outcome({"cancelled": "true"}).cancelled is False
    assert normalize_worker_outcome({}).cancelled is False


def test_worker_outcome_normalizes_resolved_analysis_identity(tmp_path) -> None:
    project_root = tmp_path / "Project"
    outcome = normalize_worker_outcome(
        {
            "analysis_source_kind": "managed_full_fft_provenance",
            "analysis_project_root": str(project_root),
        }
    )

    assert outcome.analysis_source_kind == "managed_full_fft_provenance"
    assert outcome.analysis_project_root == str(project_root)
    assert outcome.post_processing_required_reason is None
    assert normalize_worker_outcome(
        {
            "analysis_source_kind": 1,
            "analysis_project_root": [],
        }
    ).analysis_project_root is None

    remediation = normalize_worker_outcome(
        {"post_processing_required_reason": "Provenance is stale."}
    )
    assert remediation.post_processing_required_reason == "Provenance is stale."


def test_qc_project_mutation_requires_matching_managed_run_identity(tmp_path) -> None:
    active_root = tmp_path / "Project"
    mismatch_root = tmp_path / "Other Project"

    assert managed_analysis_matches_active_project(
        analysis_source_kind="managed_full_fft_provenance",
        analysis_project_root=active_root / ".." / "Project",
        active_project_root=active_root,
    )
    assert not managed_analysis_matches_active_project(
        analysis_source_kind="legacy_application_settings",
        analysis_project_root=None,
        active_project_root=active_root,
    )
    assert not managed_analysis_matches_active_project(
        analysis_source_kind="managed_full_fft_provenance",
        analysis_project_root=mismatch_root,
        active_project_root=active_root,
    )
    assert not managed_analysis_matches_active_project(
        analysis_source_kind="managed_full_fft_provenance",
        analysis_project_root=None,
        active_project_root=active_root,
    )


def test_qc_exclusion_prompt_uses_resolved_run_project_identity(
    tmp_path,
    monkeypatch,
) -> None:
    active_root = tmp_path / "Project"
    flags = [
        {
            "condition": "Condition A",
            "pid": "P01",
            "electrode": f"E{index:02d}",
            "flag_count": 1,
        }
        for index in range(64)
    ]
    prompt_calls: list[str] = []
    monkeypatch.setattr(
        "Tools.Plot_Generator.generation_workflow.QMessageBox.question",
        lambda *_args, **_kwargs: prompt_calls.append("prompt") or QMessageBox.No,
    )
    project = SimpleNamespace(
        project_root=active_root,
        preprocessing={},
        update_preprocessing=lambda _payload: (_ for _ in ()).throw(
            AssertionError("a declined prompt must not update project state")
        ),
    )

    for identity in (
        ("legacy_application_settings", None),
        ("managed_full_fft_provenance", str(tmp_path / "Other Project")),
    ):
        host = SimpleNamespace(
            _spectral_qc_flags=flags,
            _spectral_qc_analysis_identities=[identity],
            _project=project,
            _project_root=active_root,
        )
        PlotGeneratorWorkflowMixin._offer_spectral_qc_participant_exclusions(host)

    assert prompt_calls == []

    stale_cache_host = SimpleNamespace(
        _spectral_qc_flags=flags,
        _spectral_qc_analysis_identities=[
            ("managed_full_fft_provenance", str(active_root.resolve()))
        ],
        _project=SimpleNamespace(project_root=tmp_path / "Loaded Other Project"),
        _project_root=active_root,
    )
    PlotGeneratorWorkflowMixin._offer_spectral_qc_participant_exclusions(
        stale_cache_host
    )

    assert prompt_calls == []

    matching_host = SimpleNamespace(
        _spectral_qc_flags=flags,
        _spectral_qc_analysis_identities=[
            ("managed_full_fft_provenance", str(active_root.resolve()))
        ],
        _project=project,
        _project_root=active_root,
    )
    PlotGeneratorWorkflowMixin._offer_spectral_qc_participant_exclusions(
        matching_host
    )

    assert prompt_calls == ["prompt"]


def test_qc_exclusion_marks_outputs_stale_and_requests_shared_rebuild(
    tmp_path,
    monkeypatch,
) -> None:
    active_root = tmp_path / "Project"
    flags = [
        {
            "condition": "Condition A",
            "pid": "P01",
            "electrode": f"E{index:02d}",
            "flag_count": 1,
        }
        for index in range(64)
    ]
    question_defaults: list[object] = []

    def accept_prompt(*args, **_kwargs):
        question_defaults.append(args[-1])
        return QMessageBox.Yes

    monkeypatch.setattr(
        "Tools.Plot_Generator.generation_workflow.QMessageBox.question",
        accept_prompt,
    )
    stale_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "Main_App.processing.frequency_domain_qc.mark_frequency_domain_outputs_stale",
        lambda root, *, reason: stale_calls.append((Path(root), reason)),
    )
    saved_payloads: list[dict] = []
    project = SimpleNamespace(
        project_root=active_root,
        preprocessing={},
        update_preprocessing=lambda payload: saved_payloads.append(dict(payload)),
        save=lambda: None,
    )
    logs: list[str] = []
    host = SimpleNamespace(
        _spectral_qc_flags=flags,
        _spectral_qc_analysis_identities=[
            ("managed_full_fft_provenance", str(active_root.resolve()))
        ],
        _project=project,
        _project_root=active_root,
        _post_processing_required_request=None,
        _append_log=logs.append,
    )

    PlotGeneratorWorkflowMixin._offer_spectral_qc_participant_exclusions(host)

    assert question_defaults == [QMessageBox.No]
    assert saved_payloads == [{"manual_excluded_participants": ["P01"]}]
    assert stale_calls == [
        (
            active_root,
            "Manual participant exclusions changed after the current "
            "frequency-domain outputs were created.",
        )
    ]
    assert host._post_processing_required_request == (
        stale_calls[0][1],
        str(active_root),
    )
    assert logs == ["Added manual participant exclusion(s): P01"]


def test_cancel_request_keeps_thread_queue_and_generate_locked() -> None:
    class _Button:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    worker = SimpleNamespace(stop_calls=0)
    worker.stop = lambda: setattr(worker, "stop_calls", worker.stop_calls + 1)
    thread = SimpleNamespace(quit_calls=0)
    thread.quit = lambda: setattr(thread, "quit_calls", thread.quit_calls + 1)
    logs: list[str] = []
    host = SimpleNamespace(
        _worker=worker,
        _thread=thread,
        _conditions_queue=["Condition B"],
        gen_btn=_Button(False),
        cancel_btn=_Button(True),
        _append_log=logs.append,
    )

    PlotGeneratorWorkflowMixin._cancel_generation(host)

    assert worker.stop_calls == 1
    assert thread.quit_calls == 0
    assert host._conditions_queue == ["Condition B"]
    assert host.gen_btn.enabled is False
    assert host.cancel_btn.enabled is False
    assert host._cancel_requested is True
    assert logs == [
        "Cancellation requested; waiting for the current plot operation to stop."
    ]


def test_shutdown_requests_cancel_and_retains_active_lifecycle() -> None:
    class _Host(PlotGeneratorWorkflowMixin):
        pass

    class _Button:
        def __init__(self) -> None:
            self.enabled = True

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    worker = SimpleNamespace(stop_calls=0)
    worker.stop = lambda: setattr(worker, "stop_calls", worker.stop_calls + 1)
    logs: list[str] = []
    host = _Host()
    host._worker = worker
    host._thread = object()
    host._cancel_requested = False
    host.cancel_btn = _Button()
    host._append_log = logs.append

    assert host.has_active_generation() is True
    assert host.shutdown() is True
    assert worker.stop_calls == 1
    assert host._thread is not None
    assert host._worker is worker
    assert host.cancel_btn.enabled is False

    assert host.shutdown() is True
    assert worker.stop_calls == 1

    host._thread = None
    host._worker = None
    assert host.has_active_generation() is False
    assert host.shutdown() is False


def test_all_conditions_worker_outcome_retains_prepared_dataset_index(
    tmp_path,
) -> None:
    index = _empty_dataset_index(tmp_path.resolve())
    host = SimpleNamespace(
        _all_conditions=True,
        _batch_dataset_index=None,
        _worker_outcome_received=False,
        _worker_reported_cancelled=False,
        _generated_paths=[],
        _failed_items=[],
        _warning_items=[],
        _spectral_qc_flags=[],
        _spectral_qc_analysis_identities=[],
        _post_processing_required_request=None,
        _project_root=None,
        _append_log=lambda _message: None,
    )

    PlotGeneratorWorkflowMixin._on_worker_finished(
        host,
        {"_prepared_dataset_index": index},
    )

    assert host._batch_dataset_index is index


def test_late_gui_cancel_trusts_committed_worker_outcome() -> None:
    completed: list[str] = []
    cancelled: list[str] = []
    logs: list[str] = []
    host = SimpleNamespace(
        _thread=object(),
        _worker=object(),
        _cancel_requested=True,
        _worker_reported_cancelled=False,
        _worker_outcome_received=True,
        _conditions_queue=["Condition B"],
        _append_log=logs.append,
        _finish_all=lambda: completed.append("complete"),
        _finish_cancelled=lambda: cancelled.append("cancelled"),
    )

    PlotGeneratorWorkflowMixin._generation_finished(host)

    assert host._thread is None
    assert host._worker is None
    assert host._conditions_queue == []
    assert completed == ["complete"]
    assert cancelled == []
    assert logs == [
        "Cancellation arrived after a figure pair was already saved; "
        "the completed files were kept."
    ]


def test_worker_cancelled_before_run_emits_cancelled_without_failure(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _worker(tmp_path)
    payloads: list[dict] = []
    messages: list[str] = []
    worker.finished.connect(payloads.append)
    worker.progress.connect(lambda message, *_args: messages.append(message))
    monkeypatch.setattr(
        worker,
        "_run",
        lambda: (_ for _ in ()).throw(AssertionError("run must be skipped")),
    )

    worker.stop()
    worker.run()

    assert payloads == [
        {
            "condition": "Condition A",
            "overlay": False,
            "generated_paths": [],
            "spectral_qc_flags": [],
            "failed_items": [],
            "warning_items": [],
            "cancelled": True,
            "analysis_source_kind": None,
            "analysis_project_root": None,
            "post_processing_required_reason": None,
        }
    ]
    assert messages == ["Generation cancelled by user."]


def test_worker_writes_only_direct_figures_without_run_bundle(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _worker(tmp_path)
    payloads: list[dict] = []
    worker.finished.connect(payloads.append)

    def write_direct_figures() -> None:
        png_path = tmp_path / "complete.png"
        pdf_path = tmp_path / "complete.pdf"
        png_path.write_bytes(b"png")
        pdf_path.write_bytes(b"pdf")
        worker._record_figure_pair(
            png_path=png_path,
            pdf_path=pdf_path,
        )
        worker.stop()

    monkeypatch.setattr(worker, "_run", write_direct_figures)

    worker.run()

    assert payloads[0]["cancelled"] is False
    assert payloads[0]["generated_paths"] == [
        str(tmp_path / "complete.png"),
        str(tmp_path / "complete.pdf"),
    ]
    assert "source_data_paths" not in payloads[0]
    assert "run_manifest_paths" not in payloads[0]
    assert "output_bundle_paths" not in payloads[0]
    assert not list(tmp_path.glob("SNR_Plot_Run_*"))
    assert not list(tmp_path.glob("*.csv"))
    assert not list(tmp_path.glob("*.xlsx"))
    assert not list(tmp_path.glob("*.json"))


def test_worker_emits_resolved_analysis_identity(tmp_path, monkeypatch) -> None:
    worker = _worker(tmp_path)
    payloads: list[dict] = []
    worker.finished.connect(payloads.append)
    resolved_project_root = (tmp_path / "Project").resolve()
    context = SNRAnalysisContext(
        project_root=resolved_project_root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
        allowed_workbook_paths=frozenset(),
        provenance={"source_kind": "managed_full_fft_provenance"},
    )
    monkeypatch.setattr(
        "Tools.Plot_Generator.output_interface.resolve_snr_analysis_context",
        lambda *_args, **_kwargs: context,
    )

    def _capture_managed_context() -> None:
        worker._configure_analysis_context(
            SimpleNamespace(
                ordered_groups=(),
                manifest=object(),
                project_root=resolved_project_root,
            )
        )

    monkeypatch.setattr(worker, "_run", _capture_managed_context)

    worker.run()

    assert payloads[0]["analysis_source_kind"] == "managed_full_fft_provenance"
    assert payloads[0]["analysis_project_root"] == str(resolved_project_root)


def test_worker_reports_actionable_post_processing_remedy(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _worker(tmp_path)
    project_root = (tmp_path / "Project").resolve()
    worker._analysis_project_root = project_root
    worker._analysis_source_kind = "managed_full_fft_provenance"
    payloads: list[dict] = []
    worker.finished.connect(payloads.append)
    reason = "Neutral FullFFT provenance is stale."
    monkeypatch.setattr(
        worker,
        "_run",
        lambda: (_ for _ in ()).throw(FullFftProvenanceStaleError(reason)),
    )

    worker.run()

    assert payloads[0]["post_processing_required_reason"] == reason
    assert payloads[0]["analysis_project_root"] == str(project_root)
    assert payloads[0]["failed_items"] == [
        {
            "item": "Condition A",
            "error": f"Post-processing required: {reason}",
        }
    ]


def test_overlay_cancel_after_first_condition_suppresses_second_collection(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _worker(
        tmp_path,
        condition_b="Condition B",
        overlay=True,
    )
    payloads: list[dict] = []
    collected: list[str] = []
    worker.finished.connect(payloads.append)
    monkeypatch.setattr(worker, "_list_excel_files", lambda _condition: [tmp_path / "p.xlsx"])

    def _collect(condition, **_kwargs):
        collected.append(condition)
        worker.stop()
        return [1.0], {"P01": {"ROI": [2.0]}}

    monkeypatch.setattr(worker, "_collect_data", _collect)

    worker.run()

    assert collected == ["Condition A"]
    assert payloads[0]["cancelled"] is True
    assert payloads[0]["generated_paths"] == []


def test_collection_stops_after_costly_workbook_read(tmp_path, monkeypatch) -> None:
    condition_dir = tmp_path / "Condition A"
    condition_dir.mkdir()
    workbook = condition_dir / "P01_Condition A_Results.xlsx"
    workbook.write_bytes(b"test workbook placeholder")
    worker = _worker(tmp_path)
    reads: list[Path] = []

    monkeypatch.setattr(worker, "_list_excel_files", lambda _condition: [workbook])
    monkeypatch.setattr(worker, "_subject_id_for_workbook", lambda _path: "P01")

    def _read(path, **_kwargs):
        reads.append(path)
        worker.stop()
        return pd.DataFrame({"Electrode": ["Cz"], "1.0": [2.0]}), [1.0], ["1.0"]

    monkeypatch.setattr(worker, "_read_full_snr_direct", _read)

    freqs, data = worker._collect_data("Condition A")

    assert reads == [workbook]
    assert freqs == []
    assert data == {}


def test_render_cancelled_before_publication_writes_no_files(
    tmp_path,
    monkeypatch,
) -> None:
    worker = _worker(tmp_path)
    save_calls: list[Path] = []

    def _stop_during_layout(_figure, *_args, **_kwargs):
        worker.stop()

    monkeypatch.setattr("matplotlib.figure.Figure.tight_layout", _stop_during_layout)
    monkeypatch.setattr(
        "matplotlib.figure.Figure.savefig",
        lambda _figure, path, **_kwargs: save_calls.append(Path(path)),
    )

    worker._plot([1.0, 2.0], {"ROI": [1.5, 2.5]})

    assert save_calls == []
    assert worker.generated_paths == []
    assert worker._stop_requested is True
