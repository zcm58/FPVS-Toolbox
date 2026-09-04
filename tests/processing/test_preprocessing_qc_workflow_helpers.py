from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

pytest.importorskip("PySide6")

from Main_App.gui import preprocessing_qc_workflow as workflow  # noqa: E402


class _LabelStub:
    def __init__(self) -> None:
        self.text = ""
        self.visible = True

    def setText(self, text: str) -> None:
        self.text = text

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class _ChoiceStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self) -> str:
        return self._value


class _TableStub:
    def __init__(self, cells: dict[tuple[int, int], _ChoiceStub]) -> None:
        self._cells = cells

    def cellWidget(self, row: int, column: int):  # noqa: ANN201
        return self._cells.get((row, column))


@pytest.mark.parametrize(
    ("step", "title", "expected"),
    (
        (
            workflow._SCAN_SIGNAL_HEALTH_STEP,
            "Scan Signal Health",
            "Step 1 of 7: Scan Signal Health",
        ),
        (
            workflow._REVIEW_MARKER_OCCURRENCES_STEP,
            "Review Marker Occurrence",
            "Step 2 of 7: Review Marker Occurrence",
        ),
        (
            workflow._CONFIRM_CONDITION_EXCLUSIONS_STEP,
            "Confirm Condition Exclusions",
            "Step 3 of 7: Confirm Condition Exclusions",
        ),
        (
            workflow._CONFIRM_REMOVED_ELECTRODES_STEP,
            "Confirm Removed Electrodes",
            "Step 4 of 7: Confirm Removed Electrodes",
        ),
        (
            workflow._CONFIRM_PARTICIPANT_EXCLUSIONS_STEP,
            "Confirm Participant Exclusions",
            "Step 5 of 7: Confirm Participant Exclusions",
        ),
        (
            workflow._REVIEW_KURTOSIS_STEP,
            "Review Kurtosis Findings",
            "Step 6 of 7: Review Kurtosis Findings",
        ),
        (
            workflow._REVIEW_OTHER_FLAGS_STEP,
            "Review Other Flags",
            "Step 7 of 7: Review Other Flags",
        ),
    ),
)
def test_data_quality_step_labels_are_contiguous(
    step: int,
    title: str,
    expected: str,
) -> None:
    label = _LabelStub()
    section_title = _LabelStub()
    host = SimpleNamespace(
        processing_step_label=label,
        processing_status_title_label=section_title,
    )

    workflow._begin_preflight_page(
        host,
        step=step,
        title=title,
        message="Checking data quality.",
        busy=False,
        review_visible=False,
    )

    assert label.text == expected
    assert label.visible is True
    assert section_title.text == title


def test_kurtosis_receipt_merge_replaces_only_scanned_recordings() -> None:
    existing = {
        "sub-01_ses-01": {"A1": {"decision": "legacy-stale"}},
        "sub-02_ses-01": {"B2": {"decision": "keep-current"}},
    }
    current = {
        "SUB-01_SES-01": {"A2": {"decision": "approve"}},
    }

    merged = workflow._merge_kurtosis_review_receipts(
        existing,
        scanned_recording_ids=("sub-01_ses-01",),
        current_scanned_receipts=current,
    )

    assert merged == {
        "sub-02_ses-01": {"B2": {"decision": "keep-current"}},
        "SUB-01_SES-01": {"A2": {"decision": "approve"}},
    }


def test_data_quality_preparation_hides_step_label() -> None:
    label = _LabelStub()
    host = SimpleNamespace(processing_step_label=label)

    workflow._begin_preflight_page(
        host,
        step=None,
        title="Check Raw Files",
        message="Checking BDF headers.",
        busy=True,
        review_visible=False,
    )

    assert label.visible is False


def test_data_quality_review_updates_flat_section_title() -> None:
    review_panel = _LabelStub()
    review_title = _LabelStub()
    host = SimpleNamespace(
        processing_files_card=review_panel,
        processing_files_title_label=review_title,
    )

    workflow._set_review_visible(host, True, title="Review flagged channels")

    assert review_panel.visible is True
    assert review_title.text == "Review flagged channels"


def test_group_display_requires_canonical_membership() -> None:
    assert workflow._group_display_name(None, {}) == "Single group"
    with pytest.raises(RuntimeError, match="without a group_id"):
        workflow._group_display_name(None, {"control": "Control"})
    with pytest.raises(RuntimeError, match="unknown project group_id"):
        workflow._group_display_name("missing", {"control": "Control"})


def test_live_scan_status_includes_group_label() -> None:
    host = SimpleNamespace(_preflight_qc_group_by_file={"p01.bdf": "Control"})

    assert (
        workflow._grouped_scan_progress_text(host, "Scanning P01.bdf")
        == "Scanning Control · P01.bdf"
    )


def test_live_scan_status_keeps_file_identity_with_condition_detail() -> None:
    host = SimpleNamespace(_preflight_qc_group_by_file={"p01.bdf": "Control"})

    message = "Scanning P01.bdf · Faces 2/4 · time-domain blocks"

    assert workflow._file_name_from_progress(message) == "p01.bdf"
    assert workflow._grouped_scan_progress_text(host, message) == (
        "Scanning Control · P01.bdf · Faces 2/4 · time-domain blocks"
    )


def test_preflight_worker_passes_explicit_project_and_event_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _scan(raw_file_infos, settings, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        captured["raw_file_infos"] = raw_file_infos
        captured["settings"] = settings
        return workflow.PreflightQcScan(results=())

    monkeypatch.setattr(workflow, "scan_preprocessing_qc", _scan)
    worker = workflow._PreflightQcWorker(
        [],
        {"event_id_map": {"Faces": 1}},
        [],
        max_workers=12,
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    worker.run()

    assert captured["project_root"] == tmp_path
    assert captured["event_map"] == {"Faces": 1}
    assert captured["max_workers"] == 12


def _hard_candidate(raw_payload: dict[str, object]) -> workflow.PreflightQcFileResult:
    return workflow.PreflightQcFileResult(
        path=Path("p34.bdf"),
        participant_id="P34",
        load_error=None,
        raw_channel_qc=raw_payload,
        raw_spectral_qc=None,
        group_id="control",
    )


def _review_candidate(
    *,
    participant_id: str = "P13",
    raw_payload: dict[str, object] | None = None,
    spectral_payload: dict[str, object] | None = None,
) -> workflow.PreflightQcFileResult:
    return workflow.PreflightQcFileResult(
        path=Path(f"{participant_id.casefold()}.bdf"),
        participant_id=participant_id,
        load_error=None,
        raw_channel_qc=raw_payload,
        raw_spectral_qc=spectral_payload,
        group_id="patient",
    )


def test_removed_electrode_review_scope_preserves_unreviewed_participants() -> None:
    existing = {"P01": ["P9"], "P02": ["Oz"]}
    review_participants = ["P03"]

    visible = workflow._filter_removed_map_for_participants(
        existing,
        review_participants,
    )
    assert visible == {}

    updated = workflow._replace_removed_map_for_participants(
        existing,
        {"P03": ["PO8"]},
        review_participants,
    )

    assert updated == {"P01": ["P9"], "P02": ["Oz"], "P03": ["PO8"]}


@pytest.mark.parametrize("mode", ("auto", "off"))
def test_reviewed_manual_maps_activate_without_changing_detector_mode(mode: str) -> None:
    updated = workflow._settings_with_reviewed_manual_removed_electrodes(
        {
            "removed_electrode_detection_mode": mode,
            "auto_detect_removed_electrodes": mode == "auto",
            "manual_removed_electrodes_enabled": False,
        },
        participant_map={"P12": ["P9"]},
        recording_map={"P12__follicular": ["Oz"]},
    )

    assert updated["removed_electrode_detection_mode"] == mode
    assert updated["auto_detect_removed_electrodes"] is (mode == "auto")
    assert updated["manual_removed_electrodes_enabled"] is True
    assert updated["manual_removed_electrodes"] == {"P12": ["P9"]}
    assert updated["manual_removed_electrodes_by_recording"] == {
        "P12__follicular": ["Oz"]
    }


def test_removed_electrode_review_rows_split_auto_and_manual_sources() -> None:
    rows = workflow._removed_review_row_values(
        ["P34"],
        {"P34": ["FT7"]},
        {"P34": ["FT7", "P9"]},
        {"P34": "Control"},
        {"P34": "Low signal / flat candidate(s): FT7"},
    )

    assert rows == [
        (
            "P34",
            "Control",
            "FT7",
            "Low signal / flat candidate(s): FT7",
            "P9",
            "FT7, P9",
        )
    ]


def test_removed_electrode_review_parser_moves_auto_field_additions_to_manual() -> None:
    records, final_confirmed, warnings = workflow._removed_review_records_from_rows(
        [("P34", "FT7, P9", "", "FT7, P9")],
        {"P34": ["FT7"]},
    )

    assert final_confirmed == {"P34": ["FT7", "P9"]}
    assert records["P34"]["accepted_auto_flagged"] == ["FT7"]
    assert records["P34"]["manual_additions"] == ["P9"]
    assert records["P34"]["manual_only_missed_by_auto"] == ["P9"]
    assert "P34: moved to Manual additions: P9" in warnings


def test_removed_electrode_review_parser_tracks_rejected_auto_flags() -> None:
    records, final_confirmed, warnings = workflow._removed_review_records_from_rows(
        [("P36", "FT7", "", "FT7")],
        {"P36": ["FT7", "P9"]},
    )

    assert final_confirmed == {"P36": ["FT7"]}
    assert records["P36"]["accepted_auto_flagged"] == ["FT7"]
    assert records["P36"]["rejected_auto_flagged"] == ["P9"]
    assert records["P36"]["manual_additions"] == []
    assert warnings == []


def test_removed_electrode_review_parser_ignores_reason_column() -> None:
    records, final_confirmed, warnings = workflow._removed_review_records_from_rows(
        [("P36", "FT7", "High-amplitude candidate(s): P9", "", "FT7")],
        {"P36": ["FT7", "P9"]},
    )

    assert final_confirmed == {"P36": ["FT7"]}
    assert records["P36"]["rejected_auto_flagged"] == ["P9"]
    assert warnings == []


def test_removed_electrode_review_reasons_include_only_selected_low_signal_class() -> None:
    scan = workflow.PreflightQcScan(
        results=(
            _review_candidate(
                raw_payload={
                    "channels_to_interpolate": ["FT7"],
                    "high_amplitude_channels": ["P9"],
                    "rare_burst_channels": ["P10"],
                }
            ),
        )
    )

    assert workflow._removed_review_reason_map(scan) == {
        "P13": "Low signal / flat candidate(s): FT7"
    }


def test_remaining_review_rows_keep_unselected_signal_candidate_classes() -> None:
    scan = workflow.PreflightQcScan(
        results=(
            _review_candidate(
                participant_id="P13",
                raw_payload={
                    "high_amplitude_channels": ["C5", "T7"],
                    "rare_burst_channels": ["P9"],
                    "experimental_removed_electrode_detector": {
                        "evaluation_status": "evaluated"
                    },
                },
            ),
            _review_candidate(
                participant_id="P17",
                raw_payload={
                    "high_amplitude_channels": ["Iz"],
                    "spatial_outlier_channels": ["AF3", "F7"],
                    "experimental_removed_electrode_detector": {
                        "evaluation_status": "evaluated"
                    },
                },
            ),
        )
    )

    assert workflow._remaining_review_rows(
        scan,
        set(),
        {"patient": "Patient"},
    ) == [
        ("P13", "Patient", "p13.bdf", "High-amplitude channel review: C5, T7"),
        ("P13", "Patient", "p13.bdf", "Rare-burst channel review: P9"),
        ("P17", "Patient", "p17.bdf", "High-amplitude channel review: Iz"),
        (
            "P17",
            "Patient",
            "p17.bdf",
            "Spatially inconsistent channel review: AF3, F7",
        )
    ]


def test_severe_amplitude_review_reason_is_condensed_with_details() -> None:
    result = _hard_candidate(
        {
            "excluded": False,
            "message": (
                "p34.bdf excluded by raw channel-health QC: participant-level raw "
                "amplitude baseline was excessively noisy."
            ),
            "review_rules": ["raw_amplitude_baseline_severe_review"],
            "raw_amplitude_review_findings": [
                {
                    "severity": "severe_review",
                    "median_std_uv": 32193.4,
                    "median_p2p_99_uv": 260426.5,
                }
            ],
            "raw_baseline_median_std_uv": 32193.4,
            "raw_baseline_median_p2p_99_uv": 260426.5,
            "bad_channels": ["CPz", "FT7"],
            "thresholds": {
                "baseline_severe_review_median_std_uv": 10000.0,
                "baseline_severe_review_median_p2p_99_uv": 100000.0,
            },
        }
    )

    assert workflow._hard_candidate_flag(result) == "Signal review"
    assert workflow._hard_candidate_reason(result) == "High raw signal amplitude"
    assert workflow._hard_candidate_row_values(
        [result],
        {"control": "Control"},
    ) == [
        (
            "P34",
            "Control",
            "Signal review",
            "High raw signal amplitude",
            "",
            "",
        )
    ]
    assert "Referencing may reduce shared electrical noise" in (
        workflow._hard_candidate_plain_explanation(result)
    )

    details = workflow._hard_candidate_detail_text(result, {"control": "Control"})
    assert "Group: Control" in details
    assert "Median STD: 32193.4 uV (severe review >= 10000.0 uV)" in details
    assert "Median P2P99: 260426.5 uV (severe review >= 100000.0 uV)" in details
    assert "raw_amplitude_baseline_severe_review" in details
    assert "Original raw QC message" in details


def test_severe_transient_amplitude_detail_does_not_misstate_aggregate() -> None:
    result = _hard_candidate(
        {
            "excluded": False,
            "review_rules": [
                "condition_transient_amplitude_baseline_severe_review"
            ],
            "raw_baseline_median_std_uv": 1200.0,
            "raw_baseline_median_p2p_99_uv": 8000.0,
            "raw_amplitude_review_findings": [
                {
                    "scope": "overlapping_diagnostic_window_union",
                    "condition_label": "Faces",
                    "occurrence_display": 2,
                    "severity": "severe_review",
                    "median_std_uv": 12000.0,
                    "median_p2p_99_uv": 110000.0,
                    "diagnostic_window_count": 2,
                    "flagged_window_union_spans": [[500, 1250]],
                }
            ],
            "thresholds": {
                "baseline_severe_review_median_std_uv": 10000.0,
                "baseline_severe_review_median_p2p_99_uv": 100000.0,
            },
        }
    )

    details = workflow._hard_candidate_detail_text(result)

    assert "Full-occurrence aggregate metrics" in details
    assert "Median STD: 1200.0 uV" in details
    assert "Amplitude review evidence" in details
    assert "Faces, occurrence 2" in details
    assert "median STD 12000.0 uV, median P2P99 110000.0 uV" in details
    assert "flagged-window union [[500, 1250]]" in details


def test_hard_exclusion_rows_require_explicit_per_row_exclude_choice() -> None:
    candidates = [
        _review_candidate(participant_id="P01"),
        _review_candidate(participant_id="P02"),
        _review_candidate(participant_id="P03"),
    ]
    table = _TableStub(
        {
            (0, workflow._HARD_EXCLUSION_DECISION_COLUMN): _ChoiceStub(
                workflow._HARD_EXCLUSION_DECISION_UNSELECTED
            ),
            (1, workflow._HARD_EXCLUSION_DECISION_COLUMN): _ChoiceStub(
                workflow._HARD_EXCLUSION_DECISION_KEEP
            ),
            (2, workflow._HARD_EXCLUSION_DECISION_COLUMN): _ChoiceStub(
                workflow._HARD_EXCLUSION_DECISION_EXCLUDE
            ),
        }
    )

    selected = workflow._selected_hard_exclusions(
        table,
        candidates,
        recording_mode=False,
    )

    assert selected == [(candidates[2], "participant")]

    recording = replace(candidates[0], recording_id="P01__visit-2")
    recording_table = _TableStub(
        {
            (0, 7): _ChoiceStub(workflow._HARD_EXCLUSION_DECISION_EXCLUDE),
            (0, 8): _ChoiceStub("recording"),
        }
    )
    assert workflow._selected_hard_exclusions(
        recording_table,
        [recording],
        recording_mode=True,
    ) == [(recording, "recording")]


def test_amplitude_help_label_is_brief_and_links_to_biosemi() -> None:
    label = _LabelStub()
    host = SimpleNamespace(processing_current_file_label=label)

    workflow._set_amplitude_help_label(
        host,
        "processing_current_file_label",
        "Review this recording.",
    )

    assert "Large raw signals detected" in label.text
    assert "Referencing may reduce shared electrical noise" in label.text
    assert 'href="https://www.biosemi.com/faq/cms%26drl.htm"' in label.text


def test_remaining_review_rows_make_occurrence_and_transient_scope_prominent() -> None:
    result = _review_candidate(
        raw_payload={
            "review_rules": ["condition_occurrence_channel_review"],
            "experimental_removed_electrode_detector": {
                "evaluation_status": "evaluated"
            },
            "occurrence_review_findings": [
                {
                    "channel": "P7",
                    "condition_label": "Condition A",
                    "occurrence_display": 1,
                    "categories": ["low_variance"],
                    "start_sample": 100,
                    "stop_sample": 500,
                    "statement": (
                        "P7 was flagged as potentially bad in Condition A, "
                        "occurrence 1 only. It was not flagged in the other 3 "
                        "evaluated occurrences."
                    ),
                }
            ],
            "transient_review_findings": [
                {
                    "channel": "P8",
                    "condition_label": "Condition B",
                    "occurrence_display": 2,
                    "category": "rare_burst",
                    "diagnostic_window_count": 2,
                }
            ],
            "occurrence_evaluation_scope": [
                {
                    "condition_label": "Condition C",
                    "occurrence_display": 1,
                    "evaluation_status": "not_evaluated",
                    "reason": "missing_required_marker",
                }
            ],
        }
    )

    rows = workflow._remaining_review_rows(
        workflow.PreflightQcScan(results=(result,)),
        set(),
        {"patient": "Patient"},
    )
    messages = [row[-1] for row in rows]

    assert any(
        message.startswith("P7 was flagged as potentially bad in Condition A")
        and "Analyzed samples: [100, 500)" in message
        for message in messages
    )
    assert any(
        "P8 had a transient rare burst flag in Condition B, occurrence 2" in message
        and "not measured artifact duration" in message
        for message in messages
    )
    assert any(
        "Condition C, occurrence 1: Not evaluated" in message
        and "excluded from the evaluated comparison count" in message
        for message in messages
    )


def test_detector_off_review_row_says_not_evaluated_without_inferred_findings() -> None:
    result = _review_candidate(
        raw_payload={
            "experimental_removed_electrode_detector": {
                "evaluation_status": "not_evaluated",
                "reason": "disabled_in_project_settings",
            }
        }
    )

    rows = workflow._remaining_review_rows(
        workflow.PreflightQcScan(results=(result,)),
        set(),
        {"patient": "Patient"},
    )

    assert len(rows) == 1
    assert rows[0][-1] == (
        "Experimental removed-electrode assessment: Not evaluated (disabled in "
        "project settings). No detector finding is inferred."
    )


def test_review_flags_workbook_preserves_group_membership(tmp_path: Path) -> None:
    host = SimpleNamespace(currentProject=SimpleNamespace(project_root=tmp_path))

    path = workflow._write_preflight_review_flags(
        host,
        [("P17", "Patient", "p17.bdf", "spatially inconsistent channel(s): AF3")],
    )

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook["Review Flags"].iter_rows(values_only=True))
    finally:
        workbook.close()
    assert rows == [
        ("PID", "Group", "Source File", "Flagged Item"),
        ("P17", "Patient", "p17.bdf", "spatially inconsistent channel(s): AF3"),
    ]


def test_condition_crop_review_replaces_only_reviewed_exclusion_pairs(
    tmp_path: Path,
) -> None:
    candidates = (
        workflow.PreflightConditionCropObservation(
            path=tmp_path / "P1.bdf",
            participant_id="P1",
            group_id="control",
            condition_label="Negative Valence",
            condition_id=22,
            repetition_count=2,
            oddball_cycles=21,
            duration_s=17.5,
            issue=None,
            already_excluded=True,
        ),
        workflow.PreflightConditionCropObservation(
            path=tmp_path / "P4.bdf",
            participant_id="P4",
            group_id="control",
            condition_label="Negative Valence",
            condition_id=22,
            repetition_count=3,
            oddball_cycles=21,
            duration_s=17.5,
            issue=None,
        ),
    )

    updated = workflow._replace_reviewed_condition_exclusions(
        {
            "P1": ["Negative Valence", "Faces"],
            "P9": ["Neutral Happy"],
        },
        candidates,
        {("p4", "negative valence")},
    )

    assert updated == {
        "P1": ["Faces"],
        "P4": ["Negative Valence"],
        "P9": ["Neutral Happy"],
    }
