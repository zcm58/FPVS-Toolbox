"""Exercise settings geometry reconciliation with real projects, without Qt."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.projects import Project
from Main_App.projects import preprocessing_settings
from Tools.Stats.analysis import dv_policy_settings


SOURCE = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"
ANATOMICAL = "anatomical_labels"
AB = "biosemi64_1020_ab_v1"


class _Combo:
    def __init__(self, values, selected):
        self.values = list(values)
        self.index = self.values.index(selected)

    def currentData(self):
        return self.values[self.index]

    def findData(self, value):
        return self.values.index(value) if value in self.values else -1

    def setCurrentIndex(self, index):
        self.index = index


def _load_methods(panel):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "SettingsDialog")
    namespace = {
        **vars(preprocessing_settings), **vars(dv_policy_settings),
        "config": SimpleNamespace(DEFAULT_STIM_CHANNEL="Status"),
        "REMOVED_ELECTRODE_DETECTION_MODE_AUTO": "auto",
        "QMessageBox": panel.messages,
    }
    names = {
        "_collect_project_preprocessing_inputs", "_sync_electrode_geometry_controls",
        "_validated_preproc_payload", "_save_project_preprocessing_for_harmonic_recalculation",
    }
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef)
               and node.name in names]
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    ), *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    for method in methods:
        setattr(panel, method.name, namespace[method.name].__get__(panel))


def _panel(tmp_path, mapping):
    manifest = {"preprocessing": {
        "electrode_montage": "biosemi64", "electrode_mapping_profile": mapping,
    }}
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(tmp_path, manifest)
    defaults = project.preprocessing
    canonical = (
        "low_pass", "high_pass", "downsample", "rejection_z", "ref_chan1", "ref_chan2",
        "max_chan_idx_keep", "max_bad_chans", "max_parallel_workers_override",
    )
    def edit(value):
        return SimpleNamespace(text=lambda: str(value))

    def check(value):
        return SimpleNamespace(isChecked=lambda: value)

    panel = SimpleNamespace(
        project=project, messages=Mock(), _project_cache=dict(defaults),
        _electrode_geometry_control_baseline={
            "electrode_montage": "biosemi64", "electrode_mapping_profile": mapping,
        },
        electrode_montage_combo=_Combo(["biosemi64"], "biosemi64"),
        electrode_mapping_profile_combo=_Combo([ANATOMICAL, AB], mapping),
        preproc_edits=[edit(defaults[key]) for key in canonical],
        line_noise_filter_enabled_check=check(False),
        kurtosis_auto_interpolate_all_check=check(True),
        line_noise_frequency_combo=_Combo([50, 60], 60),
        _removed_electrode_detection_mode=lambda: "off",
        _manual_removed_electrodes_by_pid={}, _manual_removed_electrodes_by_recording={},
        manual_removed_electrodes_enabled_check=check(False),
        _manual_excluded_participants=[], _manual_excluded_recordings=[],
        _manual_excluded_participant_conditions={}, _manual_excluded_recording_conditions={},
        harmonic_summation_method_combo=_Combo(["legacy_fpvs_toolbox"], "legacy_fpvs_toolbox"),
        _fixed_harmonic_list_selected=lambda: False,
        harmonic_electrode_scope_combo=_Combo(["all_retained_scalp"], "all_retained_scalp"),
        harmonic_selection_electrodes_edit=edit(""), fixed_harmonic_freqs_edit=edit("1.2, 2.4"),
        fixed_harmonic_input_mode_combo=_Combo(["frequency_list"], "frequency_list"),
        fixed_harmonic_upper_index_edit=edit(""), fixed_harmonic_upper_frequency_edit=edit(""),
        _focus_invalid_preproc_field=Mock(),
        _harmonic_policy_payload_from_preprocessing=lambda normalized: normalized,
    )
    _load_methods(panel)
    return panel


def _external_mapping(project, mapping):
    path = project.project_root / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["electrode_mapping_profile"] = mapping
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path.read_bytes()


@pytest.mark.parametrize("already_refreshed", [False, True])
def test_unchanged_settings_combo_preserves_external_mapping_repair(tmp_path, already_refreshed):
    panel = _panel(tmp_path, AB)
    expected_bytes = _external_mapping(panel.project, ANATOMICAL)
    if already_refreshed:
        panel.project.refresh_electrode_geometry_settings()
        # An unrelated panel action can update this cache while the combo stays stale.
        panel._project_cache = dict(panel.project.preprocessing)
    panel.preproc_edits[1] = SimpleNamespace(text=lambda: "0.5")

    for _ in range(2):
        values = panel._collect_project_preprocessing_inputs()
        assert values["electrode_mapping_profile"] == ANATOMICAL
        assert values["high_pass"] == "0.5"
        assert panel.electrode_mapping_profile_combo.currentData() == ANATOMICAL
    assert (tmp_path / "project.json").read_bytes() == expected_bytes


def test_explicit_mapping_change_survives_repeated_collection(tmp_path):
    panel = _panel(tmp_path, ANATOMICAL)
    panel.electrode_mapping_profile_combo.setCurrentIndex(1)
    for _ in range(2):
        assert panel._collect_project_preprocessing_inputs()["electrode_mapping_profile"] == AB
        assert panel._electrode_geometry_control_baseline["electrode_mapping_profile"] == ANATOMICAL


@pytest.mark.parametrize("next_action", ["external_repair", "return_to_original_choice"])
def test_successful_mapping_save_rebases_controls_for_later_changes(tmp_path, next_action):
    panel = _panel(tmp_path, ANATOMICAL)
    panel.electrode_mapping_profile_combo.setCurrentIndex(1)
    values = panel._collect_project_preprocessing_inputs()
    assert panel._save_project_preprocessing_for_harmonic_recalculation(values)
    assert panel._electrode_geometry_control_baseline["electrode_mapping_profile"] == AB
    if next_action == "external_repair":
        _external_mapping(panel.project, ANATOMICAL)
    else:
        panel.electrode_mapping_profile_combo.setCurrentIndex(0)

    assert panel._collect_project_preprocessing_inputs()["electrode_mapping_profile"] == ANATOMICAL


def test_failed_mapping_save_keeps_explicit_control_pending(tmp_path):
    panel = _panel(tmp_path, ANATOMICAL)
    panel.electrode_mapping_profile_combo.setCurrentIndex(1)
    panel.project.save = Mock(side_effect=OSError("Project is read-only"))

    assert not panel._save_project_preprocessing_for_harmonic_recalculation(
        panel._collect_project_preprocessing_inputs()
    )
    assert panel._electrode_geometry_control_baseline["electrode_mapping_profile"] == ANATOMICAL
    assert panel._collect_project_preprocessing_inputs()["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("failure", [OSError("Project is read-only"), ValueError("Invalid manifest")])
def test_settings_geometry_refresh_failure_blocks_save_validation(tmp_path, failure):
    panel = _panel(tmp_path, AB)
    panel.project.refresh_electrode_geometry_settings = Mock(side_effect=failure)

    assert panel._validated_preproc_payload() is None
    panel.messages.warning.assert_called_once()
    assert str(failure) in panel.messages.warning.call_args.args[2]
