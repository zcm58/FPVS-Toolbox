from __future__ import annotations

import json
import logging
from pathlib import Path
import queue
from types import SimpleNamespace

import mne
import numpy as np
import pytest

import Main_App.Shared.processing_mixin as compatibility_processing
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    biosemi64_geometry_identity,
    cached_biosemi64_montage,
)
from Main_App.processing.raw_channel_qc import (
    LEFT_HEMISPHERE_CHANNELS,
    RAW_CHANNEL_QC_METHOD_VERSION,
    RIGHT_HEMISPHERE_CHANNELS,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.analysis_spans import (
    read_source_analysis_span_plan,
    realize_target_analysis_span_plan,
)
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers import process_runner


class _CompatibilitySettings:
    @staticmethod
    def debug_enabled() -> bool:
        return False


def _compatibility_raw() -> mne.io.RawArray:
    info = mne.create_info(
        ["Cz", "Status"],
        sfreq=256.0,
        ch_types=["eeg", "stim"],
    )
    return mne.io.RawArray(np.zeros((2, 3_000)), info, verbose=False)


def _with_biosemi64_montage(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    raw.set_montage(
        cached_biosemi64_montage(),
        on_missing="raise",
    )
    retained = [name for name in BIOSEMI64_CHANNELS if name in raw.ch_names]
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=retained,
        stim_channel="Status" if "Status" in raw.ch_names else None,
    )
    return raw


def _protocol_settings(
    *,
    file_path: Path,
    events: np.ndarray,
    event_map: dict[str, int],
    sfreq: float,
    n_times: int,
    presentation_rate_hz: float,
    oddball_every_n: int,
    expected_cycles: int,
) -> dict[str, object]:
    protocol = FrequencyProtocol.from_recurrence(
        presentation_rate_hz,
        oddball_every_n,
        expected_analyzed_oddball_cycles=expected_cycles,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    plan = plan_preflight_qc_events(
        events=events,
        event_map=event_map,
        sfreq=sfreq,
        n_times=n_times,
        frequency_protocol=protocol,
    )
    return {
        "frequency_protocol": protocol,
        "_fpvs_preflight_event_plans_by_file": {
            str(file_path.resolve()): plan.to_payload()
        },
    }


def _analysis_plan_fixture(
    *,
    file_path: Path,
    sfreq: float,
    n_times: int,
    event_map: dict[str, int],
) -> tuple[np.ndarray, dict[str, object]]:
    cycles = max(1, min(500, (n_times - 2) // 2))
    condition_code = int(next(iter(event_map.values())))
    marker_samples = [1 + 2 * index for index in range(cycles + 1)]
    events = np.asarray(
        [
            [0, 0, condition_code],
            *[[sample, 0, 55] for sample in marker_samples],
        ],
        dtype=int,
    )
    return events, _protocol_settings(
        file_path=file_path,
        events=events,
        event_map=event_map,
        sfreq=sfreq,
        n_times=n_times,
        presentation_rate_hz=sfreq,
        oddball_every_n=2,
        expected_cycles=cycles,
    )


def _passthrough_preprocessing_with_realized_spans(
    raw_input,
    params,
    *_args,
    **_kwargs,
):
    target_plan = realize_target_analysis_span_plan(
        params["_fpvs_source_analysis_span_plan"],
        target_sfreq_hz=float(raw_input.info["sfreq"]),
        target_n_times=int(raw_input.n_times),
        target_first_samp=int(raw_input.first_samp),
    )
    params["_fpvs_realized_analysis_span_plan"] = target_plan
    params["_fpvs_analysis_scoring_sample_count"] = target_plan[
        "unique_sample_count"
    ]
    return raw_input, 0


def _run_compatibility_worker(
    monkeypatch,
    tmp_path,
    *,
    events_by_file: list[np.ndarray],
    event_map: dict[str, int],
):
    raw = _compatibility_raw()
    post_calls: list[dict[str, object]] = []

    class Host(compatibility_processing.ProcessingMixin):
        pass

    host = Host()
    source_paths = [
        str(tmp_path / f"P{index:02d}.bdf")
        for index in range(1, len(events_by_file) + 1)
    ]
    host.data_paths = list(source_paths)
    host.preprocessed_data = {}
    host.save_folder_path = SimpleNamespace(get=lambda: str(tmp_path))
    host.settings = _CompatibilitySettings()
    host.load_eeg_file = lambda _path: raw.copy()

    def _post_process(labels):
        post_calls.append(
            {
                "labels": list(labels),
                "metadata": {
                    label: epochs_list[0].metadata.copy()
                    for label, epochs_list in host.preprocessed_data.items()
                },
            }
        )

    host.post_process = _post_process
    monkeypatch.setattr(
        compatibility_processing,
        "perform_preprocessing",
        lambda raw_input, **_kwargs: (raw_input, 0),
    )
    monkeypatch.setattr(
        compatibility_processing.mne,
        "find_events",
        lambda *_args, **_kwargs: np.array(events_by_file.pop(0), copy=True),
    )

    output_queue: queue.Queue = queue.Queue()
    host._processing_thread_func(
        source_paths,
        {
            "event_id_map": event_map,
            "stim_channel": "Status",
            "max_bad_channels_alert_thresh": 20,
        },
        output_queue,
    )
    messages = []
    while not output_queue.empty():
        messages.append(output_queue.get_nowait())
    return messages, post_calls


def test_compatibility_worker_requires_locked_marker_crop_and_skips_export(
    monkeypatch,
    tmp_path,
) -> None:
    messages, post_calls = _run_compatibility_worker(
        monkeypatch,
        tmp_path,
        events_by_file=[
            np.asarray(
                [
                    (100, 0, 1),
                    (300, 0, 55),
                    (940, 0, 55),
                    (1_500, 0, 2),
                    (1_700, 0, 55),
                ],
                dtype=int,
            )
        ],
        event_map={"Valid": 1, "Invalid": 2},
    )

    errors = [message["message"] for message in messages if message["type"] == "error"]
    assert len(errors) == 1
    assert "Locked FFT crop required" in errors[0]
    assert "Fixed-epoch fallback is disabled" in errors[0]
    assert post_calls == []


def test_compatibility_worker_exports_only_55_onbin_metadata(
    monkeypatch,
    tmp_path,
) -> None:
    messages, post_calls = _run_compatibility_worker(
        monkeypatch,
        tmp_path,
        events_by_file=[
            np.asarray(
                [
                    (100, 0, 1),
                    (300, 0, 55),
                    (940, 0, 55),
                ],
                dtype=int,
            )
        ],
        event_map={"Valid": 1},
    )

    assert not [message for message in messages if message["type"] == "error"]
    assert len(post_calls) == 1
    metadata = post_calls[0]["metadata"]["Valid"]
    assert metadata["crop_mode"].tolist() == ["55_onbin"]
    assert metadata["N_mod_step"].tolist() == [0]


def test_compatibility_worker_continues_after_invalid_file(
    monkeypatch,
    tmp_path,
) -> None:
    messages, post_calls = _run_compatibility_worker(
        monkeypatch,
        tmp_path,
        events_by_file=[
            np.asarray(
                [
                    (100, 0, 1),
                    (300, 0, 55),
                ],
                dtype=int,
            ),
            np.asarray(
                [
                    (100, 0, 1),
                    (300, 0, 55),
                    (940, 0, 55),
                ],
                dtype=int,
            ),
        ],
        event_map={"Condition": 1},
    )

    assert len(post_calls) == 1
    assert [
        message["value"] for message in messages if message["type"] == "progress"
    ] == [1, 2]
    errors = [message for message in messages if message["type"] == "error"]
    assert len(errors) == 1
    assert "P01.bdf" in errors[0]["message"]


def test_compatibility_queue_error_finalizes_unsuccessfully() -> None:
    finalized: list[bool] = []
    host = SimpleNamespace(
        gui_queue=queue.Queue(),
        processing_thread=None,
        log=lambda *_args, **_kwargs: None,
        _finalize_processing=finalized.append,
    )
    host.gui_queue.put({"type": "error", "message": "crop failed"})
    host.gui_queue.put({"type": "done"})

    compatibility_processing.ProcessingMixin._periodic_queue_check(host)

    assert finalized == [False]


def test_compatibility_queue_done_finalizes_successfully() -> None:
    finalized: list[bool] = []
    host = SimpleNamespace(
        gui_queue=queue.Queue(),
        processing_thread=None,
        log=lambda *_args, **_kwargs: None,
        _finalize_processing=finalized.append,
    )
    host.gui_queue.put({"type": "done"})

    compatibility_processing.ProcessingMixin._periodic_queue_check(host)

    assert finalized == [True]


def test_source_epoch_set_keeps_available_configured_conditions() -> None:
    available = [object()]

    result = process_runner._available_source_epoch_set(
        {"A": available, "B": []},
        {"A": 21, "B": 22},
    )

    assert result == {"A": available}


def test_skipped_conditions_are_logged_once_per_file(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=process_runner.__name__):
        process_runner._log_skipped_condition_summary(
            Path("P07.bdf"),
            [
                ("Angry Caucasian", 41, "0 matching events"),
                ("Happy Caucasian", 43, "0 epochs after epoching"),
            ],
        )

    records = [
        record
        for record in caplog.records
        if "[AUDIT WARNING]" in record.getMessage()
    ]
    assert len(records) == 1
    assert "P07.bdf" in records[0].getMessage()
    assert "'Angry Caucasian' (code=41): 0 matching events" in records[0].getMessage()
    assert "'Happy Caucasian' (code=43): 0 epochs after epoching" in records[
        0
    ].getMessage()


def test_expected_source_epoch_gap_logs_without_traceback(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger=process_runner.__name__):
        try:
            process_runner._available_source_epoch_set(
                {"A": [], "B": []},
                {"A": 21, "B": 22},
            )
        except RuntimeError as exc:
            process_runner._log_source_derivative_issue(Path("P07.bdf"), exc)

    records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("source_ready_time_domain_incomplete")
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].exc_info is None
    assert "missing_conditions=['A', 'B']" in records[0].getMessage()


def test_unexpected_source_derivative_issue_keeps_traceback(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger=process_runner.__name__):
        try:
            raise OSError("disk unavailable")
        except OSError as exc:
            process_runner._log_source_derivative_issue(Path("P07.bdf"), exc)

    records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("source_ready_time_domain_failed")
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


def test_source_epoch_set_preserves_configured_condition_order() -> None:
    first = [object()]
    second = [object()]

    result = process_runner._available_source_epoch_set(
        {"B": second, "A": first},
        {"A": 21, "B": 22},
    )

    assert list(result) == ["A", "B"]
    assert result == {"A": first, "B": second}


def _write_bdf_header(path: Path, *, header_bytes: int = 512, data_records: int = 0, channels: int = 1) -> None:
    header = bytearray(b" " * 256)

    def _put(start: int, stop: int, value: object) -> None:
        header[start:stop] = str(value).ljust(stop - start).encode("ascii")

    _put(184, 192, header_bytes)
    _put(236, 244, data_records)
    _put(244, 252, 1)
    _put(252, 256, channels)
    path.write_bytes(bytes(header) + (b" " * max(0, header_bytes - 256)))


def test_group_output_settings_are_routed_per_raw_file_and_require_complete_map(
    tmp_path: Path,
) -> None:
    control_file = tmp_path / "Control" / "P01.bdf"
    treatment_file = tmp_path / "Treatment" / "P02.bdf"
    mapping = {
        str(control_file.resolve()): "Control",
        str(treatment_file.resolve()): "Treatment",
    }
    settings = {
        "_fpvs_grouped_project": True,
        "_fpvs_output_group_by_file": mapping,
        "alpha": 0.05,
    }

    control_settings = process_runner._settings_for_file(control_file, settings)
    treatment_settings = process_runner._settings_for_file(treatment_file, settings)

    assert control_settings["output_group_folder"] == "Control"
    assert treatment_settings["output_group_folder"] == "Treatment"
    assert "output_group_folder" not in settings
    with pytest.raises(ValueError, match="no output-folder assignment"):
        process_runner._settings_for_file(tmp_path / "P03.bdf", settings)
    with pytest.raises(ValueError, match="requires a canonical per-file"):
        process_runner._settings_for_file(
            control_file,
            {"_fpvs_grouped_project": True},
        )


def test_file_settings_default_detector_off_and_select_kurtosis_receipts(
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "P01.bdf"
    file_key = str(fake_bdf.resolve())
    settings = {
        "_fpvs_participant_id_by_file": {file_key: "P01"},
        "kurtosis_review_decisions_by_recording": {
            "p01": {"Oz": {"decision": "approve"}},
            "P02": {"P9": {"decision": "reject"}},
        },
    }

    resolved = process_runner._settings_for_file(fake_bdf, settings)

    assert resolved["removed_electrode_detection_mode"] == "off"
    assert resolved["auto_detect_removed_electrodes"] is False
    assert resolved["_fpvs_source_file_path"] == file_key
    assert resolved["_fpvs_participant_id"] == "P01"
    assert resolved["_fpvs_kurtosis_review_decisions"] == {
        "Oz": {"decision": "approve"}
    }


def test_condition_exclusions_resolve_by_participant_and_recording(
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "P12_visit2.bdf"
    file_key = str(fake_bdf.resolve())
    settings = {
        "_fpvs_participant_id_by_file": {file_key: "P12"},
        "_fpvs_recording_id_by_file": {file_key: "P12__visit2"},
        "manual_excluded_participant_conditions": {"p12": ["Faces"]},
        "manual_excluded_recording_conditions": {
            "p12__VISIT2": ["Objects"]
        },
    }

    assert process_runner._excluded_condition_labels_for_file(
        fake_bdf,
        settings,
        {"Faces": 21, "Objects": 22, "Words": 23},
    ) == ("Faces", "Objects")


def test_run_full_pipeline_excludes_header_only_bdf_before_loader(monkeypatch, tmp_path: Path) -> None:
    fake_bdf = tmp_path / "p16.bdf"
    _write_bdf_header(fake_bdf, header_bytes=512, data_records=0, channels=1)

    def _unexpected_loader(*_args, **_kwargs):
        raise AssertionError("header-only BDF should be excluded before load_eeg_file")

    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", _unexpected_loader)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {"p16": []},
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "excluded"
    assert result["stage"] == "preflight"
    assert result["reason"] == "recording_not_started"
    assert "did not click Record in BioSemi" in str(result["message"])
    assert result["bdf_preflight"]["file_size"] == 512
    assert result["bdf_preflight"]["header_bytes"] == 512
    assert result["bdf_preflight"]["data_records"] == 0


def test_run_full_pipeline_skips_loader_when_every_condition_is_excluded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "P12.bdf"
    fake_bdf.write_bytes(b"not a real bdf")
    events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=128,
        event_map={"Faces": 21},
    )

    def _unexpected_loader(*_args, **_kwargs):
        raise AssertionError("fully excluded conditions must skip raw loading")

    monkeypatch.setattr(process_runner, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", _unexpected_loader)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "manual_excluded_participant_conditions": {"P12": ["Faces"]},
            "_fpvs_participant_id_by_file": {
                str(fake_bdf.resolve()): "P12"
            },
            **plan_settings,
        },
        event_map={"Faces": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert events.size
    assert result["status"] == "excluded"
    assert result["stage"] == "condition_scope"
    assert result["reason"] == "all_conditions_excluded_from_analysis"


def test_run_full_pipeline_scores_only_included_condition_spans(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(
        ["Cz", "Pz", "Status"],
        sfreq=8.0,
        ch_types=["eeg", "eeg", "stim"],
    )
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    )
    events = np.asarray(
        [
            [8, 0, 21],
            [10, 0, 55],
            [14, 0, 55],
            [32, 0, 22],
            [34, 0, 55],
            [38, 0, 55],
        ],
        dtype=int,
    )
    fake_bdf = tmp_path / "P12-partial.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    captured: dict[str, object] = {}

    monkeypatch.setattr(process_runner, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": fake_bdf.name},
    )

    def _capture_scoring_scope(raw_input, params, *_args, **_kwargs):  # noqa: ARG001
        captured["source_plan"] = params["_fpvs_source_analysis_span_plan"]
        captured["raw_qc_spans"] = list(params["_fpvs_raw_qc_scoring_spans"])
        raise RuntimeError("stop after analyzed-scope capture")

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _capture_scoring_scope,
    )

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "removed_electrode_detection_mode": "off",
            "auto_detect_removed_electrodes": False,
            "manual_excluded_participant_conditions": {"P12": ["Objects"]},
            "_fpvs_participant_id_by_file": {
                str(fake_bdf.resolve()): "P12"
            },
            **_protocol_settings(
                file_path=fake_bdf,
                events=events,
                event_map={"Faces": 21, "Objects": 22},
                sfreq=8.0,
                n_times=64,
                presentation_rate_hz=4.0,
                oddball_every_n=2,
                expected_cycles=1,
            ),
        },
        event_map={"Faces": 21, "Objects": 22},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "preprocess"
    source_plan = captured["source_plan"]
    assert isinstance(source_plan, dict)
    assert source_plan["condition_selection"]["excluded_condition_labels"] == [
        "Objects"
    ]
    assert [span["condition_label"] for span in source_plan["spans"]] == [
        "Faces"
    ]
    assert captured["raw_qc_spans"] == [[10, 14]]


def test_run_full_pipeline_manual_participant_exclusion_skips_loader(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "p12.bdf"
    fake_bdf.write_bytes(b"not a real bdf")

    def _unexpected_loader(*_args, **_kwargs):
        raise AssertionError("manual participant exclusion should skip the loader")

    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", _unexpected_loader)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "manual_excluded_participants": ["P12"],
            "_fpvs_participant_id_by_file": {
                str(fake_bdf.resolve()): "P12",
            },
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "excluded"
    assert result["stage"] == "preflight"
    assert result["reason"] == "manual_participant_exclusion"
    assert "P12 was manually excluded" in str(result["message"])


def test_run_full_pipeline_manual_recording_exclusion_preserves_paired_visit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    luteal = tmp_path / "p12_luteal.bdf"
    luteal.write_bytes(b"not a real bdf")

    def _unexpected_loader(*_args, **_kwargs):
        raise AssertionError("manual recording exclusion should skip the loader")

    monkeypatch.setattr("Main_App.io.load_utils.load_eeg_file", _unexpected_loader)
    file_key = str(luteal.resolve())

    result = process_runner._run_full_pipeline_for_file(
        file_path=luteal,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "manual_excluded_recordings": ["P12__luteal"],
            "_fpvs_participant_id_by_file": {file_key: "P12"},
            "_fpvs_recording_id_by_file": {file_key: "P12__luteal"},
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "excluded"
    assert result["stage"] == "preflight"
    assert result["reason"] == "manual_recording_exclusion"
    assert "P12__luteal was manually excluded" in str(result["message"])


def test_recording_manual_removed_electrodes_override_participant_defaults(
    tmp_path: Path,
) -> None:
    follicular = tmp_path / "p12_follicular.bdf"
    follicular.write_bytes(b"not a real bdf")
    file_key = str(follicular.resolve())
    settings = {
        "removed_electrode_detection_mode": "auto",
        "auto_detect_removed_electrodes": True,
        "manual_removed_electrodes_enabled": True,
        "manual_removed_electrodes": {"P12": ["P9"]},
        "manual_removed_electrodes_by_recording": {
            "P12__follicular": ["Oz"],
        },
        "_fpvs_participant_id_by_file": {file_key: "P12"},
        "_fpvs_recording_id_by_file": {file_key: "P12__follicular"},
    }

    assert process_runner._manual_removed_electrodes_for_file(
        follicular,
        settings,
    ) == ["Oz"]
    assert process_runner._manual_removed_electrodes_for_file(
        follicular,
        {
            **settings,
            "removed_electrode_detection_mode": "off",
            "auto_detect_removed_electrodes": False,
        },
    ) == ["Oz"]
    assert process_runner._manual_removed_electrodes_for_file(
        follicular,
        {**settings, "manual_removed_electrodes_enabled": False},
    ) == []
    assert process_runner._manual_removed_electrodes_for_file(
        follicular,
        {
            **settings,
            "manual_removed_electrodes_by_recording": {
                "P12__follicular": [],
            },
        },
    ) == []


def test_parallel_runner_skips_manual_participant_exclusions_before_pool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "p12.bdf"
    fake_bdf.write_bytes(b"not a real bdf")

    def _unexpected_pool(*_args, **_kwargs):
        raise AssertionError("all manual exclusions should skip process-pool creation")

    monkeypatch.setattr(process_runner, "ProcessPoolExecutor", _unexpected_pool)

    class _Queue:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def put(self, value: dict[str, object]) -> None:
            self.messages.append(value)

    queue = _Queue()
    process_runner.run_project_parallel(
        process_runner.RunParams(
            project_root=tmp_path / "project",
            data_files=[fake_bdf],
            settings={
                "manual_excluded_participants": ["P12"],
                "_fpvs_participant_id_by_file": {
                    str(fake_bdf.resolve()): "P12",
                },
            },
            event_map={"A": 21},
            save_folder=tmp_path / "out",
            max_workers=1,
        ),
        progress_queue=queue,
    )

    assert queue.messages[0]["type"] == "progress"
    result = queue.messages[0]["result"]
    assert isinstance(result, dict)
    assert result["reason"] == "manual_participant_exclusion"
    assert queue.messages[-1]["type"] == "done"
    assert queue.messages[-1]["excluded_count"] == 1


def test_parallel_runner_skips_preflight_header_only_files_before_pool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "p08.bdf"
    _write_bdf_header(fake_bdf, header_bytes=512, data_records=0, channels=1)

    def _unexpected_pool(*_args, **_kwargs):
        raise AssertionError("preflight header-only exclusions should skip pool creation")

    monkeypatch.setattr(process_runner, "ProcessPoolExecutor", _unexpected_pool)

    class _Queue:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def put(self, value: dict[str, object]) -> None:
            self.messages.append(value)

    queue = _Queue()
    process_runner.run_project_parallel(
        process_runner.RunParams(
            project_root=tmp_path / "project",
            data_files=[fake_bdf],
            settings={
                "_fpvs_preflight_recording_not_started_files": [
                    str(fake_bdf.resolve())
                ],
            },
            event_map={"A": 21},
            save_folder=tmp_path / "out",
            max_workers=1,
        ),
        progress_queue=queue,
    )

    assert queue.messages[0]["type"] == "progress"
    result = queue.messages[0]["result"]
    assert isinstance(result, dict)
    assert result["reason"] == "recording_not_started"
    assert result["bdf_preflight"]["data_records"] == 0
    assert queue.messages[-1]["type"] == "done"
    assert queue.messages[-1]["excluded_count"] == 1


def test_run_full_pipeline_passes_project_channel_limit_to_validating_loader(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _capture_loader(_app, _filepath, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after loader argument capture")

    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        _capture_loader,
    )
    monkeypatch.setattr(process_runner, "inspect_bdf_header", lambda _path: None)
    fake_bdf = tmp_path / "reduced.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    _events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=128,
        event_map={"A": 21},
    )

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
                "max_idx_keep": None,
                "max_chan_idx_keep": 16,
                **plan_settings,
            },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "load"
    assert captured["first_n_channels"] == 16
    payload = process_runner._preproc_cache_payload(
        fake_bdf,
        {
            "max_idx_keep": None,
            "max_chan_idx_keep": 16,
        },
        mne_version=str(mne.__version__),
    )
    assert payload["loader_profile"]["bdf_first_n_channels"] == 16
    assert payload["geometry"]["retained_scalp_channels"] == list(
        process_runner.BIOSEMI64_CHANNELS[:16]
    )


def test_preproc_cache_fingerprints_effective_detector_mode_and_manual_switch(
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "detector-cache.bdf"
    fake_bdf.write_bytes(b"raw source")
    base_settings = {
        "auto_detect_removed_electrodes": False,
        "manual_removed_electrodes_enabled": False,
        "removed_electrode_detection_choice_schema_version": "1.0",
        "removed_electrode_detection_choice_status": "ready",
        "removed_electrode_detection_choice_source": "user_confirmed",
    }

    detector_off = process_runner._preproc_cache_payload(
        fake_bdf,
        base_settings,
        mne_version=str(mne.__version__),
    )
    manual_enabled = process_runner._preproc_cache_payload(
        fake_bdf,
        {**base_settings, "manual_removed_electrodes_enabled": True},
        mne_version=str(mne.__version__),
    )

    detector_settings = detector_off["preprocessing_settings"]
    assert detector_settings["removed_electrode_detection_mode"] == "off"
    assert detector_settings["auto_detect_removed_electrodes"] is False
    assert detector_settings["manual_removed_electrodes_enabled"] is False
    assert detector_settings["removed_electrode_detection_choice_schema_version"] == (
        "1.0"
    )
    assert detector_settings["removed_electrode_detection_choice_status"] == "ready"
    assert detector_settings["removed_electrode_detection_choice_source"] == (
        "user_confirmed"
    )
    assert process_runner._preproc_cache_key(detector_off) != (
        process_runner._preproc_cache_key(manual_enabled)
    )

    reviewed = process_runner._preproc_cache_payload(
        fake_bdf,
        {
            **base_settings,
            "_fpvs_kurtosis_review_decisions": {
                "Oz": {"decision": "approve", "fingerprint": "current"}
            },
        },
        mne_version=str(mne.__version__),
    )
    assert reviewed["preprocessing_settings"][
        "kurtosis_review_decisions_for_file"
    ] == {"Oz": {"decision": "approve", "fingerprint": "current"}}
    assert process_runner._preproc_cache_key(detector_off) != (
        process_runner._preproc_cache_key(reviewed)
    )


def test_interpolation_failure_keeps_requested_and_error_provenance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(
        ["Fp1", "AF7", "Status"],
        sfreq=256.0,
        ch_types=["eeg", "eeg", "stim"],
    )
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 128), dtype=float), info, verbose=False)
    )

    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(process_runner, "inspect_bdf_header", lambda _path: None)

    def _failed_interpolation(raw_input, params, *_args, **_kwargs):
        geometry = process_runner._attach_processed_geometry(raw_input, params)
        params["_fpvs_geometry"] = geometry
        params["_fpvs_retained_scalp_channels"] = ["Fp1", "AF7"]
        params["_fpvs_retained_scalp_set_fingerprint"] = geometry[
            "retained_scalp_set_fingerprint"
        ]
        params["_fpvs_interpolation_status"] = "failed"
        params["_fpvs_interpolation_requested_channels"] = ["Fp1"]
        params["_fpvs_interpolated_channels"] = []
        params["_fpvs_interpolation_error"] = "spline solve failed"
        return None, 0

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _failed_interpolation,
    )
    fake_bdf = tmp_path / "interpolation-failure.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=128,
        event_map={"A": 21},
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "max_idx_keep": 2,
                "auto_detect_removed_electrodes": False,
                "removed_electrode_detection_mode": "off",
                **plan_settings,
            },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "preprocess"
    assert result["interpolation_status"] == "failed"
    assert result["interpolation_requested_channels"] == ["Fp1"]
    assert result["interpolated_channels"] == []
    assert result["interpolation_error"] == "spline solve failed"
    assert result["audit"]["interpolation_status"] == "failed"
    assert result["audit"]["interpolation_requested_channels"] == ["Fp1"]
    assert result["audit"]["interpolated_channels"] == []
    assert result["audit"]["interpolation_error"] == "spline solve failed"
    assert result["geometry"] == result["audit"]["geometry"]


def test_run_full_pipeline_continues_after_candidate_burden_review_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    left = list(LEFT_HEMISPHERE_CHANNELS)
    right = list(RIGHT_HEMISPHERE_CHANNELS)
    midline = ["Iz", "Oz", "POz", "Pz", "CPz", "AFz", "Fz", "FCz", "Cz", "Fpz"]
    names = [*left, *midline, *right, "Status"]
    rng = np.random.default_rng(123)
    data = rng.normal(scale=500e-6, size=(len(names), 2048))
    for index, name in enumerate(names):
        if name in LEFT_HEMISPHERE_CHANNELS:
            data[index] = rng.normal(scale=2e-6, size=data.shape[1])
    info = mne.create_info(
        names,
        sfreq=256.0,
        ch_types=["eeg"] * (len(names) - 1) + ["stim"],
    )
    raw = _with_biosemi64_montage(
        mne.io.RawArray(data, info, verbose=False)
    )

    preprocess_calls: list[str] = []
    export_calls: list[str] = []

    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )

    captured: dict[str, object] = {}

    def _continue_to_preprocessing(raw_input, params, *_args, **_kwargs):  # noqa: ARG001
        preprocess_calls.append("called")
        captured["review_rules"] = list(params["_fpvs_raw_qc_review_rules"])
        captured["candidate_burden"] = list(
            params["_fpvs_raw_qc_candidate_burden_findings"]
        )
        raise RuntimeError("stop after raw QC continuation capture")

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _continue_to_preprocessing,
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        lambda *_args, **_kwargs: export_calls.append("called"),
    )

    fake_bdf = tmp_path / "p21.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=2_048,
        event_map={"A": 21},
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "max_bad_chans": 20,
            "removed_electrode_detection_mode": "auto",
            "auto_detect_removed_electrodes": True,
            **plan_settings,
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "preprocess"
    assert "left_hemisphere_candidate_burden_review" in captured["review_rules"]
    assert any(
        finding["rule"] == "left_hemisphere_candidate_burden_review"
        for finding in captured["candidate_burden"]
    )
    assert preprocess_calls == ["called"]
    assert export_calls == []


def test_run_full_pipeline_auto_marks_removed_electrode_before_preprocessing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = [*montage.ch_names, "Status"]
    rng = np.random.default_rng(321)
    data = rng.normal(scale=500e-6, size=(len(names), 4096))
    data[names.index("P9")] = rng.normal(scale=2e-6, size=data.shape[1])
    raw = mne.io.RawArray(
        data,
        mne.create_info(
            names,
            sfreq=256.0,
            ch_types=["eeg"] * (len(names) - 1) + ["stim"],
        ),
        verbose=False,
    )
    raw = _with_biosemi64_montage(raw)

    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "p03.bdf"},
    )
    captured: dict[str, object] = {}

    def _capture_preprocessing(raw_input, params, *_args, **_kwargs):
        captured["raw_bads"] = list(raw_input.info["bads"])
        captured["raw_qc_bad_channels"] = list(params["_fpvs_raw_qc_bad_channels"])
        raise RuntimeError("stop after raw QC capture")

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _capture_preprocessing,
    )

    fake_bdf = tmp_path / "p03.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=4_096,
        event_map={"A": 21},
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "max_bad_chans": 20,
            "auto_detect_removed_electrodes": True,
            **plan_settings,
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert captured["raw_bads"] == ["P9"]
    assert captured["raw_qc_bad_channels"] == ["P9"]


def test_run_full_pipeline_manual_removed_electrodes_supersede_auto_detection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = [*montage.ch_names, "Status"]
    rng = np.random.default_rng(322)
    data = rng.normal(scale=500e-6, size=(len(names), 4096))
    data[names.index("P9")] = rng.normal(scale=2e-6, size=data.shape[1])
    raw = mne.io.RawArray(
        data,
        mne.create_info(
            names,
            sfreq=256.0,
            ch_types=["eeg"] * (len(names) - 1) + ["stim"],
        ),
        verbose=False,
    )
    raw = _with_biosemi64_montage(raw)

    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "p03.bdf"},
    )
    captured: dict[str, object] = {}

    def _capture_preprocessing(raw_input, params, *_args, **_kwargs):
        captured["raw_bads"] = list(raw_input.info["bads"])
        captured["raw_qc_bad_channels"] = list(params["_fpvs_raw_qc_bad_channels"])
        captured["manual_channels"] = list(
            params["_fpvs_raw_qc_manual_removed_channels"]
        )
        captured["low_variance_channels"] = list(
            params["_fpvs_raw_qc_low_variance_channels"]
        )
        raise RuntimeError("stop after manual raw QC capture")

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _capture_preprocessing,
    )

    fake_bdf = tmp_path / "p03.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256.0,
        n_times=4_096,
        event_map={"A": 21},
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "max_bad_chans": 20,
            "auto_detect_removed_electrodes": True,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {"P03": ["FT8"]},
            "_fpvs_participant_id_by_file": {
                str(fake_bdf.resolve()): "P03",
            },
            **plan_settings,
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert captured["raw_bads"] == ["FT8"]
    assert captured["raw_qc_bad_channels"] == ["FT8"]
    assert captured["manual_channels"] == ["FT8"]
    assert captured["low_variance_channels"] == []


def test_run_full_pipeline_publishes_available_source_conditions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(["Cz", "Pz", "Status"], sfreq=8.0, ch_types=["eeg", "eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    )
    events = np.asarray(
        [
            [8, 0, 21],
            [10, 0, 55],
            [14, 0, 55],
            [32, 0, 21],
            [34, 0, 55],
            [38, 0, 55],
        ],
        dtype=int,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "fake.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _passthrough_preprocessing_with_realized_spans,
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _capture_post_export(ctx, _labels):
        captured["epochs_dict"] = ctx.preprocessed_data
        ctx.export_timing_records.append(
            {"source": "post_process", "stage": "workbook_write", "elapsed_ms": 7}
        )
        ctx.export_receipts.append(
            {
                "condition_label": "A",
                "occurrence_key": "21:0",
                "status": "written",
            }
        )
        return 1

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _capture_post_export,
    )

    def _capture_source_derivative(**kwargs):
        captured["source_derivative_kwargs"] = kwargs
        source_root = tmp_path / "project" / "6 - Source Localization"
        return SimpleNamespace(
            participant_id="fake",
            artifacts=(
                SimpleNamespace(
                    fif_path=source_root / "fake_A_avg_raw.fif",
                    sidecar_path=source_root / "fake_A_avg_raw.json",
                ),
            ),
            manifest_path=source_root / "manifests" / "fake.json",
        )

    monkeypatch.setattr(
        process_runner,
        "write_source_ready_time_domain_derivatives",
        _capture_source_derivative,
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"fake bdf")

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "_fpvs_processing_fingerprint": "fixture-fingerprint",
            "_fpvs_processing_fingerprint_version": "fixture-version",
            **_protocol_settings(
                file_path=fake_bdf,
                events=events,
                event_map={"A": 21, "B": 22},
                sfreq=8,
                n_times=64,
                presentation_rate_hz=4,
                oddball_every_n=2,
                expected_cycles=1,
            ),
        },
        event_map={"A": 21, "B": 22},
        save_folder=tmp_path / "out",

        project_root=tmp_path / "project",
    )

    assert result["status"] == "ok"
    assert "epochs_dict" in captured
    assert captured["epochs_dict"]["B"] == []
    epochs = captured["epochs_dict"]["A"][0]
    assert epochs.get_data().shape == (2, 3, 4)
    assert epochs.metadata["crop_mode"].tolist() == [
        "project_marker_plan_target_grid_v2",
        "project_marker_plan_target_grid_v2",
    ]
    assert epochs.metadata["N_step"].tolist() == [4, 4]
    assert epochs.metadata["N_mod_step"].tolist() == [0, 0]
    assert epochs.metadata["fallback_reason"].tolist() == ["", ""]
    assert epochs.metadata["occurrence_key"].tolist() == ["21:0", "21:1"]
    assert epochs.metadata["repetition_index"].tolist() == [0, 1]
    assert result["preproc_cache_status"] == "disabled"
    assert "events" in result["timings_ms"]
    assert "epochs" in result["timings_ms"]
    assert result["export_timing_records"] == [
        {"source": "post_process", "stage": "workbook_write", "elapsed_ms": 7}
    ]
    assert result["export_receipts"] == [
        {
            "condition_label": "A",
            "occurrence_key": "21:0",
            "status": "written",
        }
    ]
    source_kwargs = captured["source_derivative_kwargs"]
    assert tuple(source_kwargs["condition_epochs"]) == ("A",)
    assert (
        source_kwargs["condition_epochs"]["A"]
        is captured["epochs_dict"]["A"]
    )
    assert source_kwargs["condition_ids"] == {"A": 21}
    provenance = source_kwargs["processing_provenance"]
    assert provenance["processing_fingerprint"] == "fixture-fingerprint"
    assert provenance["processing_fingerprint_version"] == "fixture-version"
    assert (
        provenance["preprocessing_order_version"]
        == process_runner.backend_preprocess.PREPROCESSING_ORDER_VERSION
    )
    assert provenance["preprocessed_raw_cache_version"] == (
        process_runner.PREPROC_CACHE_VERSION
    )
    assert provenance["geometry"] == biosemi64_geometry_identity(
        retained_channels=("Cz", "Pz")
    )
    assert provenance["analysis_span_plan_version"] == "analysis_span_plan_v1"
    assert provenance["source_analysis_span_plan"]["fingerprint"]
    assert provenance["realized_analysis_span_plan"]["fingerprint"]
    assert result["source_derivative_status"] == "complete"
    assert result["source_derivative_warning"] == ""
    assert result["source_derivative_manifest"].endswith("manifests/fake.json")
    assert not Path(result["source_derivative_manifest"]).is_absolute()
    assert all(
        not Path(path).is_absolute()
        for path in result["source_derivative_outputs"]
    )
    assert len(result["source_derivative_outputs"]) == 3


def test_run_full_pipeline_returns_partial_receipts_when_export_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(
        ["Cz", "Pz", "Status"],
        sfreq=8.0,
        ch_types=["eeg", "eeg", "stim"],
    )
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    )
    events = np.asarray(
        [
            [8, 0, 21],
            [10, 0, 55],
            [14, 0, 55],
            [32, 0, 21],
            [34, 0, 55],
            [38, 0, 55],
        ],
        dtype=int,
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "export-failure.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _passthrough_preprocessing_with_realized_spans,
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _fail_after_one_receipt(ctx, _labels):
        ctx.export_receipts.append(
            {
                "condition_label": "A",
                "occurrence_key": "21:0",
                "status": "written",
            }
        )
        raise RuntimeError("fixture export failure")

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _fail_after_one_receipt,
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "export-failure.bdf"
    fake_bdf.write_bytes(b"fake bdf")
    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            **_protocol_settings(
                file_path=fake_bdf,
                events=events,
                event_map={"A": 21},
                sfreq=8,
                n_times=64,
                presentation_rate_hz=4,
                oddball_every_n=2,
                expected_cycles=1,
            ),
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "export"
    assert result["export_receipts"] == [
        {
            "condition_label": "A",
            "occurrence_key": "21:0",
            "status": "written",
        }
    ]


def test_run_full_pipeline_uses_one_project_oddball_marker_across_conditions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(["Cz", "Pz", "Status"], sfreq=256.0, ch_types=["eeg", "eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 5000), dtype=float), info, verbose=False)
    )
    events = np.asarray(
        [
            [100, 0, 1],
            [200, 0, 55],
            [413, 0, 55],
            [627, 0, 55],
            [840, 0, 55],
            [2200, 0, 2],
            [2300, 0, 55],
            [2513, 0, 55],
            [2727, 0, 55],
            [2940, 0, 55],
        ],
        dtype=int,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "condition-specific.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        _passthrough_preprocessing_with_realized_spans,
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _capture_post_export(ctx, _labels):
        captured["epochs_dict"] = ctx.preprocessed_data
        return 1

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _capture_post_export,
    )

    def _failed_source_derivative(**_kwargs):
        raise RuntimeError("fixture source derivative failure")

    monkeypatch.setattr(
        process_runner,
        "write_source_ready_time_domain_derivatives",
        _failed_source_derivative,
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "condition-specific.bdf"
    fake_bdf.write_bytes(b"fake bdf")

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            "_fpvs_processing_fingerprint": "fixture-fingerprint",
            "_fpvs_processing_fingerprint_version": "fixture-version",
            **_protocol_settings(
                file_path=fake_bdf,
                events=events,
                event_map={"fruit": 1, "veg": 2},
                sfreq=256,
                n_times=5000,
                presentation_rate_hz=6,
                oddball_every_n=5,
                expected_cycles=3,
            ),
        },
        event_map={"fruit": 1, "veg": 2},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "ok"
    fruit_epochs = captured["epochs_dict"]["fruit"][0]
    veg_epochs = captured["epochs_dict"]["veg"][0]
    assert fruit_epochs.metadata["crop_mode"].tolist() == [
        "project_marker_plan_target_grid_v2"
    ]
    assert veg_epochs.metadata["crop_mode"].tolist() == [
        "project_marker_plan_target_grid_v2"
    ]
    assert fruit_epochs.metadata["oddball_id"].tolist() == [55]
    assert veg_epochs.metadata["oddball_id"].tolist() == [55]
    assert int(fruit_epochs.get_data().shape[2]) % 640 == 0
    assert int(veg_epochs.get_data().shape[2]) % 640 == 0
    assert result["post_export_ok"] is True
    assert result["source_derivative_status"] == "incomplete"
    assert result["source_derivative_outputs"] == []
    assert result["source_derivative_warning"] == "fixture source derivative failure"


def test_run_full_pipeline_hard_fails_when_locked_fft_crop_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(["Cz", "Pz", "Status"], sfreq=8.0, ch_types=["eeg", "eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    )
    events = np.asarray(
        [
            [8, 0, 21],
            [10, 0, 55],
            [14, 0, 55],
            [32, 0, 21],
            [34, 0, 55],
        ],
        dtype=int,
    )
    post_export_calls: list[str] = []

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "fake.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        lambda raw_input, params, log_func, filename_for_log: (raw_input, 0),
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, **_kwargs: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _unexpected_post_export(_ctx, _labels):
        post_export_calls.append("called")
        return 1

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _unexpected_post_export,
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"fake bdf")

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
            **_protocol_settings(
                file_path=fake_bdf,
                events=events,
                event_map={"A": 21},
                sfreq=8,
                n_times=64,
                presentation_rate_hz=4,
                oddball_every_n=2,
                expected_cycles=1,
            ),
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "preflight"
    assert "require review" in str(result["error"])
    assert post_export_calls == []


def test_preprocessed_cache_round_trip_preserves_audit_metadata(tmp_path: Path) -> None:
    info = mne.create_info(["Fp1", "Status"], sfreq=8.0, ch_types=["eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((2, 16), dtype=float), info, verbose=False)
    )
    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"raw source")
    settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "downsample_rate": 8,
        "max_idx_keep": 1,
        "enable_preprocessed_cache": True,
        "auto_detect_removed_electrodes": True,
        "_fpvs_raw_qc_bad_channels": ["P9"],
        "_fpvs_raw_qc_low_variance_channels": ["P9"],
        "_fpvs_raw_qc_high_amplitude_channels": [],
        "_fpvs_raw_qc_rare_burst_channels": ["P10"],
        "_fpvs_raw_qc_spatial_outlier_channels": [],
        "_fpvs_raw_qc_manual_removed_channels": ["P9"],
        "_fpvs_raw_qc_method_version": RAW_CHANNEL_QC_METHOD_VERSION,
        "_fpvs_raw_qc_review_rules": ["candidate_count_review"],
        "_fpvs_raw_qc_candidate_sources": {
            "P9": ["low_variance"],
            "P10": ["rare_burst"],
        },
        "_fpvs_raw_qc_candidate_burden_findings": [
            {
                "rule": "candidate_count_review",
                "authority": "review_only",
                "observed": 21,
                "threshold": 20,
                "comparator": ">",
                "channels": ["P9", "P10"],
            }
        ],
        "_fpvs_raw_qc_amplitude_review_findings": [
            {
                "scope": "recording_analyzed_interval_union",
                "severity": "severe_review",
                "authority": "review_only",
            }
        ],
        "_fpvs_raw_qc_baseline_severe_review": True,
        "_fpvs_raw_qc_baseline_median_std_uv": 520.4,
        "_fpvs_raw_qc_baseline_median_p2p_99_uv": 1671.6,
        "_fpvs_raw_qc_baseline_warning": False,
        "_fpvs_raw_qc_baseline_excluded": False,
        "_fpvs_removed_electrode_original_auto_flagged": ["FT7"],
        "_fpvs_removed_electrode_accepted_auto_flagged": ["FT7"],
        "_fpvs_removed_electrode_rejected_auto_flagged": [],
        "_fpvs_removed_electrode_manual_additions": ["P9"],
        "_fpvs_removed_electrode_final_confirmed_removed": ["FT7", "P9"],
        "_fpvs_removed_electrode_manual_only_missed_by_auto": ["P9"],
        "_fpvs_removed_electrode_auto_manual_overlap": ["FT7"],
        "_fpvs_removed_electrode_agreement_status": "partial",
        "_fpvs_kurtosis_bad_channels": ["Cz"],
        "_fpvs_interpolation_status": "succeeded",
        "_fpvs_interpolation_requested_channels": ["P9", "Cz"],
        "_fpvs_interpolated_channels": ["P9", "Cz"],
        "_fpvs_interpolation_error": "",
        "_fpvs_fft_multinotch_requested_centers_hz": [60.0, 120.0, 180.0],
        "_fpvs_fft_multinotch_applied_centers_hz": [60.0],
        "_fpvs_fft_multinotch_skipped_centers": [
            {"center_hz": 120.0, "reason": "above_low_pass_transition"},
            {"center_hz": 180.0, "reason": "above_low_pass_transition"},
        ],
    }
    load_settings = dict(settings)
    load_settings.pop("_fpvs_raw_qc_bad_channels")
    load_settings.pop("_fpvs_raw_qc_low_variance_channels")
    load_settings.pop("_fpvs_raw_qc_high_amplitude_channels")
    load_settings.pop("_fpvs_raw_qc_rare_burst_channels")
    load_settings.pop("_fpvs_raw_qc_spatial_outlier_channels")
    load_settings.pop("_fpvs_raw_qc_manual_removed_channels")
    load_settings.pop("_fpvs_raw_qc_method_version")
    load_settings.pop("_fpvs_raw_qc_review_rules")
    load_settings.pop("_fpvs_raw_qc_candidate_sources")
    load_settings.pop("_fpvs_raw_qc_candidate_burden_findings")
    load_settings.pop("_fpvs_raw_qc_amplitude_review_findings")
    load_settings.pop("_fpvs_raw_qc_baseline_severe_review")
    load_settings.pop("_fpvs_raw_qc_baseline_median_std_uv")
    load_settings.pop("_fpvs_raw_qc_baseline_median_p2p_99_uv")
    load_settings.pop("_fpvs_raw_qc_baseline_warning")
    load_settings.pop("_fpvs_raw_qc_baseline_excluded")
    load_settings.pop("_fpvs_removed_electrode_original_auto_flagged")
    load_settings.pop("_fpvs_removed_electrode_accepted_auto_flagged")
    load_settings.pop("_fpvs_removed_electrode_rejected_auto_flagged")
    load_settings.pop("_fpvs_removed_electrode_manual_additions")
    load_settings.pop("_fpvs_removed_electrode_final_confirmed_removed")
    load_settings.pop("_fpvs_removed_electrode_manual_only_missed_by_auto")
    load_settings.pop("_fpvs_removed_electrode_auto_manual_overlap")
    load_settings.pop("_fpvs_removed_electrode_agreement_status")
    load_settings.pop("_fpvs_kurtosis_bad_channels")
    load_settings.pop("_fpvs_interpolation_status")
    load_settings.pop("_fpvs_interpolation_requested_channels")
    load_settings.pop("_fpvs_interpolated_channels")
    load_settings.pop("_fpvs_interpolation_error")
    load_settings.pop("_fpvs_fft_multinotch_requested_centers_hz")
    load_settings.pop("_fpvs_fft_multinotch_applied_centers_hz")
    load_settings.pop("_fpvs_fft_multinotch_skipped_centers")
    audit_before = {"file": "fake.bdf", "ch_names": ["Cz", "EXG1", "EXG2", "Status"]}
    payload = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
    )

    stored = process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=settings,
        project_root=tmp_path / "project",
        mne_module=mne,
        audit_before=audit_before,
        n_rejected=2,
    )
    loaded, loaded_audit, n_rejected, status = process_runner._load_preprocessed_cache(
        file_path=fake_bdf,
        settings=load_settings,
        project_root=tmp_path / "project",
        mne_module=mne,
    )

    assert stored == "stored"
    assert payload["version"] == (
        "preprocessed-raw-v12-condition-scope-kurtosis-review"
    )
    assert payload["geometry"] == biosemi64_geometry_identity(
        retained_channels=("Fp1",)
    )
    assert payload["preprocessing_settings"]["line_noise_filter_enabled"] is True
    assert payload["preprocessing_settings"]["line_noise_frequency_hz"] == 60
    assert payload["preprocessing_settings"]["line_noise_filter_method_version"]
    assert payload["preprocessing_settings"]["line_noise_filter_half_width_hz"] == 0.5
    assert payload["preprocessing_settings"]["line_noise_filter_component_count"] == 3
    assert payload["preprocessing_settings"]["raw_channel_qc_method_version"] == (
        RAW_CHANNEL_QC_METHOD_VERSION
    )
    assert status == "hit"
    assert loaded is not None
    assert loaded.get_data().shape == raw.get_data().shape
    assert loaded_audit == audit_before
    assert n_rejected == 2
    assert load_settings["_fpvs_raw_qc_bad_channels"] == ["P9"]
    assert load_settings["_fpvs_raw_qc_low_variance_channels"] == ["P9"]
    assert load_settings["_fpvs_raw_qc_high_amplitude_channels"] == []
    assert load_settings["_fpvs_raw_qc_rare_burst_channels"] == ["P10"]
    assert load_settings["_fpvs_raw_qc_spatial_outlier_channels"] == []
    assert load_settings["_fpvs_raw_qc_manual_removed_channels"] == ["P9"]
    assert load_settings["_fpvs_raw_qc_method_version"] == RAW_CHANNEL_QC_METHOD_VERSION
    assert load_settings["_fpvs_raw_qc_review_rules"] == ["candidate_count_review"]
    assert load_settings["_fpvs_raw_qc_candidate_sources"] == {
        "P9": ["low_variance"],
        "P10": ["rare_burst"],
    }
    assert load_settings["_fpvs_raw_qc_candidate_burden_findings"][0]["rule"] == (
        "candidate_count_review"
    )
    assert load_settings["_fpvs_raw_qc_amplitude_review_findings"][0][
        "severity"
    ] == "severe_review"
    assert load_settings["_fpvs_raw_qc_baseline_severe_review"] is True
    assert load_settings["_fpvs_raw_qc_baseline_median_std_uv"] == 520.4
    assert load_settings["_fpvs_raw_qc_baseline_median_p2p_99_uv"] == 1671.6
    assert load_settings["_fpvs_raw_qc_baseline_warning"] is False
    assert load_settings["_fpvs_raw_qc_baseline_excluded"] is False
    assert load_settings["_fpvs_removed_electrode_original_auto_flagged"] == ["FT7"]
    assert load_settings["_fpvs_removed_electrode_accepted_auto_flagged"] == ["FT7"]
    assert load_settings["_fpvs_removed_electrode_rejected_auto_flagged"] == []
    assert load_settings["_fpvs_removed_electrode_manual_additions"] == ["P9"]
    assert load_settings["_fpvs_removed_electrode_final_confirmed_removed"] == [
        "FT7",
        "P9",
    ]
    assert load_settings["_fpvs_removed_electrode_manual_only_missed_by_auto"] == [
        "P9"
    ]
    assert load_settings["_fpvs_removed_electrode_auto_manual_overlap"] == ["FT7"]
    assert load_settings["_fpvs_removed_electrode_agreement_status"] == "partial"
    assert load_settings["_fpvs_kurtosis_bad_channels"] == ["Cz"]
    assert load_settings["_fpvs_interpolation_status"] == "succeeded"
    assert load_settings["_fpvs_interpolation_requested_channels"] == ["P9", "Cz"]
    assert load_settings["_fpvs_interpolated_channels"] == ["P9", "Cz"]
    assert load_settings["_fpvs_interpolation_error"] == ""
    assert load_settings["_fpvs_geometry"] == biosemi64_geometry_identity(
        retained_channels=("Fp1",)
    )
    assert load_settings["_fpvs_retained_scalp_channels"] == ["Fp1"]
    assert load_settings["_fpvs_retained_scalp_set_fingerprint"]
    assert load_settings["_fpvs_fft_multinotch_requested_centers_hz"] == [
        60.0,
        120.0,
        180.0,
    ]
    assert load_settings["_fpvs_fft_multinotch_applied_centers_hz"] == [60.0]
    assert load_settings["_fpvs_fft_multinotch_skipped_centers"] == [
        {"center_hz": 120.0, "reason": "above_low_pass_transition"},
        {"center_hz": 180.0, "reason": "above_low_pass_transition"},
    ]


def test_preprocessed_cache_identity_and_hit_require_current_span_plan(
    tmp_path: Path,
) -> None:
    info = mne.create_info(["Fp1", "Status"], sfreq=8.0, ch_types=["eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((2, 16), dtype=float), info, verbose=False)
    )
    fake_bdf = tmp_path / "span-cache.bdf"
    fake_bdf.write_bytes(b"raw source")
    event_map = {"A": 21}
    events = np.asarray(
        [[0, 0, 21], [2, 0, 55], [6, 0, 55]],
        dtype=int,
    )
    protocol_settings = _protocol_settings(
        file_path=fake_bdf,
        events=events,
        event_map=event_map,
        sfreq=8,
        n_times=16,
        presentation_rate_hz=4,
        oddball_every_n=2,
        expected_cycles=1,
    )
    event_plan = protocol_settings["_fpvs_preflight_event_plans_by_file"][
        str(fake_bdf.resolve())
    ]
    source_plan = read_source_analysis_span_plan(event_plan)
    target_plan = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=8,
        target_n_times=16,
        target_first_samp=0,
    )
    settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "downsample_rate": 8,
        "max_idx_keep": 1,
        "enable_preprocessed_cache": True,
        "_fpvs_require_analysis_spans": True,
        "_fpvs_source_analysis_span_plan": source_plan,
        "_fpvs_realized_analysis_span_plan": target_plan,
    }
    payload = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
    )
    assert payload["analysis_span_plan"]["fingerprint"] == source_plan[
        "fingerprint"
    ]
    assert process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=settings,
        project_root=tmp_path / "project",
        mne_module=mne,
        audit_before={"file": fake_bdf.name},
        n_rejected=0,
    ) == "stored"

    cache_key = process_runner._preproc_cache_key(payload)
    _raw_path, meta_path = process_runner._preproc_cache_paths(
        tmp_path / "project",
        fake_bdf,
        cache_key,
    )
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("realized_analysis_span_plan")
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    loaded, _audit, _n_rejected, status = process_runner._load_preprocessed_cache(
        file_path=fake_bdf,
        settings={
            **settings,
            "_fpvs_realized_analysis_span_plan": None,
        },
        project_root=tmp_path / "project",
        mne_module=mne,
    )
    assert loaded is None
    assert status == "miss_missing_analysis_spans"


def test_preprocessed_cache_key_binds_current_protocol_and_condition_map(
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "context-cache.bdf"
    fake_bdf.write_bytes(b"raw source")
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    changed_marker_protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        oddball_marker_code=56,
    )
    settings = {"stim_channel": "Status", "max_idx_keep": 64}

    original = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
        frequency_protocol=protocol,
        event_map={"Faces": 21},
    )
    changed_protocol = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
        frequency_protocol=changed_marker_protocol,
        event_map={"Faces": 21},
    )
    changed_event_map = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
        frequency_protocol=protocol,
        event_map={"Objects": 21},
    )

    assert original["frequency_protocol"] == {
        "canonical_payload": protocol.canonical_payload(),
        "fingerprint": protocol.fingerprint,
    }
    assert original["condition_event_map"] == {"Faces": 21}
    assert process_runner._preproc_cache_key(original) != (
        process_runner._preproc_cache_key(changed_protocol)
    )
    assert process_runner._preproc_cache_key(original) != (
        process_runner._preproc_cache_key(changed_event_map)
    )


def test_runner_rejects_stale_event_map_before_cache_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_bdf = tmp_path / "stale-plan.bdf"
    fake_bdf.write_bytes(b"raw source")
    _events, plan_settings = _analysis_plan_fixture(
        file_path=fake_bdf,
        sfreq=256,
        n_times=128,
        event_map={"Faces": 21},
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.inspect_bdf_header",
        lambda _path: None,
    )
    monkeypatch.setattr(
        process_runner,
        "_load_preprocessed_cache",
        lambda **_kwargs: pytest.fail("stale context reached cache lookup"),
    )

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "enable_preprocessed_cache": True,
            **plan_settings,
        },
        event_map={"Objects": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "preflight"
    assert "event map is stale" in str(result["error"])


def test_preprocessed_cache_key_tracks_fft_multinotch_settings(tmp_path: Path) -> None:
    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"raw source")
    base_settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": 60,
    }

    enabled_60 = process_runner._preproc_cache_payload(
        fake_bdf,
        base_settings,
        mne_version=str(mne.__version__),
    )
    enabled_50 = process_runner._preproc_cache_payload(
        fake_bdf,
        {**base_settings, "line_noise_frequency_hz": 50},
        mne_version=str(mne.__version__),
    )
    disabled = process_runner._preproc_cache_payload(
        fake_bdf,
        {**base_settings, "line_noise_filter_enabled": False},
        mne_version=str(mne.__version__),
    )

    assert process_runner._preproc_cache_key(enabled_60) != process_runner._preproc_cache_key(
        enabled_50
    )
    assert process_runner._preproc_cache_key(enabled_60) != process_runner._preproc_cache_key(
        disabled
    )


def test_preprocessed_cache_prunes_old_entries_for_same_source(tmp_path: Path) -> None:
    info = mne.create_info(["Fp1", "Status"], sfreq=8.0, ch_types=["eeg", "stim"])
    raw = _with_biosemi64_montage(
        mne.io.RawArray(np.zeros((2, 16), dtype=float), info, verbose=False)
    )
    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"raw source")
    project_root = tmp_path / "project"
    base_settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "downsample_rate": 8,
        "max_idx_keep": 1,
        "enable_preprocessed_cache": True,
    }
    old_settings = dict(base_settings, high_pass=0.1)
    new_settings = dict(base_settings, high_pass=1.0)

    assert process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=old_settings,
        project_root=project_root,
        mne_module=mne,
        audit_before={"file": "fake.bdf", "version": "old"},
        n_rejected=1,
    ) == "stored"
    old_payload = process_runner._preproc_cache_payload(
        fake_bdf,
        old_settings,
        mne_version=str(mne.__version__),
    )
    old_raw_path, old_meta_path = process_runner._preproc_cache_paths(
        project_root,
        fake_bdf,
        process_runner._preproc_cache_key(old_payload),
    )

    assert old_raw_path.exists()
    assert old_meta_path.exists()

    assert process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=new_settings,
        project_root=project_root,
        mne_module=mne,
        audit_before={"file": "fake.bdf", "version": "new"},
        n_rejected=2,
    ) == "stored"
    new_payload = process_runner._preproc_cache_payload(
        fake_bdf,
        new_settings,
        mne_version=str(mne.__version__),
    )
    new_raw_path, new_meta_path = process_runner._preproc_cache_paths(
        project_root,
        fake_bdf,
        process_runner._preproc_cache_key(new_payload),
    )

    assert not old_raw_path.exists()
    assert not old_meta_path.exists()
    assert new_raw_path.exists()
    assert new_meta_path.exists()
    _, loaded_audit, n_rejected, status = process_runner._load_preprocessed_cache(
        file_path=fake_bdf,
        settings=new_settings,
        project_root=project_root,
        mne_module=mne,
    )
    assert status == "hit"
    assert loaded_audit == {"file": "fake.bdf", "version": "new"}
    assert n_rejected == 2


def test_preprocessed_cache_prune_scopes_scan_by_sanitized_source_stem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    source_path = (tmp_path / "Subject.01.bdf").resolve()
    colliding_source_path = (tmp_path / "Subject_01.bdf").resolve()
    unrelated_source_path = (tmp_path / "Other.bdf").resolve()
    _, keep_meta_path = process_runner._preproc_cache_paths(
        project_root,
        source_path,
        "a" * 64,
    )
    old_raw_path, old_meta_path = process_runner._preproc_cache_paths(
        project_root,
        source_path,
        "b" * 64,
    )
    collision_raw_path, collision_meta_path = process_runner._preproc_cache_paths(
        project_root,
        colliding_source_path,
        "c" * 64,
    )
    unrelated_raw_path, unrelated_meta_path = process_runner._preproc_cache_paths(
        project_root,
        unrelated_source_path,
        "d" * 64,
    )
    assert process_runner._preproc_cache_safe_stem(
        source_path
    ) == process_runner._preproc_cache_safe_stem(colliding_source_path)

    def write_entry(meta_path: Path, raw_path: Path, payload_source: Path) -> None:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({"payload": {"source_path": str(payload_source)}}),
            encoding="utf-8",
        )
        raw_path.write_bytes(b"cached raw")

    keep_raw_path = process_runner._raw_cache_path_for_meta(keep_meta_path)
    write_entry(keep_meta_path, keep_raw_path, source_path)
    write_entry(old_meta_path, old_raw_path, source_path)
    write_entry(
        collision_meta_path,
        collision_raw_path,
        colliding_source_path,
    )
    write_entry(
        unrelated_meta_path,
        unrelated_raw_path,
        unrelated_source_path,
    )
    original_read_text = Path.read_text
    read_paths: list[Path] = []

    def tracked_read_text(self: Path, *args, **kwargs) -> str:
        read_paths.append(self)
        if self == unrelated_meta_path:
            pytest.fail("unrelated cache metadata should not be read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)

    pruned = process_runner._prune_stale_preprocessed_cache(
        cache_dir=keep_meta_path.parent,
        source_path=str(source_path),
        keep_meta_path=keep_meta_path,
    )

    assert pruned == 1
    assert not old_meta_path.exists()
    assert not old_raw_path.exists()
    assert keep_meta_path.exists()
    assert keep_raw_path.exists()
    assert collision_meta_path.exists()
    assert collision_raw_path.exists()
    assert collision_meta_path in read_paths
    assert unrelated_meta_path.exists()
    assert unrelated_raw_path.exists()
    assert unrelated_meta_path not in read_paths
