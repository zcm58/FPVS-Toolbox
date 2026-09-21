from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from Main_App.gui.project_protocol import (
    ProjectProtocolRequiredError,
    ProtocolEditorValues,
    build_manual_protocol,
    condition_marker_editor_rows,
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


def _mapped_protocol():
    return FrequencyProtocol.from_recurrence("6", 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual").with_condition_oddball_marker_codes({1: 51, 2: 52, 3: 53, 4: 54, 5: 55})


def _build_editor_protocol(protocol, **changes):
    values = editor_values_for_protocol(protocol)
    fields = dict(
        presentation_rate_hz=values.presentation_rate_hz,
        oddball_input_mode=values.oddball_input_mode,
        oddball_every_n=values.oddball_every_n,
        oddball_rate_hz=values.entered_oddball_rate_hz,
        expected_analyzed_oddball_cycles=values.expected_analyzed_oddball_cycles,
        oddball_marker_code=values.oddball_marker_code,
        existing_protocol=protocol, require_ready=True,
    )
    return build_manual_protocol(**(fields | changes))


def test_unrelated_protocol_rebuild_preserves_exact_condition_marker_mapping():
    protocol = _mapped_protocol()
    rebuilt = _build_editor_protocol(protocol)
    assert rebuilt.fingerprint == protocol.fingerprint
    changed_rate = _build_editor_protocol(protocol, presentation_rate_hz="3")
    assert changed_rate.condition_oddball_marker_codes == protocol.condition_oddball_marker_codes
    assert editor_values_for_protocol(changed_rate).condition_oddball_markers_enabled


def test_explicit_marker_mapping_disable_restores_one_shared_code_even_with_invalid_drafts():
    protocol = _mapped_protocol()
    disabled = _build_editor_protocol(
        protocol, condition_oddball_markers_enabled=False,
        condition_oddball_marker_codes=(("1", "incomplete edit"),),
    )
    assert disabled.condition_oddball_marker_codes == ()
    assert disabled.oddball_marker_code_for_condition(1) == 55
    assert disabled.oddball_marker_code_for_condition(5) == 55
    assert not editor_values_for_protocol(disabled).condition_oddball_markers_enabled


def test_enabled_mapping_uses_explicit_edited_values_and_cannot_be_empty():
    protocol = FrequencyProtocol.from_recurrence("6", 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual")
    mapped = _build_editor_protocol(
        protocol, condition_oddball_markers_enabled=True,
        condition_oddball_marker_codes=(("1", "51"), ("2", "52")),
    )
    assert mapped.condition_oddball_marker_codes == ((1, 51), (2, 52))
    assert protocol.condition_oddball_marker_codes == ()
    with pytest.raises(FrequencyProtocolError, match="every condition"):
        _build_editor_protocol(protocol, condition_oddball_markers_enabled=True, condition_oddball_marker_codes=())


def test_condition_editor_rows_use_onset_identity_after_renaming_and_reordering():
    values = editor_values_for_protocol(_mapped_protocol())
    rows = condition_marker_editor_rows({"Semantic Response": 3, "Color renamed": 1, "Color Response 2": 2}, values)
    assert rows == (("Color renamed", "1", "51"), ("Color Response 2", "2", "52"), ("Semantic Response", "3", "53"))
    assert condition_marker_editor_rows({"New condition": 6}, values) == (("New condition", "6", ""),)


def test_mapping_change_and_disable_are_detected_by_settings_save_policy():
    initial = editor_values_for_protocol(_mapped_protocol())
    assert not protocol_settings_save_requested(initial, initial, protocol_tab_active=False)
    changed = replace(initial, condition_oddball_marker_codes=(("1", "77"),))
    disabled = replace(initial, condition_oddball_markers_enabled=False)
    assert protocol_settings_save_requested(initial, changed, protocol_tab_active=False)
    assert protocol_settings_save_requested(initial, disabled, protocol_tab_active=False)
    other_drafts = replace(disabled, condition_oddball_marker_codes=(("1", "draft"),))
    assert not protocol_settings_save_requested(disabled, other_drafts, protocol_tab_active=False)


def test_condition_aliases_share_one_editable_marker_and_roundtrip_unchanged():
    from Main_App.projects import validate_protocol_condition_codes

    protocol = _mapped_protocol().with_condition_oddball_marker_codes({1: 51, 2: 52})
    event_map = {"Faces": 1, "Faces alias": 1, "Objects": 2}
    rows = condition_marker_editor_rows(event_map, editor_values_for_protocol(protocol))
    assert rows == (("Faces / Faces alias", "1", "51"), ("Objects", "2", "52"))
    rebuilt = _build_editor_protocol(
        protocol, condition_oddball_markers_enabled=True,
        condition_oddball_marker_codes=tuple((onset, marker) for _label, onset, marker in rows),
    )
    validate_protocol_condition_codes(rebuilt, event_map.values())
    assert rebuilt.fingerprint == protocol.fingerprint


def test_recording_trigger_schemas_survive_unrelated_protocol_rebuild():
    protocol = _mapped_protocol().with_recording_oddball_marker_codes({
        "P01": {onset: onset + 50 for onset in range(1, 6)},
        "P22": {onset: 55 for onset in range(1, 6)},
    })
    assert _build_editor_protocol(protocol).fingerprint == protocol.fingerprint
    changed = _build_editor_protocol(protocol, expected_analyzed_oddball_cycles="120")
    assert changed.recording_oddball_marker_codes == protocol.recording_oddball_marker_codes
    disabled = _build_editor_protocol(protocol, recording_oddball_markers_enabled=False)
    assert disabled.recording_oddball_marker_codes == ()
    assert disabled.condition_oddball_marker_codes == protocol.condition_oddball_marker_codes
    initial = editor_values_for_protocol(protocol)
    off = replace(initial, recording_oddball_markers_enabled=False)
    assert protocol_settings_save_requested(initial, off, protocol_tab_active=False)
    assert not protocol_settings_save_requested(off, replace(off, recording_oddball_marker_codes=()), protocol_tab_active=False)


def test_new_recording_schema_mode_cannot_silently_use_the_project_default():
    with pytest.raises(FrequencyProtocolError, match="every recording"):
        _build_editor_protocol(_mapped_protocol(), recording_oddball_markers_enabled=True, recording_oddball_marker_codes=())


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
