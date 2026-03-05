from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys

import pytest
pd = pytest.importorskip("pandas")


ROOT = Path(__file__).resolve().parents[1]
RM_ANOVA_MODULE_PATH = ROOT / "src" / "Tools" / "Stats" / "Legacy" / "repeated_m_anova.py"
REPORTING_MODULE_PATH = ROOT / "src" / "Tools" / "Stats" / "PySide6" / "reporting_summary.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rm_mod = _load_module(RM_ANOVA_MODULE_PATH, "rm_anova_legacy_mod")
report_mod = _load_module(REPORTING_MODULE_PATH, "rm_anova_report_mod")


def test_tidy_from_pingouin_maps_eps_and_sphericity_fields():
    pg_df = pd.DataFrame(
        [
            {
                "Source": "condition",
                "ddof1": 1,
                "ddof2": 19,
                "F": 5.2,
                "p-unc": 0.03,
                "eps": 0.81,
                "p-GG-corr": 0.041,
                "W-spher": 0.92,
                "p-spher": 0.12,
                "sphericity": True,
            }
        ]
    )
    out = rm_mod._tidy_from_pingouin(pg_df)
    for col in [
        "epsilon (GG)",
        "Pr > F (GG)",
        "W (Mauchly)",
        "p (Mauchly)",
        "Sphericity (bool)",
    ]:
        assert col in out.columns


def test_pingouin_success_prefers_corrected_p_for_reported_value():
    anova_df = pd.DataFrame(
        [
            {
                "Effect": "condition",
                "F Value": 4.3,
                "Num DF": 1,
                "Den DF": 10,
                "Pr > F": 0.07,
                "Pr > F (GG)": 0.049,
            }
        ]
    )
    anova_df.attrs["rm_anova_backend"] = "pingouin"

    text = report_mod.build_rm_anova_text_report(
        anova_df=anova_df,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        project_name="Demo",
    )

    assert "p_reported=0.049 (GG corrected)" in text
    assert "p_uncorrected=0.07" in text


def test_statsmodels_fallback_marks_correction_and_sphericity_not_available():
    anova_df = pd.DataFrame(
        [
            {
                "Effect": "condition",
                "F Value": 4.3,
                "Num DF": 1,
                "Den DF": 10,
                "Pr > F": 0.07,
            }
        ]
    )
    anova_df.attrs["rm_anova_backend"] = "statsmodels"

    text = report_mod.build_rm_anova_text_report(
        anova_df=anova_df,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        project_name="Demo",
    )

    assert "RM-ANOVA backend: statsmodels" in text
    assert "epsilon (GG)=NOT AVAILABLE (statsmodels fallback)" in text
    assert "W (Mauchly)=NOT AVAILABLE (statsmodels fallback)" in text
    assert "Pr > F (GG)=NOT AVAILABLE (statsmodels fallback)" in text


def test_rm_anova_report_export_path_writes_to_results_folder(tmp_path):
    generated = datetime(2025, 1, 2, 3, 4, 5)
    results_dir = tmp_path / "Statistical Analysis Results"
    report_path = report_mod.build_rm_anova_report_path(results_dir, generated)

    anova_df = pd.DataFrame([{"Effect": "condition", "F Value": 2.1, "Num DF": 1, "Den DF": 8, "Pr > F": 0.1}])
    anova_df.attrs["rm_anova_backend"] = "statsmodels"

    text = report_mod.build_rm_anova_text_report(
        anova_df=anova_df,
        generated_local=generated,
        project_name="Demo",
    )
    report_path.write_text(text, encoding="utf-8")

    assert report_path.exists()
    assert "RM_ANOVA_Report_2025-01-02_030405.txt" == report_path.name
    content = report_path.read_text(encoding="utf-8")
    assert "Timestamp (local): 2025-01-02 03:04:05" in content
    assert "RM-ANOVA backend: statsmodels" in content
