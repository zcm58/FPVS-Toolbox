from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects import Project
from Tools.Plot_Generator.gui_settings import (
    PlotGeneratorSettingsMixin,
    _project_plot_input_folder,
)
from Tools.Plot_Generator.selection_state import (
    PlotGeneratorSelectionMixin,
    _group_color_assignment,
)


class _Value:
    def __init__(self, value):
        self._value = value

    def text(self):
        return self._value

    def value(self):
        return self._value

    def isChecked(self):
        return self._value

    def setChecked(self, value):
        self._value = value

    def currentText(self):
        return self._value


class _LegendField:
    def __init__(self, value: str = ""):
        self._value = value

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        self._value = value


class _SavingProject(SimpleNamespace):
    def save(self, *, updated_tool_namespaces=()):
        self.saved = True
        self.saved_tool_names = set(updated_tool_namespaces)


class _FakeWindow(PlotGeneratorSettingsMixin, SimpleNamespace):
    pass


def test_multigroup_project_uses_canonical_excel_root_over_saved_input() -> None:
    project = SimpleNamespace(
        groups={"control": {"label": "Control"}, "patient": {"label": "Patient"}},
        manifest={},
    )

    assert (
        _project_plot_input_folder(
            "C:/Project/1 - Excel Data Files",
            {"input_folder": "C:/Old/Condition"},
            project,
        )
        == "C:/Project/1 - Excel Data Files"
    )


def test_single_group_project_can_restore_saved_input_folder() -> None:
    project = SimpleNamespace(groups={}, manifest={})

    assert (
        _project_plot_input_folder(
            "C:/Project/1 - Excel Data Files",
            {"input_folder": "C:/Saved/Excel"},
            project,
        )
        == "C:/Saved/Excel"
    )


def test_multigroup_project_settings_drop_stale_saved_input_folder() -> None:
    project = _SavingProject(
        saved=False,
        groups={"control": {"label": "Control"}, "patient": {"label": "Patient"}},
        manifest={
            "tools": {
                "snr_plot": {
                    "plot_settings": {
                        "input_folder": "C:/Old/Condition",
                        "output_folder": "C:/Old/Plots",
                    }
                }
            }
        },
    )
    window = _FakeWindow(
        _project=project,
        _ui_initializing=False,
        stem_color="#ff0000",
        stem_color_b="#0000ff",
        extra_colors=["#009E73", "#CC79A7", "#D5A000"],
        folder_edit=_Value("C:/Browse/Other"),
        out_edit=_Value("C:/Project/2 - SNR Plots"),
        _append_log=lambda _message: None,
    )

    assert PlotGeneratorSettingsMixin._persist_project_plot_settings(
        window,
        include_paths=True,
    )
    plot_settings = project.manifest["tools"]["snr_plot"]["plot_settings"]
    assert "input_folder" not in plot_settings
    assert plot_settings["output_folder"] == "C:/Project/2 - SNR Plots"
    assert project.saved is True
    assert project.saved_tool_names == {"snr_plot"}


def test_plot_settings_survive_successive_project_disk_roundtrips(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(
        json.dumps({"name": "Plot persistence"}),
        encoding="utf-8",
    )
    project = Project.load(project_root)
    window = _FakeWindow(
        _project=project,
        _ui_initializing=False,
        stem_color="#111111",
        stem_color_b="#222222",
        extra_colors=["#009E73", "#CC79A7", "#D5A000"],
        folder_edit=_Value(str(project_root / "1 - Excel Data Files")),
        out_edit=_Value(str(project_root / "2 - SNR Plots")),
        spectral_qc_check=_Value(True),
        legend_custom_check=_Value(True),
        legend_condition_a_edit=_Value("Condition A"),
        legend_condition_b_edit=_Value("Condition B"),
        legend_a_peaks_edit=_Value("A Peaks"),
        legend_b_peaks_edit=_Value("B Peaks"),
        _append_log=lambda _message: None,
        _legend_auto_values={},
    )
    window._legend_fields = {
        "condition_a_label": window.legend_condition_a_edit,
        "condition_b_label": window.legend_condition_b_edit,
        "a_peaks_label": window.legend_a_peaks_edit,
        "b_peaks_label": window.legend_b_peaks_edit,
        "condition_c_label": _Value("Condition C"),
        "c_peaks_label": _Value("C Peaks"),
    }

    window._persist_legend_settings()
    assert window._persist_project_plot_settings(include_paths=True)

    disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    disk_manifest["tools"]["stats"] = {"external_marker": "preserve"}
    manifest_path.write_text(json.dumps(disk_manifest, indent=2), encoding="utf-8")
    window.legend_condition_a_edit = _Value("Updated Condition A")
    window._legend_fields["condition_a_label"] = window.legend_condition_a_edit
    window._persist_legend_settings()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    snr_plot = saved["tools"]["snr_plot"]
    assert snr_plot["legend_labels"]["condition_a_label"] == "Updated Condition A"
    assert snr_plot["legend_labels"]["condition_c_label"] == "Condition C"
    assert snr_plot["plot_settings"] == {
        "stem_color": "#111111",
        "stem_color_b": "#222222",
        "extra_colors": ["#009E73", "#CC79A7", "#D5A000"],
        "spectral_qc_enabled": True,
        "input_folder": str(project_root / "1 - Excel Data Files"),
        "output_folder": str(project_root / "2 - SNR Plots"),
    }
    assert saved["tools"]["stats"] == {"external_marker": "preserve"}


def test_group_options_require_canonical_project_excel_root(tmp_path: Path) -> None:
    excel_root = tmp_path / "1 - Excel Data Files"
    condition_folder = excel_root / "CondA"
    condition_folder.mkdir(parents=True)
    window = SimpleNamespace(_canonical_project_excel_root=excel_root)

    assert PlotGeneratorSelectionMixin._folder_is_canonical_project_excel_root(
        window,
        str(excel_root),
    )
    assert not PlotGeneratorSelectionMixin._folder_is_canonical_project_excel_root(
        window,
        str(condition_folder),
    )


def test_force_legend_defaults_replaces_stale_group_labels() -> None:
    fields = {
        "condition_a_label": _LegendField("After Creatine"),
        "condition_b_label": _LegendField("After Creatine"),
        "a_peaks_label": _LegendField("After Creatine Peaks"),
        "b_peaks_label": _LegendField("After Creatine Peaks"),
    }
    window = _FakeWindow(
        _legend_fields=fields,
        _legend_auto_values={},
        _legend_manual_overrides=set(fields),
        _syncing_legend_defaults=False,
        _group_overlay_enabled=lambda: True,
        _selected_groups=lambda: ["After Creatine", "Before Creatine"],
        extra_condition_combos=[],
    )

    window._force_legend_defaults()

    assert fields["condition_a_label"].text() == "After Creatine"
    assert fields["condition_b_label"].text() == "Before Creatine"
    assert fields["a_peaks_label"].text() == "After Creatine Peaks"
    assert fields["b_peaks_label"].text() == "Before Creatine Peaks"
    assert window._legend_manual_overrides == set()


def test_group_color_assignment_follows_selected_group_order() -> None:
    selected = ["After Creatine", "Before Creatine"]

    assert _group_color_assignment(
        "After Creatine",
        selected,
        "#005500",
        "#ff00ff",
    ) == ("#005500", True, "First selected group")
    assert _group_color_assignment(
        "Before Creatine",
        selected,
        "#005500",
        "#ff00ff",
    ) == ("#ff00ff", True, "Second selected group")
    assert _group_color_assignment(
        "Not Selected",
        selected,
        "#005500",
        "#ff00ff",
    ) == ("#d9dee8", False, "Not selected")


def _legend_window_for_reload(conditions, labels=None):
    fields = {
        key: _LegendField()
        for letter in "abcde"
        for key in (f"condition_{letter}_label", f"{letter}_peaks_label")
    }
    return _FakeWindow(
        _project=_SavingProject(manifest={"tools": {"snr_plot": {"legend_labels": labels or {}}}}),
        _project_root=None,
        _ui_initializing=True,
        condition_combo=_Value(conditions[0]),
        condition_b_combo=_Value(conditions[1]),
        extra_condition_combos=[_Value(condition) for condition in conditions[2:]],
        legend_custom_check=_Value(True),
        _legend_fields=fields,
        _legend_auto_values={},
        _legend_manual_overrides=set(),
        _syncing_legend_defaults=False,
        _toggle_custom_legend_labels=lambda _checked: None,
    )


@pytest.mark.parametrize("custom", [False, True])
def test_extra_legend_automatic_values_survive_reopen_before_condition_population(custom):
    original = _legend_window_for_reload(["A", "B", "Patterns", "D", "E"])
    original._force_legend_defaults()
    if custom:
        original._legend_fields["condition_c_label"].setText("Custom C")
        original._on_legend_condition_label_edited("condition_c_label")
        original._legend_fields["e_peaks_label"].setText("Custom E peaks")
        original._mark_legend_manual_override("e_peaks_label")
    saved = original._legend_settings_payload()
    assert saved["extra_auto_values"]["condition_c_label"] == "Patterns"
    assert "condition_a_label" not in saved["extra_auto_values"]

    reopened = _legend_window_for_reload(["", "", "", "", ""], saved)
    reopened._load_legend_settings()
    reopened.extra_condition_combos[0]._value = "Animals"
    reopened._sync_legend_defaults_with_conditions()
    assert reopened._legend_fields["condition_c_label"].text() == ("Custom C" if custom else "Animals")
    assert reopened._legend_fields["c_peaks_label"].text() == ("Custom C Peaks" if custom else "Animals Peaks")
    reopened.extra_condition_combos[0]._value = "Tools"
    reopened._sync_legend_defaults_with_conditions()
    assert reopened._legend_fields["condition_c_label"].text() == ("Custom C" if custom else "Tools")
    if custom:
        assert reopened._legend_fields["e_peaks_label"].text() == "Custom E peaks"
