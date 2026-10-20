from __future__ import annotations

import json

import pytest

from Main_App.projects.hardware import (
    HardwareChangeConfirmationRequired, confirm_hardware_selection,
    detect_hardware_from_paths, hardware_evidence, require_hardware_ready,
    resolve_hardware,
)
from Main_App.projects.preprocessing_settings import (
    new_project_preprocessing_settings, normalize_preprocessing_settings,
)
from Main_App.projects.project import Project


def _brain_products(settings=None):
    return confirm_hardware_selection(settings or new_project_preprocessing_settings(),
                                      "brain_products", confirmed_change=True)


def test_legacy_biosemi_does_not_gain_hardware_metadata():
    normalized = normalize_preprocessing_settings({})
    assert "hardware_platform" not in normalized
    assert resolve_hardware(normalized).source == "legacy_biosemi"
    assert require_hardware_ready(normalized, ["p01.bdf"]) == "biosemi"


def test_explicit_switch_requires_warning_without_mutating_original():
    original = new_project_preprocessing_settings()
    before = dict(original)
    with pytest.raises(HardwareChangeConfirmationRequired, match="break Toolbox"):
        confirm_hardware_selection(original, "brain_products")
    assert original == before
    selected = _brain_products(original)
    assert selected["max_chan_idx_keep"] is None
    assert selected["initial_reference"] == "recorded"
    assert selected["electrode_montage"] == "recorded"
    assert selected["ref_chan1"] == ""
    assert not selected["kurtosis_screening_enabled"]


def test_project_roundtrip_preserves_hardware_reference_and_qc(tmp_path):
    selected = _brain_products()
    selected.update(initial_reference="channels", initial_reference_channels=["TP9", "TP10"],
                    electrode_montage="easycap-M1", drop_reference_channels=True)
    project = Project.load(tmp_path, manifest={"preprocessing": selected})
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["hardware_platform"] == "brain_products"
    assert reopened.preprocessing["hardware_confirmed"] is True
    assert reopened.preprocessing["initial_reference_channels"] == ["TP9", "TP10"]
    assert reopened.preprocessing["electrode_montage"] == "easycap-M1"
    assert reopened.preprocessing["max_chan_idx_keep"] is None
    assert not reopened.experimental_qc_settings.kurtosis_screening_enabled
    assert not reopened.experimental_qc_settings.raw_signal_screening_enabled
    assert not reopened.experimental_qc_settings.interpolation_burden_review_enabled


def test_stale_unrelated_save_preserves_new_hardware_policy(tmp_path):
    old = Project.load(tmp_path)
    old.save()
    other = Project.load(tmp_path)
    other.update_preprocessing(_brain_products(other.preprocessing))
    other.save()
    old.name = "Unrelated edit"
    old.save()
    reopened = Project.load(tmp_path)
    assert reopened.name == "Unrelated edit"
    assert reopened.preprocessing["hardware_platform"] == "brain_products"
    assert reopened.preprocessing["max_chan_idx_keep"] is None
    assert reopened.preprocessing["ref_chan1"] == ""
    assert not reopened.experimental_qc_settings.kurtosis_screening_enabled


def test_conflicting_hardware_policy_edits_require_reload(tmp_path):
    original = Project.load(tmp_path)
    original.save()
    concurrent = Project.load(tmp_path)
    concurrent.update_preprocessing(_brain_products(concurrent.preprocessing))
    concurrent.save()
    before = (tmp_path / "project.json").read_bytes()
    original.preprocessing["electrode_mapping_profile"] = "biosemi64_1020_ab_v1"
    with pytest.raises(ValueError, match="another window"):
        original.save()
    assert (tmp_path / "project.json").read_bytes() == before


def test_invalid_explicit_hardware_cannot_fall_back_to_biosemi(tmp_path):
    (tmp_path / "project.json").write_text(json.dumps({"preprocessing": {
        "hardware_platform": "unknown", "hardware_confirmed": True,
    }}), encoding="utf-8")
    with pytest.raises(ValueError, match="hardware"):
        Project.load(tmp_path)


@pytest.mark.parametrize("paths, expected", [
    (["p01.VHDR", "p02.bvrh"], "brain_products"),
    (["p01.bdf"], None), (["p01.eeg"], None),
])
def test_file_evidence_uses_primary_header_only(paths, expected):
    assert detect_hardware_from_paths(paths) == expected


def test_mixed_formats_and_wrong_saved_hardware_fail():
    with pytest.raises(ValueError, match="mixes"):
        detect_hardware_from_paths(["a.bdf", "b.vhdr"])
    with pytest.raises(ValueError, match="configured"):
        require_hardware_ready({}, ["a.vhdr"])
    with pytest.raises(ValueError, match="Confirm"):
        require_hardware_ready({"hardware_platform": "brain_products"}, ["a.vhdr"])


def test_future_importer_evidence_is_not_user_confirmation():
    evidence = hardware_evidence("brain_products", source="verified_external_adapter")
    assert evidence.platform == "brain_products"
    assert not evidence.confirmed


@pytest.mark.parametrize("value", ["easycap-M1", "EASYCAP-M1", "standard_1005", "recorded"])
def test_brain_products_normalizer_supports_explicit_geometry(value):
    normalized = normalize_preprocessing_settings({**_brain_products(), "electrode_montage": value})
    assert normalized["max_idx_keep"] is None
    assert normalized["electrode_montage"] == (value if value != "EASYCAP-M1" else "easycap-M1")


def test_brain_products_reference_channels_require_explicit_names():
    with pytest.raises(ValueError, match="at least one"):
        normalize_preprocessing_settings({**_brain_products(), "initial_reference": "channels"})
    normalized = normalize_preprocessing_settings({**_brain_products(), "initial_reference": "channels",
                                                   "initial_reference_channels": "TP9, TP10"})
    assert normalized["initial_reference_channels"] == ["TP9", "TP10"]


@pytest.mark.parametrize("invalid", ["EOG=unknown", "EOG=eog, EOG=misc", "EOG", ["EOG"]])
def test_channel_type_overrides_reject_invalid_or_duplicate_roles(invalid):
    with pytest.raises(ValueError, match="[Cc]hannel type"):
        normalize_preprocessing_settings({**_brain_products(), "channel_types": invalid})


def test_channel_type_overrides_are_canonical_and_persist(tmp_path):
    project = Project.load(tmp_path, manifest={"preprocessing": {
        **_brain_products(), "channel_types": "VEOG=EOG, ECG=ecg, AUX1=misc",
    }})
    project.save()
    assert Project.load(tmp_path).preprocessing["channel_types"] == {
        "VEOG": "eog", "ECG": "ecg", "AUX1": "misc",
    }


def test_biosemi_cannot_select_other_montage():
    with pytest.raises(ValueError, match="BioSemi processing"):
        normalize_preprocessing_settings({"electrode_montage": "standard_1020"})


def test_brain_products_channel_limit_rejects_unusable_average_reference():
    with pytest.raises(ValueError, match="at least two"):
        normalize_preprocessing_settings({**_brain_products(), "max_chan_idx_keep": 1})


@pytest.mark.parametrize("platform", ["biosemi", "biosemi_active_three", "unicorn"])
def test_bdf_requires_explicit_platform_without_inferring_manufacturer(platform):
    settings = confirm_hardware_selection({}, platform, confirmed_change=True)
    assert detect_hardware_from_paths(["p01.bdf"]) is None
    assert require_hardware_ready(settings, ["p01.bdf"]) == platform
    with pytest.raises(ValueError, match="Confirm"):
        require_hardware_ready({**settings, "hardware_confirmed": False}, ["p01.bdf"])
    with pytest.raises(ValueError, match="configured"):
        require_hardware_ready(settings, ["p01.vhdr"])


def test_brain_products_cannot_process_a_bdf_under_a_different_reader():
    with pytest.raises(ValueError, match="incompatible"):
        require_hardware_ready(_brain_products(), ["p01.bdf"])


@pytest.mark.parametrize("spelling", ["BrainProducts", "brain products", "brain_products"])
def test_brain_products_spelling_aliases_canonicalize(spelling):
    assert confirm_hardware_selection({}, spelling, confirmed_change=True)["hardware_platform"] == "brain_products"


@pytest.mark.parametrize("platform", ["biosemi_active_three", "unicorn"])
def test_new_platforms_require_warning_and_persist_settings_without_biosemi_defaults(tmp_path, platform):
    original = new_project_preprocessing_settings()
    with pytest.raises(HardwareChangeConfirmationRequired):
        confirm_hardware_selection(original, platform)
    selected = confirm_hardware_selection(original, platform, confirmed_change=True)
    project = Project.load(tmp_path, manifest={"preprocessing": selected})
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["hardware_platform"] == platform
    assert reopened.preprocessing["hardware_confirmed"] is True
    assert reopened.preprocessing["ref_chan1"] == ""
    assert reopened.preprocessing["ref_chan2"] == ""
    assert not reopened.experimental_qc_settings.kurtosis_screening_enabled
    assert not reopened.experimental_qc_settings.raw_signal_screening_enabled
    assert not reopened.experimental_qc_settings.condition_specific_interpolation_enabled
    if platform == "unicorn":
        assert reopened.preprocessing["downsample"] == 250
        assert reopened.preprocessing["max_chan_idx_keep"] == 8
        assert reopened.preprocessing["electrode_montage"] == "unicorn8"
        assert reopened.preprocessing["acquisition_profile"]["reference_policy"] == "average_scalp"
    else:
        assert reopened.preprocessing["max_chan_idx_keep"] is None
        assert reopened.preprocessing["electrode_montage"] == "recorded"
        assert reopened.preprocessing["initial_reference"] == "recorded"


def test_activethree_retains_configured_references_and_template(tmp_path):
    selected = confirm_hardware_selection({}, "biosemi_active_three", confirmed_change=True)
    selected.update(initial_reference="channels", initial_reference_channels=["EXG1", "EXG2"],
                    drop_reference_channels=True, electrode_montage="standard_1020", channel_types={"VEOG": "eog"})
    project = Project.load(tmp_path, manifest={"preprocessing": selected})
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["initial_reference_channels"] == ["EXG1", "EXG2"]
    assert reopened.preprocessing["drop_reference_channels"] is True
    assert reopened.preprocessing["electrode_montage"] == "standard_1020"
    assert reopened.preprocessing["channel_types"] == {"VEOG": "eog"}


def test_unicorn_factory_mapping_is_explicit_and_persists_with_evidence(tmp_path):
    from Main_App.io.acquisition_profiles import UNICORN_FACTORY_RECORDED_LABEL_MAP, UNICORN_FACTORY_MAPPING_SOURCE_URL
    from Main_App.projects.hardware import UNICORN_FACTORY_MAPPING_PROFILE

    selected = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    assert "source_to_canonical" not in selected["acquisition_profile"]
    selected["electrode_mapping_profile"] = UNICORN_FACTORY_MAPPING_PROFILE
    project = Project.load(tmp_path, manifest={"preprocessing": selected})
    project.save()
    reopened = Project.load(tmp_path)
    profile = reopened.preprocessing["acquisition_profile"]
    assert profile["source_to_canonical"] == dict(UNICORN_FACTORY_RECORDED_LABEL_MAP)
    assert profile["label_mapping_evidence"] == {"status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL}


@pytest.mark.parametrize("override, message", [
    ({"downsample": 256}, "250 Hz"),
    ({"max_chan_idx_keep": 7}, "all eight"),
    ({"electrode_montage": "biosemi64"}, "all eight"),
    ({"manual_removed_electrodes_enabled": True}, "interpolation"),
    ({"kurtosis_auto_interpolate_all": True}, "interpolation"),
    ({"electrode_mapping_profile": "biosemi64_1020_ab_v1"}, "mapping"),
    ({"initial_reference": "channels", "initial_reference_channels": ["Fz"]}, "average reference"),
    ({"drop_reference_channels": True}, "reference channels"),
])
def test_unicorn_rejects_incompatible_processing_settings(override, message):
    settings = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    with pytest.raises(ValueError, match=message):
        normalize_preprocessing_settings({**settings, **override})


def test_unicorn_event_policy_roundtrips_without_guessing_annotation_codes(tmp_path):
    selected = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    selected["acquisition_profile"]["event_decoder_id"] = "explicit_annotations"
    with pytest.raises(ValueError, match="event policy"):
        normalize_preprocessing_settings(selected)
    selected["recording_event_policy"] = {
        "authority": "annotations", "numeric_annotations": False,
        "named_annotation_codes": {"Target": 17}, "marker_labels": ["Target"],
    }
    project = Project.load(tmp_path, manifest={"preprocessing": selected})
    project.save()
    assert Project.load(tmp_path).preprocessing["recording_event_policy"] == selected["recording_event_policy"]


@pytest.mark.parametrize("value", [None, {"authority": "guess"}, {"authority": {}}, {"named_annotation_codes": {"Target": 0}},
                                  {"named_annotation_codes": {"Target": True}}, {"marker_labels": "Target"}])
def test_unicorn_invalid_event_policy_is_rejected(value):
    selected = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    with pytest.raises(ValueError):
        normalize_preprocessing_settings({**selected, "recording_event_policy": value})


def test_unicorn_profile_is_in_stale_save_conflict_boundary(tmp_path):
    selected = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    original = Project.load(tmp_path, manifest={"preprocessing": selected})
    original.save()
    current = Project.load(tmp_path)
    current.preprocessing["acquisition_profile"]["event_decoder_id"] = "explicit_annotations"
    current.preprocessing["recording_event_policy"] = {"authority": "annotations"}
    current.save()
    original.name = "Unrelated change"
    original.save()
    reopened = Project.load(tmp_path)
    assert reopened.name == "Unrelated change"
    assert reopened.preprocessing["acquisition_profile"]["event_decoder_id"] == "explicit_annotations"


def test_switching_away_from_unicorn_drops_nested_profile_and_event_policy():
    selected = confirm_hardware_selection({}, "unicorn", confirmed_change=True)
    selected["recording_event_policy"] = {"authority": "status"}
    switched = confirm_hardware_selection(selected, "biosemi", confirmed_change=True)
    assert "acquisition_profile" not in switched
    assert "recording_event_policy" not in switched
    assert normalize_preprocessing_settings(switched)["max_chan_idx_keep"] == 64
