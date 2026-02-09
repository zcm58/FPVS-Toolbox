from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
from matplotlib import cm, colors as mcolors
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from .constants import EPS, MANUAL_EXCLUDED_POINT_COLOR, MANUAL_EXCLUDED_POINT_MARKER, PALETTES


@dataclass(frozen=True)
class PlotPanel:
    val_col: str
    mean_col: str
    sem_col: str
    ylabel: str
    hline_y: Optional[float] = None
    ylim: Optional[tuple[float, float]] = None
    title: Optional[str] = None


def build_roi_palette(palette_choice: str, rois: list[str]) -> dict[str, str]:
    base = PALETTES.get(palette_choice, PALETTES["vibrant"]).copy()
    default_color = base.get("Default", "#7F8C8D")

    out: dict[str, str] = {}
    for key, value in base.items():
        if key != "Default":
            out[key] = value

    cmap = cm.get_cmap("tab20")
    cmap_n = getattr(cmap, "N", 20)
    idx = 0

    for roi in rois:
        if roi in out:
            continue
        out[roi] = mcolors.to_hex(cmap(idx % cmap_n))
        idx += 1

    out["Default"] = default_color
    return out


def compute_stable_ylim(
    values: np.ndarray,
    pad_frac: float = 0.08,
    q_low: float = 2.0,
    q_high: float = 98.0,
    force_include: Optional[float] = None,
) -> Optional[tuple[float, float]]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None

    lo = float(np.nanpercentile(v, q_low))
    hi = float(np.nanpercentile(v, q_high))

    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None

    if force_include is not None and np.isfinite(force_include):
        lo = min(lo, float(force_include))
        hi = max(hi, float(force_include))

    if abs(hi - lo) <= EPS:
        lo -= 1.0
        hi += 1.0

    pad = (hi - lo) * pad_frac
    return (lo - pad, hi + pad)


def ordered_conditions(df: pd.DataFrame, cond_a: str, cond_b: str) -> list[str]:
    present = df["condition_label"].dropna().tolist()
    uniq: list[str] = []
    for value in present:
        if value not in uniq:
            uniq.append(value)

    ordered: list[str] = []
    for pref in [cond_a, cond_b]:
        if pref in uniq:
            ordered.append(pref)
    for value in uniq:
        if value not in ordered:
            ordered.append(value)
    return ordered


def make_raincloud_figure(
    df_part_all: pd.DataFrame,
    df_group_used: pd.DataFrame,
    panel: PlotPanel,
    out_path_no_ext: Path,
    roi_defs: dict[str, list[str]],
    palette_choice: str,
    run_label: str,
    png_dpi: int,
    cond_a: str,
    cond_b: str,
    excluded_col: str = "is_manual_excluded",
    log_func: Callable[[str], None] | None = None,
) -> None:
    if excluded_col in df_part_all.columns:
        df_part_all = df_part_all.copy()
        df_part_all[excluded_col] = df_part_all[excluded_col].fillna(False).astype(bool)

    rois = list(roi_defs.keys())
    palette = build_roi_palette(palette_choice, rois)
    conds = ordered_conditions(df_part_all, cond_a, cond_b)

    seed = abs(hash(run_label)) % (2**32)
    rng = np.random.default_rng(seed)

    fig = Figure(figsize=(10, 6))
    FigureCanvas(fig)
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.12, bottom=0.18, top=0.90)

    n_rois = max(len(rois), 1)
    cluster_width = 0.70
    step = cluster_width / n_rois
    roi_offsets = (np.arange(n_rois) - (n_rois - 1) / 2.0) * step
    violin_width = min(0.32, step * 0.85)

    for i, cond in enumerate(conds):
        for j, roi in enumerate(rois):
            pos = float(i + roi_offsets[j])
            roi_color = palette.get(roi, palette["Default"])

            sub = df_part_all[
                (df_part_all["condition_label"] == cond) & (df_part_all["ROI"] == roi)
            ].copy()

            if sub.empty:
                continue

            sub_in = sub[sub[excluded_col] == False]  # noqa: E712
            sub_ex = sub[sub[excluded_col] == True]   # noqa: E712

            data_in = pd.to_numeric(sub_in[panel.val_col], errors="coerce").dropna().to_numpy(dtype=float)
            data_ex = pd.to_numeric(sub_ex[panel.val_col], errors="coerce").dropna().to_numpy(dtype=float)
            if log_func:
                log_func(
                    "Ratio plot counts: "
                    f"ROI={roi} condition={cond} metric={panel.val_col} "
                    f"included_n={len(sub_in)} excluded_n={len(sub_ex)} "
                    f"included_finite={data_in.size} excluded_finite={data_ex.size}"
                )
                if len(sub_in) == 0 and len(sub_ex) > 0:
                    log_func(
                        "Warning: All participants are marked manual-excluded (or included filter failed). "
                        "Plot will omit violin/box/mean overlays."
                    )

            if data_in.size > 0:
                v = ax.violinplot(data_in, positions=[pos], showextrema=False, widths=violin_width)
                for pc in v["bodies"]:
                    pc.set_facecolor(roi_color)
                    pc.set_edgecolor("none")
                    pc.set_alpha(0.30)
                    clip_rect = Rectangle((-1e9, -1e9), 1e9 + pos, 2e9, transform=ax.transData)
                    pc.set_clip_path(clip_rect)

                jitter = (rng.random(len(data_in)) - 0.5) * (step * 0.30)
                x_pts = np.full(len(data_in), pos + (violin_width * 0.22)) + jitter
                ax.scatter(x_pts, data_in, color=roi_color, alpha=0.60, s=20, zorder=3)

                ax.boxplot(
                    data_in,
                    positions=[pos],
                    widths=max(0.06, violin_width * 0.22),
                    showfliers=False,
                    patch_artist=True,
                    boxprops=dict(facecolor="white", edgecolor=roi_color, linewidth=1.5),
                    whiskerprops=dict(color=roi_color, linewidth=1.5),
                    capprops=dict(color=roi_color, linewidth=1.5),
                    medianprops=dict(color="black", linewidth=2),
                )

                g = df_group_used[(df_group_used["condition_label"] == cond) & (df_group_used["ROI"] == roi)]
                if not g.empty:
                    m = float(g.iloc[0][panel.mean_col])
                    se = float(g.iloc[0][panel.sem_col])
                    if np.isfinite(m):
                        if np.isfinite(se) and se > 0:
                            ax.errorbar(
                                [pos],
                                [m],
                                yerr=[se],
                                fmt="o",
                                color=roi_color,
                                capsize=4,
                                elinewidth=2,
                                markersize=7,
                                zorder=6,
                            )
                        else:
                            ax.plot([pos], [m], marker="o", color=roi_color, markersize=7, zorder=6)

            if data_ex.size > 0:
                jitter_ex = (rng.random(len(data_ex)) - 0.5) * (step * 0.30)
                x_ex = np.full(len(data_ex), pos + (violin_width * 0.22)) + jitter_ex
                ax.scatter(
                    x_ex,
                    data_ex,
                    color=MANUAL_EXCLUDED_POINT_COLOR,
                    marker=MANUAL_EXCLUDED_POINT_MARKER,
                    alpha=0.85,
                    s=35,
                    zorder=7,
                )

    if panel.hline_y is not None:
        ax.axhline(panel.hline_y, color="red", linestyle=":", linewidth=2, alpha=0.8)

    if panel.ylim is not None:
        ax.set_ylim(panel.ylim)

    ax.set_ylabel(panel.ylabel, fontsize=12, fontweight="bold")
    if panel.title:
        ax.set_title(panel.title, fontsize=14, fontweight="bold", pad=10)

    ax.grid(axis="y", linestyle="--", alpha=0.4)

    ax.set_xticks(np.arange(len(conds)))
    ax.set_xticklabels(conds, fontsize=11, fontweight="bold")

    roi_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=palette.get(r, palette["Default"]),
            markersize=10,
            label=r,
        )
        for r in rois
    ]
    excl_handle = Line2D(
        [0], [0],
        marker=MANUAL_EXCLUDED_POINT_MARKER,
        color=MANUAL_EXCLUDED_POINT_COLOR,
        linestyle="None",
        markersize=10,
        label="Manual excluded",
    )
    ax.legend(handles=roi_handles + [excl_handle], loc="upper right", frameon=True)

    fig.savefig(out_path_no_ext.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out_path_no_ext.with_suffix(".png"), dpi=png_dpi, bbox_inches="tight")
    fig.savefig(out_path_no_ext.with_suffix(".svg"), bbox_inches="tight")


def make_raincloud_figure_roi_x(
    df_part_all: pd.DataFrame,
    df_group_used: pd.DataFrame,
    panel: PlotPanel,
    out_path_no_ext: Path,
    roi_defs: dict[str, list[str]],
    palette_choice: str,
    run_label: str,
    png_dpi: int,
    xlabel: str = "ROI",
    excluded_col: str = "is_manual_excluded",
    log_func: Callable[[str], None] | None = None,
) -> None:
    if excluded_col in df_part_all.columns:
        df_part_all = df_part_all.copy()
        df_part_all[excluded_col] = df_part_all[excluded_col].fillna(False).astype(bool)

    rois_all = list(roi_defs.keys())
    palette = build_roi_palette(palette_choice, rois_all)

    rois_present = [r for r in rois_all if r in set(df_part_all["ROI"].dropna().astype(str).tolist())]
    if not rois_present:
        raise ValueError("No ROI entries found for ROI-x ratio plot.")

    seed = abs(hash(run_label)) % (2**32)
    rng = np.random.default_rng(seed)

    fig = Figure(figsize=(10, 6))
    FigureCanvas(fig)
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.12, bottom=0.18, top=0.88)

    violin_width = 0.65
    jitter_scale = 0.18

    for j, roi in enumerate(rois_present):
        pos = float(j)
        roi_color = palette.get(roi, palette["Default"])

        sub = df_part_all[df_part_all["ROI"] == roi].copy()
        if sub.empty:
            continue

        sub_in = sub[sub[excluded_col] == False]  # noqa: E712
        sub_ex = sub[sub[excluded_col] == True]   # noqa: E712

        data_in = pd.to_numeric(sub_in[panel.val_col], errors="coerce").dropna().to_numpy(dtype=float)
        data_ex = pd.to_numeric(sub_ex[panel.val_col], errors="coerce").dropna().to_numpy(dtype=float)
        if log_func:
            log_func(
                "Ratio plot counts: "
                f"ROI={roi} metric={panel.val_col} "
                f"included_n={len(sub_in)} excluded_n={len(sub_ex)} "
                f"included_finite={data_in.size} excluded_finite={data_ex.size}"
            )
            if len(sub_in) == 0 and len(sub_ex) > 0:
                log_func(
                    "Warning: All participants are marked manual-excluded (or included filter failed). "
                    "Plot will omit violin/box/mean overlays."
                )

        if data_in.size > 0:
            v = ax.violinplot(data_in, positions=[pos], showextrema=False, widths=violin_width)
            for pc in v["bodies"]:
                pc.set_facecolor(roi_color)
                pc.set_edgecolor("none")
                pc.set_alpha(0.30)

            jitter = (rng.random(len(data_in)) - 0.5) * jitter_scale
            x_pts = np.full(len(data_in), pos) + jitter
            ax.scatter(x_pts, data_in, color=roi_color, alpha=0.60, s=20, zorder=3)

            ax.boxplot(
                data_in,
                positions=[pos],
                widths=0.18,
                showfliers=False,
                patch_artist=True,
                boxprops=dict(facecolor="white", edgecolor=roi_color, linewidth=1.5),
                whiskerprops=dict(color=roi_color, linewidth=1.5),
                capprops=dict(color=roi_color, linewidth=1.5),
                medianprops=dict(color="black", linewidth=2),
            )

            g = df_group_used[df_group_used["ROI"] == roi]
            if not g.empty:
                m = float(g.iloc[0][panel.mean_col])
                se = float(g.iloc[0][panel.sem_col])
                if np.isfinite(m):
                    if np.isfinite(se) and se > 0:
                        ax.errorbar(
                            [pos],
                            [m],
                            yerr=[se],
                            fmt="o",
                            color=roi_color,
                            capsize=4,
                            elinewidth=2,
                            markersize=7,
                            zorder=6,
                        )
                    else:
                        ax.plot([pos], [m], marker="o", color=roi_color, markersize=7, zorder=6)

        if data_ex.size > 0:
            jitter_ex = (rng.random(len(data_ex)) - 0.5) * jitter_scale
            x_ex = np.full(len(data_ex), pos) + jitter_ex
            ax.scatter(
                x_ex,
                data_ex,
                color=MANUAL_EXCLUDED_POINT_COLOR,
                marker=MANUAL_EXCLUDED_POINT_MARKER,
                alpha=0.85,
                s=35,
                zorder=7,
            )

    if panel.hline_y is not None:
        ax.axhline(panel.hline_y, color="red", linestyle=":", linewidth=2, alpha=0.8)

    if panel.ylim is not None:
        ax.set_ylim(panel.ylim)

    ax.set_xlabel(xlabel, fontsize=12, fontweight="bold")
    ax.set_ylabel(panel.ylabel, fontsize=12, fontweight="bold")

    if panel.title:
        ax.set_title(panel.title, fontsize=14, fontweight="bold", pad=10)

    ax.grid(axis="y", linestyle="--", alpha=0.4)

    ax.set_xticks(np.arange(len(rois_present)))
    ax.set_xticklabels(rois_present, fontsize=11, fontweight="bold")

    roi_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=palette.get(r, palette["Default"]),
            markersize=10,
            label=r,
        )
        for r in rois_present
    ]
    excl_handle = Line2D(
        [0], [0],
        marker=MANUAL_EXCLUDED_POINT_MARKER,
        color=MANUAL_EXCLUDED_POINT_COLOR,
        linestyle="None",
        markersize=10,
        label="Manual excluded",
    )
    ax.legend(handles=roi_handles + [excl_handle], loc="upper right", frameon=True)

    fig.savefig(out_path_no_ext.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out_path_no_ext.with_suffix(".png"), dpi=png_dpi, bbox_inches="tight")
    fig.savefig(out_path_no_ext.with_suffix(".svg"), bbox_inches="tight")
