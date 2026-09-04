from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS, BIOSEMI64_MONTAGE_ID
from Main_App.processing import kurtosis_review_scan as scan_module
from Main_App.processing.kurtosis_qc import (
    KURTOSIS_DECISION_APPROVE,
    build_kurtosis_review_decision,
)
from Main_App.processing.kurtosis_review_scan import (
    KURTOSIS_REVIEW_FILE_STATUS_ERROR,
    KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED,
    KURTOSIS_REVIEW_FILE_STATUS_SKIPPED,
    KURTOSIS_REVIEW_PENDING_NEW,
    KURTOSIS_REVIEW_PENDING_STALE,
    KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
    KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED,
    reconcile_kurtosis_review_decisions,
    scan_kurtosis_review,
)
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol


class _FakeRaw:
    def __init__(self) -> None:
        self.info = {"sfreq": 100.0}
        self.n_times = 1_000
        self.first_samp = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _protocol() -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        10,
        5,
        expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _settings(**updates: object) -> dict[str, object]:
    result: dict[str, object] = {
        "frequency_protocol": _protocol(),
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "stim_channel": "Status",
        "max_idx_keep": 64,
        "reject_thresh": 5.0,
        "removed_electrode_detection_mode": "manual",
        "manual_removed_electrodes_enabled": True,
        "manual_removed_electrodes": {"P01": ["Fp2"]},
    }
    result.update(updates)
    return result


def _info(path, participant: str, recording: str | None = None):  # noqa: ANN001
    return SimpleNamespace(
        path=path,
        subject_id=participant,
        recording_id=recording,
        session_id="session-1" if recording else None,
        session_label="Visit 1" if recording else None,
        visit_index=1 if recording else None,
    )


def _source_plan(*conditions: str) -> dict[str, object]:
    return {
        "spans": [
            {"condition_label": condition, "occurrence_key": f"{index}:1"}
            for index, condition in enumerate(conditions, start=1)
        ]
    }


def _prepared(
    *,
    condition: str = "Objects",
    ready: bool = False,
    raw_kurtosis: float = 12.25,
) -> dict[str, object]:
    channel = BIOSEMI64_CHANNELS[0]
    channel_evidence: dict[str, object] = {
        "channel": channel,
        "raw_kurtosis": raw_kurtosis,
        "signed_z": -6.125,
        "threshold": 5.0,
        "exceeds_threshold": True,
        "validity": "valid",
        "validity_reason": None,
    }
    channel_evidence["fingerprint"] = _fingerprint(channel_evidence)
    evidence: dict[str, object] = {
        "method_version": "eeglab_inspired_trimmed_kurtosis_v1",
        "corroborator_registry_version": "kurtosis_corroborators_v1_empty",
        "scoring_scope": {
            "analysis_span_fingerprint": "b" * 64,
            "occurrences": [
                {
                    "condition_label": condition,
                    "repetition_index": 0,
                    "occurrence_key": "2:0",
                }
            ],
        },
        "channels": [channel_evidence],
    }
    evidence["fingerprint"] = _fingerprint(evidence)
    return {
        "evidence": evidence,
        "decision_plan": {
            "ready_for_interpolation": ready,
            "blocking_reasons": [] if ready else [f"review_required:{channel}"],
            "channel_decisions": (
                []
                if ready
                else [
                    {
                        "channel": channel,
                        "state": "review_required",
                        "corroborator_assessments": [
                            {
                                "eligible": False,
                                "reason": "method_not_registered",
                                "finding": {
                                    "method_id": "experimental_detector",
                                    "method_version": "v1",
                                    "authority": "review_only",
                                },
                            }
                        ],
                    }
                ]
            ),
        },
        "signal_preview": {
            "unit": "uV",
            "source_sample_count": 501,
            "channels": {channel: [-2.0, 0.5, None, 3.0]},
        },
    }


def _configure_active_scan(
    monkeypatch,
    *,
    loaded_raws: list[_FakeRaw],
    prepared: dict[str, object] | None = None,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _load(_app, filepath: str, **kwargs):  # noqa: ANN001
        captured.setdefault("loader_calls", []).append((filepath, kwargs))
        raw = _FakeRaw()
        loaded_raws.append(raw)
        return raw

    monkeypatch.setattr(scan_module.load_utils, "load_eeg_file", _load)
    monkeypatch.setattr(
        scan_module,
        "validate_raw_biosemi64_geometry",
        lambda raw, **kwargs: captured.setdefault("geometry", (raw, kwargs)),
    )
    monkeypatch.setattr(
        scan_module,
        "_find_raw_events",
        lambda raw, *, stim_channel: ([[0, 0, 1]], "stim"),
    )
    monkeypatch.setattr(
        scan_module,
        "validate_source_analysis_span_context",
        lambda **kwargs: _source_plan("Faces", "Objects"),
    )

    def _validate_plan(**kwargs):  # noqa: ANN003
        captured["validated_plan"] = kwargs
        return _source_plan("Faces", "Objects")

    monkeypatch.setattr(scan_module, "validate_source_analysis_span_plan", _validate_plan)

    def _restrict(plan, *, excluded_condition_labels, exclusion_scope):  # noqa: ANN001
        captured["excluded_conditions"] = tuple(excluded_condition_labels)
        captured["exclusion_scope"] = dict(exclusion_scope)
        excluded = {value.casefold() for value in excluded_condition_labels}
        return {"spans": [row for row in plan["spans"] if row["condition_label"].casefold() not in excluded]}

    monkeypatch.setattr(
        scan_module,
        "restrict_source_analysis_span_plan_by_condition",
        _restrict,
    )

    def _prepare(raw, params, log_func, filename, *, direct_bad_channels):  # noqa: ANN001
        captured["prepare"] = {
            "raw": raw,
            "params": params,
            "filename": filename,
            "direct_bad_channels": tuple(direct_bad_channels),
        }
        log_func("prepared")
        return prepared or _prepared()

    monkeypatch.setattr(scan_module, "prepare_kurtosis_review_evidence", _prepare)
    return captured


def test_scan_validates_raw_and_limits_evidence_to_current_conditions(
    tmp_path,
    monkeypatch,
) -> None:
    path = (tmp_path / "P01_visit-1.bdf").resolve()
    path.touch()
    loaded: list[_FakeRaw] = []
    captured = _configure_active_scan(monkeypatch, loaded_raws=loaded)
    progress: list[tuple[str, int, int]] = []

    scan = scan_kurtosis_review(
        [_info(path, "P01", "P01__visit-1")],
        _settings(
            manual_excluded_participant_conditions={"p01": ["faces"]},
        ),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={str(path): {"reviewed": True}},
        raw_channel_qc_by_recording={
            "p01__VISIT-1": {
                "candidate_sources": {"fp1": ["high_amplitude"]},
                "high_amplitude_channels": ["FP1"],
                "spatial_outlier_channels": ["Fp1"],
                "transient_high_amplitude_channels": ["fP1"],
                "transient_review_findings": [
                    {
                        "channel": "FP1",
                        "condition_label": "Objects",
                        "occurrence": 0,
                        "category": "high_amplitude",
                    }
                ],
            }
        },
        progress=lambda message, completed, total: progress.append((message, completed, total)),
    )

    assert scan.cancelled is False
    assert not scan.errors
    assert len(scan.results) == 1
    result = scan.results[0]
    assert result.status == KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED
    assert result.analyzed_conditions == ("Objects",)
    assert result.review_required_channels == (BIOSEMI64_CHANNELS[0],)
    item = result.review_items[0]
    assert item.occurrence_summary == "Objects (occurrence 1)"
    assert item.raw_kurtosis == 12.25
    assert item.signed_normalized_score == -6.125
    assert item.corroborator_summary == ("None approved; experimental_detector v1: method_not_registered")
    assert item.display_only_channel_health == (
        "Candidate sources: high amplitude",
        "Channel flags: persistent high amplitude, persistent spatial outlier, transient high amplitude",
        "Transient flag: high amplitude in Objects occurrence 1",
    )
    assert item.display_only_channel_health_summary.endswith("review-only; not an approved corroborator")
    assert all(not state.eligible for state in item.corroborator_states)
    assert item.signal_preview == (-2.0, 0.5, None, 3.0)
    assert captured["excluded_conditions"] == ("Faces",)
    assert captured["prepare"]["direct_bad_channels"] == ("Fp2",)
    assert captured["prepare"]["params"]["_fpvs_source_analysis_span_plan"] == {
        "spans": [{"condition_label": "Objects", "occurrence_key": "2:1"}]
    }
    assert "raw_channel_qc_by_recording" not in captured["prepare"]["params"]
    loader_kwargs = captured["loader_calls"][0][1]
    assert loader_kwargs["electrode_montage"] == BIOSEMI64_MONTAGE_ID
    assert loader_kwargs["first_n_channels"] == len(BIOSEMI64_CHANNELS)
    geometry_kwargs = captured["geometry"][1]
    assert geometry_kwargs["expected_retained_channels"] == BIOSEMI64_CHANNELS
    assert geometry_kwargs["require_runtime_identity"] is True
    assert loaded[0].closed is True
    assert progress[-1] == (
        f"Finished kurtosis review scan for {path.name}",
        1,
        1,
    )


def test_scan_skips_fully_excluded_recordings_and_condition_sets(
    tmp_path,
    monkeypatch,
) -> None:
    participant_path = (tmp_path / "P01.bdf").resolve()
    condition_path = (tmp_path / "P02.bdf").resolve()
    participant_path.touch()
    condition_path.touch()
    monkeypatch.setattr(
        scan_module,
        "validate_source_analysis_span_context",
        lambda **kwargs: _source_plan("Faces", "Objects"),
    )
    monkeypatch.setattr(
        scan_module.load_utils,
        "load_eeg_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("excluded files must not load Raw")),
    )

    scan = scan_kurtosis_review(
        [_info(participant_path, "P01"), _info(condition_path, "P02")],
        _settings(
            manual_excluded_participants=["p01"],
            manual_excluded_participant_conditions={
                "P02": ["objects", "faces"],
            },
        ),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={str(condition_path): {"reviewed": True}},
    )

    assert [result.status for result in scan.results] == [
        KURTOSIS_REVIEW_FILE_STATUS_SKIPPED,
        KURTOSIS_REVIEW_FILE_STATUS_SKIPPED,
    ]
    assert [result.skip_reason for result in scan.results] == [
        KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED,
        KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
    ]


def test_scan_keeps_per_file_errors_and_continues(tmp_path, monkeypatch) -> None:
    first = (tmp_path / "P01.bdf").resolve()
    second = (tmp_path / "P02.bdf").resolve()
    first.touch()
    second.touch()
    loaded: list[_FakeRaw] = []
    _configure_active_scan(monkeypatch, loaded_raws=loaded)
    original_loader = scan_module.load_utils.load_eeg_file

    def _load(app, filepath: str, **kwargs):  # noqa: ANN001
        if filepath == str(first):
            raise OSError("synthetic read failure")
        return original_loader(app, filepath, **kwargs)

    monkeypatch.setattr(scan_module.load_utils, "load_eeg_file", _load)

    scan = scan_kurtosis_review(
        [_info(first, "P01"), _info(second, "P02")],
        _settings(),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={
            str(first): {"reviewed": True},
            str(second): {"reviewed": True},
        },
    )

    assert scan.cancelled is False
    assert [result.status for result in scan.results] == [
        KURTOSIS_REVIEW_FILE_STATUS_ERROR,
        KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED,
    ]
    assert scan.results[0].error == "synthetic read failure"
    assert scan.errors == (scan.results[0],)
    assert loaded[0].closed is True


def test_scan_cancellation_is_cooperative_and_closes_loaded_raw(
    tmp_path,
    monkeypatch,
) -> None:
    path = (tmp_path / "P01.bdf").resolve()
    path.touch()
    loaded: list[_FakeRaw] = []
    _configure_active_scan(monkeypatch, loaded_raws=loaded)
    checks = iter((False, True))

    scan = scan_kurtosis_review(
        [_info(path, "P01")],
        _settings(),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={str(path): {"reviewed": True}},
        should_cancel=lambda: next(checks),
    )

    assert scan.cancelled is True
    assert scan.results == ()
    assert loaded[0].closed is True


def test_unavailable_unreviewable_evidence_is_a_file_error(
    tmp_path,
    monkeypatch,
) -> None:
    path = (tmp_path / "P01.bdf").resolve()
    path.touch()
    loaded: list[_FakeRaw] = []
    unavailable = _prepared(ready=True)
    unavailable["decision_plan"] = {
        "ready_for_interpolation": False,
        "blocking_reasons": ["kurtosis_evidence_unavailable"],
        "channel_decisions": [],
    }
    _configure_active_scan(
        monkeypatch,
        loaded_raws=loaded,
        prepared=unavailable,
    )

    scan = scan_kurtosis_review(
        [_info(path, "P01")],
        _settings(),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={str(path): {"reviewed": True}},
    )

    assert scan.results[0].status == KURTOSIS_REVIEW_FILE_STATUS_ERROR
    assert "without a reviewable channel" in str(scan.results[0].error)
    assert scan.can_continue is False


def _scan_one_pending_item(tmp_path, monkeypatch, *, raw_kurtosis: float = 12.25):
    path = (tmp_path / "P01_visit-1.bdf").resolve()
    path.touch(exist_ok=True)
    _configure_active_scan(
        monkeypatch,
        loaded_raws=[],
        prepared=_prepared(raw_kurtosis=raw_kurtosis),
    )
    scan = scan_kurtosis_review(
        [_info(path, "P01", "P01__visit-1")],
        _settings(),
        event_map={"Faces": 1, "Objects": 2},
        reviewed_event_plans_by_file={str(path): {"reviewed": True}},
    )
    assert len(scan.review_items) == 1
    return scan, scan.review_items[0]


def _approve_receipt(item):  # noqa: ANN001
    return build_kurtosis_review_decision(
        item.evidence,
        channel=item.channel,
        decision=KURTOSIS_DECISION_APPROVE,
        reason="Reviewed the signal and approved the fixed recording-wide repair.",
        review_scope=item.review_scope,
        reviewed_at_utc="2026-09-04T18:22:00Z",
    ).to_payload()


def test_reconciliation_reuses_only_current_case_insensitive_receipts(
    tmp_path,
    monkeypatch,
) -> None:
    scan, item = _scan_one_pending_item(tmp_path, monkeypatch)
    receipt = _approve_receipt(item)
    unrelated = deepcopy(receipt)
    unrelated["channel"] = "Fp2"

    reconciled = reconcile_kurtosis_review_decisions(
        scan,
        {
            "p01__VISIT-1": {
                item.channel.swapcase(): receipt,
                "Fp2": unrelated,
            },
            "old-recording": {item.channel: receipt},
        },
    )

    assert reconciled.pending_items == ()
    assert reconciled.scan.can_continue is True
    assert reconciled.pending_status_by_recording == {}
    assert reconciled.processing_decisions_by_recording == {item.recording_id: {item.channel: receipt}}


def test_reconciliation_marks_missing_receipt_as_new(
    tmp_path,
    monkeypatch,
) -> None:
    scan, item = _scan_one_pending_item(tmp_path, monkeypatch)

    reconciled = reconcile_kurtosis_review_decisions(scan, {})

    assert reconciled.processing_decisions_by_recording == {}
    assert reconciled.pending_items[0].review_status == KURTOSIS_REVIEW_PENDING_NEW
    assert reconciled.pending_status_by_recording == {item.recording_id: {item.channel: KURTOSIS_REVIEW_PENDING_NEW}}


def test_reconciliation_reprompts_changed_evidence_as_stale(
    tmp_path,
    monkeypatch,
) -> None:
    original_scan, original_item = _scan_one_pending_item(tmp_path, monkeypatch)
    receipt = _approve_receipt(original_item)
    changed_scan, changed_item = _scan_one_pending_item(
        tmp_path,
        monkeypatch,
        raw_kurtosis=13.5,
    )
    assert changed_item.evidence["fingerprint"] != original_item.evidence["fingerprint"]

    reconciled = reconcile_kurtosis_review_decisions(
        changed_scan,
        {"P01__VISIT-1": {changed_item.channel.lower(): receipt}},
    )

    assert reconciled.processing_decisions_by_recording == {}
    assert len(reconciled.pending_items) == 1
    assert reconciled.pending_items[0].review_status == KURTOSIS_REVIEW_PENDING_STALE
    assert reconciled.pending_status_by_recording == {
        changed_item.recording_id: {changed_item.channel: KURTOSIS_REVIEW_PENDING_STALE}
    }
