from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

from Main_App.projects import (
    EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT,
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED,
    FREQUENCY_PROTOCOL_STATUS_INCOMPLETE,
    FREQUENCY_PROTOCOL_STATUS_READY,
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    FrequencyProtocol,
    FrequencyProtocolError,
    enumerate_exact_harmonics,
    enumerate_protocol_harmonics,
    new_manual_frequency_protocol,
)
from Main_App.projects.project import Project

pytestmark = pytest.mark.project_io


def test_new_manual_protocol_seeds_rates_but_not_expected_cycles() -> None:
    protocol = new_manual_frequency_protocol()

    assert protocol.status == FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
    assert protocol.presentation_rate_hz == Fraction(6, 1)
    assert protocol.oddball_every_n == 5
    assert protocol.oddball_rate_hz == Fraction(6, 5)
    assert protocol.expected_analyzed_oddball_cycles is None
    assert protocol.expected_analyzed_oddball_cycles_source is None
    assert protocol.derived_analyzed_seconds is None


def test_recurrence_protocol_is_exact_immutable_and_has_stable_identity() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        "6.0",
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    equivalent = FrequencyProtocol.from_recurrence(
        6,
        "5.0",
        expected_analyzed_oddball_cycles="144",
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )

    assert protocol.status == FREQUENCY_PROTOCOL_STATUS_READY
    assert protocol.oddball_rate_hz == Fraction(6, 5)
    assert protocol.derived_analyzed_seconds == Fraction(120, 1)
    assert protocol.to_manifest()["presentation_rate_hz"] == "6"
    assert protocol.to_manifest()["oddball_rate_hz"] == "1.2"
    assert protocol.canonical_json() == equivalent.canonical_json()
    assert protocol.fingerprint == equivalent.fingerprint
    assert len(protocol.fingerprint) == 64
    with pytest.raises(FrozenInstanceError):
        protocol.oddball_every_n = 6  # type: ignore[misc]


def test_direct_constructor_normalizes_runtime_types_once() -> None:
    protocol = FrequencyProtocol(
        version="1.0.0",
        status="ready",
        presentation_rate_hz="6",  # type: ignore[arg-type]
        oddball_input_mode="oddball_every_n",
        oddball_every_n="5",  # type: ignore[arg-type]
        oddball_rate_hz="1.2",  # type: ignore[arg-type]
        entered_oddball_rate_hz=None,
        expected_analyzed_oddball_cycles="144",  # type: ignore[arg-type]
        expected_analyzed_oddball_cycles_source="manual",
    )

    assert protocol.presentation_rate_hz == Fraction(6, 1)
    assert protocol.oddball_rate_hz == Fraction(6, 5)
    assert protocol.oddball_every_n == 5
    assert protocol.expected_analyzed_oddball_cycles == 144


def test_direct_hz_accepts_display_rounded_recurrence_then_canonicalizes() -> None:
    protocol = FrequencyProtocol.from_direct_hz(
        3,
        "0.3333",
        expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source=(
            EXPECTED_CYCLES_SOURCE_FPVS_STUDIO_IMPORT
        ),
    )

    assert protocol.oddball_input_mode == ODDBALL_INPUT_MODE_DIRECT_HZ
    assert protocol.oddball_every_n == 9
    assert protocol.oddball_rate_hz == Fraction(1, 3)
    assert protocol.to_manifest()["oddball_rate_hz"] == "1/3"


def test_direct_hz_canonicalizes_ten_hz_every_three_repeating_decimal() -> None:
    protocol = FrequencyProtocol.from_direct_hz(
        10,
        "3.333333",
        expected_analyzed_oddball_cycles=90,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )

    assert protocol.oddball_every_n == 3
    assert protocol.oddball_rate_hz == Fraction(10, 3)
    assert protocol.to_manifest()["oddball_rate_hz"] == "10/3"
    assert protocol.to_manifest()["entered_oddball_rate_hz"] == "3.333333"
    assert protocol.derived_analyzed_seconds == Fraction(27, 1)

    same_protocol = FrequencyProtocol.from_direct_hz(
        10,
        "3.3333",
        expected_analyzed_oddball_cycles=90,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    assert same_protocol.fingerprint == protocol.fingerprint
    assert same_protocol.to_manifest() != protocol.to_manifest()


def test_direct_hz_rejects_nonrecurring_pair_and_reports_nearby_choices() -> None:
    with pytest.raises(FrequencyProtocolError, match="Nearby valid choices"):
        FrequencyProtocol.from_direct_hz(3, "0.31")


@pytest.mark.parametrize(
    ("presentation_rate", "recurrence", "cycles", "source"),
    [
        (0, 5, 144, EXPECTED_CYCLES_SOURCE_MANUAL),
        (float("nan"), 5, 144, EXPECTED_CYCLES_SOURCE_MANUAL),
        (6, 1, 144, EXPECTED_CYCLES_SOURCE_MANUAL),
        (6, 5, 0, EXPECTED_CYCLES_SOURCE_MANUAL),
        (6, 5, 144, "unknown"),
    ],
)
def test_protocol_rejects_invalid_rate_recurrence_and_cycle_values(
    presentation_rate,
    recurrence,
    cycles,
    source,
) -> None:
    with pytest.raises(FrequencyProtocolError):
        FrequencyProtocol.from_recurrence(
            presentation_rate,
            recurrence,
            expected_analyzed_oddball_cycles=cycles,
            expected_analyzed_oddball_cycles_source=source,
        )


def test_expected_sample_count_is_exact_and_rejects_nonintegral_grid() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    incompatible = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=145,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )

    assert protocol.expected_analyzed_samples(256) == 30_720
    with pytest.raises(FrequencyProtocolError, match="incompatible"):
        incompatible.expected_analyzed_samples(256)


def test_exact_harmonic_enumeration_uses_only_the_caller_bound() -> None:
    protocol = FrequencyProtocol.from_recurrence(3, 10)

    assert enumerate_exact_harmonics("0.3", "1.0") == (
        Fraction(3, 10),
        Fraction(3, 5),
        Fraction(9, 10),
    )
    targets = enumerate_protocol_harmonics(protocol, 6)
    assert len(targets) == 20
    assert targets[9].frequency_hz == Fraction(3, 1)
    assert targets[9].presentation_harmonic_order == 1
    assert targets[19].presentation_harmonic_order == 2
    assert targets[8].presentation_harmonic_order is None


def test_protocol_manifest_round_trip_preserves_exact_repeating_rate() -> None:
    original = FrequencyProtocol.from_direct_hz(
        3,
        "0.3333",
        expected_analyzed_oddball_cycles=120,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )

    restored = FrequencyProtocol.from_manifest(original.to_manifest())

    assert restored == original
    assert restored.fingerprint == original.fingerprint


def test_new_project_persists_explicitly_incomplete_seed(tmp_path) -> None:
    project_root = tmp_path / "New Project"

    project = Project.load(project_root)
    project.save()

    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert saved["frequency_protocol"]["status"] == (
        FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
    )
    assert saved["frequency_protocol"]["presentation_rate_hz"] == "6"
    assert saved["frequency_protocol"]["oddball_every_n"] == 5
    assert saved["frequency_protocol"]["expected_analyzed_oddball_cycles"] is None
    assert Project.load(project_root).frequency_protocol == project.frequency_protocol


def test_existing_manifest_without_protocol_remains_unconfirmed_and_absent(tmp_path) -> None:
    project_root = tmp_path / "Legacy Project"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "Historical",
                "tools": {"processing": {"historical_artifact": "keep"}},
            }
        ),
        encoding="utf-8",
    )

    project = Project.load(project_root)
    assert project.frequency_protocol.status == (
        FREQUENCY_PROTOCOL_STATUS_CONFIRMATION_REQUIRED
    )
    project.save()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "frequency_protocol" not in saved
    assert saved["tools"]["processing"]["historical_artifact"] == "keep"


def test_confirmed_protocol_persists_without_changing_historical_tools(tmp_path) -> None:
    project_root = tmp_path / "Legacy Project"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(
        json.dumps({"tools": {"stats": {"historical": True}}}),
        encoding="utf-8",
    )
    project = Project.load(project_root)
    protocol = FrequencyProtocol.from_recurrence(
        10,
        5,
        expected_analyzed_oddball_cycles=200,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )

    project.update_frequency_protocol(protocol)
    project.save()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["frequency_protocol"] == protocol.to_manifest()
    assert saved["tools"] == {"stats": {"historical": True}}
    assert Project.load(project_root).frequency_protocol == protocol


def test_malformed_persisted_protocol_is_rejected(tmp_path) -> None:
    project_root = tmp_path / "Broken Project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "frequency_protocol": {
                    "version": "1.0.0",
                    "status": "ready",
                    "presentation_rate_hz": "6",
                    "oddball_input_mode": "oddball_every_n",
                    "oddball_every_n": 5,
                    "oddball_rate_hz": "1.3",
                    "expected_analyzed_oddball_cycles": 144,
                    "expected_analyzed_oddball_cycles_source": "manual",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FrequencyProtocolError, match="must equal"):
        Project.load(project_root)


def test_null_persisted_protocol_is_rejected_instead_of_treated_as_absent(
    tmp_path,
) -> None:
    project_root = tmp_path / "Broken Project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"frequency_protocol": None}),
        encoding="utf-8",
    )

    with pytest.raises(FrequencyProtocolError, match="JSON object"):
        Project.load(project_root)


@pytest.mark.parametrize(
    "record",
    [
        {
            "version": "99.0.0",
            "status": "confirmation_required",
        },
        {
            "version": "1.0.0",
            "status": "confirmation_required",
            "presentation_rate_hz": "6",
        },
    ],
)
def test_confirmation_required_manifest_rejects_unsupported_or_claimed_values(
    record,
) -> None:
    with pytest.raises(FrequencyProtocolError):
        FrequencyProtocol.from_manifest(record)
