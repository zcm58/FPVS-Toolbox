"""Header-grid resolution is saved before downstream QC consumes a snapshot."""

from fractions import Fraction
from types import SimpleNamespace

import pytest

from Main_App.gui import processing_inputs
from Main_App.projects import FrequencyProtocol, Project
from tests.processing.test_shared_load_utils import _write_sampling_bdf


@pytest.fixture
def warning_messages(monkeypatch):
    messages = []
    monkeypatch.setattr(
        processing_inputs.QMessageBox, "warning",
        lambda _host, title, message: messages.append((title, message)),
    )
    return messages


def _project_and_params(tmp_path):
    project = Project.load(tmp_path / "project")
    project.event_map = {"Faces": 1}
    project.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(8, 2).with_studio_window(
            145, target_sampling_rate_hz=256,
        )
    )
    project.save()
    params = {
        "frequency_protocol": project.frequency_protocol,
        "frequency_protocol_fingerprint": project.frequency_protocol.fingerprint,
        "downsample": 256, "stim_channel": "Status",
        "analysis": {
            "base_freq": 8.0, "oddball_freq": 4.0,
            "frequency_protocol": project.frequency_protocol.to_manifest(),
            "frequency_protocol_fingerprint": project.frequency_protocol.fingerprint,
        },
    }
    return project, params


def test_header_resolution_saves_one_target_for_all_source_grids(tmp_path, warning_messages):
    project, params = _project_and_params(tmp_path)
    sources = []
    for rate in (250, 1024):
        path = tmp_path / f"P{rate}.bdf"
        _write_sampling_bdf(path, samples=(rate, rate, rate))
        sources.append(SimpleNamespace(path=path))
    host = SimpleNamespace(currentProject=project)

    assert processing_inputs._resolve_analysis_window_for_processing(host, sources, params)

    resolved = params["frequency_protocol"]
    assert resolved is project.frequency_protocol
    assert resolved.expected_analyzed_oddball_cycles == 144
    assert resolved.analysis_window.maximum_oddball_cycles == 145
    assert resolved.analysis_window.source_sampling_rates_hz == (Fraction(250), Fraction(1024))
    assert resolved.expected_analyzed_samples(250) == 9000
    assert resolved.expected_analyzed_samples(256) == 9216
    assert params["frequency_protocol_fingerprint"] == resolved.fingerprint
    assert params["analysis"]["frequency_protocol"] == resolved.to_manifest()
    assert params["analysis"]["frequency_protocol_fingerprint"] == resolved.fingerprint
    assert params["analysis"]["oddball_freq"] == 4.0
    assert Project.load(project.project_root).frequency_protocol == resolved
    assert warning_messages == []


def test_subset_processing_preserves_the_previously_verified_project_grids(tmp_path, warning_messages):
    project, params = _project_and_params(tmp_path)
    first = tmp_path / "P1.bdf"
    second = tmp_path / "P2.bdf"
    _write_sampling_bdf(first, samples=(250, 250, 250))
    _write_sampling_bdf(second, samples=(1024, 1024, 1024))
    host = SimpleNamespace(currentProject=project)
    assert processing_inputs._resolve_analysis_window_for_processing(
        host, [SimpleNamespace(path=first), SimpleNamespace(path=second)], params,
    )
    before = project.frequency_protocol.fingerprint
    assert processing_inputs._resolve_analysis_window_for_processing(
        host, [SimpleNamespace(path=second)], params,
    )
    assert project.frequency_protocol.fingerprint == before
    assert project.frequency_protocol.expected_analyzed_oddball_cycles == 144
    assert warning_messages == []


def test_single_file_launch_resolves_against_the_entire_project_before_qc(
    tmp_path, warning_messages, inline_source_registration_work,
):
    project, params = _project_and_params(tmp_path)
    project.input_folder.mkdir(parents=True, exist_ok=True)
    first = project.input_folder / "P1.bdf"
    second = project.input_folder / "P2.bdf"
    _write_sampling_bdf(first, samples=(256, 256, 256))
    _write_sampling_bdf(second, samples=(250, 250, 250))
    project.save()
    qc_targets = []

    def qc_workflow(_host, _infos, current_params):
        qc_targets.append(current_params["frequency_protocol"].expected_analyzed_oddball_cycles)
        return True

    host = SimpleNamespace(
        currentProject=project, data_paths=[str(first)],
        file_mode=SimpleNamespace(get=lambda: "Single"),
        settings=SimpleNamespace(debug_enabled=lambda: False),
        log=lambda *_args, **_kwargs: None,
        _build_validated_params=lambda: {**params, "event_id_map": {"Faces": 1}},
        review_participants_for_processing=lambda *_args: True,
        run_preprocessing_qc_workflow=qc_workflow,
    )
    assert processing_inputs.validate_inputs(host)
    assert len(inline_source_registration_work) == 1
    assert not inline_source_registration_work[0].requires_source_review
    assert [row.raw_file for row in inline_source_registration_work[0].additions] == [first]
    assert qc_targets == [144]
    assert project.frequency_protocol.analysis_window.source_sampling_rates_hz == (
        Fraction(250), Fraction(256),
    )
    assert host.data_paths == [str(first)]
    assert warning_messages == []


def test_not_started_recording_keeps_existing_exclusion_policy(tmp_path, monkeypatch, warning_messages):
    project, params = _project_and_params(tmp_path)
    path = tmp_path / "P1.bdf"
    header_size = _write_sampling_bdf(path, samples=(250, 250, 250))
    data = bytearray(path.read_bytes()[:header_size])
    data[236:244] = b"0       "
    path.write_bytes(data)
    monkeypatch.setattr(
        processing_inputs, "read_bdf_sampling_rate_hz",
        lambda *_args, **_kwargs: pytest.fail("An excluded empty recording has no source grid."),
    )
    before = project.frequency_protocol
    assert processing_inputs._resolve_analysis_window_for_processing(
        SimpleNamespace(currentProject=project), [SimpleNamespace(path=path)], params,
    )
    assert project.frequency_protocol == before
    assert warning_messages == []


def test_malformed_header_stops_window_resolution_without_changing_the_project(tmp_path, warning_messages):
    project, params = _project_and_params(tmp_path)
    path = tmp_path / "P1.bdf"
    _write_sampling_bdf(path, samples=(250, 250, 256))
    before = project.frequency_protocol
    assert not processing_inputs._resolve_analysis_window_for_processing(
        SimpleNamespace(currentProject=project), [SimpleNamespace(path=path)], params,
    )
    assert project.frequency_protocol == before
    assert Project.load(project.project_root).frequency_protocol == before
    assert params["frequency_protocol_fingerprint"] == before.fingerprint
    assert warning_messages[0][0] == "Analysis Window Unavailable"
    assert "share one sampling rate" in warning_messages[0][1]


def test_window_save_failure_stops_processing_and_restores_live_protocol(tmp_path, monkeypatch, warning_messages):
    project, params = _project_and_params(tmp_path)
    path = tmp_path / "P1.bdf"
    _write_sampling_bdf(path, samples=(250, 250, 250))
    before = project.frequency_protocol

    def fail_save():
        raise OSError("Project is read-only")

    monkeypatch.setattr(project, "save", fail_save)
    assert not processing_inputs._resolve_analysis_window_for_processing(
        SimpleNamespace(currentProject=project), [SimpleNamespace(path=path)], params,
    )
    assert project.frequency_protocol == before
    assert params["frequency_protocol"] is before
    assert Project.load(project.project_root).frequency_protocol == before
    assert warning_messages == [("Analysis Window Unavailable", "Project is read-only")]


def test_runtime_incompatible_fractional_grid_fails_before_qc(tmp_path, warning_messages):
    project, params = _project_and_params(tmp_path)
    path = tmp_path / "P1.bdf"
    _write_sampling_bdf(path, samples=(256, 256, 256), duration="3")
    before = project.frequency_protocol
    assert not processing_inputs._resolve_analysis_window_for_processing(
        SimpleNamespace(currentProject=project), [SimpleNamespace(path=path)], params,
    )
    assert project.frequency_protocol == before
    assert "256/3 Hz" in warning_messages[0][1]
    assert "exact processing grid" in warning_messages[0][1]


def test_fixed_advanced_protocol_is_not_recalculated(tmp_path, monkeypatch):
    project, params = _project_and_params(tmp_path)
    fixed = project.frequency_protocol.with_expected_cycles(144, source="manual")
    project.update_frequency_protocol(fixed)
    params["frequency_protocol"] = fixed
    params["frequency_protocol_fingerprint"] = fixed.fingerprint
    monkeypatch.setattr(
        processing_inputs, "inspect_bdf_header",
        lambda *_args: pytest.fail("Fixed protocols retain their explicit target."),
    )
    assert processing_inputs._resolve_analysis_window_for_processing(
        SimpleNamespace(currentProject=project), [SimpleNamespace(path=tmp_path / "missing.bdf")], params,
    )
    assert project.frequency_protocol is fixed
