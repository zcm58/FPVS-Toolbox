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
) -> pd.DataFrame:
    """
    Build a long-format DataFrame for generic cross-phase LMM.

    phase_data[phase][pid][condition][roi] = value
    phase_group_maps[phase][pid] = group label (e.g., "BC" / "Control").
    Returns columns: subject, group, phase, condition, roi, value.
    """

    logger = logging.getLogger(__name__)
    phases = list(phase_data.keys())
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

    common_canon_subjects: List[str] = (
        sorted(set.intersection(*phase_canon_sets)) if phase_canon_sets else []
    )

    dropped_for_missing: List[str] = []
    for canon_id in sorted(set().union(*phase_canon_sets) - set(common_canon_subjects)):
        raw_per_phase: List[str] = []
        for phase in phases:
            raw_id = phase_indices[phase]["canon_to_raw"].get(canon_id)
            if raw_id:
                raw_per_phase.append(f"{phase}:{raw_id}")
        detail = f"{canon_id} ({', '.join(sorted(raw_per_phase))})" if raw_per_phase else canon_id
        dropped_for_missing.append(detail)
    if dropped_for_missing:
        logger.warning("Dropping subjects missing in some phases: %s", dropped_for_missing)

    # Check group consistency across phases
    consistent_subjects: List[str] = []
    dropped_for_group_conflict: List[str] = []
    for canon_subj in common_canon_subjects:
        groups = []
        for phase in phases:
            raw_id = phase_indices[phase]["canon_to_raw"].get(canon_subj)
            gmap = phase_group_maps.get(phase, {})
            if raw_id is None or raw_id not in gmap:
                groups = None  # type: ignore[assignment]
                break
            groups.append(gmap[raw_id])
        if groups is None or len(set(groups)) != 1:
            dropped_for_group_conflict.append(canon_subj)
            continue
        consistent_subjects.append(canon_subj)
    if dropped_for_group_conflict:
        logger.warning(
            "Dropping subjects with inconsistent group labels: %s", sorted(set(dropped_for_group_conflict))
        )

    rows: List[Dict[str, object]] = []
    for phase in phase_labels:
        subj_map = phase_data.get(phase, {})
        gmap = phase_group_maps.get(phase, {})
        canon_to_raw = phase_indices[phase]["canon_to_raw"]
        for canon_subj in consistent_subjects:
            raw_id = canon_to_raw.get(canon_subj)
            if raw_id is None or raw_id not in subj_map:
                continue
            group_label = gmap.get(raw_id)
            for condition, roi_map in subj_map[raw_id].items():
                for roi, value in roi_map.items():
                    if not np.isfinite(value):
                        continue
                    rows.append(
                        {
                            "subject": canon_subj,
                            "group": group_label,
                            "phase": phase,
                            "condition": condition,
                            "roi": roi,
                            "value": float(value),
                        }
                    )

    return pd.DataFrame(rows, columns=["subject", "group", "phase", "condition", "roi", "value"])


def _build_fixed_effects_table(result) -> List[Dict[str, object]]:
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

    required_cols = {"subject", "group", "phase", "condition", "roi", "value"}
    missing = required_cols - set(df_long.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = df_long.copy()
    df = df.replace({"group": {None: ""}})
    df = df.dropna(subset=["value", "subject", "group", "phase", "condition", "roi"])
    df = df[np.isfinite(df["value"].to_numpy())]

    design_formula = "group * phase * C(condition, Sum) * C(roi, Sum)"
    model_formula = f"value ~ {design_formula}"

    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:
        raise ImportError("statsmodels is required. Install via `pip install statsmodels`.") from e

    result_obj = None
    with single_threaded_blas():
        try:
            model = smf.mixedlm(model_formula, df, groups=df["subject"])
            result_obj = model.fit(reml=True, method="lbfgs", maxiter=1000, full_output=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Cross-phase MixedLM failed: %s", exc)
            meta_warnings.append(f"MixedLM failed to converge: {exc}")

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

    meta = {
        "n_subjects": int(df["subject"].nunique()),
        "phase_labels": sorted(df["phase"].unique().tolist()),
        "roi_included": True,
        "warnings": meta_warnings,
    }

    return {
        "fixed_effects": fixed_effects,
        "effects_of_interest": effects_of_interest,
        "meta": meta,
    }
