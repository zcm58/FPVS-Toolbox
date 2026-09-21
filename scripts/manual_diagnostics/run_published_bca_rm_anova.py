"""Freeze and run a headless, complete-case Condition x ROI BCA analysis.

Run ``--prepare`` first and inspect analysis_plan.json before ``--fit``.
Only processing-published harmonics and final-release ROI definitions are used.
This diagnostic never changes the project configuration or selects harmonics.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from itertools import combinations
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import linalg, stats

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Main_App.io import (  # noqa: E402
    condition_companion_identity,
    read_condition_sheet_selected_columns,
)
from Main_App.processing.harmonic_selection_qc import (  # noqa: E402
    load_processing_harmonic_selection_metadata,
)
from Main_App.processing.post_processing_context import (  # noqa: E402
    post_processing_validation_scope,
)
from Main_App.processing.processing_ledger import ledger_path  # noqa: E402
from Main_App.processing.roi_coverage import (  # noqa: E402
    ROI_VALUE_AVAILABLE,
    require_canonical_released_dataset_index,
    require_project_final_release,
)
from Main_App.projects import load_project_dataset_index  # noqa: E402

LOGGER = logging.getLogger(__name__)
VERSION = "published_bca_rm_anova_v1"


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def holm(values: list[float]) -> np.ndarray:
    p = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("Holm requires finite probabilities.")
    order = np.argsort(p, kind="stable")
    result = np.empty_like(p)
    result[order] = np.minimum(1.0, np.maximum.accumulate(p[order] * np.arange(len(p), 0, -1)))
    return result


def gg_epsilon(scores: np.ndarray) -> float:
    """GG epsilon in an orthonormal contrast basis, including interactions."""
    q = scores.shape[1]
    if q == 1:
        return 1.0
    covariance = np.atleast_2d(np.cov(scores, rowvar=False, ddof=1))
    denominator = q * np.sum(covariance * covariance)
    if denominator <= 0:
        raise ValueError("Within-subject covariance is degenerate; GG inference is undefined.")
    return float(np.clip(np.trace(covariance) ** 2 / denominator, 1.0 / q, 1.0))


def rm_anova(values: np.ndarray) -> pd.DataFrame:
    """Balanced two-factor RM ANOVA using independent contrast-space sums of squares."""
    y = np.asarray(values, dtype=float)
    if y.ndim != 3 or min(y.shape) < 2 or y.shape[0] < 3 or not np.all(np.isfinite(y)):
        raise ValueError("ANOVA requires a finite participant x condition x ROI tensor with >=3 participants.")
    n, a, b = y.shape
    ha, hb = linalg.helmert(a, full=False), linalg.helmert(b, full=False)
    projections = [
        ("Condition", y.mean(axis=2) @ ha.T, b),
        ("ROI", y.mean(axis=1) @ hb.T, a),
        ("Condition:ROI", np.einsum("ncr,ac,br->nab", y, ha, hb).reshape(n, -1), 1),
    ]
    rows = []
    for term, scores, scale in projections:
        mean = scores.mean(axis=0)
        ss = float(scale * n * np.sum(mean * mean))
        error = float(scale * np.sum((scores - mean) ** 2))
        df1 = scores.shape[1]
        df2 = (n - 1) * df1
        if error <= 0:
            raise ValueError(f"{term} has zero residual variance; finite F inference is undefined.")
        f = (ss / df1) / (error / df2)
        epsilon = gg_epsilon(scores)
        rows.append({
            "term": term, "ss": ss, "ss_error": error, "df1": df1, "df2": df2,
            "F": f, "p_uncorrected": float(stats.f.sf(f, df1, df2)),
            "epsilon_GG": epsilon, "df1_GG": epsilon * df1, "df2_GG": epsilon * df2,
            "p_GG": float(stats.f.sf(f, epsilon * df1, epsilon * df2)),
            "partial_eta_squared": ss / (ss + error),
        })
    result = pd.DataFrame(rows)
    result["p_GG_Holm_three_omnibus"] = holm(result["p_GG"].tolist())
    return result


def paired_contrasts(values: np.ndarray, conditions: list[str], rois: list[str],
                     participants: list[str] | None = None) -> pd.DataFrame:
    rows = []
    n = values.shape[0]
    for r, roi in enumerate(rois):
        for a, b in combinations(range(len(conditions)), 2):
            difference = values[:, a, r] - values[:, b, r]
            mean, sd = float(difference.mean()), float(difference.std(ddof=1))
            if sd <= 0:
                raise ValueError(f"Degenerate paired contrast: {roi}, {conditions[a]} - {conditions[b]}.")
            se = sd / np.sqrt(n)
            width = float(stats.t.ppf(0.975, n - 1) * se)
            t = mean / se
            largest = int(np.argmax(np.abs(difference - mean)))
            shapiro = stats.shapiro(difference)
            rows.append({
                "ROI": roi, "condition_a": conditions[a], "condition_b": conditions[b], "n": n,
                "mean_a_uv": float(values[:, a, r].mean()), "mean_b_uv": float(values[:, b, r].mean()),
                "mean_difference_a_minus_b_uv": mean, "sd_paired_difference_uv": sd,
                "ci95_lower_uv_unadjusted": mean - width, "ci95_upper_uv_unadjusted": mean + width,
                "t": t, "df": n - 1, "p_raw": float(2 * stats.t.sf(abs(t), n - 1)), "paired_dz": mean / sd,
                "difference_shapiro_W": float(shapiro.statistic),
                "difference_shapiro_p_diagnostic_only": float(shapiro.pvalue),
                "max_abs_standardized_difference": float(abs(difference[largest] - mean) / sd),
                "participant_with_max_abs_standardized_difference": participants[largest] if participants else str(largest),
            })
    result = pd.DataFrame(rows)
    result["p_Holm_all_condition_pairs_across_ROIs"] = holm(result["p_raw"].tolist())
    return result


def load_inputs(root: Path, conditions: list[str]) -> tuple[pd.DataFrame, dict]:
    """Read exact released source cells; no alternative membership or harmonic selection."""
    initial_manifest_hash = file_hash(root / "project.json")
    initial_ledger_hash = file_hash(ledger_path(root))
    index = load_project_dataset_index(root)
    if index.is_repeated_session or index.is_multi_group:
        raise ValueError("This runner supports one group with one recording per participant only.")
    if len(conditions) != 3 or len(set(conditions)) != 3 or not set(conditions).issubset(index.conditions):
        raise ValueError(f"Choose exactly three distinct canonical conditions from {index.conditions!r}.")
    manifest = dict(index.manifest or {})
    selection_state = manifest.get("tools", {}).get("processing", {}).get("harmonic_selection", {})
    saved = selection_state.get("active") if isinstance(selection_state, dict) else None
    if not isinstance(saved, dict) or not isinstance(saved.get("selection_metadata"), dict):
        raise ValueError("Published harmonic-selection metadata is required; this runner cannot migrate or calculate it.")
    project = SimpleNamespace(project_root=root, event_map=manifest.get("event_map", {}),
                              preprocessing=manifest.get("preprocessing", {}))
    with post_processing_validation_scope():
        outcomes, coverage, receipt = require_project_final_release(root)
        index = require_canonical_released_dataset_index(root, index, final_coverage=coverage)
        metadata = load_processing_harmonic_selection_metadata(project)
        columns = list(metadata["selected_columns"])
        harmonics = list(metadata["selected_harmonics_hz"])
        if not columns or len(columns) != len(set(columns)) or len(columns) != len(harmonics):
            raise ValueError("Published harmonic columns are empty, repeated, or inconsistent.")
        roi_definitions = coverage.roi_snapshot.as_mapping()
        if len(roi_definitions) < 2:
            raise ValueError("Condition x ROI requires at least two frozen ROIs.")
        records = {}
        for record in index.select(conditions=conditions):
            key = (record.participant_id, record.condition)
            if key in records:
                raise ValueError(f"Duplicate canonical input cell: {key!r}.")
            records[key] = record
        participant_ids = sorted(index.participants or index.participant_ids, key=str.casefold)
        audit, included = [], []
        for pid in participant_ids:
            reasons = []
            for condition in conditions:
                record = records.get((pid, condition))
                if record is None:
                    reasons.append(f"{condition}: missing or excluded by canonical dataset index")
                    continue
                cell = coverage.cell_for(record.recording_id or pid, condition)
                if cell is None:
                    raise ValueError(f"Missing final-release coverage for {pid}/{condition}.")
                if cell.downstream_cell_excluded:
                    reasons.append(f"{condition}: reviewed exclusion ({', '.join(cell.decision_reason_codes)})")
                memberships = {item.roi_name: item for item in cell.roi_memberships}
                for roi, channels in roi_definitions.items():
                    member = memberships.get(roi)
                    if member is None or member.status != ROI_VALUE_AVAILABLE:
                        reasons.append(f"{condition}/{roi}: unavailable frozen ROI")
                    elif tuple(channels) != member.used_channels:
                        raise ValueError(f"ROI membership changed: {pid}/{condition}/{roi}.")
            audit.append({"participant_id": pid, "included_complete_case": not reasons, "reasons": reasons})
            if not reasons:
                included.append(pid)
        if len(included) < 3:
            raise ValueError("Fewer than three complete eligible participants.")
        rows, sources = [], []
        for pid in included:
            for condition in conditions:
                record = records[(pid, condition)]
                path = record.path.resolve()
                if not path.is_relative_to(root):
                    raise ValueError("Published BCA source must be inside the selected project root.")
                anchor_hash = file_hash(path)
                descriptor = condition_companion_identity(path)
                frame = read_condition_sheet_selected_columns(path, sheet_name="BCA (uV)",
                                                              required_columns=["Electrode", *columns])
                names = frame["Electrode"].astype(str).str.casefold()
                if names.duplicated().any():
                    raise ValueError(f"Duplicate source electrodes in {path.name}.")
                frame.index = names
                cell = coverage.cell_for(record.recording_id or pid, condition)
                for roi, channels in roi_definitions.items():
                    electrode_values = frame.loc[[name.casefold() for name in channels], columns].to_numpy(dtype=float)
                    if not np.all(np.isfinite(electrode_values)):
                        raise ValueError(f"Non-finite published BCA: {pid}/{condition}/{roi}.")
                    rows.append({"participant_id": pid, "group_id": record.group_id or "", "Condition": condition,
                                 "ROI": roi, "summed_bca_uv": float(electrode_values.sum(axis=1).mean())})
                source = {"participant_id": pid, "condition": condition, "path": path.relative_to(root).as_posix(),
                          "anchor_sha256": anchor_hash, "roi_coverage": cell.to_payload(),
                          "condition_companion": descriptor}
                if file_hash(path) != anchor_hash:
                    raise ValueError("Source anchor changed while reading.")
                sources.append(source)
    if file_hash(root / "project.json") != initial_manifest_hash or file_hash(ledger_path(root)) != initial_ledger_hash:
        raise ValueError("Project configuration or processing ledger changed during the input read.")
    tidy = pd.DataFrame(rows)
    payload = {
        "version": VERSION, "conditions": conditions, "roi_snapshot": coverage.roi_snapshot.to_payload(),
        "participants": included, "cohort_audit": audit, "n": len(included),
        "selection_metadata": metadata, "harmonic_selection_record": saved,
        "final_release_fingerprint": receipt.fingerprint, "outcome_ledger_fingerprint": outcomes.fingerprint,
        "roi_coverage_fingerprint": coverage.fingerprint, "reviewed_decisions": dict(coverage.decision_payload),
        "dataset_diagnostics": [{"code": row.code, "message": row.message} for row in index.diagnostics],
        "project_manifest_sha256": initial_manifest_hash, "processing_ledger_sha256": initial_ledger_hash,
        "source_workbooks": sources, "tidy_data_sha256": digest(tidy.to_dict(orient="records")),
    }
    return tidy, payload


def model_plan(inputs: dict) -> dict:
    return {
        "version": VERSION, "created_at_utc": datetime.now(UTC).isoformat(),
        "script_sha256": file_hash(Path(__file__)), "input_fingerprint": digest(inputs), "inputs": inputs,
        "endpoint": "Mean over every frozen ROI electrode of the sum of published selected BCA columns, in uV",
        "normalization": "None: signed BCA values retained without clipping or L2/RMS scaling",
        "model": "Two-way within-participant Condition x ROI, complete cases, no extra outlier exclusion",
        "omnibus_family": "Holm across the three Greenhouse-Geisser corrected omnibus p-values",
        "contrast_family": "Holm across every paired condition comparison in every ROI (3 pairs x ROI count)",
        "confidence_intervals": "Marginal unadjusted paired t 95% CIs; not simultaneous confidence intervals",
        "effect_sizes": "Partial eta squared for omnibus effects; paired mean differences in uV and Cohen dz",
        "cross_check": "Independent contrast-space sums of squares vs statsmodels AnovaRM raw F and degrees of freedom",
        "interpretation": "Focused secondary condition analysis after inspection of FHC; not independent replication. "
                          "No causal separation of color and semantics or test of additivity. "
                          "Raw Condition x ROI interaction is not proof of different normalized topographies or sources.",
    }


def plot_participants(tidy: pd.DataFrame, conditions: list[str], rois: list[str], output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from Main_App.exports.figure_style import FIGURE_EXPORT_DPI, matplotlib_figure_rcparams

    with plt.rc_context(matplotlib_figure_rcparams()):
        figure, axes = plt.subplots(1, len(rois), figsize=(6.5, 3.6), sharey=True, squeeze=False)
        labels = [condition.replace(" Response", "") for condition in conditions]
        if len(set(labels)) != len(labels):
            labels = conditions
        for r, roi in enumerate(rois):
            ax = axes[0, r]
            wide = tidy.loc[tidy.ROI == roi].pivot(index="participant_id", columns="Condition", values="summed_bca_uv")
            wide = wide[conditions]
            for row in wide.to_numpy():
                ax.plot(range(len(conditions)), row, "o-", color="#9aa6b2", alpha=0.40, markersize=2, linewidth=0.6)
            ax.plot(range(len(conditions)), wide.mean().to_numpy(), "o-", color="#1261a0", markersize=5, linewidth=1.8)
            ax.axhline(0, color="#555555", linewidth=0.6)
            ax.set_xticks(range(len(conditions)), labels)
            ax.set_xlim(-0.35, len(conditions) - 0.65)
            ax.set_title(roi)
            ax.spines[["top", "right"]].set_visible(False)
            ax.text(-0.08, 1.08, chr(65 + r), transform=ax.transAxes, fontsize=12, fontweight="bold")
        axes[0, 0].set_ylabel("Summed baseline-corrected\namplitude (μV)")
        figure.subplots_adjust(left=0.12, right=0.99, bottom=0.24, top=0.83, wspace=0.15)
        for suffix in ("png", "pdf"):
            figure.savefig(output / f"participant_bca.{suffix}", dpi=FIGURE_EXPORT_DPI)
        plt.close(figure)


def fit(tidy: pd.DataFrame, plan: dict, output: Path) -> None:
    from statsmodels.stats.anova import AnovaRM
    import scipy
    import statsmodels

    conditions = plan["inputs"]["conditions"]
    rois = [roi["name"] for roi in plan["inputs"]["roi_snapshot"]["rois"]]
    participants = plan["inputs"]["participants"]
    ordered = pd.MultiIndex.from_product([participants, conditions, rois], names=["participant_id", "Condition", "ROI"])
    values = tidy.set_index(["participant_id", "Condition", "ROI"])["summed_bca_uv"].reindex(ordered).to_numpy()
    values = values.reshape(len(participants), len(conditions), len(rois))
    anova = rm_anova(values)
    crosscheck = AnovaRM(tidy, "summed_bca_uv", "participant_id", within=["Condition", "ROI"]).fit().anova_table
    for row in anova.to_dict(orient="records"):
        np.testing.assert_allclose([row["F"], row["df1"], row["df2"]],
                                   crosscheck.loc[row["term"], ["F Value", "Num DF", "Den DF"]].to_numpy(),
                                   rtol=1e-8, atol=1e-9)
    contrasts = paired_contrasts(values, conditions, rois, participants)
    means = tidy.groupby(["Condition", "ROI"], sort=False).summed_bca_uv.agg(["count", "mean", "std"]).reset_index()
    anova.to_csv(output / "anova.csv", index=False)
    contrasts.to_csv(output / "paired_contrasts.csv", index=False)
    means.to_csv(output / "descriptive_means.csv", index=False)
    crosscheck.to_csv(output / "statsmodels_crosscheck.csv")
    plot_participants(tidy, conditions, rois, output)
    results = {"plan_fingerprint": digest(plan), "input_fingerprint": plan["input_fingerprint"],
               "completed_at_utc": datetime.now(UTC).isoformat(), "crosscheck_passed": True,
               "versions": {"numpy": np.__version__, "scipy": scipy.__version__, "statsmodels": statsmodels.__version__},
               "anova": anova.to_dict(orient="records"), "paired_contrasts": contrasts.to_dict(orient="records"),
               "descriptive_means": means.to_dict(orient="records")}
    lines = ["# Published BCA repeated-measures analysis", "", f"Complete eligible participants: **{len(participants)}**.", "",
             plan["endpoint"] + ".", "", "Conditions: " + ", ".join(conditions) + ".", "",
             "ROIs: " + "; ".join(f"{r['name']}: {', '.join(r['electrodes'])}" for r in plan["inputs"]["roi_snapshot"]["rois"]) + ".", "",
             "Published harmonics (Hz): " + ", ".join(f"{f:g}" for f in plan["inputs"]["selection_metadata"]["selected_harmonics_hz"]) + ".", "",
             "## Omnibus results", "", "| Effect | F | GG df | GG p | Holm p (3 effects) | Partial eta² |", "|---|---:|---|---:|---:|---:|"]
    for row in anova.to_dict(orient="records"):
        lines.append(f"| {row['term']} | {row['F']:.4f} | {row['df1_GG']:.3f}, {row['df2_GG']:.3f} | {row['p_GG']:.6g} | {row['p_GG_Holm_three_omnibus']:.6g} | {row['partial_eta_squared']:.4f} |")
    lines.extend(["", "## Paired contrasts", "", "Differences are A minus B in μV. CIs are unadjusted 95% intervals, not simultaneous intervals.", "",
                  "| ROI | A − B | Mean difference | 95% CI | dz | Holm p (all pairs × ROIs) |", "|---|---|---:|---|---:|---:|"])
    for row in contrasts.to_dict(orient="records"):
        lines.append(f"| {row['ROI']} | {row['condition_a']} − {row['condition_b']} | {row['mean_difference_a_minus_b_uv']:.4f} | [{row['ci95_lower_uv_unadjusted']:.4f}, {row['ci95_upper_uv_unadjusted']:.4f}] | {row['paired_dz']:.4f} | {row['p_Holm_all_condition_pairs_across_ROIs']:.6g} |")
    lines.extend(["", "## Interpretation and audit", "", plan["interpretation"], "",
                  "Sphericity is handled with term-specific GG epsilon in orthonormal contrast space. "
                  "Uncorrected F and df independently match statsmodels AnovaRM. Shapiro statistics in paired_contrasts.csv are diagnostic only; they did not trigger exclusions.", "",
                  "Thin gray lines in participant_bca show individuals; the blue line shows arithmetic means. "
                  "The shared y scale preserves magnitude comparisons. No data were normalized or clipped.", "",
                  "Excluded from the common complete-case cohort:", ""])
    excluded = [row for row in plan["inputs"]["cohort_audit"] if not row["included_complete_case"]]
    lines.extend(f"- {row['participant_id']}: {'; '.join(row['reasons'])}" for row in excluded)
    if not excluded:
        lines.append("None.")
    lines.extend(["", "Paired-difference diagnostics (descriptive; no automatic exclusions):", "",
                  "| ROI | A − B | Shapiro p | Largest absolute standardized difference | Participant |",
                  "|---|---|---:|---:|---|"])
    for row in contrasts.to_dict(orient="records"):
        lines.append(f"| {row['ROI']} | {row['condition_a']} − {row['condition_b']} | {row['difference_shapiro_p_diagnostic_only']:.4g} | {row['max_abs_standardized_difference']:.3f} | {row['participant_with_max_abs_standardized_difference']} |")
    lines.extend(["", "The frozen plan includes source hashes, exact harmonic-selection metadata, QC decisions, ROI memberships and cohort reasons. "
                  "The run consumes published BCA and does not recalculate or select harmonics.", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    # Publish the completion receipt only after every report and figure exists.
    write_json(output / "results.json", results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New report directory under the selected project root")
    parser.add_argument("--conditions", nargs=3, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="Freeze inputs/model without fitting")
    mode.add_argument("--fit", action="store_true", help="Fit only if the prepared plan and every input are unchanged")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve(strict=True)
    output = args.output.expanduser()
    output = (root / output).resolve() if not output.is_absolute() else output.resolve()
    if output == root or not output.is_relative_to(root):
        parser.error("The output must be a dedicated directory inside the selected project.")
    if args.prepare and output.exists() and any(output.iterdir()):
        parser.error("Preparation requires an empty or new output directory.")
    if args.fit and (output / "results.json").exists():
        parser.error("This run is already complete. Prepare a new output directory for another run.")
    tidy, inputs = load_inputs(root, args.conditions)
    if args.prepare:
        output.mkdir(parents=True, exist_ok=True)
        tidy.to_csv(output / "participant_condition_roi_bca.csv", index=False)
        plan = model_plan(inputs)
        plan["tidy_csv_sha256"] = file_hash(output / "participant_condition_roi_bca.csv")
        write_json(output / "analysis_plan.json", plan)
        LOGGER.info("Plan frozen without fitting: n=%d; %s", inputs["n"], output / "analysis_plan.json")
    else:
        plan = json.loads((output / "analysis_plan.json").read_text(encoding="utf-8"))
        if plan["script_sha256"] != file_hash(Path(__file__)) or plan["input_fingerprint"] != digest(inputs):
            raise ValueError("The analysis script or published inputs changed after preparation. Prepare a new plan.")
        if digest(plan["inputs"]) != plan["input_fingerprint"]:
            raise ValueError("The saved plan input payload does not match its fingerprint.")
        if file_hash(output / "participant_condition_roi_bca.csv") != plan["tidy_csv_sha256"]:
            raise ValueError("The prepared tidy CSV changed after preparation. Prepare a new plan.")
        fit(tidy, plan, output)
        LOGGER.info("ANOVA complete and cross-checked: %s", output / "report.md")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
