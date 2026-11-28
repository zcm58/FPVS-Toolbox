from dataclasses import replace

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_profiles import UNICORN_CHANNELS
from Main_App.io.acticap_montages import make_acticap_montage
from Main_App.projects.hardware import ACTICAP_GACS_64, ACTICAP_GACS_128
from Tools.Publication_Maps.display_montage import display_montage_choices, load_display_montage


@pytest.mark.parametrize("name", mne.channels.get_builtin_montages())
def test_builtin_display_montages_keep_each_templates_own_labels_and_head_coordinates(name):
    montage = mne.channels.make_standard_montage(name)
    expected = mne.create_info(montage.ch_names, 100, "eeg")
    expected.set_montage(montage)
    chosen = load_display_montage(name)
    assert tuple(dict(chosen.positions)) == tuple(expected.ch_names)
    np.testing.assert_allclose(list(dict(chosen.positions).values()), [ch["loc"][:3] for ch in expected["chs"]])


@pytest.mark.parametrize("cap", (ACTICAP_GACS_64, ACTICAP_GACS_128))
@pytest.mark.parametrize("recorded_fcz", (False, True))
def test_named_acticap_choices_use_the_selected_channel_64_wiring(cap, recorded_fcz):
    key = f"{cap}:FCz" if recorded_fcz else cap
    site = "FCz" if recorded_fcz else "Iz"
    assert f"{site} recorded" in dict(display_montage_choices())[key]
    selected = load_display_montage(key)
    actual = dict(selected.positions)
    expected = make_acticap_montage(cap, recorded_fcz=recorded_fcz).get_positions()["ch_pos"]
    assert tuple(actual) == tuple(expected) and tuple(actual)[63] == site
    np.testing.assert_array_equal(tuple(actual.values()), tuple(expected.values()))


def test_named_unicorn_choice_uses_its_acquisition_sites_and_keeps_all_mne_choices():
    choices = dict(display_montage_choices())
    assert len(choices) == len(mne.channels.get_builtin_montages()) + 5
    assert set(mne.channels.get_builtin_montages()) <= choices.keys()
    assert "Unicorn" in choices["unicorn8"]
    expected = mne.create_info(UNICORN_CHANNELS, 250, "eeg")
    expected.set_montage("standard_1020")
    actual = dict(load_display_montage("unicorn8").positions)
    assert tuple(actual) == UNICORN_CHANNELS
    np.testing.assert_array_equal(tuple(actual.values()), [ch["loc"][:3] for ch in expected["chs"]])


def test_custom_head_coordinates_preserve_arbitrary_names_and_units(tmp_path):
    path = tmp_path / "Lab cap.tsv"
    path.write_text("electrode\tx_mm\ty_mm\tz_mm\nL-17\t-52\t2\t73\nR-9\t54\t4\t72\n", encoding="utf-8")
    chosen = load_display_montage(path)
    assert chosen.name == path.name and list(dict(chosen.positions)) == ["L-17", "R-9"]
    np.testing.assert_allclose(dict(chosen.positions)["L-17"], [-.052, .002, .073])
    assert load_display_montage(chosen) is chosen
    with pytest.raises(ValueError, match="unique"):
        replace(chosen, positions=(chosen.positions[0], ("l-17", (.01, .01, .05))))


@pytest.mark.parametrize("body,reason", [
    ("electrode,x,y,z\nL,1,2,3", "x_m"),
    ("electrode,x_m,y_m,z_m\nL,1,2,3", "units"),
    ("electrode,x_m,y_m,z_m\nL,,.01,.02", "line 2"),
    ("electrode,x_m,y_m,z_m\nL,.01,nan,.02", "finite"),
])
def test_bad_custom_coordinates_report_actionable_error(tmp_path, body, reason):
    path = tmp_path / "cap.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        load_display_montage(path)


def test_digitization_file_requires_known_orientation(tmp_path):
    path = tmp_path / "lab-dig.fif"
    positions = {"Sensor 9": [-.055, .045, .061]}
    mne.channels.make_dig_montage(ch_pos=positions, coord_frame="unknown").save(path)
    with pytest.raises(ValueError, match="landmarks"):
        load_display_montage(path)
    mne.channels.make_dig_montage(ch_pos=positions, coord_frame="head").save(path, overwrite=True)
    np.testing.assert_allclose(dict(load_display_montage(path).positions)["Sensor 9"], positions["Sensor 9"])


def test_captrak_file_reads_measured_positions_in_metres(tmp_path):
    path = tmp_path / "Lab.bvct"
    points = {"Nasion": (0, 100, 0), "LPA": (-80, 0, 0), "RPA": (80, 0, 0), "Site 7": (35, 20, 82)}
    entries = "".join(
        f"<Electrode><Name>{name}</Name><X>{x}</X><Y>{y}</Y><Z>{z}</Z></Electrode>"
        for name, (x, y, z) in points.items()
    )
    path.write_text(f"<CapTrak><CapTrakElectrodeList>{entries}</CapTrakElectrodeList></CapTrak>")
    assert tuple(dict(load_display_montage(path).positions)) == ("Site 7",)
    np.testing.assert_allclose(dict(load_display_montage(path).positions)["Site 7"], [.035, .020, .082])
    path.write_text("<CapTrak><CapTrakElectrodeList /></CapTrak>")
    with pytest.raises(ValueError, match="landmarks"):
        load_display_montage(path)
