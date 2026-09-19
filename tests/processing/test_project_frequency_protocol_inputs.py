from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.gui import processing_inputs
from Main_App.gui.condition_input_model import validate_condition_rows
from Main_App.projects import FrequencyProtocol, Project


@pytest.fixture
def condition_validation(monkeypatch):
    calls = []

    def validated_rows(host, *, focus_error=False):
        calls.append((tuple(host.event_rows), focus_error))
        mapping, errors = validate_condition_rows(host.event_rows)
        return None if errors else mapping

    monkeypatch.setattr(processing_inputs, "validated_event_map", validated_rows)
    return calls


def _ready_project(root: Path, *, marker_code: int = 55) -> Project:
    project = Project.load(root)
    project.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            "3",
            10,
            expected_analyzed_oddball_cycles=144,
            expected_analyzed_oddball_cycles_source="manual",
            oddball_marker_code=marker_code,
        )
    )
    return project


def test_processing_params_use_one_frozen_project_protocol_snapshot(tmp_path, condition_validation) -> None:
    project = _ready_project(tmp_path / "project")
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=object(),
        event_rows=[("Condition A", "11")],
    )

    params = processing_inputs.build_validated_params(host)

    assert params is not None
    assert condition_validation == [((("Condition A", "11"),), True)]
    assert params["event_id_map"] == {"Condition A": 11}
    assert params["frequency_protocol"] is project.frequency_protocol
    assert params["frequency_protocol"].oddball_rate_hz.numerator == 3
    assert params["frequency_protocol"].oddball_rate_hz.denominator == 10
    assert params["frequency_protocol_fingerprint"] == project.frequency_protocol.fingerprint
    assert params["base_freq"] == 3.0
    assert params["oddball_freq"] == 0.3
    assert "bca_upper_limit" not in params
    assert "bca_upper_limit" not in params["analysis"]
    assert params["analysis"]["frequency_protocol"] == (
        project.frequency_protocol.to_manifest()
    )


def test_processing_params_block_incomplete_protocol_before_event_parsing(
    tmp_path,
    monkeypatch,
    condition_validation,
) -> None:
    project = Project.load(tmp_path / "project")
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        processing_inputs.QMessageBox,
        "warning",
        lambda _host, title, message: warnings.append((title, message)),
    )
    host = SimpleNamespace(
        currentProject=project,
        settings=object(),
        event_rows=[],
    )

    assert processing_inputs.build_validated_params(host) is None
    assert condition_validation == []
    assert warnings == [
        (
            "FPVS Protocol Required",
            "Enter the expected number of analyzed oddball cycles in Settings > "
            "Protocol and save before processing.",
        )
    ]


def test_processing_params_reject_marker_condition_code_collision(
    tmp_path,
    monkeypatch,
    condition_validation,
) -> None:
    project = _ready_project(tmp_path / "project", marker_code=55)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        processing_inputs.QMessageBox,
        "warning",
        lambda _host, title, message: warnings.append((title, message)),
    )
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=object(),
        event_rows=[("Condition A", "55")],
    )

    assert processing_inputs.build_validated_params(host) is None
    assert condition_validation == [((("Condition A", "55"),), True)]
    assert warnings[0][0] == "Invalid FPVS Protocol"
    assert "also a condition-onset code" in warnings[0][1]
