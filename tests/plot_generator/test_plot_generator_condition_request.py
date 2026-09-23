"""Widget-free checks at the condition-selection/export-request boundary."""

from types import SimpleNamespace

import pytest

from Tools.Plot_Generator.export_plan import inspect_destinations
from Tools.Plot_Generator.export_workflow import PlotExportWorkflowMixin
from Tools.Plot_Generator.render_naming import claim_figure_stem
from Tools.Plot_Generator.selection_state import PlotGeneratorSelectionMixin


class _Value:
    def __init__(self, value):
        self.data = value

    def currentText(self):
        return self.data

    def text(self):
        return self.data

    def value(self):
        return self.data

    def isChecked(self):
        return self.data


class _Selection(PlotGeneratorSelectionMixin, PlotExportWorkflowMixin):
    def __init__(self, names, count=5):
        self.condition_combo, self.condition_b_combo = map(_Value, names[:2])
        self.extra_condition_combos = list(map(_Value, names[2:]))
        self.overlay_count_spin = _Value(count)
        self.overlay_check = _Value(True)
        self.title_edit = _Value("")
        self.extra_colors = ["#009E73", "#CC79A7", "#D5A000"]
        self._legend_fields = {
            key: _Value(f"Custom {key}")
            for letter in "cde"
            for key in (f"condition_{letter}_label", f"{letter}_peaks_label")
        }

    def _worker_roi_selection(self):
        return {"LOT": ["P7"], "ROT": ["P8"]}, "(All ROIs)"

    def _session_comparison_active(self):
        return False

    def _group_overlay_enabled(self):
        return False


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_condition_count_bounds_export_and_worker_request(count):
    names = ["Faces", "Objects", "Words", "Bodies", "Textures"]
    selection = _Selection(names, count)
    assert selection._condition_overlay_validation() == ("", None)
    assert selection._selected_overlay_conditions() == tuple(names[:count])
    payload = selection._extra_overlay_worker_kwargs()
    assert payload["extra_conditions"] == tuple(names[2:count])
    assert len(payload["extra_colors"]) == count - 2
    assert len(payload["legend_extra_conditions"]) == count - 2
    assert len(payload["legend_extra_peaks"]) == count - 2
    expected_title = " vs ".join(names[:count])
    assert selection._export_identities() == (
        (expected_title, "LOT", ""), (expected_title, "ROT", ""),
    )
    # Later edits cannot mutate a request already handed to a worker.
    selection.extra_condition_combos[0].data = "Replacement"
    selection.extra_colors[0] = "black"
    selection._legend_fields["condition_c_label"].data = "Replacement label"
    assert payload["extra_conditions"] == tuple(names[2:count])
    if count > 2:
        assert payload["extra_colors"][0] == "#009E73"
        assert payload["legend_extra_conditions"][0] == "Custom condition_c_label"


@pytest.mark.parametrize("invalid", ["", "All Conditions", "Faces"])
def test_invalid_fifth_condition_focuses_offending_row_and_hidden_rows_do_not_block(invalid):
    selection = _Selection(["Faces", "Objects", "Words", "Bodies", invalid])
    message, target = selection._condition_overlay_validation()
    assert "Condition E" in message
    assert target is selection.extra_condition_combos[2]
    selection.overlay_count_spin.data = 4
    assert selection._condition_overlay_validation() == ("", None)
    selection.overlay_check.data = False
    selection.condition_b_combo.data = "Faces"
    assert selection._condition_overlay_validation() == ("", None)


def test_five_long_names_keep_preflight_and_render_destinations_identical(tmp_path):
    names = [f"Condition {letter} with a very long descriptive comparison name" for letter in "ABCDE"]
    selection = _Selection(names)
    identities = selection._export_identities()
    choices = inspect_destinations(tmp_path, identities, lambda: False)
    owner = SimpleNamespace(_figure_export_plan=choices.replace)
    for item in choices.replace:
        title, roi, suffix = item.identity
        assert title == " vs ".join(names)
        assert claim_figure_stem(owner, base_title=title, roi=roi, suffix=suffix) == item.png_path.stem
        assert len(item.png_path.stem) <= 96
    selection.title_edit.data = "Manually named comparison"
    assert all(title == "Manually named comparison" for title, _roi, _suffix in selection._export_identities())
