"""Named BDF caps retain electrode identity, sample values, and channel roles."""
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_metadata import freeze_retained_geometry, validate_loaded_geometry
from Main_App.io.load_utils import open_preflight_eeg_file
from Main_App.io.pipeline_events import canonical_recording_events
from Main_App.processing.reference import apply_recorded_reference
from Main_App.projects.hardware import confirm_hardware_selection, unicorn_acquisition_profile
from tests.bdf_factory import write_bdf
from tests.project_io.test_unicorn_raw import AUXILIARIES, _fixture


BIOSEMI_BANKS = tuple(f"{bank}{number}" for bank in "ABCD" for number in range(1, 33))
UNICORN_CLIPS = ("Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8")


def _settings(root, platform, montage):
    settings = confirm_hardware_selection({}, platform, confirmed_change=True)
    settings.update(project_root=str(root), electrode_montage=montage)
    return settings


def _assert_template_positions(geometry, names, template):
    expected = mne.create_info(list(names), sfreq=250, ch_types="eeg")
    expected.set_montage(template)
    assert geometry["coordinate_source"] == "explicit_project_template"
    assert geometry["coordinate_frame"] == "head"
    assert set(geometry["channel_coordinates_m"]) == set(names)
    for name, channel in zip(names, expected["chs"], strict=True):
        np.testing.assert_array_equal(geometry["channel_coordinates_m"][name], channel["loc"][:3])


@pytest.mark.parametrize("use_external_reference", [False, True], ids=["recorded-reference", "dropped-reference"])
def test_activethree_radial_banks_bind_by_label_across_preflight_and_reference(tmp_path, use_external_reference):
    # Reorder channels across all four banks and insert an auxiliary
    # between two scalp electrodes. Every electrode carries a distinguishable signal.
    scalp = [BIOSEMI_BANKS[index] for index in [*range(127, -1, -2), *range(0, 128, 2)]]
    source_order = [*scalp[:9], "EXG3", *scalp[9:], "AUX1"]
    rate = 256
    samples = np.arange(rate)
    expected_uv = np.arange(128)[:, None] * 10 + samples
    values = {name: [wave] for name, wave in zip(BIOSEMI_BANKS, expected_uv, strict=True)}
    values.update(EXG3=[[4] * rate], AUX1=[[5] * rate], Status=[[0, 21, 0, 55] + [0] * (rate - 4)])
    path = write_bdf(
        tmp_path / "participant.bdf", variant="BDF", record_onsets=("0",), eeg_names=source_order,
        samples_per_record=rate, signal_values=values, signal_units={"AUX1": ""},
    )
    settings = _settings(tmp_path, "biosemi_active_three", "biosemi128")
    settings["channel_types"] = {"AUX1": "misc"}
    if use_external_reference:
        settings.update(initial_reference="channels", initial_reference_channels=["EXG3"], drop_reference_channels=True)
    with open_preflight_eeg_file(SimpleNamespace(log=lambda _: None), str(path), acquisition_settings=settings) as raw:
        assert raw.info["sfreq"] == rate and raw.n_times == rate
        assert [name for name in raw.ch_names if name in BIOSEMI_BANKS] == scalp
        assert raw.get_channel_types(picks=["AUX1", "Status"]) == ["misc", "stim"]
        np.testing.assert_array_equal(raw.get_data(picks=list(BIOSEMI_BANKS)), expected_uv * 1e-6)
        np.testing.assert_array_equal(raw.get_data(picks=["Status"])[0], values["Status"][0])
        contract = raw._fpvs_recording_contract
        contract.validate(raw, settings)
        assert contract.montage_id == "biosemi128" and not contract.spatial_qc_supported
        assert contract.geometry["retained_scalp_channels"] == scalp
        assert set(contract.geometry["canonical_scalp_channels"]) == set(BIOSEMI_BANKS)
        _assert_template_positions(contract.geometry, BIOSEMI_BANKS, "biosemi128")
        raw.load_data()
        apply_recorded_reference(raw, settings, contract)
        if use_external_reference:
            assert "EXG3" not in raw.ch_names
            np.testing.assert_allclose(raw.get_data(picks=list(BIOSEMI_BANKS)), (expected_uv - 4) * 1e-6, atol=1e-18, rtol=0)
        else:
            assert raw.get_channel_types(picks=["EXG3"]) == ["misc"]
        geometry = freeze_retained_geometry(raw, settings, stim_channel="Status", recording_contract=contract)
        assert geometry["retained_scalp_channels"] == scalp
        assert geometry["montage_id"] == "biosemi128"
        assert geometry["channel_coordinates_m"] == contract.geometry["channel_coordinates_m"]


@pytest.mark.parametrize("substitute", [(), ("PO8",)], ids=["missing", "same-count-wrong-label"])
def test_activethree_radial_preset_rejects_incompatible_electrodes(tmp_path, substitute):
    path = write_bdf(tmp_path / "participant.bdf", variant="BDF", record_onsets=("0",),
                     eeg_names=BIOSEMI_BANKS[:-1] + substitute, signal_values={"Status": [[0, 21] + [0] * 248]})
    settings = _settings(tmp_path, "biosemi_active_three", "biosemi128")
    with pytest.raises(ValueError, match="D32|PO8|128"):
        with open_preflight_eeg_file(SimpleNamespace(log=lambda _: None), str(path), acquisition_settings=settings):
            pytest.fail("Incomplete radial cap passed admission")


def test_unicorn_factory_clips_keep_their_positions_and_volts_in_a_reordered_header(tmp_path):
    shuffled = [7, 1, 4, 6, 0, 5, 2, 3]
    recorded = [f"EEG {index + 1}" for index in shuffled]
    path = _fixture(tmp_path / "participant.bdf", eeg_names=[*recorded, *AUXILIARIES])
    settings = _settings(tmp_path, "unicorn", "unicorn8")
    settings["electrode_mapping_profile"] = "unicorn_factory_v1"
    settings["acquisition_profile"] = unicorn_acquisition_profile(settings)
    with open_preflight_eeg_file(SimpleNamespace(log=lambda _: None), str(path), acquisition_settings=settings) as raw:
        assert raw.info["sfreq"] == 250 and raw.n_times == 250
        assert [name for name in raw.ch_names if name in UNICORN_CLIPS] == [UNICORN_CLIPS[index] for index in shuffled]
        assert raw.get_channel_types(picks=list(UNICORN_CLIPS)) == ["eeg"] * 8
        assert raw.get_channel_types(picks=[*AUXILIARIES, "Status"]) == ["misc", "misc", "misc", "stim"]
        expected_codes = -1000 * np.arange(1, 9)
        expected_volts = ((expected_codes + 8388608) * (1500000 / 16777215) - 750000) * 1e-6
        np.testing.assert_allclose(raw.get_data(picks=list(UNICORN_CLIPS), start=1, stop=2)[:, 0],
                                   expected_volts, rtol=0, atol=2e-16)
        np.testing.assert_array_equal(canonical_recording_events(raw)[:, [0, 2]], [[1, 55], [2, 55], [3, 1], [4, 255]])
        contract = raw._fpvs_recording_contract
        contract.validate(raw, settings)
        assert contract.montage_id == "unicorn8" and not contract.interpolation_allowed
        assert validate_loaded_geometry(raw, contract) == contract.geometry
        _assert_template_positions(contract.geometry, UNICORN_CLIPS, "standard_1020")
