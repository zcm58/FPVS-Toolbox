from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from Main_App.gui import processing_inputs
from Main_App.projects import FrequencyProtocol, Project


class _Edit:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _EventRow:
    def __init__(self, label: str, code: int) -> None:
        self._edits = [_Edit(label), _Edit(str(code))]

    def findChildren(self, _widget_type):
        return list(self._edits)


class _Settings:
    @staticmethod
    def get(_section: str, option: str, fallback: str) -> str:
        if option == "bca_upper_limit":
            return "16.8"
        return fallback


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


def test_processing_params_use_one_frozen_project_protocol_snapshot(tmp_path) -> None:
    project = _ready_project(tmp_path / "project")
    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        settings=_Settings(),
        event_rows=[_EventRow("Condition A", 11)],
    )

    params = processing_inputs.build_validated_params(host)

    assert params is not None
    assert params["frequency_protocol"] is project.frequency_protocol
    assert params["frequency_protocol"].oddball_rate_hz.numerator == 3
    assert params["frequency_protocol"].oddball_rate_hz.denominator == 10
    assert params["frequency_protocol_fingerprint"] == project.frequency_protocol.fingerprint
    assert params["base_freq"] == 3.0
    assert params["oddball_freq"] == 0.3
    assert params["analysis"]["frequency_protocol"] == (
        project.frequency_protocol.to_manifest()
    )


def test_processing_params_block_incomplete_protocol_before_event_parsing(
    tmp_path,
    monkeypatch,
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
        settings=_Settings(),
        event_rows=[],
    )

    assert processing_inputs.build_validated_params(host) is None
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
        settings=_Settings(),
        event_rows=[_EventRow("Condition A", 55)],
    )

    assert processing_inputs.build_validated_params(host) is None
    assert warnings[0][0] == "Invalid FPVS Protocol"
    assert "also a condition-onset code" in warnings[0][1]
