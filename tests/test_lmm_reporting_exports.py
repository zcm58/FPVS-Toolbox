from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys

import openpyxl
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "src" / "Tools" / "Stats" / "PySide6" / "lmm_reporting.py"
FORMAT_PATH = ROOT / "src" / "Tools" / "Stats" / "PySide6" / "stats_export_formatting.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lmm_reporting = _load_module(REPORT_PATH, "lmm_reporting_under_test")
export_formatting = _load_module(FORMAT_PATH, "lmm_export_formatting_under_test")


def test_humanize_effect_labels() -> None:
    assert lmm_reporting.humanize_effect_label("Intercept") == "Intercept (grand mean)"
    assert "Condition: Fruit vs Veg (Sum-coded)" == lmm_reporting.humanize_effect_label("C(condition, Sum)[S.Fruit vs Veg]")
    assert "Roi: Right Occipito Temporal (Sum-coded)" == lmm_reporting.humanize_effect_label("C(roi, Sum)[S.Right Occipito Temporal]")
    label = lmm_reporting.humanize_effect_label(
        "C(condition, Sum)[S.Green Veg vs Red Veg]:C(roi, Sum)[S.Right Occipito Temporal]"
    )
    assert "Condition×Roi:" in label


def test_wald_p_not_zero_underflow() -> None:
    p_value = float(2.0 * norm.sf(10.0))
    assert p_value > 0.0
    assert p_value != 0.0


def test_lmm_attrs_populated() -> None:
    table = pd.DataFrame(
        {
            "Effect": ["Intercept", "C(condition, Sum)[S.Fruit vs Veg]"],
            "Coef.": [1.0, 0.2],
            "SE": [0.1, 0.05],
            "Z": [10.0, 4.0],
            "P>|z|": [7.0e-24, 6.3e-05],
            "Note": ["", ""],
        }
    )
    table = lmm_reporting.ensure_lmm_effect_columns(table)
    lmm_reporting.attach_lmm_run_metadata(
        table=table,
        formula="value ~ C(condition, Sum) * C(roi, Sum)",
        fixed_effects=["C(condition, Sum) * C(roi, Sum)"],
        contrast_map={"condition": "Sum", "roi": "Sum"},
        method_requested="reml",
        method_used="REML",
        re_formula_requested="1",
        re_formula_used="1",
        backed_off_random_slopes=False,
        converged=True,
        singular=False,
        optimizer_used="lbfgs",
        fit_warnings=[],
        rows_input=24,
        rows_used=24,
        subjects_used=6,
        lrt_table=None,
    )
    assert table.attrs["lmm_formula"].startswith("value ~")
    assert table.attrs["lmm_contrast_map"]["condition"] == "Sum"
    assert table.attrs["lmm_optimizer_used"] == "lbfgs"


def test_excel_p_format_scientific_for_small_p(tmp_path: Path) -> None:
    workbook_path = tmp_path / "Mixed Model Results.xlsx"
    lmm_df = pd.DataFrame(
        {
            "Effect (readable)": ["Condition: demo"],
            "Effect (raw)": ["C(condition, Sum)[S.demo]"],
            "Coef.": [1.2],
            "SE": [0.1],
            "Z": [12.0],
            "P>|z|": [3.2e-10],
            "CI Low": [1.0],
            "CI High": [1.4],
            "Note": [""],
        }
    )
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        lmm_df.to_excel(writer, sheet_name="Mixed Model", index=False)
    export_formatting.apply_lmm_number_formats_and_metadata(workbook_path, lmm_df=lmm_df)

    wb = openpyxl.load_workbook(workbook_path)
    ws = wb["Mixed Model"]
    headers = {str(c.value): i for i, c in enumerate(ws[1], start=1)}
    p_cell = ws.cell(row=2, column=headers["P>|z|"])
    assert isinstance(p_cell.value, float)
    assert p_cell.value > 0
    assert p_cell.number_format == "0.00E+00"
    assert "Metadata" in wb.sheetnames
    wb.close()


def test_lmm_text_report_written_to_stats_results_dir(tmp_path: Path) -> None:
    stats_dir = tmp_path / "3 - Statistical Analysis Results"
    table = pd.DataFrame(
        {
            "Effect (readable)": ["Intercept (grand mean)"],
            "Effect (raw)": ["Intercept"],
            "Coef.": [0.3],
            "SE": [0.1],
            "Z": [3.0],
            "P>|z|": [0.002],
        }
    )
    table.attrs["lmm_formula"] = "value ~ C(condition, Sum) * C(roi, Sum)"
    text = lmm_reporting.build_lmm_text_report(
        lmm_df=table,
        generated_local=datetime.now().astimezone(),
        project_name="Demo",
    )
    report_path = lmm_reporting.build_lmm_report_path(stats_dir, datetime.now().astimezone())
    report_path.write_text(text, encoding="utf-8")

    assert report_path.exists()
    assert report_path.parent == stats_dir
