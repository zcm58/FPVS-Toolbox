"""Real BrainVision loading, marker planning, preprocessing and spectral export."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.io.load_utils import open_preflight_eeg_file
from Main_App.io.recording_sources import companion_identity
from Main_App.io.spectral_data import SPECTRAL_SHEET_NAMES, read_spectral_sheet
from Main_App.processing.preflight_qc import _find_preflight_events, scan_preprocessing_qc
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.qc_source_prefetch import QcSourcePrefetch
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers.process_runner import _run_full_pipeline_for_file


pytestmark = [pytest.mark.processing, pytest.mark.project_io, pytest.mark.integration]
CHANNELS = ["Fz", "Cz", "Pz", "O1", "O2"]
SFREQ = 256


def _recording(tmp_path: Path, extension: str, channels: list[str] | None = None) -> tuple[Path, np.ndarray]:
    channels = channels or CHANNELS
    times = np.arange(80 * SFREQ) / SFREQ
    amplitudes = (np.array([10, 8, 4, 2, 1]) if channels == CHANNELS else np.linspace(10, 1, len(channels)))[:, None]
    signal_uv = amplitudes * np.sin(2 * np.pi * 2 * times)
    signal_uv += np.linspace(1, 5, len(channels))[:, None] * np.sin(2 * np.pi * 8 * times)
    # Small deterministic noise keeps neighboring-noise metrics well-defined.
    signal_uv += np.random.default_rng(1234).normal(scale=.03, size=signal_uv.shape)
    samples = [2 * SFREQ + index * (SFREQ // 2) for index in range(129)]
    events = np.array([[0, 0, 21], *[[sample, 0, 55] for sample in samples]])
    path = tmp_path / f"P01{extension}"
    if extension == ".vhdr":
        path.write_text(
            "Brain Vision Data Exchange Header File Version 1.0\n"
            "[Common Infos]\nCodepage=UTF-8\nDataFile=P01.eeg\nMarkerFile=P01.vmrk\n"
            f"DataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels={len(channels)}\n"
            f"SamplingInterval={1e6 / SFREQ}\n[Binary Infos]\nBinaryFormat=IEEE_FLOAT_32\n"
            "[Channel Infos]\n" + "".join(f"Ch{i}={name},,1,µV\n" for i, name in enumerate(channels, 1)),
            encoding="utf-8",
        )
        path.with_suffix(".vmrk").write_text(
            "Brain Vision Data Exchange Marker File, Version 1.0\n"
            "[Common Infos]\nCodepage=UTF-8\nDataFile=P01.eeg\n[Marker Infos]\n"
            + "".join(f"Mk{i}=Stimulus,S {code},{sample + 1},1,0\n" for i, (sample, _, code) in enumerate(events, 1)),
            encoding="utf-8",
        )
        signal_uv.T.astype("<f4").tofile(path.with_suffix(".eeg"))
    else:
        path.write_text(json.dumps({
            "BVRF": {"Version": "1.0.0"}, "BVRFHeaderFile": {"Version": "1.0.0"},
            "EEGModality": {
                "BVRFFiles": {"DataFile": {"Version": "1.0.0", "NumericDataType": "Single"},
                              "MarkerFile": {"Version": "1.0.0"}},
                "DataSpecific": {"SamplingFrequencyInHertz": SFREQ},
                "Channels": [{"Name": name, "Type": "EEG", "Unit": "µV", "ResolutionPerBit": 1}
                             for name in channels],
            },
        }), encoding="utf-8")
        path.with_suffix(".bvrm").write_text(
            "Sample\tType\tCode\tValue\n" + "".join(f"{sample}\tStimulus\tS\t{code}\n" for sample, _, code in events),
            encoding="utf-8",
        )
        signal_uv.T.astype("<f4").tofile(path.with_suffix(".bvrd"))
    return path, events


def _settings(path: Path, *, preload_in_memory: bool) -> dict:
    return {
        "hardware_platform": "brain_products", "hardware_confirmed": True,
        "electrode_montage": "recorded", "initial_reference": "recorded",
        "initial_reference_channels": [], "drop_reference_channels": False,
        "max_idx_keep": None, "stim_channel": "Status", "downsample_rate": 128,
        "high_pass": 1.0, "low_pass": 40.0, "line_noise_filter_enabled": False,
        "kurtosis_screening_enabled": False, "raw_signal_screening_enabled": False,
        "removed_electrode_detection_mode": "off", "auto_detect_removed_electrodes": False,
        "enable_preprocessed_cache": True, "experimental_ram_preload": preload_in_memory,
        "event_id_map": {"Faces": 21},
        "_fpvs_participant_id_by_file": {str(path.resolve()): "P01"},
        "_fpvs_recording_id_by_file": {str(path.resolve()): "P01"},
        "_fpvs_processing_fingerprint": "brain-products-integration-fixture",
        "_fpvs_processing_fingerprint_version": "integration-v1",
    }


@pytest.mark.parametrize("extension,preload_in_memory,montage,channels", [
    (".vhdr", False, "recorded", CHANNELS), (".bvrh", False, "recorded", CHANNELS),
    (".vhdr", True, "recorded", CHANNELS), (".bvrh", True, "recorded", CHANNELS),
    (".vhdr", False, "standard_1020", CHANNELS),
    (".bvrh", False, "recorded", [f"Sensor{i:02d}" for i in range(64)]),
])
def test_real_recording_to_spectral_export(tmp_path, extension, preload_in_memory, montage, channels):
    project_root = tmp_path / "project"
    project_root.mkdir()
    path, expected_events = _recording(project_root, extension, channels)
    settings = _settings(path, preload_in_memory=preload_in_memory)
    settings["electrode_montage"] = montage
    protocol = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=128,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    app = SimpleNamespace(log=lambda _: None)
    with open_preflight_eeg_file(app, str(path), acquisition_settings=settings) as raw:
        events, source = _find_preflight_events(raw, stim_channel="Status")
        assert source == "stim"
        np.testing.assert_array_equal(events, expected_events)
        assert raw.ch_names == [*channels, "Status"]
        plan = plan_preflight_qc_events(
            events=events, event_map={"Faces": 21}, sfreq=SFREQ, n_times=raw.n_times,
            frequency_protocol=protocol,
        )
        assert not plan.unresolved_occurrences
    settings.update(frequency_protocol=protocol, _fpvs_preflight_event_plans_by_file={str(path.resolve()): plan.to_payload()})
    result = _run_full_pipeline_for_file(path, settings, {"Faces": 21}, project_root, project_root)
    assert result["status"] == "ok", result
    assert result["post_export_ok"] is True
    assert result["geometry"]["hardware_platform"] == "brain_products"
    assert result["geometry"]["retained_scalp_channels"] == channels
    assert result["geometry"]["geometry_status"] == ("available" if montage == "standard_1020" else "unavailable")
    assert result["audit"]["sfreq"] == 128
    assert result["export_receipts"]
    assert result["preproc_cache_status"] == "stored"
    assert result["source_derivative_status"] == "complete", result["source_derivative_warning"]
    source_root = project_root / "6 - Source Localization" / "Source-Ready Time Domain v1"
    source_sidecars = [json.loads(item.read_text(encoding="utf-8"))
                       for item in source_root.rglob("*.json") if "manifests" not in item.parts]
    assert len(source_sidecars) == 1
    assert source_sidecars[0]["source_signature"]["recording_sources"] == companion_identity(path)["recording_sources"]
    bundles = list(project_root.rglob("*.fpvs"))
    assert len(bundles) == 1
    full_fft = read_spectral_sheet(bundles[0], sheet_name=SPECTRAL_SHEET_NAMES[0])
    assert full_fft.iloc[:, 0].tolist() == channels
    frequencies = np.array([float(name.removesuffix("_Hz")) for name in full_fft.columns[1:]])
    row = np.asarray(full_fft.iloc[0, 1:], dtype=float)
    peak = frequencies[int(np.argmax(row))]
    assert peak == pytest.approx(2.0)
    # The exported amplitudes are µV; 10µV at Fz minus the five-channel 5µV mean.
    expected_uv = 5.0 if channels == CHANNELS else 4.5
    assert row[int(np.argmin(abs(frequencies - 2)))] == pytest.approx(expected_uv, rel=.08)
    second = _run_full_pipeline_for_file(path, settings, {"Faces": 21}, project_root, project_root)
    assert second["status"] == "ok", second
    assert second["preproc_cache_status"] == "hit"
    assert second["geometry"] == result["geometry"]
    cached_fft = read_spectral_sheet(bundles[0], sheet_name=SPECTRAL_SHEET_NAMES[0])
    # The established FIF cache stores single precision; its roundoff is below
    # 1e-8 microvolts here, including bins whose true amplitude is almost zero.
    np.testing.assert_allclose(cached_fft.iloc[:, 1:].to_numpy(dtype=float),
                               full_fft.iloc[:, 1:].to_numpy(dtype=float), atol=1e-8)


@pytest.mark.parametrize("extension", [".vhdr", ".bvrh"])
@pytest.mark.parametrize("change_companion", [False, True])
def test_threaded_prefetch_owns_memmap_and_rechecks_all_companions(tmp_path, extension, change_companion):
    path, events = _recording(tmp_path, extension)
    settings = _settings(path, preload_in_memory=False)
    session = QcSourcePrefetch(tmp_path, [SimpleNamespace(path=path, subject_id="P01")], settings)
    with ThreadPoolExecutor(max_workers=1) as workers:
        workers.submit(session.run).result(timeout=30)
        staged = list((tmp_path / ".fpvs_processing").rglob("*_raw.dat"))
        assert len(staged) == 1
        if change_companion:
            companion = path.with_suffix(".eeg" if extension == ".vhdr" else ".bvrd")
            with companion.open("r+b") as handle:
                handle.write(np.array([12.5], dtype="<f4").tobytes())
        raw = workers.submit(session.take, path, settings=settings).result(timeout=30)
        if change_companion:
            assert raw is None
        else:
            assert isinstance(raw._data, np.memmap)
            assert session.source_content_identity_for(raw)["sha256"]
            np.testing.assert_array_equal(raw._fpvs_brain_products_events, events)
            workers.submit(session.release, raw).result(timeout=30)
        workers.submit(session.close).result(timeout=30)
    assert not any(item.exists() for item in staged)


@pytest.mark.parametrize("extension", [".vhdr", ".bvrh"])
def test_real_preprocessing_qc_scanner_preserves_brain_products_marker_plan(tmp_path, extension):
    path, events = _recording(tmp_path, extension)
    settings = _settings(path, preload_in_memory=False)
    settings["frequency_protocol"] = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=128,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    result = scan_preprocessing_qc(
        [RawFileInfo(path, "P01", "control")], settings,
        max_workers=1, project_root=tmp_path, event_map={"Faces": 21},
    )
    assert not result.cancelled
    assert len(result.results) == 1
    item = result.results[0]
    assert not item.load_error, item
    assert item.participant_id == "P01"
    assert item.condition_qc["event_plan"]["event_count"] == len(events)
    assert item.condition_qc["event_plan"]["approved_occurrences"]
