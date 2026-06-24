"""Publication Report QC tables and distribution figures."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Publication_Report.models import (
    QC_NORMALITY_CHECKS_SHEET,
    QC_OUTLIER_SUMMARY_SHEET,
    QC_OUTLIER_VALUES_SHEET,
)

QC_FIGURE_SUBDIR = "qc"

_TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
}
_PALETTE = [
    ("#F0986E", "#804126"),
    ("#A3BEFA", "#2E4780"),
    ("#A3D576", "#386411"),
    ("#F390CA", "#8A3A6F"),
    ("#FFE15B", "#736422"),
]
_NEUTRAL = "#7A828F"


def build_qc_frames(
    *,
    response_values: pd.DataFrame,
    individual_roi_summed_z: pd.DataFrame,
    semantic_color_ratio_values: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build descriptive QC sheets for manual outlier and normality review."""

    values = _qc_observation_frame(
        response_values=response_values,
        individual_roi_summed_z=individual_roi_summed_z,
        semantic_color_ratio_values=semantic_color_ratio_values,
    )
    if values.empty:
        empty_values = pd.DataFrame(columns=_qc_value_columns())
        return {
            QC_OUTLIER_VALUES_SHEET: empty_values,
            QC_OUTLIER_SUMMARY_SHEET: pd.DataFrame(columns=_qc_summary_columns()),
            QC_NORMALITY_CHECKS_SHEET: pd.DataFrame(columns=_qc_normality_columns()),
        }

    values, summary = _apply_iqr_flags(values)
    normality = _normality_frame(values)
    summary = summary.merge(
        normality[
            [
                "metric_source",
                "condition",
                "roi",
                "normality_statistic",
                "normality_p",
                "normality_met",
                "qq_correlation",
            ]
        ],
        on=["metric_source", "condition", "roi"],
        how="left",
    )
    return {
        QC_OUTLIER_VALUES_SHEET: values[_qc_value_columns()],
        QC_OUTLIER_SUMMARY_SHEET: summary[_qc_summary_columns()],
        QC_NORMALITY_CHECKS_SHEET: normality[_qc_normality_columns()],
    }


def render_qc_figures(
    *,
    qc_frames: dict[str, pd.DataFrame],
    output_root: Path,
    z_thresholds: tuple[float, ...],
    warnings: list[str],
) -> tuple[list[Path], pd.DataFrame]:
    """Render manual-inspection QC figures and return manifest rows."""

    values = qc_frames.get(QC_OUTLIER_VALUES_SHEET, pd.DataFrame())
    normality = qc_frames.get(QC_NORMALITY_CHECKS_SHEET, pd.DataFrame())
    if values.empty:
        return [], pd.DataFrame(columns=_figure_manifest_columns())
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        warnings.append(f"QC figure rendering skipped because matplotlib could not be imported: {exc}")
        return [], pd.DataFrame(columns=_figure_manifest_columns())

    _configure_matplotlib(plt)
    figure_root = Path(output_root) / "figures" / QC_FIGURE_SUBDIR
    figure_root.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    manifest_rows: list[dict[str, object]] = []

    for metric_source in _metric_order(values):
        metric_frame = values.loc[values["metric_source"].astype(str) == metric_source].copy()
        if metric_frame.empty:
            continue
        metric_label = str(metric_frame["metric_label"].dropna().iloc[0])
        metric_normality = normality.loc[
            normality.get("metric_source", pd.Series(dtype=str)).astype(str) == metric_source
        ]
        figure_specs = [
            (
                "boxplot",
                _render_boxplot_figure(plt, metric_frame, metric_label, z_thresholds),
            ),
            (
                "histograms",
                _render_histogram_figure(plt, metric_frame, metric_normality, metric_label),
            ),
            (
                "qq",
                _render_qq_figure(plt, metric_frame, metric_normality, metric_label),
            ),
        ]
        for figure_type, figure in figure_specs:
            if figure is None:
                continue
            stem = f"qc_{_safe_stem(metric_source)}_{figure_type}"
            paths = _save_figure(figure, figure_root, stem)
            generated.extend(paths)
            for path in paths:
                manifest_rows.append(
                    {
                        "figure_family": "qc_distributions",
                        "figure_id": stem,
                        "metric_source": metric_source,
                        "requested": True,
                        "status": "generated",
                        "path": str(path),
                        "format": path.suffix.lstrip("."),
                        "source_sheet": QC_OUTLIER_VALUES_SHEET,
                    }
                )
            plt.close(figure)

    return generated, pd.DataFrame(manifest_rows, columns=_figure_manifest_columns())


def _qc_observation_frame(
    *,
    response_values: pd.DataFrame,
    individual_roi_summed_z: pd.DataFrame,
    semantic_color_ratio_values: pd.DataFrame,
) -> pd.DataFrame:
    frames = [
        _response_qc_observations(response_values),
        _roi_z_qc_observations(individual_roi_summed_z),
        _ratio_qc_observations(semantic_color_ratio_values),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=_qc_value_columns())
    combined = pd.concat(frames, ignore_index=True)
    combined["value"] = pd.to_numeric(combined["value"], errors="coerce")
    return combined.loc[np.isfinite(combined["value"])].reset_index(drop=True)


def _response_qc_observations(response_values: pd.DataFrame) -> pd.DataFrame:
    columns = {"condition", "subject_id", "roi", "roi_role", "summed_bca_uv"}
    if response_values.empty or not columns.issubset(response_values.columns):
        return pd.DataFrame(columns=_base_observation_columns())
    frame = response_values.copy()
    return pd.DataFrame(
        {
            "metric_source": "summed_bca_uv",
            "metric_label": "Summed BCA (uV)",
            "participant_id": frame["subject_id"].astype(str),
            "condition": frame["condition"].astype(str),
            "roi": frame["roi"].astype(str),
            "roi_role": frame["roi_role"].astype(str),
            "value": pd.to_numeric(frame["summed_bca_uv"], errors="coerce"),
        }
    )


def _roi_z_qc_observations(individual_roi_summed_z: pd.DataFrame) -> pd.DataFrame:
    columns = {"condition", "participant_id", "roi", "z_sum"}
    if individual_roi_summed_z.empty or not columns.issubset(individual_roi_summed_z.columns):
        return pd.DataFrame(columns=_base_observation_columns())
    frame = individual_roi_summed_z.copy()
    return pd.DataFrame(
        {
            "metric_source": "roi_summed_z",
            "metric_label": "ROI summed-harmonic Z",
            "participant_id": frame["participant_id"].astype(str),
            "condition": frame["condition"].astype(str),
            "roi": frame["roi"].astype(str),
            "roi_role": "",
            "value": pd.to_numeric(frame["z_sum"], errors="coerce"),
        }
    )


def _ratio_qc_observations(semantic_color_ratio_values: pd.DataFrame) -> pd.DataFrame:
    columns = {"subject_id", "roi", "roi_role", "semantic_color_ratio", "ratio_valid"}
    if semantic_color_ratio_values.empty or not columns.issubset(semantic_color_ratio_values.columns):
        return pd.DataFrame(columns=_base_observation_columns())
    frame = semantic_color_ratio_values.copy()
    valid = frame["ratio_valid"].fillna(False).astype(bool)
    frame = frame.loc[valid].copy()
    semantic = (
        str(frame["semantic_condition"].dropna().iloc[0])
        if "semantic_condition" in frame.columns and not frame["semantic_condition"].dropna().empty
        else "Semantic"
    )
    color = (
        str(frame["color_condition"].dropna().iloc[0])
        if "color_condition" in frame.columns and not frame["color_condition"].dropna().empty
        else "Color"
    )
    return pd.DataFrame(
        {
            "metric_source": "semantic_color_ratio",
            "metric_label": "Semantic / Color summed BCA ratio",
            "participant_id": frame["subject_id"].astype(str),
            "condition": f"{semantic} / {color}",
            "roi": frame["roi"].astype(str),
            "roi_role": frame["roi_role"].astype(str),
            "value": pd.to_numeric(frame["semantic_color_ratio"], errors="coerce"),
        }
    )


def _apply_iqr_flags(values: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = values.copy()
    for column in (
        "median",
        "q1",
        "q3",
        "iqr",
        "lower_iqr_fence",
        "upper_iqr_fence",
        "absolute_deviation_from_median",
    ):
        frame[column] = np.nan
    frame["iqr_outlier"] = False
    frame["outlier_direction"] = ""
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(["metric_source", "metric_label", "condition", "roi"], dropna=False):
        metric_source, metric_label, condition, roi = keys
        numeric = _finite_array(group["value"])
        q1 = _percentile(numeric, 25)
        q3 = _percentile(numeric, 75)
        iqr = q3 - q1 if np.isfinite(q1) and np.isfinite(q3) else np.nan
        lower = q1 - 1.5 * iqr if np.isfinite(iqr) else np.nan
        upper = q3 + 1.5 * iqr if np.isfinite(iqr) else np.nan
        mask = (
            frame["metric_source"].astype(str).eq(str(metric_source))
            & frame["condition"].astype(str).eq(str(condition))
            & frame["roi"].astype(str).eq(str(roi))
        )
        frame.loc[mask, "q1"] = q1
        frame.loc[mask, "q3"] = q3
        frame.loc[mask, "iqr"] = iqr
        frame.loc[mask, "lower_iqr_fence"] = lower
        frame.loc[mask, "upper_iqr_fence"] = upper
        frame.loc[mask, "median"] = float(np.median(numeric)) if len(numeric) else np.nan
        frame.loc[mask, "absolute_deviation_from_median"] = (
            frame.loc[mask, "value"] - frame.loc[mask, "median"]
        ).abs()
        outlier = mask & (
            (frame["value"] < lower if np.isfinite(lower) else False)
            | (frame["value"] > upper if np.isfinite(upper) else False)
        )
        frame.loc[outlier, "iqr_outlier"] = True
        frame.loc[outlier & (frame["value"] < lower), "outlier_direction"] = "low"
        frame.loc[outlier & (frame["value"] > upper), "outlier_direction"] = "high"
        outlier_ids = sorted(frame.loc[outlier, "participant_id"].dropna().astype(str).unique())
        rows.append(
            {
                "metric_source": metric_source,
                "metric_label": metric_label,
                "condition": condition,
                "roi": roi,
                "n": int(len(numeric)),
                "mean": float(np.mean(numeric)) if len(numeric) else np.nan,
                "sd": float(np.std(numeric, ddof=1)) if len(numeric) >= 2 else np.nan,
                "median": float(np.median(numeric)) if len(numeric) else np.nan,
                "q1": q1,
                "q3": q3,
                "iqr": iqr,
                "lower_iqr_fence": lower,
                "upper_iqr_fence": upper,
                "min": float(np.min(numeric)) if len(numeric) else np.nan,
                "max": float(np.max(numeric)) if len(numeric) else np.nan,
                "iqr_outlier_count": int(outlier.sum()),
                "iqr_outlier_participant_ids": ", ".join(outlier_ids),
                "manual_review_note": _review_note(len(outlier_ids)),
            }
        )
    frame["iqr_outlier"] = frame["iqr_outlier"].astype(bool)
    return frame, pd.DataFrame(rows, columns=_summary_base_columns())


def _normality_frame(values: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for keys, group in values.groupby(["metric_source", "metric_label", "condition", "roi"], dropna=False):
        metric_source, metric_label, condition, roi = keys
        numeric = np.sort(_finite_array(group["value"]))
        shapiro_stat = np.nan
        shapiro_p = np.nan
        if 3 <= len(numeric) <= 5000:
            result = stats.shapiro(numeric)
            shapiro_stat = float(result.statistic)
            shapiro_p = float(result.pvalue)
        rows.append(
            {
                "metric_source": metric_source,
                "metric_label": metric_label,
                "condition": condition,
                "roi": roi,
                "n": int(len(numeric)),
                "normality_test": "Shapiro-Wilk" if 3 <= len(numeric) <= 5000 else "not_tested",
                "normality_statistic": shapiro_stat,
                "normality_p": shapiro_p,
                "normality_met": bool(np.isfinite(shapiro_p) and shapiro_p >= 0.05),
                "normality_alpha": 0.05,
                "skewness": float(stats.skew(numeric, bias=False)) if len(numeric) >= 3 else np.nan,
                "excess_kurtosis": float(stats.kurtosis(numeric, fisher=True, bias=False))
                if len(numeric) >= 4
                else np.nan,
                "qq_correlation": _qq_correlation(numeric),
                "manual_review_note": _normality_note(shapiro_p, len(numeric)),
            }
        )
    return pd.DataFrame(rows, columns=_qc_normality_columns())


def _render_boxplot_figure(plt, values: pd.DataFrame, metric_label: str, z_thresholds: tuple[float, ...]):
    grouped = _plot_groups(values)
    if not grouped:
        return None
    rois = _ordered_unique(values["roi"])
    conditions = _ordered_unique(values["condition"])
    fig_width = max(9.5, 1.45 * len(rois) * max(len(conditions), 1))
    fig, ax = plt.subplots(figsize=(fig_width, 6.6))
    offsets = _condition_offsets(len(conditions))
    rng = np.random.default_rng(43)
    for roi_index, roi in enumerate(rois):
        for condition_index, condition in enumerate(conditions):
            group = grouped.get((condition, roi), pd.DataFrame())
            if group.empty:
                continue
            numeric = _finite_array(group["value"])
            if len(numeric) == 0:
                continue
            fill, edge = _PALETTE[condition_index % len(_PALETTE)]
            position = roi_index + offsets[condition_index]
            box = ax.boxplot(
                numeric,
                positions=[position],
                widths=[min(0.28, 0.78 / max(len(conditions), 1))],
                patch_artist=True,
                showfliers=False,
                whis=1.5,
            )
            for patch in box["boxes"]:
                patch.set(facecolor=fill, edgecolor=edge, alpha=0.72, linewidth=1.0)
            for element in ("whiskers", "caps", "medians"):
                for artist in box[element]:
                    artist.set(color=edge, linewidth=1.0)
            jitter = rng.normal(0, 0.018, len(group))
            ax.scatter(
                np.full(len(group), position) + jitter,
                group["value"],
                s=22,
                color=fill,
                edgecolor=edge,
                linewidth=0.5,
                alpha=0.72,
                zorder=3,
                label=condition if roi_index == 0 else None,
            )
            for row in group.loc[group["iqr_outlier"].fillna(False).astype(bool)].itertuples(index=False):
                ax.text(
                    position + 0.025,
                    float(row.value),
                    str(row.participant_id),
                    fontsize=7,
                    color=_TOKENS["ink"],
                    ha="left",
                    va="bottom",
                )
    if values["metric_source"].astype(str).eq("roi_summed_z").any():
        for threshold in z_thresholds:
            if np.isfinite(float(threshold)):
                ax.axhline(float(threshold), color=_NEUTRAL, linestyle=":", linewidth=0.9)
    ax.set_xticks(range(len(rois)), rois)
    ax.set_xlabel("ROI")
    ax.set_ylabel(metric_label)
    if len(conditions) > 1:
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, ncol=min(len(conditions), 4))
    _add_chart_header(
        fig,
        ax,
        f"{metric_label} QC boxplots",
        "Box edges show Q1-Q3, whiskers use 1.5xIQR, points are participants, and IQR outliers are labeled.",
    )
    return fig


def _render_histogram_figure(plt, values: pd.DataFrame, normality: pd.DataFrame, metric_label: str):
    grouped = _plot_groups(values)
    if not grouped:
        return None
    fig, axes = _small_multiple_axes(plt, len(grouped), title_rows=1)
    normality_lookup = _normality_lookup(normality)
    for ax, ((condition, roi), group) in zip(axes, grouped.items()):
        numeric = _finite_array(group["value"])
        fill, edge = _PALETTE[_condition_index(values, condition) % len(_PALETTE)]
        bins = min(max(int(np.ceil(np.sqrt(len(numeric)))), 4), 14) if len(numeric) else 4
        ax.hist(numeric, bins=bins, color=fill, edgecolor=edge, linewidth=0.8, alpha=0.76)
        if len(numeric):
            ax.axvline(np.median(numeric), color=_TOKENS["ink"], linestyle=":", linewidth=1.0)
        lower = _first_finite(group["lower_iqr_fence"])
        upper = _first_finite(group["upper_iqr_fence"])
        if np.isfinite(lower):
            ax.axvline(lower, color=_NEUTRAL, linestyle="--", linewidth=0.8)
        if np.isfinite(upper):
            ax.axvline(upper, color=_NEUTRAL, linestyle="--", linewidth=0.8)
        ax.set_title(_panel_title(condition, roi, normality_lookup), fontsize=9, color=_TOKENS["ink"])
        ax.set_xlabel(metric_label)
        ax.set_ylabel("Participants")
    _hide_unused_axes(axes, len(grouped))
    _add_chart_header(
        fig,
        axes[0],
        f"{metric_label} histograms",
        "Panels are condition x ROI groups; dotted lines mark medians and dashed lines mark 1.5xIQR fences.",
    )
    return fig


def _render_qq_figure(plt, values: pd.DataFrame, normality: pd.DataFrame, metric_label: str):
    grouped = _plot_groups(values)
    if not grouped:
        return None
    fig, axes = _small_multiple_axes(plt, len(grouped), title_rows=1)
    normality_lookup = _normality_lookup(normality)
    for ax, ((condition, roi), group) in zip(axes, grouped.items()):
        numeric = _finite_array(group["value"])
        fill, edge = _PALETTE[_condition_index(values, condition) % len(_PALETTE)]
        if len(numeric) >= 3:
            (theoretical, ordered), (slope, intercept, _r) = stats.probplot(numeric, dist="norm", fit=True)
            ax.scatter(theoretical, ordered, s=22, color=fill, edgecolor=edge, linewidth=0.5, alpha=0.78)
            x_line = np.asarray([np.min(theoretical), np.max(theoretical)])
            ax.plot(x_line, slope * x_line + intercept, color=_TOKENS["ink"], linewidth=1.0)
        else:
            ax.text(
                0.5,
                0.5,
                "n < 3",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color=_TOKENS["muted"],
            )
        ax.set_title(_panel_title(condition, roi, normality_lookup), fontsize=9, color=_TOKENS["ink"])
        ax.set_xlabel("Theoretical quantiles")
        ax.set_ylabel("Observed values")
    _hide_unused_axes(axes, len(grouped))
    _add_chart_header(
        fig,
        axes[0],
        f"{metric_label} Q-Q plots",
        "Panels compare observed participant values with expected normal quantiles for manual normality review.",
    )
    return fig


def _configure_matplotlib(plt) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": _TOKENS["surface"],
            "axes.facecolor": _TOKENS["panel"],
            "axes.edgecolor": _TOKENS["axis"],
            "axes.labelcolor": _TOKENS["ink"],
            "axes.grid": True,
            "grid.color": _TOKENS["grid"],
            "grid.linewidth": 0.8,
            "font.family": "sans-serif",
            "font.sans-serif": ["Aptos", "Segoe UI", "DejaVu Sans", "Arial"],
            "savefig.facecolor": _TOKENS["surface"],
            "savefig.edgecolor": "none",
        }
    )


def _add_chart_header(fig, ax, title: str, subtitle: str) -> None:
    title_text = textwrap.fill(title, width=84, break_long_words=False)
    subtitle_text = textwrap.fill(subtitle, width=126, break_long_words=False)
    fig.subplots_adjust(top=0.84)
    left = ax.get_position().x0
    fig.text(
        left,
        0.985,
        title_text,
        ha="left",
        va="top",
        fontsize=13,
        fontweight="semibold",
        color=_TOKENS["ink"],
    )
    fig.text(left, 0.93, subtitle_text, ha="left", va="top", fontsize=9, color=_TOKENS["muted"])
    for axis in fig.axes:
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.tick_params(colors=_TOKENS["ink"])


def _save_figure(fig, figure_root: Path, stem: str) -> list[Path]:
    paths = [figure_root / f"{stem}.png", figure_root / f"{stem}.svg"]
    for path in paths:
        fig.savefig(path, dpi=180, bbox_inches="tight")
    return paths


def _small_multiple_axes(plt, panel_count: int, *, title_rows: int):
    columns = min(3, max(panel_count, 1))
    rows = int(np.ceil(panel_count / columns))
    fig_width = max(10.0, 4.1 * columns)
    fig_height = 3.35 * rows + 0.8 * title_rows
    fig, axes_obj = plt.subplots(rows, columns, figsize=(fig_width, fig_height), squeeze=False)
    fig.subplots_adjust(hspace=0.72, wspace=0.30)
    axes = list(axes_obj.ravel())
    return fig, axes


def _hide_unused_axes(axes: list[object], used_count: int) -> None:
    for ax in axes[used_count:]:
        ax.set_visible(False)


def _plot_groups(values: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    groups: dict[tuple[str, str], pd.DataFrame] = {}
    for condition in _ordered_unique(values["condition"]):
        for roi in _ordered_unique(values["roi"]):
            group = values.loc[
                values["condition"].astype(str).eq(condition) & values["roi"].astype(str).eq(roi)
            ].copy()
            if not group.empty:
                groups[(condition, roi)] = group
    return groups


def _normality_lookup(normality: pd.DataFrame) -> dict[tuple[str, str], tuple[float, float]]:
    lookup: dict[tuple[str, str], tuple[float, float]] = {}
    if normality.empty:
        return lookup
    for row in normality.itertuples(index=False):
        lookup[(str(row.condition), str(row.roi))] = (
            _coerce_float(row.normality_p),
            _coerce_float(row.qq_correlation),
        )
    return lookup


def _panel_title(condition: str, roi: str, normality_lookup: dict[tuple[str, str], tuple[float, float]]) -> str:
    shapiro_p, qq_r = normality_lookup.get((condition, roi), (np.nan, np.nan))
    p_text = f"Shapiro p={shapiro_p:.3g}" if np.isfinite(shapiro_p) else "Shapiro n/a"
    r_text = f"Q-Q r={qq_r:.3f}" if np.isfinite(qq_r) else "Q-Q n/a"
    return f"{condition} / {roi}\n{p_text}; {r_text}"


def _condition_offsets(count: int) -> np.ndarray:
    if count <= 1:
        return np.asarray([0.0])
    return np.linspace(-0.28, 0.28, count)


def _condition_index(values: pd.DataFrame, condition: str) -> int:
    try:
        return _ordered_unique(values["condition"]).index(condition)
    except ValueError:
        return 0


def _metric_order(values: pd.DataFrame) -> list[str]:
    preferred = ["summed_bca_uv", "roi_summed_z", "semantic_color_ratio"]
    available = _ordered_unique(values["metric_source"])
    return [metric for metric in preferred if metric in available] + [
        metric for metric in available if metric not in preferred
    ]


def _ordered_unique(series: pd.Series) -> list[str]:
    return [str(value) for value in pd.Series(series).dropna().drop_duplicates().tolist()]


def _finite_array(values: pd.Series | np.ndarray) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce")
    array = np.asarray(numeric, dtype=float)
    return array[np.isfinite(array)]


def _percentile(values: np.ndarray, percentile: float) -> float:
    return float(np.percentile(values, percentile)) if len(values) else np.nan


def _first_finite(values: pd.Series) -> float:
    numeric = _finite_array(values)
    return float(numeric[0]) if len(numeric) else np.nan


def _qq_correlation(values: np.ndarray) -> float:
    if len(values) < 3:
        return np.nan
    try:
        _osm_osr, fit = stats.probplot(values, dist="norm", fit=True)
    except (FloatingPointError, TypeError, ValueError):
        return np.nan
    return float(fit[2])


def _normality_note(shapiro_p: float, n: int) -> str:
    if n < 3:
        return "too_few_observations_for_shapiro"
    if not np.isfinite(shapiro_p):
        return "normality_not_available"
    if shapiro_p < 0.05:
        return "manual_review_non_normality_flag"
    return "no_shapiro_flag"


def _review_note(outlier_count: int) -> str:
    if outlier_count:
        return "manual_review_iqr_outliers_flagged"
    return "no_iqr_outliers_flagged"


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_").lower()
    return stem or "figure"


def _coerce_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    return numeric if np.isfinite(numeric) else np.nan


def _base_observation_columns() -> list[str]:
    return ["metric_source", "metric_label", "participant_id", "condition", "roi", "roi_role", "value"]


def _qc_value_columns() -> list[str]:
    return [
        *_base_observation_columns(),
        "median",
        "q1",
        "q3",
        "iqr",
        "lower_iqr_fence",
        "upper_iqr_fence",
        "absolute_deviation_from_median",
        "iqr_outlier",
        "outlier_direction",
    ]


def _summary_base_columns() -> list[str]:
    return [
        "metric_source",
        "metric_label",
        "condition",
        "roi",
        "n",
        "mean",
        "sd",
        "median",
        "q1",
        "q3",
        "iqr",
        "lower_iqr_fence",
        "upper_iqr_fence",
        "min",
        "max",
        "iqr_outlier_count",
        "iqr_outlier_participant_ids",
        "manual_review_note",
    ]


def _qc_summary_columns() -> list[str]:
    return [
        *_summary_base_columns(),
        "normality_statistic",
        "normality_p",
        "normality_met",
        "qq_correlation",
    ]


def _qc_normality_columns() -> list[str]:
    return [
        "metric_source",
        "metric_label",
        "condition",
        "roi",
        "n",
        "normality_test",
        "normality_statistic",
        "normality_p",
        "normality_met",
        "normality_alpha",
        "skewness",
        "excess_kurtosis",
        "qq_correlation",
        "manual_review_note",
    ]


def _figure_manifest_columns() -> list[str]:
    return [
        "figure_family",
        "figure_id",
        "metric_source",
        "requested",
        "status",
        "path",
        "format",
        "source_sheet",
    ]
