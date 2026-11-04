from __future__ import annotations

import json
from pathlib import Path

import mne
import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers import hauk_source_psd as psd
from Tools.LORETA_Visualizer.source_producers.native_spectral_reference import (
    build_native_sphere_model,
    deterministic_reference_samples,
)

REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "native_spectral_reference_v1.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=("MNE", "eLORETA"))
def native_model(request):
    return build_native_sphere_model(request.param)


@pytest.mark.parametrize("n_times", [511, 512])
def test_native_production_spectra_match_frozen_time_domain_inverse_reference(native_model, n_times):
    """The golden file used a native signed time-domain inverse + explicit DFT.

    It did not call production FFT/PSD, aggregation, or Z routines. Both sample
    parities include the final real-FFT bin to distinguish Nyquist scaling.
    """
    model = native_model
    expected = next(case for case in REFERENCE["cases"] if case["method"] == model.method and case["n_times"] == n_times)
    raw = mne.io.RawArray(deterministic_reference_samples(n_times), model.info.copy(), verbose=False)
    orientation = psd.SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL if model.method == "MNE" else psd.SOURCE_ORIENTATION_MODE_VECTOR_NORM
    config = psd.HaukSourcePsdConfig(
        selected_harmonics_hz=tuple(value * 200. / n_times for value in expected["harmonic_bins"]),
        inverse_method=model.method, source_orientation_mode=orientation,
    )
    result = psd.compute_hauk_source_psd(averaged_raw=raw, inverse_operator=model.inverse, config=config)
    if model.method == "MNE":
        amplitudes, _frequencies = psd._scalar_source_amplitudes(
            averaged_raw=raw, inverse_operator=model.inverse, config=config,
            frequency_plan=result.frequency_plan, compute_source_psd_func=None,
        )
        # Native scalar PSD also returns intervening bins; match exact requested bins.
        indices = np.rint(_frequencies * n_times / 200.).astype(int)
        amplitudes = amplitudes[:, np.isin(indices, expected["required_bins"])]
    else:
        amplitudes, _frequencies = psd._vector_norm_source_amplitudes(
            averaged_raw=raw, inverse_operator=model.inverse, config=config,
            frequency_plan=result.frequency_plan, apply_inverse_func=None,
        )
    np.testing.assert_allclose(amplitudes, expected["source_amplitudes"], rtol=REFERENCE["relative_tolerance"], atol=REFERENCE["amplitude_absolute_tolerance"])
    np.testing.assert_allclose(result.summed_source_amplitudes, expected["summed_source_amplitudes"], rtol=REFERENCE["relative_tolerance"], atol=REFERENCE["amplitude_absolute_tolerance"])
    np.testing.assert_allclose(result.values, expected["z_scores"], rtol=REFERENCE["relative_tolerance"], atol=REFERENCE["z_absolute_tolerance"])


def test_reference_is_explicitly_numerical_not_scientific_qualification():
    assert REFERENCE["format"] == "fpvs-native-source-spectral-reference-v1"
    assert "population inference" in REFERENCE["not_tested"]
    assert REFERENCE["dependencies"]["mne"] == "1.9.0"
