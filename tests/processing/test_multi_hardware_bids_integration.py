"""Generated format fixtures exercise BIDS admission and the shared pipeline.

These are software equivalence checks, not acquisition hardware calibration.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pytest

from tests.bdf_factory import write_bdf
from tests.processing.test_brain_products_integration import _recording, _settings
from Main_App.io.acquisition_profiles import UNICORN_CHANNELS
from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from Main_App.io.load_utils import open_preflight_eeg_file
from Main_App.io.spectral_data import SPECTRAL_SHEET_NAMES, read_spectral_sheet
from Main_App.processing.preflight_qc import _find_preflight_events
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.preprocess import perform_preprocessing
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.projects.hardware import unicorn_acquisition_profile
from Main_App.workers.process_runner import _run_full_pipeline_for_file


pytestmark = [pytest.mark.processing, pytest.mark.project_io, pytest.mark.integration]


def _bdf_recording(root: Path, case: str):
    mobile = case.startswith("unicorn")
    legacy = case == "active_two"
    rate = 250 if mobile else 256
    scalp = list(UNICORN_CHANNELS) if mobile else list(BIOSEMI64_CHANNELS) if legacy else [
        f"E{number:02d}" for number in range(1, (32 if case == "active_three_32" else 8) + 1)
    ]
    factory = case == "unicorn_factory_units"
    recorded = [f"EEG {i}" for i in range(1, 9)] if factory else scalp
    extras = ["CNT", "VALID", "DT"] if mobile else ["EXG1", "EXG2"] if legacy else ["EXG3", "EXG4", "AUX1"]
    times = np.arange(80 * rate) / rate
    amplitudes = np.linspace(10, 1, len(scalp))
    signal_uv = amplitudes[:, None] * np.sin(2 * np.pi * 2 * times)
    signal_uv += np.linspace(1, 5, len(scalp))[:, None] * np.sin(2 * np.pi * 8 * times)
    signal_uv += np.random.default_rng(643).normal(scale=.03, size=signal_uv.shape)
    physical = (-750000, 750000) if mobile else (-262144, 262143)
    digital = (-8388608, 8388607)
    gain = (physical[1] - physical[0]) / (digital[1] - digital[0])
    eeg_integers = np.rint((signal_uv - physical[0]) / gain + digital[0]).astype(np.int64)
    values = {name: eeg_integers[index].reshape(80, rate).tolist() for index, name in enumerate(recorded)}
    for name in extras:
        vector = np.arange(len(times)) if name == "CNT" else np.full(len(times), 1 if name == "VALID" else 4 if name == "DT" else 0)
        values[name] = vector.reshape(80, rate).tolist()
    samples = [2 * rate + index * (rate // 2) for index in range(129)]
    events = np.array([[rate, 0, 21], *[[sample, 0, 55] for sample in samples]], dtype=np.int64)
    status = np.zeros(len(times), dtype=np.int64)
    status[events[:, 0]] = events[:, 2]
    values["Status"] = status.reshape(80, rate).tolist()
    annotation_events = case in {"unicorn_annotations", "unicorn_reconcile"}
    annotations = [[] for _ in range(80)]
    if annotation_events:
        for sample, _, code in events:
            annotations[int(sample // rate)].append(f"+{sample / rate:g}\x14{int(code)}\x14\x00".encode("ascii"))
    path = write_bdf(
        root / "P01.bdf", variant="BDF+C" if case == "unicorn_bdf_plus" or annotation_events else "BDF",
        record_onsets=tuple(str(i) for i in range(80)), samples_per_record=rate,
        status=case != "unicorn_annotations", annotations=annotations,
        eeg_names=(*recorded, *extras), signal_values=values,
        signal_units={**{name: "?V" if factory else "uV" for name in recorded},
                      **{name: "uV" if name.startswith("EXG") else "" for name in extras}},
        physical_ranges={name: physical for name in recorded},
    )
    expected_volts = (physical[0] + (eeg_integers - digital[0]) * gain) * 1e-6
    settings = _settings(path, preload_in_memory=False)
    settings.update(hardware_platform="unicorn" if mobile else "biosemi" if legacy else "biosemi_active_three")
    if mobile:
        settings.update(electrode_montage="unicorn8", downsample_rate=250)
        if factory:
            settings["electrode_mapping_profile"] = "unicorn_factory_v1"
        settings["acquisition_profile"] = unicorn_acquisition_profile(settings)
        if annotation_events:
            settings["recording_event_policy"] = {
                "authority": "annotations" if case == "unicorn_annotations" else "reconcile",
                "numeric_annotations": True,
            }
            if case == "unicorn_annotations":
                settings["acquisition_profile"]["event_decoder_id"] = "explicit_annotations"
    elif legacy:
        settings.update(electrode_montage="biosemi64", ref_channel1="EXG1", ref_channel2="EXG2")
    else:
        settings.update(initial_reference="channels", initial_reference_channels=["EXG3"],
                        drop_reference_channels=True, channel_types={"AUX1": "misc"})
    return path, events, settings, scalp, rate, expected_volts


CASES = [
    "active_two", "active_three_8", "active_three_32", "brain_products_vhdr", "brain_products_bvrh",
    "unicorn_classic", "unicorn_bdf_plus", "unicorn_factory_units",
    "unicorn_annotations", "unicorn_reconcile",
]


@pytest.mark.parametrize("case", CASES)
def test_generated_hardware_bids_pipeline_and_cache(tmp_path, case):
    root = tmp_path / "project"
    root.mkdir()
    if case.startswith("brain_products"):
        path, expected_events = _recording(root, ".vhdr" if case.endswith("vhdr") else ".bvrh")
        settings = _settings(path, preload_in_memory=False)
        channels, rate, expected_volts = ["Fz", "Cz", "Pz", "O1", "O2"], 256, None
    else:
        path, expected_events, settings, channels, rate, expected_volts = _bdf_recording(root, case)
    original_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    protocol = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=128,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    app = SimpleNamespace(log=lambda _: None)
    import_started = perf_counter()
    with open_preflight_eeg_file(app, str(path), acquisition_settings=settings) as raw:
        events, source = _find_preflight_events(raw, stim_channel="Status")
        np.testing.assert_array_equal(events, expected_events)
        assert source == ("canonical" if case.startswith("unicorn") else "stim")
        assert raw.info["sfreq"] == rate
        import_metadata = dict(raw._fpvs_bids_import)
        assert ".fpvs_cache" in Path(import_metadata["dataset_root"]).parts
        if expected_volts is not None:
            # Equivalent calibration arithmetic differs at ~5e-17 V because
            # its offset and scale are evaluated in a different order by MNE.
            np.testing.assert_allclose(raw.get_data(picks=channels), expected_volts, atol=1e-16, rtol=0)
        plan = plan_preflight_qc_events(
            events=events, event_map={"Faces": 21}, sfreq=rate, n_times=raw.n_times,
            frequency_protocol=protocol,
        )
        assert not plan.unresolved_occurrences
        if case.startswith("unicorn"):
            assert raw._fpvs_mobile_import["hardware_amplitude_calibration"] == "unverified"
            assert raw._fpvs_mobile_import["physical_timing"] == "unknown_uncalibrated"
            assert not raw._fpvs_recording_contract.interpolation_allowed
    preparation_seconds = perf_counter() - import_started
    settings.update(frequency_protocol=protocol, _fpvs_preflight_event_plans_by_file={str(path.resolve()): plan.to_payload()})
    started = perf_counter()
    first = _run_full_pipeline_for_file(path, settings, {"Faces": 21}, root, root)
    processing_seconds = perf_counter() - started
    assert first["status"] == "ok", first
    assert first["post_export_ok"] is True
    assert first["source_derivative_status"] == "complete", first["source_derivative_warning"]
    assert first["preproc_cache_status"] == "stored"
    assert first["geometry"]["retained_scalp_channels"] == channels
    assert first["audit"]["sfreq"] == (250 if case.startswith("unicorn") else 128)
    if case != "active_two":
        assert first["geometry"]["hardware_platform"] == settings["hardware_platform"]
    bundle, = root.rglob("*.fpvs")
    sheets = {name: read_spectral_sheet(bundle, sheet_name=name) for name in SPECTRAL_SHEET_NAMES}
    full_fft = sheets[SPECTRAL_SHEET_NAMES[0]]
    assert full_fft.iloc[:, 0].tolist() == channels
    frequencies = np.array([float(name.removesuffix("_Hz")) for name in full_fft.columns[1:]])
    amplitudes = full_fft.iloc[0, 1:].to_numpy(dtype=float)
    assert frequencies[np.argmax(amplitudes)] == pytest.approx(2)
    expected_amplitude = 5.0 if case.startswith("brain_products") else 4.5
    assert amplitudes[np.argmin(abs(frequencies - 2))] == pytest.approx(expected_amplitude, rel=.08)
    started = perf_counter()
    second = _run_full_pipeline_for_file(path, settings, {"Faces": 21}, root, root)
    cached_seconds = perf_counter() - started
    assert second["status"] == "ok", second
    assert second["preproc_cache_status"] == "hit", second
    assert second["geometry"] == first["geometry"]
    assert second["audit"]["sfreq"] == first["audit"]["sfreq"]
    compared = 0
    maximum_difference = 0.0
    for name, frame in sheets.items():
        cached = read_spectral_sheet(bundle, sheet_name=name)
        assert cached.columns.tolist() == frame.columns.tolist()
        assert cached.iloc[:, 0].tolist() == frame.iloc[:, 0].tolist()
        values, cached_values = frame.iloc[:, 1:].to_numpy(dtype=float), cached.iloc[:, 1:].to_numpy(dtype=float)
        # Historical preprocessing FIF caches use float32; derived noise ratios
        # can magnify its roundoff, so compare with an explicit relative bound.
        if name == SPECTRAL_SHEET_NAMES[0]:
            np.testing.assert_allclose(cached_values, values, atol=1e-8, rtol=0, equal_nan=True)
        else:
            np.testing.assert_allclose(cached_values, values, atol=1e-3, rtol=2e-3, equal_nan=True)
        finite = np.isfinite(values) & np.isfinite(cached_values)
        maximum_difference = max(maximum_difference, float(np.max(abs(values[finite] - cached_values[finite]), initial=0)))
        compared += int(values.size)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_digest
    receipts = tmp_path.parent / "receipts"
    receipts.mkdir(exist_ok=True)
    (receipts / f"{case}.json").write_text(json.dumps({
        "case": case, "hardware_platform": settings["hardware_platform"], "fixture": "generated_not_hardware_qualification",
        "qc": "off", "source_format": path.suffix, "source_sfreq": rate, "output_sfreq": first["audit"]["sfreq"],
        "scalp_channels": len(channels), "canonical_event_count": len(expected_events),
        "bids_conversion_seconds": import_metadata["conversion_seconds"], "import_preparation_seconds": preparation_seconds,
        "processing_seconds": processing_seconds, "warm_cache_processing_seconds": cached_seconds,
        "source_bytes_preserved": True, "cache_numeric_values_compared": compared,
        "cache_maximum_absolute_difference": maximum_difference,
    }, indent=2), encoding="utf-8")


@pytest.mark.parametrize("variant", ["BDF", "BDF+C"])
def test_adjacent_repeated_mobile_markers_survive_bids_and_preprocessing(tmp_path, variant):
    codes = [1, 1, 2, 1, 255, *range(1, 256)]
    values = np.zeros(500, dtype=np.int64)
    values[2:2 + len(codes)] = codes
    path = write_bdf(
        tmp_path / "adjacent.bdf", variant=variant, eeg_names=UNICORN_CHANNELS,
        signal_values={"Status": values.reshape(2, 250).tolist()},
    )
    settings = _settings(path, preload_in_memory=True)
    settings.update(hardware_platform="unicorn", electrode_montage="unicorn8", downsample_rate=250,
                    high_pass=None, low_pass=None)
    settings["acquisition_profile"] = unicorn_acquisition_profile(settings)
    expected = np.column_stack((np.arange(2, 2 + len(codes)), np.zeros(len(codes), dtype=int), codes))
    with open_preflight_eeg_file(SimpleNamespace(log=lambda _: None), str(path), acquisition_settings=settings) as raw:
        np.testing.assert_array_equal(_find_preflight_events(raw, stim_channel="Status")[0], expected)
        working = raw.copy().load_data()
        processed, rejected = perform_preprocessing(
            working, settings, lambda _: None, str(path), recording_contract=raw._fpvs_recording_contract,
        )
        assert processed is not None, settings.get("_fpvs_preprocessing_error")
        assert rejected == 0 and processed.info["sfreq"] == 250
        np.testing.assert_array_equal(_find_preflight_events(processed, stim_channel="Status")[0], expected)
        processed.close()
