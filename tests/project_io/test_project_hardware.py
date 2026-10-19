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
    (["p01.bdf"], "biosemi"), (["p01.eeg"], None),
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
