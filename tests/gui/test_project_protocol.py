from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from Main_App.gui.project_protocol import (
    ProjectProtocolRequiredError,
    ProtocolEditorValues,
    build_manual_protocol,
    duration_summary,
    editor_values_for_protocol,
    protocol_settings_save_requested,
    processing_protocol_snapshot,
    rate_summary,
)
from Main_App.projects import (
    EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT,
    FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED,
    LEGACY_FREQUENCY_PROTOCOL_VERSION,
    FrequencyProtocol,
    FrequencyProtocolError,
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    ODDBALL_INPUT_MODE_RECURRENCE,
    ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
    ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55,
    ODDBALL_MARKER_SOURCE_MANUAL,
    Project,
)


def test_legacy_confirmation_uses_visible_proposal_without_claiming_protocol() -> None:
    protocol = FrequencyProtocol.confirmation_required()

    values = editor_values_for_protocol(protocol)

    assert protocol.status == FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
    assert values.requires_confirmation is True
    assert values.presentation_rate_hz == "6"
    assert values.oddball_every_n == "5"
    assert values.expected_analyzed_oddball_cycles == ""
    assert values.oddball_marker_code == "55"


def test_recurrence_editor_builds_ready_exact_project_protocol() -> None:
    protocol = build_manual_protocol(
        presentation_rate_hz="3",
        oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE,
        oddball_every_n="10",
        oddball_rate_hz="",
        expected_analyzed_oddball_cycles="144",
        oddball_marker_code="55",
        require_ready=True,
    )

    assert protocol.is_ready
    assert protocol.oddball_rate_hz == Fraction(3, 10)
    assert protocol.derived_analyzed_seconds == Fraction(480, 1)
    assert protocol.oddball_marker_code == 55
    assert rate_summary(protocol.oddball_rate_hz) == "0.3 Hz (exactly 3/10 Hz)"
    assert duration_summary(protocol.derived_analyzed_seconds) == "480 seconds"


def test_direct_rate_editor_shows_exact_whole_stimulus_recurrence() -> None:
    protocol = build_manual_protocol(
        presentation_rate_hz="10",
        oddball_input_mode=ODDBALL_INPUT_MODE_DIRECT_HZ,
        oddball_every_n="",
        oddball_rate_hz="3.3333",
        expected_analyzed_oddball_cycles="120",
        oddball_marker_code="77",
        require_ready=True,
    )

    assert protocol.oddball_every_n == 3
    assert protocol.oddball_rate_hz == Fraction(10, 3)
    assert protocol.oddball_marker_code == 77
    assert "exactly 10/3 Hz" in rate_summary(protocol.oddball_rate_hz)


def test_direct_rate_editor_rejects_noninteger_recurrence() -> None:
    with pytest.raises(FrequencyProtocolError, match="Nearby valid choices"):
        build_manual_protocol(
            presentation_rate_hz="6",
            oddball_input_mode=ODDBALL_INPUT_MODE_DIRECT_HZ,
            oddball_every_n="",
            oddball_rate_hz="1.1",
            expected_analyzed_oddball_cycles="144",
            oddball_marker_code="55",
            require_ready=True,
        )


def test_gui_save_preserves_unchanged_imported_protocol_provenance() -> None:
    imported = FrequencyProtocol.from_recurrence(
        "6",
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=(
            EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
        ),
        oddball_marker_code=55,
        oddball_marker_code_source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
    )

    rebuilt = build_manual_protocol(
        presentation_rate_hz="6",
        oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE,
        oddball_every_n="5",
        oddball_rate_hz="",
        expected_analyzed_oddball_cycles="144",
        oddball_marker_code="55",
        existing_protocol=imported,
        require_ready=True,
    )

    assert rebuilt.expected_analyzed_oddball_cycles_source == (
        EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
    )
    assert rebuilt.oddball_marker_code_source == (
        ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT
    )
    assert rebuilt.fingerprint == imported.fingerprint


def test_changed_imported_marker_records_manual_source() -> None:
    imported = FrequencyProtocol.from_recurrence(
        "6",
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=(
            EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
        ),
        oddball_marker_code=55,
        oddball_marker_code_source=ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
    )

    rebuilt = build_manual_protocol(
        presentation_rate_hz="6",
        oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE,
        oddball_every_n="5",
        oddball_rate_hz="",
        expected_analyzed_oddball_cycles="144",
        oddball_marker_code="77",
        existing_protocol=imported,
        require_ready=True,
    )

    assert rebuilt.oddball_marker_code == 77
    assert rebuilt.oddball_marker_code_source == ODDBALL_MARKER_SOURCE_MANUAL


def test_legacy_default_marker_source_is_recorded_only_when_confirmed() -> None:
    legacy = FrequencyProtocol.confirmation_required()
    proposed = editor_values_for_protocol(legacy)

    assert legacy.oddball_marker_code is None
    assert legacy.oddball_marker_code_source is None
    assert not protocol_settings_save_requested(
        proposed,
        proposed,
        protocol_tab_active=False,
    )

    confirmed = build_manual_protocol(
        presentation_rate_hz=proposed.presentation_rate_hz,
        oddball_input_mode=proposed.oddball_input_mode,
        oddball_every_n=proposed.oddball_every_n,
        oddball_rate_hz=proposed.entered_oddball_rate_hz,
        expected_analyzed_oddball_cycles="144",
        oddball_marker_code=proposed.oddball_marker_code,
        existing_protocol=legacy,
        require_ready=True,
    )

    assert confirmed.oddball_marker_code_source == (
        ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55
    )


def test_markerless_v1_confirmation_preserves_known_protocol_values() -> None:
    migrated = FrequencyProtocol.from_manifest(
        {
            "version": LEGACY_FREQUENCY_PROTOCOL_VERSION,
            "status": "ready",
            "presentation_rate_hz": "3",
            "oddball_input_mode": ODDBALL_INPUT_MODE_RECURRENCE,
            "oddball_every_n": 10,
            "oddball_rate_hz": "0.3",
            "entered_oddball_rate_hz": None,
            "expected_analyzed_oddball_cycles": 90,
            "expected_analyzed_oddball_cycles_source": (
                EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
            ),
        }
    )
    values = editor_values_for_protocol(migrated)

    assert values.presentation_rate_hz == "3"
    assert values.oddball_every_n == "10"
    assert values.expected_analyzed_oddball_cycles == "90"
    confirmed = build_manual_protocol(
        presentation_rate_hz=values.presentation_rate_hz,
        oddball_input_mode=values.oddball_input_mode,
        oddball_every_n=values.oddball_every_n,
        oddball_rate_hz=values.entered_oddball_rate_hz,
        expected_analyzed_oddball_cycles=(
            values.expected_analyzed_oddball_cycles
        ),
        oddball_marker_code=values.oddball_marker_code,
        existing_protocol=migrated,
        require_ready=True,
    )

    assert confirmed.presentation_rate_hz == migrated.presentation_rate_hz
    assert confirmed.oddball_rate_hz == migrated.oddball_rate_hz
    assert confirmed.expected_analyzed_oddball_cycles == 90
    assert confirmed.expected_analyzed_oddball_cycles_source == (
        EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
    )
    assert confirmed.oddball_marker_code_source == (
        ODDBALL_MARKER_SOURCE_LEGACY_DEFAULT_55
    )


def test_protocol_save_policy_allows_unrelated_save_but_detects_edit_or_confirmation() -> None:
    initial = ProtocolEditorValues(
        presentation_rate_hz="6",
        oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE,
        oddball_every_n="5",
        entered_oddball_rate_hz="1.2",
        expected_analyzed_oddball_cycles="",
        oddball_marker_code="55",
        requires_confirmation=True,
    )
    changed = replace(
        initial,
        expected_analyzed_oddball_cycles="144",
    )

    assert not protocol_settings_save_requested(
        initial,
        initial,
        protocol_tab_active=False,
    )
    assert protocol_settings_save_requested(
        initial,
        initial,
        protocol_tab_active=True,
    )
    assert protocol_settings_save_requested(
        initial,
        changed,
        protocol_tab_active=False,
    )


@pytest.mark.parametrize(
    ("protocol", "message"),
    [
        (
            FrequencyProtocol.confirmation_required(),
            "Confirm this project's FPVS protocol",
        ),
        (
            FrequencyProtocol.from_recurrence("6", 5),
            "expected number of analyzed oddball cycles",
        ),
    ],
)
def test_processing_snapshot_blocks_unconfirmed_or_incomplete_protocols(
    protocol: FrequencyProtocol,
    message: str,
) -> None:
    with pytest.raises(ProjectProtocolRequiredError, match=message):
        processing_protocol_snapshot(SimpleNamespace(frequency_protocol=protocol))


def test_processing_snapshot_returns_same_frozen_ready_value() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        "6",
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )

    snapshot = processing_protocol_snapshot(
        SimpleNamespace(frequency_protocol=protocol)
    )

    assert snapshot is protocol
    with pytest.raises(AttributeError):
        snapshot.oddball_every_n = 10


def test_protocol_values_remain_independent_between_projects(tmp_path) -> None:
    project_a = Project.load(tmp_path / "project_a")
    project_b = Project.load(tmp_path / "project_b")
    project_a.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            "6",
            5,
            expected_analyzed_oddball_cycles=144,
            expected_analyzed_oddball_cycles_source="manual",
        )
    )
    project_b.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            "3",
            10,
            expected_analyzed_oddball_cycles=90,
            expected_analyzed_oddball_cycles_source="manual",
        )
    )
    project_a.save()
    project_b.save()

    reopened_a = Project.load(project_a.project_root)
    reopened_b = Project.load(project_b.project_root)

    assert reopened_a.frequency_protocol.oddball_rate_hz == Fraction(6, 5)
    assert reopened_a.frequency_protocol.expected_analyzed_oddball_cycles == 144
    assert reopened_b.frequency_protocol.oddball_rate_hz == Fraction(3, 10)
    assert reopened_b.frequency_protocol.expected_analyzed_oddball_cycles == 90
