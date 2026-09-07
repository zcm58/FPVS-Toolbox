from __future__ import annotations

from pathlib import Path
from copy import copy
from datetime import datetime

import numpy as np
import openpyxl
import pandas as pd
import pytest

from Tools.Stats.analysis.baseline_vs_zero import export_baseline_vs_zero_results_to_excel
from Tools.Stats.reporting import reporting_summary
from Tools.Stats.reporting import stats_export
from Tools.Stats.reporting import stats_export_formatting as export_formatting


def test_rm_anova_excel_preserves_small_p_values(tmp_path: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "Effect": "condition",
                "Num DF": 1,
                "Den DF": 19,
                "F Value": 34.2,
                "Pr > F": 3.23e-08,
                "Pr > F (GG)": 3.23e-08,
                "epsilon (GG)": 0.77,
            }
        ]
    )
    out = tmp_path / "RM-ANOVA Results.xlsx"

    stats_export.export_rm_anova_results_to_excel(df, out, lambda _msg: None)
    export_formatting.apply_rm_anova_pvalue_number_formats(out)

    wb = openpyxl.load_workbook(out, data_only=False)
    ws = wb["RM-ANOVA Table"]
    header_map = {str(cell.value): i for i, cell in enumerate(ws[1], start=1)}

    p_cell = ws.cell(row=2, column=header_map["Pr > F"])
    gg_cell = ws.cell(row=2, column=header_map["Pr > F (GG)"])

    assert float(p_cell.value) == 3.23e-08
    assert float(gg_cell.value) == 3.23e-08
    assert float(p_cell.value) != 0.0
    assert p_cell.number_format == "0.00E+00"
    assert gg_cell.number_format == "0.00E+00"
    assert ws.auto_filter.ref == ws.dimensions
    assert ws.column_dimensions["A"].width > 10

    wb.close()


def test_fmt_p_scientific_threshold() -> None:
    assert "e-" in reporting_summary.fmt_p(3.23e-08)
    assert "e" not in reporting_summary.fmt_p(0.0014).lower()
    assert reporting_summary.fmt_p(0.0) == "0"


@pytest.mark.parametrize("kind", ["anova", "lmm", "baseline_vs_zero"])
def test_in_memory_export_matches_original_excel_roundtrip(tmp_path, kind, monkeypatch):
    values = [3.23e-8, np.nextafter(0.001, 0.0), 0.001, 1.2345678901234567,
              -0.0, np.nextafter(0.0, 1.0), np.nan, np.inf]
    if kind == "baseline_vs_zero":
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 7, 12, 0, 0, tzinfo=tz)

        monkeypatch.setitem(export_baseline_vs_zero_results_to_excel.__globals__, "datetime", FixedDateTime)
        data = {"results_df": pd.DataFrame({
            "condition": ["A"] * len(values), "roi": ["Central"] * len(values),
            "p_raw": values, "p_corr": values[::-1], "N": [8] * len(values),
        })}
        exporter = export_baseline_vs_zero_results_to_excel
        formatter = export_formatting.apply_baseline_vs_zero_number_formats
    else:
        data = pd.DataFrame({
            "Effect": [f"Effect {index}" for index in range(len(values))],
            "Pr > F" if kind == "anova" else "P>|z|": values,
            "Coef.": values[::-1],
            "Note": ["", "=1+2", "line\nbreak", "text", None, "é", "end", "note"],
        })
        if kind == "anova":
            exporter = stats_export.export_rm_anova_results_to_excel
            formatter = export_formatting.apply_rm_anova_pvalue_number_formats
        else:
            data.attrs["lrt_table"] = pd.DataFrame({"Block": ["Condition"], "p (chi2)": [3.23e-8]})
            data.attrs["lmm_formula"] = "value ~ condition"
            exporter = stats_export.export_mixed_model_results_to_excel
            formatter = export_formatting.apply_lmm_number_formats_and_metadata
    before_path, after_path = tmp_path / "before.xlsx", tmp_path / "after.xlsx"
    exporter(data, before_path, lambda _message: None)
    formatter(before_path, **({"lmm_df": data} if kind == "lmm" else {}))

    original_load = openpyxl.load_workbook
    loaded_sources = []

    def tracked_load(source, *args, **kwargs):
        loaded_sources.append(source)
        return original_load(source, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(export_formatting.openpyxl, "load_workbook", tracked_load)
        export_formatting.export_formatted_stats_results(
            exporter, data, after_path, lambda _message: None, kind=kind,
        )
    assert len(loaded_sources) == 1
    assert hasattr(loaded_sources[0], "read")  # No intermediate disk workbook.

    before, after = original_load(before_path), original_load(after_path)
    try:
        assert before.sheetnames == after.sheetnames
        for left, right in zip(before, after):
            assert left.dimensions == right.dimensions
            assert left.auto_filter == right.auto_filter
            assert {key: dict(value) for key, value in left.column_dimensions.items()} == {
                key: dict(value) for key, value in right.column_dimensions.items()
            }
            for left_row, right_row in zip(left, right):
                for a, b in zip(left_row, right_row):
                    assert a.data_type == b.data_type
                    assert type(a.value) is type(b.value)
                    if isinstance(a.value, float):
                        assert a.value.hex() == b.value.hex()
                    else:
                        assert a.value == b.value
                    for attribute in ("font", "fill", "border", "alignment",
                                      "number_format", "protection"):
                        assert copy(getattr(a, attribute)) == copy(getattr(b, attribute))
    finally:
        before.close()
        after.close()
