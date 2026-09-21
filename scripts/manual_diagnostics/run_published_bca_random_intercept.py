"""Freeze and fit balanced random-intercept sensitivity models of published BCA.

Use --prepare before --fit. An existing completed ANOVA snapshot is required;
its cells, cohort and full published-input fingerprint must still be current.
No project settings, EEG data, harmonic choices or exclusions are changed.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from itertools import combinations
import json
import logging
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import linalg, stats
import scipy
import statsmodels
from statsmodels.regression.mixed_linear_model import MixedLM, MixedLMParams

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_published_bca_rm_anova as published  # noqa: E402

LOGGER = logging.getLogger(__name__)
VERSION = "published_bca_random_intercept_v1"


def checked_path(root: Path, requested: Path) -> Path:
    path = requested.expanduser()
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Snapshot and output must be dedicated directories inside the project root.")
    return path


def snapshot_inputs(root: Path, snapshot: Path) -> tuple[pd.DataFrame, dict]:
    plan_path, result_path = snapshot / "analysis_plan.json", snapshot / "results.json"
    csv_path = snapshot / "participant_condition_roi_bca.csv"
    hashes = {p.name: published.file_hash(p) for p in (plan_path, result_path, csv_path)}
    old_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    old_results = json.loads(result_path.read_text(encoding="utf-8"))
    if old_results["plan_fingerprint"] != published.digest(old_plan) or not old_results["crosscheck_passed"]:
        raise ValueError("The source snapshot must be a completed, cross-checked ANOVA run.")
    if published.digest(old_plan["inputs"]) != old_plan["input_fingerprint"]:
        raise ValueError("Source ANOVA input payload does not match its fingerprint.")
    if hashes[csv_path.name] != old_plan["tidy_csv_sha256"]:
        raise ValueError("Source ANOVA CSV has changed since its plan was frozen.")
    canonical, inputs = published.load_inputs(root, old_plan["inputs"]["conditions"])
    if published.digest(inputs) != old_plan["input_fingerprint"]:
        raise ValueError("Canonical published inputs changed after the source ANOVA run.")
    tidy = pd.read_csv(csv_path, keep_default_na=False, float_precision="round_trip")
    pd.testing.assert_frame_equal(tidy, canonical, check_exact=True)
    rois = [roi["name"] for roi in inputs["roi_snapshot"]["rois"]]
    if len(rois) != 3:
        raise ValueError("This analysis requires exactly three existing frozen ROIs.")
    keys = ["participant_id", "Condition", "ROI"]
    expected = pd.MultiIndex.from_product([inputs["participants"], inputs["conditions"], rois], names=keys)
    observed = pd.MultiIndex.from_frame(tidy[keys])
    if observed.has_duplicates or set(observed) != set(expected):
        raise ValueError("Snapshot cells must be complete and unique for the unchanged common cohort.")
    if not np.isfinite(tidy["summed_bca_uv"].to_numpy()).all():
        raise ValueError("Non-finite BCA values are not supported.")
    for path in (plan_path, result_path, csv_path):
        if published.file_hash(path) != hashes[path.name]:
            raise ValueError("The source snapshot changed while being validated.")
    return tidy, {
        "version": VERSION, "source_snapshot": snapshot.relative_to(root).as_posix(),
        "source_file_hashes": hashes, "source_plan_fingerprint": published.digest(old_plan),
        "canonical_input_fingerprint": published.digest(inputs), "canonical_inputs": inputs,
    }


def model_definitions(inputs: dict) -> list[dict]:
    canonical = inputs["canonical_inputs"]
    conditions = canonical["conditions"]
    rois = [roi["name"] for roi in canonical["roi_snapshot"]["rois"]]
    return [
        {"family": "primary_condition_within_roi", "stratum": roi, "filter_column": "ROI",
         "factor": "Condition", "levels": conditions} for roi in rois
    ] + [
        {"family": "supplementary_roi_within_condition", "stratum": condition,
         "filter_column": "Condition", "factor": "ROI", "levels": rois} for condition in conditions
    ]


def closed_form(values: np.ndarray) -> dict:
    """Interior REML estimates for a complete balanced one-factor random intercept."""
    y = np.asarray(values, dtype=float)
    if y.ndim != 2 or min(y.shape) < 3 or not np.isfinite(y).all():
        raise ValueError("Each model requires a finite balanced participant x factor-level array.")
    n, k = y.shape
    means, subject_means, grand = y.mean(axis=0), y.mean(axis=1), y.mean()
    error = y - subject_means[:, None] - means[None, :] + grand
    df = (n - 1) * (k - 1)
    residual_variance = float(np.sum(error ** 2) / df)
    intercept_variance = float(np.var(subject_means, ddof=1) - residual_variance / k)
    if residual_variance <= 0 or intercept_variance <= 0:
        raise ValueError("Positive interior residual and random-intercept variances are required; "
                         "this prespecified CS analysis cannot silently switch at a boundary.")
    covariance = (residual_variance * np.eye(k) + intercept_variance * np.ones((k, k))) / n
    shrinkage = intercept_variance / (intercept_variance + residual_variance / k)
    f = float(n * np.sum((means - grand) ** 2) / ((k - 1) * residual_variance))
    return {"n": n, "k": k, "df": df, "means": means, "residual_variance": residual_variance,
            "intercept_variance": intercept_variance, "fixed_covariance": covariance,
            "shrinkage": shrinkage, "offsets": shrinkage * (subject_means - grand),
            "F": f, "p_F": float(stats.f.sf(f, k - 1, df)), "double_centered_residuals": error}


def fit_one(tidy: pd.DataFrame, definition: dict, participants: list[str]) -> dict:
    factor, levels = definition["factor"], definition["levels"]
    subset = tidy.loc[tidy[definition["filter_column"]] == definition["stratum"]].copy()
    ordered = pd.MultiIndex.from_product([participants, levels], names=["participant_id", factor])
    subset = subset.set_index(["participant_id", factor]).reindex(ordered).reset_index()
    subset[factor] = pd.Categorical(subset[factor], categories=levels, ordered=True)
    values = subset["summed_bca_uv"].to_numpy().reshape(len(participants), len(levels))
    exact = closed_form(values)
    model = MixedLM.from_formula(f"summed_bca_uv ~ 0 + C({factor})", groups="participant_id",
                                re_formula="1", data=subset)
    start = MixedLMParams.from_components(fe_params=exact["means"], cov_re=np.array([
        [exact["intercept_variance"] / exact["residual_variance"]]]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = model.fit(start_params=start, reml=True, method="lbfgs", maxiter=1000, full_output=True)
    fit_warnings = [{"category": item.category.__name__, "message": str(item.message)} for item in caught]
    if not fitted.converged:
        raise ValueError(f"REML did not converge: {definition!r}; warnings={fit_warnings!r}")
    k, n, df = exact["k"], exact["n"], exact["df"]
    covariance = fitted.cov_params().iloc[:k, :k].to_numpy()
    offsets = np.array([float(fitted.random_effects[pid].iloc[0]) for pid in participants])
    # These comparisons verify optimizer scale, parameter order and the covariance used for inference.
    np.testing.assert_allclose(fitted.fe_params.to_numpy(), exact["means"], rtol=1e-9, atol=1e-10)
    np.testing.assert_allclose([fitted.scale, fitted.cov_re.iloc[0, 0]],
                               [exact["residual_variance"], exact["intercept_variance"]], rtol=2e-5, atol=1e-10)
    np.testing.assert_allclose(covariance, exact["fixed_covariance"], rtol=2e-5, atol=1e-10)
    np.testing.assert_allclose(offsets, exact["offsets"], rtol=2e-5, atol=1e-9)
    common = {key: definition[key] for key in ("family", "stratum", "factor")}
    means = [{**common, "level": level, "n": n, "mean_uv": float(exact["means"][j]),
              "fixed_mean_SE_uv": float(np.sqrt(covariance[j, j]))} for j, level in enumerate(levels)]
    contrasts, difference_diagnostics = [], []
    for a, b in combinations(range(k), 2):
        contrast = np.zeros(k)
        contrast[a], contrast[b] = 1, -1
        estimate = float(contrast @ exact["means"])
        se = float(np.sqrt(exact["residual_variance"] * np.sum(contrast ** 2) / n))
        model_se = float(np.sqrt(contrast @ covariance @ contrast))
        np.testing.assert_allclose(se, model_se, rtol=2e-5, atol=1e-10)
        t = estimate / se
        width = float(stats.t.ppf(0.975, df) * se)
        differences = values[:, a] - values[:, b]
        sd = float(differences.std(ddof=1))
        contrasts.append({**common, "level_a": levels[a], "level_b": levels[b], "n": n,
                          "difference_a_minus_b_uv": estimate, "SE_CS_uv": se, "t": t, "df": df,
                          "p_raw_CS": float(2 * stats.t.sf(abs(t), df)),
                          "ci95_lower_uv_unadjusted": estimate - width,
                          "ci95_upper_uv_unadjusted": estimate + width,
                          "paired_dz_descriptive": estimate / sd if sd > 0 else None})
        difference_diagnostics.append({**common, "level_a": levels[a], "level_b": levels[b],
                                       "empirical_difference_variance_uv2": sd ** 2,
                                       "model_difference_variance_uv2": 2 * exact["residual_variance"],
                                       "empirical_to_model_variance_ratio": sd ** 2 / (2 * exact["residual_variance"])})
    pair_variances = [row["empirical_difference_variance_uv2"] for row in difference_diagnostics]
    helmert_scores = values @ linalg.helmert(k, full=False).T
    eigenvalues = np.linalg.eigvalsh(np.cov(helmert_scores, rowvar=False, ddof=1))
    summary = {**common, "n": n, "levels": k, "observations": n * k,
               "formula": f"summed_bca_uv ~ 0 + C({factor}) + (1 | participant_id)",
               "REML": True, "optimizer": "lbfgs", "initialized_at_closed_form": True,
               "converged": bool(fitted.converged), "warnings": fit_warnings, "llf_REML": float(fitted.llf),
               "residual_variance_uv2": exact["residual_variance"],
               "intercept_variance_uv2": exact["intercept_variance"],
               "ICC": exact["intercept_variance"] / (exact["intercept_variance"] + exact["residual_variance"]),
               "participant_offset_shrinkage": exact["shrinkage"],
               "F": exact["F"], "df1": k - 1, "df2": df, "p_raw_CS": exact["p_F"],
               "pair_variance_min_uv2": min(pair_variances), "pair_variance_max_uv2": max(pair_variances),
               "pair_variance_max_to_min_ratio": max(pair_variances) / min(pair_variances) if min(pair_variances) > 0 else None,
               "contrast_covariance_eigenvalue_min_uv2": float(eigenvalues.min()),
               "contrast_covariance_eigenvalue_max_uv2": float(eigenvalues.max()),
               "GG_epsilon_diagnostic_only": published.gg_epsilon(helmert_scores),
               "optimizer_variance_max_abs_error": float(np.max(np.abs(np.array([fitted.scale, fitted.cov_re.iloc[0, 0]]) -
                                                                  [exact["residual_variance"], exact["intercept_variance"]]))),
               "fixed_covariance_max_abs_error": float(np.max(np.abs(covariance - exact["fixed_covariance"]))),
               "closed_form_crosscheck_passed": True}
    random_rows, residual_rows = [], []
    predictions = np.asarray(fitted.fittedvalues).reshape(n, k)
    np.testing.assert_allclose(predictions, exact["means"][None, :] + offsets[:, None], rtol=1e-9, atol=1e-10)
    for i, pid in enumerate(participants):
        random_rows.append({**common, "participant_id": pid, "offset_BLUP_uv": float(offsets[i]),
                            "raw_participant_mean_minus_grand_uv": float(values[i].mean() - values.mean()),
                            "shrinkage": exact["shrinkage"]})
        for j, level in enumerate(levels):
            residual_rows.append({**common, "participant_id": pid, "level": level,
                                  "observed_uv": float(values[i, j]), "fixed_prediction_uv": float(exact["means"][j]),
                                  "conditional_fitted_uv": float(predictions[i, j]),
                                  "conditional_residual_uv": float(values[i, j] - predictions[i, j]),
                                  "double_centered_residual_uv": float(exact["double_centered_residuals"][i, j])})
    sample_covariance = np.cov(values, rowvar=False, ddof=1)
    covariance_rows = [{**common, "level_a": levels[a], "level_b": levels[b],
                        "empirical_covariance_uv2": float(sample_covariance[a, b]),
                        "model_covariance_uv2": exact["intercept_variance"] +
                        (exact["residual_variance"] if a == b else 0.0)} for a in range(k) for b in range(k)]
    return {"model_summary": summary, "fixed_means": means, "contrasts": contrasts,
            "pair_difference_diagnostics": difference_diagnostics, "participant_offsets": random_rows,
            "fitted_residuals": residual_rows, "covariance_diagnostics": covariance_rows}


def analysis_plan(inputs: dict) -> dict:
    return {"version": VERSION, "created_at_utc": datetime.now(UTC).isoformat(),
            "script_sha256": published.file_hash(Path(__file__)),
            "canonical_reader_script_sha256": published.file_hash(Path(published.__file__)),
            "input_fingerprint": published.digest(inputs), "inputs": inputs,
            "models": model_definitions(inputs), "estimation": "REML with a participant random intercept; no random slopes",
            "inference": "Exact balanced Gaussian compound-symmetry F and t inference using pooled double-centered "
                         "error variance and df=(n-1)(k-1); requires positive interior REML variances; "
                         "fixed-effect covariance independently cross-checked against statsmodels MixedLM",
            "multiplicity": "Separate primary and supplementary families: Holm across three omnibus p-values "
                             "and separately Holm across nine pairwise p-values within each family",
            "confidence_intervals": "Unadjusted 95% t intervals for pairwise mean differences; not simultaneous intervals",
            "diagnostics": "Empirical covariance, pair-difference variance ratios, contrast covariance eigenvalues and "
                           "GG epsilon are descriptive only; no data-driven covariance changes, refits or exclusions",
            "interpretation": "Secondary covariance-assumption sensitivity analysis following FHC and RM ANOVA. "
                              "The earlier repeated-measures ANOVA already accounted for participants. Random intercepts "
                              "assume equal marginal variances and equal within-participant covariances within each model; "
                              "they do not automatically accommodate condition-specific response differences. "
                              "These condition comparisons do not isolate color causally, establish semantic additivity, "
                              "or identify different normalized topographies or neural sources."}


def fit_all(tidy: pd.DataFrame, plan: dict, output: Path) -> None:
    participants = plan["inputs"]["canonical_inputs"]["participants"]
    fits = []
    for definition in plan["models"]:
        LOGGER.info("Fitting %s: %s", definition["family"], definition["stratum"])
        fits.append(fit_one(tidy, definition, participants))
    tables = {name: pd.DataFrame([row for fit in fits for row in fit[name]]) for name in
              ("fixed_means", "contrasts", "pair_difference_diagnostics", "participant_offsets",
               "fitted_residuals", "covariance_diagnostics")}
    tables["model_summary"] = pd.DataFrame([fit["model_summary"] for fit in fits])
    for name in ("model_summary", "contrasts"):
        table = tables[name]
        table["p_Holm_within_prespecified_family"] = np.nan
        for _, indices in table.groupby("family", sort=False).groups.items():
            table.loc[indices, "p_Holm_within_prespecified_family"] = published.holm(table.loc[indices, "p_raw_CS"].tolist())
    for name, table in tables.items():
        export = table.copy()
        if "warnings" in export:
            export["warnings"] = export["warnings"].map(json.dumps)
        export.to_csv(output / f"{name}.csv", index=False)
    canonical = plan["inputs"]["canonical_inputs"]
    lines = ["# Published BCA random-intercept models", "",
             f"The unchanged complete cohort contains **{len(participants)} participants** and **{len(tidy)} BCA cells**.", "",
             "Values are mean electrode amplitudes within each frozen ROI after summing the same published selected BCA harmonics, in μV. "
             "Signed values are retained without normalization or clipping.", "",
             "Conditions: " + ", ".join(canonical["conditions"]) + ".", "",
             "Frozen ROIs: " + "; ".join(f"{roi['name']}: {', '.join(roi['electrodes'])}" for roi in canonical["roi_snapshot"]["rois"]) + ".", "",
             f"Published domain: {len(canonical['selection_metadata']['selected_harmonics_hz'])} harmonics through "
             f"{max(canonical['selection_metadata']['selected_harmonics_hz']):g} Hz, unchanged from the ANOVA snapshot.", "",
             plan["interpretation"], "", "## Estimation and inference", "", plan["inference"] + ".", "",
             "The within-factor contrasts remove the participant offset. Their standard errors use the shared residual variance "
             "across all three levels, rather than the separate variance of each pair used by the earlier paired tests. "
             "Gaussian errors, independent participants, and compound symmetry are assumptions for the stated finite-sample inference. "
             "No asymptotic MixedLM z p-values are used for these comparisons.", "", plan["multiplicity"] + ".", "",
             "## Omnibus tests", "", "| Family | Model | F | df | Raw CS p | Holm p | ICC |", "|---|---|---:|---|---:|---:|---:|"]
    for row in tables["model_summary"].to_dict(orient="records"):
        lines.append(f"| {row['family']} | {row['stratum']} | {row['F']:.4f} | {row['df1']}, {row['df2']} | {row['p_raw_CS']:.6g} | "
                     f"{row['p_Holm_within_prespecified_family']:.6g} | {row['ICC']:.3f} |")
    lines.extend(["", "## Pairwise comparisons", "", "All differences are A minus B in μV. " + plan["confidence_intervals"] + ".", "",
                  "| Family | Model | A − B | Difference | Unadjusted 95% CI | t | df | Holm p |",
                  "|---|---|---|---:|---|---:|---:|---:|"])
    for row in tables["contrasts"].to_dict(orient="records"):
        lines.append(f"| {row['family']} | {row['stratum']} | {row['level_a']} − {row['level_b']} | "
                     f"{row['difference_a_minus_b_uv']:.4f} | [{row['ci95_lower_uv_unadjusted']:.4f}, "
                     f"{row['ci95_upper_uv_unadjusted']:.4f}] | {row['t']:.4f} | {row['df']} | {row['p_Holm_within_prespecified_family']:.6g} |")
    lines.extend(["", "## Covariance and convergence diagnostics", "",
                  "Compound symmetry implies that all pairwise differences within a model have the same population variance. "
                  "The empirical ratios below describe departures in this sample; they do not select a model or remove participants. "
                  "GG epsilon and covariance eigenvalues are diagnostics only and do not correct the LMM p-values.", "",
                  "| Family | Model | Residual variance | Intercept variance | Pair variance max/min | Diagnostic GG epsilon | Converged |",
                  "|---|---|---:|---:|---:|---:|---|"])
    for row in tables["model_summary"].to_dict(orient="records"):
        ratio = row["pair_variance_max_to_min_ratio"]
        lines.append(f"| {row['family']} | {row['stratum']} | {row['residual_variance_uv2']:.6f} | "
                     f"{row['intercept_variance_uv2']:.6f} | {ratio:.3f} | {row['GG_epsilon_diagnostic_only']:.3f} | {row['converged']} |")
        for warning in row["warnings"]:
            lines.append(f"\nOptimizer warning for {row['stratum']}: {warning['category']}: {warning['message']}\n")
    excluded = [row["participant_id"] for row in canonical["cohort_audit"] if not row["included_complete_case"]]
    lines.extend(["", "## Provenance and outputs", "", "Previously excluded participants: " + (", ".join(excluded) or "none") + ". "
                  "No additional exclusions or transformations were introduced.", "",
                  "analysis_plan.json freezes the source snapshot, all canonical input fingerprints, exact model families and script hashes. "
                  "fixed_means.csv contains population level estimates; participant_offsets.csv contains shrunken random intercept estimates "
                  "(descriptive participant offsets, not participant significance tests); fitted_residuals.csv contains conditional and "
                  "double-centered residuals. Full covariance and pair-difference diagnostics are exported separately.", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    published.write_json(output / "results.json", {
        "completed_at_utc": datetime.now(UTC).isoformat(), "plan_fingerprint": published.digest(plan),
        "input_fingerprint": plan["input_fingerprint"], "all_crosschecks_passed": True,
        "versions": {"numpy": np.__version__, "scipy": scipy.__version__, "statsmodels": statsmodels.__version__},
        "tables": {name: table.to_dict(orient="records") for name, table in tables.items()},
        "artifact_sha256": {path.name: published.file_hash(path) for path in output.iterdir() if path.is_file()},
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True, help="Completed ANOVA output directory inside the project")
    parser.add_argument("--output", type=Path, required=True, help="New LMM report directory inside the project")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--fit", action="store_true")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve(strict=True)
    snapshot, output = checked_path(root, args.snapshot), checked_path(root, args.output)
    if output == snapshot or output.is_relative_to(snapshot) or snapshot.is_relative_to(output):
        parser.error("The LMM output must be separate from the original ANOVA snapshot.")
    if args.prepare and output.exists() and any(output.iterdir()):
        parser.error("Preparation requires an empty or new output directory.")
    if args.fit and (output / "results.json").exists():
        parser.error("This run is complete. Prepare a new directory for another run.")
    tidy, inputs = snapshot_inputs(root, snapshot)
    if args.prepare:
        plan = analysis_plan(inputs)
        output.mkdir(parents=True, exist_ok=True)
        csv_path = output / "participant_condition_roi_bca.csv"
        csv_path.write_bytes((snapshot / csv_path.name).read_bytes())
        plan["tidy_csv_sha256"] = published.file_hash(csv_path)
        published.write_json(output / "analysis_plan.json", plan)
        LOGGER.info("Six-model plan frozen without fitting: %s", output / "analysis_plan.json")
        return
    plan = json.loads((output / "analysis_plan.json").read_text(encoding="utf-8"))
    if (plan["script_sha256"] != published.file_hash(Path(__file__)) or
            plan["canonical_reader_script_sha256"] != published.file_hash(Path(published.__file__))):
        raise ValueError("Analysis or canonical reader script changed after preparation.")
    if plan["input_fingerprint"] != published.digest(inputs) or published.digest(plan["inputs"]) != plan["input_fingerprint"]:
        raise ValueError("Inputs changed after preparation.")
    if published.file_hash(output / "participant_condition_roi_bca.csv") != plan["tidy_csv_sha256"]:
        raise ValueError("Prepared BCA data changed after preparation.")
    if plan["models"] != model_definitions(inputs):
        raise ValueError("The prespecified model definitions changed after preparation.")
    fit_all(tidy, plan, output)
    LOGGER.info("Six-model analysis complete: %s", output / "report.md")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
