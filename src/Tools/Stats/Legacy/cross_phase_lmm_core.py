"""Generic cross-phase LMM utilities for Legacy stats.

This module builds long-format data across phases and runs a generic
cross-phase mixed-effects model using summed BCA metrics.

Example structure
-----------------
phase_data = {
    "Luteal": {
        "subj01": {"ConditionA": {"ROI1": 1.2}},
        "subj02": {"ConditionA": {"ROI1": 0.8}},
    },
    "Follicular": {
        "subj01": {"ConditionA": {"ROI1": 1.5}},
        "subj02": {"ConditionA": {"ROI1": 0.6}},
    },
}

phase_group_maps = {
    "Luteal": {"subj01": "BC", "subj02": "Control"},
    "Follicular": {"subj01": "BC", "subj02": "Control"},
}

Example usage
-------------
>>> df_long = build_cross_phase_long_df(phase_data, phase_group_maps, ("Luteal", "Follicular"))
>>> results = run_cross_phase_lmm(df_long, focal_condition="ConditionA", focal_roi="ROI1")
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from Tools.Stats.PySide6.stats_subjects import canonical_subject_id

from .blas_limits import single_threaded_blas


def build_cross_phase_long_df(
    phase_data: Dict[str, Dict[str, Dict[str, Dict[str, float]]]],
    phase_group_maps: Dict[str, Dict[str, str]],
    phase_labels: Tuple[str, str],
    *,
    phase_label_to_code: Dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Build a long-format DataFrame for generic cross-phase LMM.

    phase_data[phase][raw_subject][condition][roi] = value
    phase_group_maps[phase][raw_subject] = group label (e.g., "BC" / "Control").

    Returns columns: subject (canonical), group, phase, condition, roi, value.

    Canonical subject IDs are derived from raw IDs using canonical_subject_id(),
    so that, for example, P10BCF and P10BCL are treated as the same subject "P10"
    across phases.
    """
    logger = logging.getLogger(__name__)

    phases: List[str] = list(phase_data.keys())
    if not phases:
        return pd.DataFrame(columns=["subject", "group", "phase", "condition", "roi", "value"])

    # Build per-phase mappings between raw and canonical IDs
    phase_indices: Dict[str, Dict[str, Dict[str, str]]] = {}
    phase_canon_sets: List[set[str]] = []

    for phase in phases:
        subj_map = phase_data.get(phase, {})
        raw_to_canon: Dict[str, str] = {}
        canon_to_raw_candidates: Dict[str, set[str]] = {}

        for raw_id in subj_map.keys():
            canon = canonical_subject_id(raw_id)
            raw_to_canon[raw_id] = canon
            canon_to_raw_candidates.setdefault(canon, set()).add(raw_id)

        canon_to_raw: Dict[str, str] = {}
        for canon_id, raw_ids in canon_to_raw_candidates.items():
            if len(raw_ids) > 1:
                chosen = sorted(raw_ids)[0]
                logger.warning(
                    "Lela Mode: multiple raw subject IDs %s share canonical ID '%s' in phase '%s'; using '%s'.",
                    sorted(raw_ids),
                    canon_id,
                    phase,
                    chosen,
                )
            else:
                chosen = next(iter(raw_ids))
            canon_to_raw[canon_id] = chosen

        phase_indices[phase] = {
            "raw_to_canon": raw_to_canon,
            "canon_to_raw": canon_to_raw,
        }
        phase_canon_sets.append(set(canon_to_raw.keys()))

    # Canonical subjects present in ALL phases
    common_canon_subjects: List[str] = (
        sorted(set.intersection(*phase_canon_sets)) if phase_canon_sets else []
    )

    # Log subjects that are missing in some phases (based on canonical IDs)
    dropped_for_missing: List[str] = []
    all_canon_ids = set().union(*phase_canon_sets)
    for canon_id in sorted(all_canon_ids - set(common_canon_subjects)):
        raw_per_phase: List[str] = []
        for phase in phases:
            raw_id = phase_indices[phase]["canon_to_raw"].get(canon_id)
            if raw_id:
                raw_per_phase.append(f"{phase}:{raw_id}")
        detail = f"{canon_id} ({', '.join(sorted(raw_per_phase))})" if raw_per_phase else canon_id
        dropped_for_missing.append(detail)

    if dropped_for_missing:
        logger.warning(
            "Dropping subjects missing in some phases: %s",
            dropped_for_missing,
        )

    # Check group consistency across phases, working in canonical ID space
    consistent_canon_subjects: List[str] = []
    dropped_for_group_conflict: List[str] = []

    for canon_subj in common_canon_subjects:
        groups: List[tuple[str, str | None, str | None]] = []
        for phase in phases:
            canon_to_raw = phase_indices[phase]["canon_to_raw"]
            raw_id = canon_to_raw.get(canon_subj)
            gmap = phase_group_maps.get(phase, {})
            if raw_id is None or raw_id not in gmap:
                groups.append((phase, None, None))
                continue
            raw_group = gmap[raw_id]
            normalized = " ".join(str(raw_group).split()).upper() if raw_group else ""
            groups.append((phase, normalized or None, raw_group))

        normalized_groups = [entry[1] for entry in groups if entry[1]]
        if not normalized_groups or len(set(normalized_groups)) != 1:
            phase_group_details = {phase: raw for phase, _norm, raw in groups}
            logger.warning(
                "Dropping subject with inconsistent group labels",
                extra={"subject": canon_subj, "groups": phase_group_details},
            )
            dropped_for_group_conflict.append(canon_subj)
            continue
        consistent_canon_subjects.append(canon_subj)

    if dropped_for_group_conflict:
        logger.warning(
            "Dropping subjects with inconsistent group labels: %s",
            sorted(dropped_for_group_conflict),
        )

    if not consistent_canon_subjects:
        # Caller will see an empty DataFrame and raise a more specific error.
        return pd.DataFrame(columns=["subject", "group", "phase", "condition", "roi", "value"])

    # Build the long-format rows, using canonical IDs as "subject"
    rows: List[Dict[str, object]] = []
    for phase in phase_labels:
        subj_map = phase_data.get(phase, {})
        gmap = phase_group_maps.get(phase, {})
        canon_to_raw = phase_indices.get(phase, {}).get("canon_to_raw", {})

        for canon_subj in consistent_canon_subjects:
            raw_id = canon_to_raw.get(canon_subj)
            if raw_id is None:
                continue
            subj_entry = subj_map.get(raw_id)
            if not subj_entry:
                continue
            group_label = gmap.get(raw_id)
            phase_value = phase_label_to_code.get(phase, phase) if phase_label_to_code else phase
            for condition, roi_map in subj_entry.items():
                for roi, value in roi_map.items():
                    if not np.isfinite(value):
                        continue
                    rows.append(
                        {
                            "subject": canon_subj,
                            "group": group_label,
                            "phase": phase_value,
                            "condition": condition,
                            "roi": roi,
                            "value": float(value),
                        }
                    )

    return pd.DataFrame(rows, columns=["subject", "group", "phase", "condition", "roi", "value"])


def _compute_cell_means(df: pd.DataFrame) -> List[Dict[str, object]]:
    """
    Compute descriptive statistics for each group x phase cell.

    Returns a list of dicts with keys:
      - group
      - phase
      - mean
      - sd
      - se
      - n
    """

    rows: List[Dict[str, object]] = []
    if df.empty:
        return rows

    for (group, phase), sub in df.groupby(["group", "phase"]):
        values = sub["value"].to_numpy()
        values = values[np.isfinite(values)]
        n = int(values.size)
        if n == 0:
            continue
        mean = float(values.mean())
        sd = float(values.std(ddof=1)) if n > 1 else float("nan")
        se = float(sd / np.sqrt(n)) if n > 1 and np.isfinite(sd) else float("nan")
        rows.append(
            {
                "group": group,
                "phase": phase,
                "mean": mean,
                "sd": sd,
                "se": se,
                "n": n,
            }
        )
    return rows


def _run_backup_2x2(df: pd.DataFrame, logger: logging.Logger) -> Dict[str, object]:
    """
    Backup 2x2 analysis for the cross-phase design when MixedLM fails.

    Assumes df contains columns: subject, group, phase, value,
    and has been filtered to a single condition and ROI.
    Performs:
      1) Between-group comparison at one phase (group2 - group1)
      2) Within-group phase difference for group2 (phaseB - phaseA)
      3) Interaction: difference-of-differences between groups.
    """

    result: Dict[str, object] = {
        "cell_means": [],
        "tests": [],
    }

    if df.empty:
        logger.warning("Backup 2x2: no data available.")
        return result

    groups = sorted(df["group"].dropna().astype(str).unique().tolist())
    phases = sorted(df["phase"].dropna().astype(str).unique().tolist())

    if len(groups) != 2 or len(phases) != 2:
        logger.warning(
            "Backup 2x2: expected exactly 2 groups and 2 phases, got groups=%s phases=%s",
            groups,
            phases,
        )
        result["cell_means"] = _compute_cell_means(df)
        return result

    g0, g1 = groups[0], groups[1]
    p0, p1 = phases[0], phases[1]

    # Build subject-level wide table: one row per subject with both phases
    wide = (
        df.pivot_table(
            index=["subject", "group"],
            columns="phase",
            values="value",
            aggfunc="mean",
        )
        .reset_index()
    )

    # Drop rows with missing phase values
    if p0 in wide.columns and p1 in wide.columns:
        wide = wide.dropna(subset=[p0, p1])
    else:
        logger.warning(
            "Backup 2x2: pivot table missing expected phase columns %s and %s",
            p0,
            p1,
        )
        result["cell_means"] = _compute_cell_means(df)
        return result

    tests: List[Dict[str, object]] = []

    def _welch_t_from_stats(
        mean1: float, sd1: float, n1: int, mean2: float, sd2: float, n2: int
    ) -> Dict[str, float]:
        """Run the welch t from stats helper used by the Legacy Stats workflow."""
        if n1 < 2 or n2 < 2 or not np.isfinite(sd1) or not np.isfinite(sd2):
            return {
                "t": float("nan"),
                "df": float("nan"),
                "p": float("nan"),
                "se": float("nan"),
                "estimate": float("nan"),
            }
        var1 = sd1 ** 2
        var2 = sd2 ** 2
        se2 = var1 / n1 + var2 / n2
        if se2 <= 0:
            return {
                "t": float("nan"),
                "df": float("nan"),
                "p": float("nan"),
                "se": float("nan"),
                "estimate": float("nan"),
            }
        se = float(np.sqrt(se2))
        estimate = float(mean1 - mean2)
        t_val = estimate / se
        num = se2 ** 2
        den = (var1 ** 2) / (n1 ** 2 * (n1 - 1)) + (var2 ** 2) / (n2 ** 2 * (n2 - 1))
        df_val = num / den if den > 0 else float("nan")
        p_val: float
        try:
            from scipy.stats import t as t_dist  # type: ignore

            p_val = float(2 * (1 - t_dist.cdf(abs(t_val), df_val)))
        except Exception:
            from math import erf, sqrt

            # Normal approximation as fallback
            z = float(t_val)
            p_val = float(2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))))
        return {
            "t": float(t_val),
            "df": float(df_val),
            "p": float(p_val),
            "se": se,
            "estimate": estimate,
        }

    def _paired_t(values_a: np.ndarray, values_b: np.ndarray) -> Dict[str, float]:
        """Run the paired t helper used by the Legacy Stats workflow."""
        mask = np.isfinite(values_a) & np.isfinite(values_b)
        diffs = (values_b - values_a)[mask]
        n = int(diffs.size)
        if n < 2:
            return {
                "t": float("nan"),
                "df": float("nan"),
                "p": float("nan"),
                "se": float("nan"),
                "estimate": float("nan"),
            }
        mean_d = float(diffs.mean())
        sd_d = float(diffs.std(ddof=1))
        if sd_d <= 0:
            return {
                "t": float("nan"),
                "df": float("nan"),
                "p": float("nan"),
                "se": float("nan"),
                "estimate": float("nan"),
            }
        se = sd_d / np.sqrt(n)
        t_val = mean_d / se
        df_val = float(n - 1)
        try:
            from scipy.stats import t as t_dist  # type: ignore

            p_val = float(2 * (1 - t_dist.cdf(abs(t_val), df_val)))
        except Exception:
            from math import erf, sqrt

            z = float(t_val)
            p_val = float(2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))))
        return {
            "t": float(t_val),
            "df": float(df_val),
            "p": float(p_val),
            "se": float(se),
            "estimate": float(mean_d),
        }

    # 1) Between-group comparison at phase p0 (group1 - group0)
    wide_p0 = wide[wide["group"].isin([g0, g1])]
    g0_vals = wide_p0.loc[wide_p0["group"] == g0, p0].to_numpy()
    g1_vals = wide_p0.loc[wide_p0["group"] == g1, p0].to_numpy()
    g0_vals = g0_vals[np.isfinite(g0_vals)]
    g1_vals = g1_vals[np.isfinite(g1_vals)]
    mean_g0 = float(g0_vals.mean()) if g0_vals.size > 0 else float("nan")
    mean_g1 = float(g1_vals.mean()) if g1_vals.size > 0 else float("nan")
    sd_g0 = float(g0_vals.std(ddof=1)) if g0_vals.size > 1 else float("nan")
    sd_g1 = float(g1_vals.std(ddof=1)) if g1_vals.size > 1 else float("nan")
    welch = _welch_t_from_stats(mean_g1, sd_g1, int(g1_vals.size), mean_g0, sd_g0, int(g0_vals.size))
    tests.append(
        {
            "label": f"{g1} vs {g0} at phase={p0}",
            "type": "between_group_at_phase",
            "phase": p0,
            "group1": g1,
            "group2": g0,
            "mean1": mean_g1,
            "mean2": mean_g0,
            "diff": float(mean_g1 - mean_g0) if np.isfinite(mean_g1) and np.isfinite(mean_g0) else float("nan"),
            "estimate": welch.get("estimate", float("nan")),
            "se": welch.get("se", float("nan")),
            "t": welch["t"],
            "df": welch["df"],
            "p": welch["p"],
        }
    )

    # 2) Within-group phase difference for group g1 (p1 - p0)
    wide_g1 = wide[wide["group"] == g1]
    vals_p0_g1 = wide_g1[p0].to_numpy()
    vals_p1_g1 = wide_g1[p1].to_numpy()
    paired = _paired_t(vals_p0_g1, vals_p1_g1)
    tests.append(
        {
            "label": f"{g1} {p1} minus {g1} {p0}",
            "type": "within_group_phase_diff",
            "group": g1,
            "phase1": p0,
            "phase2": p1,
            "estimate": paired.get("estimate", float("nan")),
            "se": paired.get("se", float("nan")),
            "t": paired["t"],
            "df": paired["df"],
            "p": paired["p"],
        }
    )

    # 3) Interaction: difference-of-differences between groups
    # delta = phase1 - phase0 for each subject, compare between groups
    wide_dd = wide[wide["group"].isin([g0, g1])].copy()
    wide_dd["delta"] = wide_dd[p1] - wide_dd[p0]
    d0 = wide_dd.loc[wide_dd["group"] == g0, "delta"].to_numpy()
    d1 = wide_dd.loc[wide_dd["group"] == g1, "delta"].to_numpy()
    d0 = d0[np.isfinite(d0)]
    d1 = d1[np.isfinite(d1)]
    mean_d0 = float(d0.mean()) if d0.size > 0 else float("nan")
    mean_d1 = float(d1.mean()) if d1.size > 0 else float("nan")
    sd_d0 = float(d0.std(ddof=1)) if d0.size > 1 else float("nan")
    sd_d1 = float(d1.std(ddof=1)) if d1.size > 1 else float("nan")
    welch_delta = _welch_t_from_stats(
        mean_d1, sd_d1, int(d1.size), mean_d0, sd_d0, int(d0.size)
    )
    tests.append(
        {
            "label": "group x phase difference-of-differences",
            "type": "interaction_diff_of_diffs",
            "group1": g1,
            "group2": g0,
            "phase1": p1,
            "phase0": p0,
            "mean_delta1": mean_d1,
            "mean_delta2": mean_d0,
            "diff_delta": float(mean_d1 - mean_d0)
            if np.isfinite(mean_d1) and np.isfinite(mean_d0)
            else float("nan"),
            "estimate": welch_delta.get("estimate", float("nan")),
            "se": welch_delta.get("se", float("nan")),
            "t": welch_delta["t"],
            "df": welch_delta["df"],
            "p": welch_delta["p"],
        }
    )

    result["cell_means"] = _compute_cell_means(df)
    result["tests"] = tests
    logger.info("Backup 2x2: computed %d tests.", len(tests))
    return result

def _build_fixed_effects_table(result) -> List[Dict[str, object]]:
    """Run the build fixed effects table helper used by the Legacy Stats workflow."""
    fe = getattr(result, "fe_params", None)
    bse = getattr(result, "bse_fe", None)
    if fe is None or bse is None:
        return []

    effects = list(fe.index)
    estimates = np.asarray(fe)
    ses = np.asarray(bse)
    zvals = estimates / ses
    try:
        from scipy.stats import norm  # type: ignore

        pvals = 2 * (1 - norm.cdf(np.abs(zvals)))
    except Exception:
        from math import erf, sqrt

        pvals = [2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))) for z in zvals]

    table = []
    for eff, est, se, z, p in zip(effects, estimates, ses, zvals, pvals):
        table.append(
            {
                "effect": eff,
                "estimate": float(est),
                "se": float(se),
                "stat": float(z),
                "p": float(p),
            }
        )
    return table


def _design_matrix_for_scenario(
    design_formula: str, columns: List[str], scenario_df: pd.DataFrame
) -> pd.DataFrame:
    """Run the design matrix for scenario helper used by the Legacy Stats workflow."""
    try:
        import patsy
    except ImportError as e:
        raise ImportError("patsy is required for contrast computation.") from e

    dm = patsy.dmatrix(design_formula, scenario_df, return_type="dataframe")
    # Align to the model's column order; missing columns are filled with zeros
    for col in columns:
        if col not in dm.columns:
            dm[col] = 0.0
    dm = dm[columns]
    return dm


def _build_contrast(
    design_formula: str,
    exog_columns: List[str],
    group_levels: List[str],
    phase_labels: Tuple[str, str],
    condition: str,
    roi: str | None,
    result,
    logger: logging.Logger,
) -> List[Dict[str, object]]:
    """Run the build contrast helper used by the Legacy Stats workflow."""
    contrasts: List[Dict[str, object]] = []
    if len(group_levels) < 2:
        logger.warning("Need at least two groups for contrasts; found: %s", group_levels)
        return contrasts

    cov_fe = result.cov_params()
    fe_params = result.fe_params
    if hasattr(cov_fe, "loc"):
        cov_fe = cov_fe.loc[fe_params.index, fe_params.index]
    cov_mat = np.asarray(cov_fe)

    base_data = {
        "group": [group_levels[0], group_levels[1]] * 2,
        "phase": [phase_labels[0], phase_labels[0], phase_labels[1], phase_labels[1]],
        "condition": [condition] * 4,
        "roi": [roi if roi is not None else ""] * 4,
    }
    scenario_df = pd.DataFrame(base_data)
    scenario_dm = _design_matrix_for_scenario(design_formula, exog_columns, scenario_df)

    # Rows: [g0-phaseA, g1-phaseA, g0-phaseB, g1-phaseB]
    g0_pa, g1_pa, g0_pb, g1_pb = scenario_dm.to_numpy()

    def _add_contrast(label: str, vec: np.ndarray):
        """Run the add contrast helper used by the Legacy Stats workflow."""
        est = float(np.dot(vec, fe_params))
        se = float(np.sqrt(np.dot(vec, np.dot(cov_mat, vec))))
        stat = est / se if se != 0 else np.nan
        try:
            from scipy.stats import norm  # type: ignore

            p = float(2 * (1 - norm.cdf(abs(stat))))
        except Exception:
            from math import erf, sqrt

            p = float(2 * (1 - 0.5 * (1 + erf(abs(stat) / sqrt(2)))))
        contrasts.append(
            {"label": label, "estimate": est, "se": se, "stat": float(stat), "p": p}
        )

    # group effect at phase A: group1 - group0
    _add_contrast(f"group_effect_phase={phase_labels[0]}", g1_pa - g0_pa)
    # group effect at phase B
    _add_contrast(f"group_effect_phase={phase_labels[1]}", g1_pb - g0_pb)
    # interaction: (group diff at B) - (group diff at A)
    _add_contrast("group_x_phase_interaction", (g1_pb - g0_pb) - (g1_pa - g0_pa))

    return contrasts


def run_cross_phase_lmm(
    df_long: pd.DataFrame,
    focal_condition: str | None = None,
    focal_roi: str | None = None,
    logger: logging.Logger | None = None,
) -> Dict[str, object]:
    """
    Generic cross-phase LMM for summed BCA.
    Between-subject: group
    Within-subject: phase, condition, roi
    Optionally computes targeted contrasts for a focal condition/ROI.
    Returns a JSON-serializable result dict.
    """

    logger = logger or logging.getLogger(__name__)
    meta_warnings: List[str] = []
    backup_2x2_results: List[Dict[str, object]] = []

    def _effect_label_from_test(test: Dict[str, object]) -> str | None:
        """Run the effect label from test helper used by the Legacy Stats workflow."""
        ttype = test.get("type")
        if ttype == "between_group_at_phase":
            return "group"
        if ttype == "within_group_phase_diff":
            return "phase"
        if ttype == "interaction_diff_of_diffs":
            return "group_x_phase"
        return str(ttype) if ttype is not None else None

    def _append_backup_rows(backup: Dict[str, object] | None) -> None:
        """Run the append backup rows helper used by the Legacy Stats workflow."""
        if not backup:
            return

        tests = backup.get("tests") or []
        roi_label = focal_roi if focal_roi is not None else ""
        for test in tests:
            effect = _effect_label_from_test(test)
            if not effect:
                continue

            estimate = test.get("estimate")
            if estimate is None or not np.isfinite(float(estimate)):
                estimate = test.get("diff_delta", test.get("diff", float("nan")))
            se_val = test.get("se")
            stat_val = float(test.get("t", float("nan")))
            if (se_val is None or not np.isfinite(float(se_val))) and np.isfinite(float(estimate)) and np.isfinite(stat_val) and stat_val != 0:
                se_val = float(estimate) / stat_val

            row: Dict[str, object] = {
                "roi": roi_label,
                "effect": effect,
                "estimate": float(estimate) if estimate is not None else float("nan"),
                "se": float(se_val) if se_val is not None else float("nan"),
                "stat": stat_val,
                "p": float(test.get("p", float("nan"))),
            }
            if "df" in test:
                row["df"] = test.get("df")
            backup_2x2_results.append(row)

    required_cols = {"subject", "group", "phase", "condition", "roi", "value"}
    missing = required_cols - set(df_long.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df_long.copy()
    df = df.replace({"group": {None: ""}})
    df = df.dropna(subset=["value", "subject", "group", "phase", "condition", "roi"])
    df = df[np.isfinite(df["value"].to_numpy())]

    design_formula = "group * phase * C(condition, Sum) * C(roi, Sum)"

    if focal_condition is not None:
        df = df[df["condition"] == focal_condition]
        if df.empty:
            raise ValueError(
                f"No data remaining after filtering for focal condition '{focal_condition}'."
            )
        design_formula = "group * phase"

    if focal_roi is not None:
        df = df[df["roi"] == focal_roi]
        if df.empty:
            raise ValueError(f"No data remaining after filtering for focal ROI '{focal_roi}'.")
        design_formula = "group * phase"

    if df.empty:
        raise ValueError("No data remaining after cleaning and focal filters.")

    model_formula = f"value ~ {design_formula}"

    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:
        raise ImportError("statsmodels is required. Install via `pip install statsmodels`.") from e

    result_obj = None
    backup_2x2: Dict[str, object] | None = None
    with single_threaded_blas():
        try:
            model = smf.mixedlm(model_formula, df, groups=df["subject"])
            result_obj = model.fit(reml=True, method="lbfgs", maxiter=1000, full_output=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Cross-phase MixedLM failed: %s", exc)
            meta_warnings.append(f"MixedLM failed to converge: {exc}")
            backup_2x2 = _run_backup_2x2(df, logger)

    fixed_effects = _build_fixed_effects_table(result_obj) if result_obj is not None else None

    effects_of_interest = None
    if focal_condition and result_obj is not None:
        try:
            groups = sorted(df["group"].unique().tolist())
            phases = tuple(sorted(df["phase"].unique().tolist()))
            if len(phases) < 2:
                raise ValueError("Need at least two phases to compute contrasts.")

            available_rois = df["roi"].unique().tolist()
            roi_level = focal_roi if focal_roi is not None else (available_rois[0] if available_rois else "")
            if roi_level not in available_rois:
                raise ValueError(f"Focal ROI '{roi_level}' not present in data.")

            contrasts = _build_contrast(
                design_formula,
                result_obj.model.exog_names,
                groups,
                (phases[0], phases[1]),
                focal_condition,
                roi_level,
                result_obj,
                logger,
            )
            effects_of_interest = {
                "focal_condition": focal_condition,
                "focal_roi": roi_level,
                "contrasts": contrasts,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to compute contrasts: %s", exc)
            meta_warnings.append(f"Failed to compute contrasts: {exc}")

    if result_obj is None or not getattr(result_obj, "converged", False):
        if "MixedLM failed to converge" not in meta_warnings:
            meta_warnings.append("MixedLM did not converge.")
        if backup_2x2 is None:
            backup_2x2 = _run_backup_2x2(df, logger)

    if result_obj is None and backup_2x2 is None:
        backup_2x2 = _run_backup_2x2(df, logger)

    _append_backup_rows(backup_2x2)

    meta = {
        "n_subjects": int(df["subject"].nunique()),
        "phase_labels": sorted(df["phase"].unique().tolist()),
        "roi_included": True,
        "warnings": meta_warnings,
        "backup_2x2_used": bool(backup_2x2_results),
    }

    return {
        "fixed_effects": fixed_effects,
        "effects_of_interest": effects_of_interest,
        "backup_2x2": backup_2x2,
        "backup_2x2_results": backup_2x2_results,
        "meta": meta,
    }
