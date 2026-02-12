"""Output-layer helpers for LMM readability and metadata.

These helpers do not alter model fitting; they only improve reporting/export payloads.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

TERM_PATTERN = re.compile(
    r"^C\((?P<var>[^,\)]+)\s*,\s*(?P<contrast>[^\)]+)\)\[S\.(?P<level>.+)\]$"
)



def _parse_single_term(term: str) -> dict[str, str] | None:
    match = TERM_PATTERN.match(term)
    if not match:
        return None
    var = match.group("var").strip()
    contrast = match.group("contrast").strip()
    level = match.group("level").strip()
    return {"var": var, "contrast": contrast, "label": level}

def humanize_effect_label(effect: Any) -> str:
    raw = str(effect)
    if raw == "Intercept":
        return "Intercept (grand mean)"
    if ":" in raw:
        parts = [part.strip() for part in raw.split(":")]
        parsed = [_parse_single_term(part) for part in parts]
        if not all(parsed):
            return raw
        labels = [item["label"] for item in parsed if item]
        vars_ = [item["var"] for item in parsed if item]
        prefix = "×".join(v.title() for v in vars_)
        return f"{prefix}: {' × '.join(f'({label})' for label in labels)}"
    parsed = _parse_single_term(raw)
    if not parsed:
        return raw
    return f"{parsed['var'].title()}: {parsed['label']} ({parsed['contrast']}-coded)"


def ensure_lmm_effect_columns(table: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(table, pd.DataFrame) or table.empty or "Effect" not in table.columns:
        return table
    out = table.copy()
    readable = out["Effect"].map(humanize_effect_label)
    out.insert(0, "Effect (readable)", readable)
    out = out.rename(columns={"Effect": "Effect (raw)"})
    return out


def compute_two_sided_wald_p(z_value: Any) -> float:
    """Compute two-sided Wald p-value with numerically stable tails."""

    try:
        z_abs = abs(float(z_value))
    except Exception:
        return float("nan")
    if not math.isfinite(z_abs):
        return float("nan")
    try:
        from scipy.stats import norm  # type: ignore

        return float(2.0 * norm.sf(z_abs))
    except Exception:
        return float(math.erfc(z_abs / math.sqrt(2.0)))


def repair_lmm_pvalues_from_z(table: pd.DataFrame) -> pd.DataFrame:
    """Ensure Wald p-values are computed from Z using a stable tail method."""

    if not isinstance(table, pd.DataFrame) or table.empty:
        return table
    if "Z" not in table.columns or "P>|z|" not in table.columns:
        return table
    out = table.copy()
    out["P>|z|"] = out["Z"].map(compute_two_sided_wald_p)
    return out


def attach_lmm_run_metadata(
    *,
    table: pd.DataFrame,
    formula: str,
    fixed_effects: list[str],
    contrast_map: dict[str, str],
    method_requested: str,
    method_used: str,
    re_formula_requested: str,
    re_formula_used: str,
    backed_off_random_slopes: bool,
    converged: bool,
    singular: bool,
    optimizer_used: str,
    fit_warnings: list[str],
    rows_input: int,
    rows_used: int,
    subjects_used: int,
    lrt_table: pd.DataFrame | None,
) -> None:
    table.attrs["lmm_formula"] = formula
    table.attrs["lmm_processed_terms"] = fixed_effects
    table.attrs["lmm_contrast_map"] = contrast_map
    table.attrs["lmm_method_requested"] = method_requested
    table.attrs["lmm_method_used"] = method_used
    table.attrs["lmm_re_formula_requested"] = re_formula_requested
    table.attrs["lmm_re_formula_used"] = re_formula_used
    table.attrs["lmm_backed_off_random_slopes"] = backed_off_random_slopes
    table.attrs["lmm_converged"] = converged
    table.attrs["lmm_singular"] = singular
    table.attrs["lmm_optimizer_used"] = optimizer_used
    table.attrs["lmm_fit_warnings"] = fit_warnings
    table.attrs["lmm_rows_input"] = rows_input
    table.attrs["lmm_rows_used"] = rows_used
    table.attrs["lmm_rows_dropped"] = max(rows_input - rows_used, 0)
    table.attrs["lmm_subjects_used"] = subjects_used
    table.attrs["lmm_lrt_computed"] = isinstance(lrt_table, pd.DataFrame)
    table.attrs["lmm_lrt_table_attached"] = isinstance(lrt_table, pd.DataFrame)
    if isinstance(lrt_table, pd.DataFrame):
        table.attrs["lrt_table"] = lrt_table


def infer_lmm_diagnostics(table: pd.DataFrame, model: Any) -> tuple[bool, bool, str, list[str]]:
    note_series = table.get("Note", pd.Series(dtype=str)).astype(str)
    singular = note_series.str.contains("near-singular", case=False, na=False).any()
    converged = bool(getattr(model, "converged", not note_series.str.contains("did not converge", case=False, na=False).any()))
    optimizer = "NOT AVAILABLE"
    hist = getattr(model, "hist", None)
    if isinstance(hist, list) and hist and isinstance(hist[0], dict):
        keys = set(hist[0].keys())
        if "gopt" in keys:
            optimizer = "lbfgs"
        elif "direc" in keys or "allvecs" in keys:
            optimizer = "powell"
    if hasattr(model, "mle_settings") and isinstance(model.mle_settings, dict):
        method = model.mle_settings.get("optimizer") or model.mle_settings.get("method")
        if method:
            optimizer = str(method)
    fit_history = getattr(model, "fit_history", None)
    if optimizer == "NOT AVAILABLE" and isinstance(fit_history, dict):
        method = fit_history.get("optimizer") or fit_history.get("method")
        if method:
            optimizer = str(method)
    if optimizer == "NOT AVAILABLE":
        optimizer = "lbfgs"
    warnings: list[str] = []
    if not converged:
        warnings.append("Convergence warning: model did not converge.")
    if singular:
        warnings.append("Random-effects covariance near-singular.")
    return converged, singular, optimizer, warnings


def fmt_p(value: Any) -> str:
    if value is None:
        return "NOT AVAILABLE (not computed by this run)"
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(numeric):
        return "NOT AVAILABLE (not computed by this run)"
    if numeric != 0.0 and abs(numeric) < 0.001:
        return f"{numeric:.3e}"
    return f"{numeric:.6g}"


def build_lmm_report_path(results_dir: Path | str, generated_local: datetime) -> Path:
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    return results_path / f"LMM_Report_{generated_local.strftime('%Y-%m-%d_%H%M%S')}.txt"


def build_lmm_text_report(
    *,
    lmm_df: pd.DataFrame | None,
    generated_local: datetime,
    project_name: str | None,
) -> str:
    lines = [
        "===================================",
        "FPVS TOOLBOX — LMM TEXT REPORT",
        "===================================",
        f"Timestamp (local): {generated_local.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Project: {project_name or 'NOT AVAILABLE (not computed by this run)'}",
        "LMM backend: statsmodels MixedLM",
    ]
    if not isinstance(lmm_df, pd.DataFrame):
        lines.append("Effects: NOT AVAILABLE (not computed by this run)")
        return "\n".join(lines)
    attrs = lmm_df.attrs
    lines.extend(
        [
            f"Formula: {attrs.get('lmm_formula', 'NOT AVAILABLE (not computed by this run)')}",
            f"Contrast coding: {attrs.get('lmm_contrast_map', 'NOT AVAILABLE (not computed by this run)')}",
            f"Method: {attrs.get('lmm_method_used', 'NOT AVAILABLE (not computed by this run)')}",
            f"Optimizer: {attrs.get('lmm_optimizer_used', 'NOT AVAILABLE (not computed by this run)')}",
            f"Converged: {attrs.get('lmm_converged', 'NOT AVAILABLE (not computed by this run)')}",
            f"Singular: {attrs.get('lmm_singular', 'NOT AVAILABLE (not computed by this run)')}",
            f"Backed off random slopes: {attrs.get('lmm_backed_off_random_slopes', 'NOT AVAILABLE (not computed by this run)')}",
            f"Warnings: {', '.join(attrs.get('lmm_fit_warnings', [])) or 'NONE'}",
            "Inference for fixed effects: Wald z-tests (normal approximation)",
            "",
            "COEFFICIENTS",
        ]
    )
    term_col = "Effect (readable)" if "Effect (readable)" in lmm_df.columns else "Effect (raw)"
    p_col = "P>|z|" if "P>|z|" in lmm_df.columns else None
    for _, row in lmm_df.iterrows():
        p_text = fmt_p(row.get(p_col)) if p_col else "NOT AVAILABLE (not computed by this run)"
        lines.append(
            f"- {row.get(term_col, row.get('Effect (raw)', 'Effect'))}: "
            f"Coef={row.get('Coef.', 'NA')} SE={row.get('SE', 'NA')} Z={row.get('Z', 'NA')} p={p_text}"
        )
    return "\n".join(lines)


__all__ = [
    "attach_lmm_run_metadata",
    "build_lmm_report_path",
    "build_lmm_text_report",
    "ensure_lmm_effect_columns",
    "fmt_p",
    "humanize_effect_label",
    "infer_lmm_diagnostics",
]
