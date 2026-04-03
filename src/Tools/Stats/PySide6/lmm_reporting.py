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

NOT_AVAILABLE = "NOT AVAILABLE (not computed by this run)"
DEFAULT_GROUP_CODING_NOTE = "Default/implicit (not explicitly set by FPVS wrapper)"


def resolve_lmm_formula(*, model: Any, fallback_formula: str) -> str:
    """Return the fitted formula when statsmodels exposes it."""

    fitted_model = getattr(model, "model", None)
    model_formula = getattr(fitted_model, "formula", None)
    if isinstance(model_formula, str) and model_formula.strip():
        return model_formula.strip()
    return str(fallback_formula or NOT_AVAILABLE)


def _extract_formula_rhs(formula: str) -> str:
    """Return the right-hand side of a model formula."""

    lhs_rhs = str(formula).split("~", maxsplit=1)
    if len(lhs_rhs) == 2:
        return lhs_rhs[1].strip()
    return str(formula).strip()


def _formula_mentions_factor(formula: str, factor: str) -> bool:
    """Return whether a factor name appears in a formula."""

    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(factor)}(?![A-Za-z0-9_])", formula))


def _factor_coding_from_formula(formula: str, factor: str) -> str:
    """Summarize the coding a factor uses in the fitted formula."""

    explicit = re.search(rf"C\(\s*{re.escape(factor)}\s*,\s*([^)]+)\)", formula)
    if explicit:
        return explicit.group(1).strip()
    if _formula_mentions_factor(formula, factor):
        if factor == "group":
            return DEFAULT_GROUP_CODING_NOTE
        return "Default/implicit"
    return NOT_AVAILABLE


def build_lmm_run_contract(
    *,
    include_group: bool,
    formula: str,
    method_used: str,
    re_formula_used: str,
) -> dict[str, Any]:
    """Build the canonical contract for the fitted LMM."""

    coding_map: dict[str, str] = {}
    if include_group:
        coding_map["group"] = _factor_coding_from_formula(formula, "group")
    if _formula_mentions_factor(formula, "condition"):
        coding_map["condition"] = _factor_coding_from_formula(formula, "condition")
    if _formula_mentions_factor(formula, "roi"):
        coding_map["roi"] = _factor_coding_from_formula(formula, "roi")
    coding_summary = "; ".join(f"{key}: {value}" for key, value in coding_map.items()) or NOT_AVAILABLE

    return {
        "scope": "supported_multigroup_between" if include_group else "single_group",
        "scope_label": (
            "Supported multigroup between-group LMM"
            if include_group
            else "Single-group LMM"
        ),
        "formula": formula,
        "formula_rhs": _extract_formula_rhs(formula),
        "fixed_effects_summary": (
            "Group, condition, ROI, and all interactions"
            if include_group
            else "Condition, ROI, and their interaction"
        ),
        "random_effects_summary": f"Random intercept for subject only (re_formula={re_formula_used})",
        "estimation_summary": f"{method_used} via statsmodels MixedLM",
        "coding_map": coding_map,
        "coding_summary": coding_summary,
    }


def classify_lmm_fit_status(
    table: pd.DataFrame,
    *,
    include_group: bool,
    converged: bool,
    singular: bool,
) -> dict[str, Any]:
    """Classify whether a fit is supportable for user-facing output."""

    issues: list[str] = []
    if not isinstance(table, pd.DataFrame) or table.empty:
        issues.append("no fixed-effects table was returned")
    else:
        required_cols = ("Coef.", "SE", "Z", "P>|z|")
        missing_cols = [col for col in required_cols if col not in table.columns]
        if missing_cols:
            issues.append(f"missing coefficient columns: {', '.join(missing_cols)}")

        numeric_labels = {
            "Coef.": "coefficient",
            "SE": "standard error",
            "Z": "Wald z statistic",
            "P>|z|": "Wald p-value",
        }
        for column, label in numeric_labels.items():
            if column not in table.columns:
                continue
            numeric = pd.to_numeric(table[column], errors="coerce")
            nonfinite_mask = ~numeric.map(math.isfinite)
            if bool(nonfinite_mask.any()):
                issues.append(f"non-finite {label} values in {int(nonfinite_mask.sum())} row(s)")
            if column == "SE":
                nonpositive_mask = numeric <= 0.0
                if bool(nonpositive_mask.fillna(False).any()):
                    issues.append(
                        f"non-positive standard error values in {int(nonpositive_mask.fillna(False).sum())} row(s)"
                    )

    if not converged:
        issues.append("optimizer reported non-convergence")
    if singular:
        issues.append("random-effects covariance is near-singular")

    scope_label = "Supported multigroup LMM" if include_group else "LMM"
    supported = not issues
    status = "supported" if supported else "unsupported"
    message = (
        f"{scope_label} fit passed convergence and finite-stat checks."
        if supported
        else f"{scope_label} blocked: {'; '.join(issues)}."
    )
    return {
        "status": status,
        "label": status.upper(),
        "supported": supported,
        "message": message,
        "issues": issues,
    }


def _parse_single_term(term: str) -> dict[str, str] | None:
    """Handle the parse single term step for the Stats PySide6 workflow."""
    match = TERM_PATTERN.match(term)
    if not match:
        return None
    var = match.group("var").strip()
    contrast = match.group("contrast").strip()
    level = match.group("level").strip()
    return {"var": var, "contrast": contrast, "label": level}


def humanize_effect_label(effect: Any) -> str:
    """Handle the humanize effect label step for the Stats PySide6 workflow."""
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
    """Handle the ensure lmm effect columns step for the Stats PySide6 workflow."""
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
    contract: dict[str, Any] | None = None,
    fit_status: dict[str, Any] | None = None,
) -> None:
    """Handle the attach lmm run metadata step for the Stats PySide6 workflow."""
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
    if isinstance(contract, dict):
        table.attrs["lmm_contract"] = contract
        table.attrs["lmm_scope"] = contract.get("scope", "")
        table.attrs["lmm_scope_label"] = contract.get("scope_label", "")
        table.attrs["lmm_fixed_effects_summary"] = contract.get("fixed_effects_summary", "")
        table.attrs["lmm_random_effects_summary"] = contract.get("random_effects_summary", "")
        table.attrs["lmm_estimation_summary"] = contract.get("estimation_summary", "")
        table.attrs["lmm_coding_summary"] = contract.get("coding_summary", "")
    if isinstance(fit_status, dict):
        table.attrs["lmm_fit_status"] = fit_status.get("status", "")
        table.attrs["lmm_fit_status_label"] = fit_status.get("label", "")
        table.attrs["lmm_fit_supported"] = bool(fit_status.get("supported", False))
        table.attrs["lmm_fit_status_message"] = fit_status.get("message", "")
        table.attrs["lmm_fit_issues"] = list(fit_status.get("issues", []))
    if isinstance(lrt_table, pd.DataFrame):
        table.attrs["lrt_table"] = lrt_table


def infer_lmm_diagnostics(table: pd.DataFrame, model: Any) -> tuple[bool, bool, str, list[str]]:
    """Handle the infer lmm diagnostics step for the Stats PySide6 workflow."""
    note_series = table.get("Note", pd.Series(dtype=str)).astype(str)
    singular = note_series.str.contains("near-singular", case=False, na=False).any()
    converged = bool(
        getattr(
            model,
            "converged",
            not note_series.str.contains("did not converge", case=False, na=False).any(),
        )
    )
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
    """Handle the fmt p step for the Stats PySide6 workflow."""
    if value is None:
        return NOT_AVAILABLE
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(numeric):
        return NOT_AVAILABLE
    if numeric != 0.0 and abs(numeric) < 0.001:
        return f"{numeric:.3e}"
    return f"{numeric:.6g}"


def build_lmm_report_path(results_dir: Path | str, generated_local: datetime) -> Path:
    """Handle the build lmm report path step for the Stats PySide6 workflow."""
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    return results_path / f"LMM_Report_{generated_local.strftime('%Y-%m-%d_%H%M%S')}.txt"


def build_lmm_text_report(
    *,
    lmm_df: pd.DataFrame | None,
    generated_local: datetime,
    project_name: str | None,
) -> str:
    """Handle the build lmm text report step for the Stats PySide6 workflow."""
    lines = [
        "===================================",
        "FPVS TOOLBOX — LMM TEXT REPORT",
        "===================================",
        f"Timestamp (local): {generated_local.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Project: {project_name or NOT_AVAILABLE}",
        "LMM backend: statsmodels MixedLM",
    ]
    if not isinstance(lmm_df, pd.DataFrame):
        lines.append(f"Effects: {NOT_AVAILABLE}")
        return "\n".join(lines)

    attrs = lmm_df.attrs
    scope_label = attrs.get("lmm_scope_label")
    if scope_label:
        lines.extend(
            [
                f"Scope: {scope_label}",
                f"Fit status: {attrs.get('lmm_fit_status_label', NOT_AVAILABLE)}",
                f"Fit status detail: {attrs.get('lmm_fit_status_message', NOT_AVAILABLE)}",
                f"Fixed-effects contract: {attrs.get('lmm_fixed_effects_summary', NOT_AVAILABLE)}",
                f"Random-effects contract: {attrs.get('lmm_random_effects_summary', NOT_AVAILABLE)}",
                f"Coding summary: {attrs.get('lmm_coding_summary', NOT_AVAILABLE)}",
            ]
        )

    lines.extend(
        [
            f"Formula: {attrs.get('lmm_formula', NOT_AVAILABLE)}",
            f"Contrast coding: {attrs.get('lmm_contrast_map', NOT_AVAILABLE)}",
            f"Method: {attrs.get('lmm_method_used', NOT_AVAILABLE)}",
            f"Optimizer: {attrs.get('lmm_optimizer_used', NOT_AVAILABLE)}",
            f"Converged: {attrs.get('lmm_converged', NOT_AVAILABLE)}",
            f"Singular: {attrs.get('lmm_singular', NOT_AVAILABLE)}",
            f"Backed off random slopes: {attrs.get('lmm_backed_off_random_slopes', NOT_AVAILABLE)}",
            f"Warnings: {', '.join(attrs.get('lmm_fit_warnings', [])) or 'NONE'}",
            "Inference for fixed effects: Wald z-tests (normal approximation)",
            "",
            "COEFFICIENTS",
        ]
    )
    term_col = "Effect (readable)" if "Effect (readable)" in lmm_df.columns else "Effect (raw)"
    p_col = "P>|z|" if "P>|z|" in lmm_df.columns else None
    for _, row in lmm_df.iterrows():
        p_text = fmt_p(row.get(p_col)) if p_col else NOT_AVAILABLE
        lines.append(
            f"- {row.get(term_col, row.get('Effect (raw)', 'Effect'))}: "
            f"Coef={row.get('Coef.', 'NA')} SE={row.get('SE', 'NA')} Z={row.get('Z', 'NA')} p={p_text}"
        )
    return "\n".join(lines)


__all__ = [
    "attach_lmm_run_metadata",
    "build_lmm_report_path",
    "build_lmm_run_contract",
    "build_lmm_text_report",
    "classify_lmm_fit_status",
    "ensure_lmm_effect_columns",
    "fmt_p",
    "humanize_effect_label",
    "infer_lmm_diagnostics",
    "resolve_lmm_formula",
]
