from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


class _LegendField:
    def __init__(self, value: str = ""):
        self._value = value

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        self._value = value


class _SavingProject(SimpleNamespace):
    def save(self):
        self.saved = True


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
