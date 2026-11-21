"""Render prepared correlation data in the FPVS publication style; no EEG reads or inference selection."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.legend_handler import HandlerTuple
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))
from Main_App.exports.figure_style import (  # noqa: E402
    FIGURE_EXPORT_DPI,
    FIGURE_FONT_FAMILY,
    apply_matplotlib_figure_style,
)

POINT, LINE, BAND = "#22779B", "#A74D18", "#F5DAC5"
INK, GRID = "#21333E", "#DFE5E8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_sha256(path: Path) -> str:
    """Bind analysis metadata to CSV text without OS line-ending/BOM differences."""
    return hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def identifier(value: str) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)),
            "Use a nonempty filename ID containing only letters, digits, underscores and hyphens.")
    return value


def probability(value: float) -> float:
    result = float(value)
    require(np.isfinite(result) and 0 <= result <= 1, "A supplied p or q must be finite and between zero and one.")
    return result


def signed(value: float) -> str:
    text = f"{value:.3g}" if 0 < abs(value) < .001 else f"{value:.3f}"
    return text.replace("-", "−")


def prob_text(value: float) -> str:
    if value == 0:
        return "< 0.001"
    return f"= {value:.3g}" if value < .01 else f"= {value:.3f}"


def prepare(spec_path: Path) -> tuple[dict, list[dict], Path]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    require(spec.get("version") == 1, "Expected template spec version 1.")
    require(isinstance(spec.get("provenance"), dict) and bool(spec["provenance"]),
            "Record endpoint, sample, analysis method and multiplicity provenance.")
    definitions = spec["panels"]
    require(1 <= len(definitions) <= 3, "This reference layout supports one to three panels.")
    ids = [identifier(panel["id"]) for panel in definitions]
    require(len(ids) == len(set(ids)), "Panel IDs must be unique.")
    identifier(spec["stem"])
    data_path = (spec_path.parent / spec["data"]).resolve(strict=True)
    require(csv_sha256(data_path) == spec["data_sha256"], "CSV hash differs from the analyzed data recorded in the spec.")
    rows = pd.read_csv(data_path, dtype={"panel": str, "participant": str})
    required = {"panel", "participant", "x", "y"}
    require(required.issubset(rows.columns), "CSV needs panel, participant, x and y columns.")
    require(not rows[list(required)].isna().any().any(), "Missing observations require an explicit upstream decision.")
    require(set(rows.panel) == set(ids), "CSV and spec must contain exactly the same panel IDs.")
    require(rows.participant.str.strip().ne("").all(), "Participant IDs cannot be blank.")
    require(not rows.duplicated(["panel", "participant"]).any(), "Duplicate participant within a panel.")
    panels = []
    for definition in definitions:
        selected = rows.loc[rows.panel.eq(definition["id"])].copy()
        x = pd.to_numeric(selected.x, errors="raise").to_numpy(dtype=float)
        y = pd.to_numeric(selected.y, errors="raise").to_numpy(dtype=float)
        n = len(x)
        require(n >= 4 and n == definition["n"], "Panel count must match the supplied analysis (at least four pairs).")
        require(np.isfinite(x).all() and np.isfinite(y).all(), "All pairs must be finite; rows are never silently dropped.")
        require(np.ptp(x) > 0 and np.ptp(y) > 0, "Constant scores/responses do not define a correlation.")
        inference = definition["spearman"]
        rho = float(stats.spearmanr(x, y).statistic)
        require(np.isclose(rho, float(inference["rho"]), atol=1e-8, rtol=0),
                "Supplied Spearman rho does not match the plotted pairs; retain full precision in the spec.")
        require(bool(inference["p_method"].strip()), "Describe the upstream p-value method.")
        p = probability(inference["p"])
        q = inference.get("q")
        if q is not None:
            q = probability(q)
            require(inference.get("correction_id") in {"benjamini_hochberg", "benjamini_yekutieli"},
                    "FDR q requires correction_id benjamini_hochberg or benjamini_yekutieli.")
            require(isinstance(inference.get("family_size"), int) and inference["family_size"] >= 1,
                    "An adjusted q requires its original family size.")
            require(bool(inference.get("correction_method")), "Describe how the supplied q was obtained.")
        fraction = float(definition.get("r2_fraction", .62))
        require(.15 <= fraction <= .85, "Place the line label between 15% and 85% of the observed x range.")
        fit = stats.linregress(x, y)
        grid = np.linspace(x.min(), x.max(), 241)
        mean = fit.intercept + fit.slope * grid
        residual = y - (fit.intercept + fit.slope * x)
        mse = float(np.sum(residual**2) / (n - 2))
        se = np.sqrt(mse * (1 / n + (grid - x.mean())**2 / np.sum((x - x.mean())**2)))
        half = stats.t.ppf(.975, n - 2) * se
        r_squared = 1 - np.sum(residual**2) / np.sum((y - y.mean())**2)
        require(np.isclose(r_squared, fit.rvalue**2, atol=1e-12), "OLS R squared verification failed.")
        panels.append({
            "id": definition["id"], "label": definition["label"], "x_label": definition["x_label"],
            "n": n, "participants": selected.participant.tolist(),
            "x": x, "y": y, "grid": grid, "mean": mean, "low": mean - half, "high": mean + half,
            "rho": rho, "p": p, "q": q, "inference": inference, "r2_fraction": fraction,
            "slope": float(fit.slope), "intercept": float(fit.intercept),
            "linear_r_squared": float(r_squared), "linear_p": float(fit.pvalue),
        })
    return spec, panels, data_path


def draw(spec: dict, panels: list[dict], bounds: tuple[float, float], path: Path) -> None:
    count = len(panels)
    combined = count > 1
    width_in = {1: 6.0, 2: 8.0, 3: 11.5}[count]
    fig = plt.figure(figsize=(width_in, 4.2))
    try:
        common_n = len({panel["n"] for panel in panels}) == 1
        heading = spec["header"] + (f"  ·  n = {panels[0]['n']}" if common_n else "")
        artists = [fig.text(.535, .975, heading, ha="center", va="top", fontsize=10,
                            fontweight="bold", color=INK)]
        point = Line2D([], [], ls="", marker="o", ms=5.5, mfc=POINT, mec="white", mew=.4, alpha=.76)
        fit_handle = (Patch(facecolor=BAND, edgecolor="none"), Line2D([], [], color=LINE, lw=1.6))
        artists.append(fig.legend([point, fit_handle], ["Participant", "Linear fit (95% CI for mean)"],
                                  handler_map={tuple: HandlerTuple(ndivide=1)}, loc="upper center",
                                  bbox_to_anchor=(.535, .925), ncol=2, frameon=False, fontsize=10))
        left, right, gap = {1: (.15, .96, 0), 2: (.105, .98, .065), 3: (.073, .986, .041)}[count]
        width = (right - left - gap * (count - 1)) / count
        axes = []
        line_labels = []
        annotation_artists = []
        for index, panel in enumerate(panels):
            ax = fig.add_axes([left + index * (width + gap), .19, width, .63])
            axes.append(ax)
            ax.set_axisbelow(True)
            ax.yaxis.grid(True, linewidth=.55, color=GRID)
            ax.fill_between(panel["grid"], panel["low"], panel["high"],
                            color=BAND, linewidth=0, zorder=1, rasterized=True)
            ax.plot(panel["grid"], panel["mean"], color=LINE, lw=1.6, zorder=2)
            dots = ax.scatter(panel["x"], panel["y"], s=27, c=POINT, alpha=.73, edgecolors="white",
                              linewidths=.42, zorder=3, rasterized=True)
            np.testing.assert_array_equal(dots.get_offsets(), np.column_stack([panel["x"], panel["y"]]))
            xpad = max(.045 * np.ptp(panel["x"]), .01)
            ax.set_xlim(panel["x"].min() - xpad, panel["x"].max() + xpad)
            ax.set_ylim(*bounds)
            ax.xaxis.set_major_locator(MaxNLocator(nbins=5 if combined else 6))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
            ax.set_xlabel(panel["x_label"], fontsize=10, labelpad=6, color=INK)
            if index == 0:
                ax.set_ylabel(spec["y_label"], fontsize=10, labelpad=6, color=INK)
            ax.tick_params(length=3, width=.6, color="#80929B", labelcolor=INK,
                           labelsize=10, labelleft=(index == 0))
            for side in ("left", "bottom"):
                ax.spines[side].set_color("#80929B")
                ax.spines[side].set_linewidth(.65)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            note = "" if common_n else f"n = {panel['n']}\n"
            note += f"Spearman ρ = {signed(panel['rho'])}\nUncorrected p {prob_text(panel['p'])}"
            if panel["q"] is not None:
                note += f"\nFDR q {prob_text(panel['q'])} ({panel['inference']['family_size']} tests)"
            annotation_artists.append(ax.text(.97, .97, note, transform=ax.transAxes,
                                             ha="right", va="top", color=INK, fontsize=10, linespacing=1.2))
            annotation_artists.append(ax.text(.035, .035,
                f"Slope = {signed(panel['slope'])} {spec['slope_unit']}\nLinear p {prob_text(panel['linear_p'])}",
                transform=ax.transAxes, ha="left", va="bottom", color=INK, fontsize=10, linespacing=1.2))
            x_position = panel["x"].min() + panel["r2_fraction"] * np.ptp(panel["x"])
            y_position = panel["intercept"] + panel["slope"] * x_position
            line_labels.append((ax, panel, x_position, y_position))
        fig.canvas.draw()
        for ax, panel, x_position, y_position in line_labels:
            points = ax.transData.transform([[x_position, y_position],
                                            [x_position + 1, y_position + panel["slope"]]])
            dx, dy = points[1] - points[0]
            annotation_artists.append(ax.text(x_position, y_position,
                f"Linear R² = {panel['linear_r_squared']:.3f}", ha="center", va="center",
                rotation=np.degrees(np.arctan2(dy, dx)), rotation_mode="anchor", color=LINE,
                fontsize=10, zorder=2.5, bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.2}))
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for artist in annotation_artists:
            box, frame = artist.get_window_extent(renderer), artist.axes.get_window_extent(renderer)
            require(frame.x0 <= box.x0 and box.x1 <= frame.x1 and frame.y0 <= box.y0 and box.y1 <= frame.y1,
                    "An annotation does not fit. Shorten labels or adapt the reference layout.")
        artists.extend(annotation_artists)
        for ax in axes:
            artists.extend([ax.xaxis.label, ax.yaxis.label])
            for axis, limits in [(ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())]:
                artists.extend(tick.label1 for tick in axis.get_major_ticks()
                               if tick.label1.get_visible() and limits[0] <= tick.get_loc() <= limits[1])
        for artist in artists:
            box = artist.get_window_extent(renderer)
            require(box.x0 >= -1 and box.y0 >= -1 and box.x1 <= fig.bbox.x1 + 1 and box.y1 <= fig.bbox.y1 + 1,
                    "Figure text is clipped. Adapt the reference layout before publishing.")
        for ext in ("png", "pdf"):
            fig.savefig(path.with_suffix(f".{ext}"), dpi=FIGURE_EXPORT_DPI, facecolor="white",
                        metadata={"Creator": "FPVS correlation figure template"})
    finally:
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="Explicit project/user-selected results folder.")
    parser.add_argument("--overwrite", action="store_true", help="Replace this template's named outputs only.")
    args = parser.parse_args()
    spec_path = args.spec.resolve(strict=True)
    spec, panels, data_path = prepare(spec_path)
    apply_matplotlib_figure_style()
    font_manager.findfont(FIGURE_FONT_FAMILY, fallback_to_default=False)
    require(FIGURE_EXPORT_DPI == 600, "The reference format requires 600dpi.")
    lo = min(float(panel["low"].min()) for panel in panels)
    hi = max(float(panel["high"].max()) for panel in panels)
    lo = min(lo, *(float(panel["y"].min()) for panel in panels))
    hi = max(hi, *(float(panel["y"].max()) for panel in panels))
    span = hi - lo
    bounds = tuple(spec.get("y_limits", [lo - .30 * span, hi + .30 * span]))
    require(len(bounds) == 2 and np.isfinite(bounds).all() and bounds[0] <= lo and bounds[1] >= hi,
            "Shared y limits must include every point and confidence band.")
    exports = [(f"{spec['stem']}-{panel['id']}", [panel]) for panel in panels]
    if len(panels) > 1:
        exports.insert(0, (f"{spec['stem']}-combined", panels))
    output = args.output_dir.resolve()
    names = [f"{name}.{ext}" for name, _ in exports for ext in ("png", "pdf")]
    receipt_name = f"{spec['stem']}-receipt.json"
    require(not {spec_path, data_path}.intersection((output / name).resolve() for name in [*names, receipt_name]),
            "Export filenames must not replace either source input.")
    require(args.overwrite or not any((output / name).exists() for name in [*names, receipt_name]),
            "An output already exists; review it or use --overwrite for this named export set.")
    output.mkdir(parents=True, exist_ok=True)
    input_hashes = {"spec": sha256(spec_path), "data": sha256(data_path)}
    with TemporaryDirectory(prefix=".correlation-stage-", dir=output) as temporary:
        stage = Path(temporary)
        for name, selected in exports:
            draw(spec, selected, bounds, stage / name)
        require(input_hashes == {"spec": sha256(spec_path), "data": sha256(data_path)},
                "An input changed during rendering.")
        receipt = {
            "template_version": 1, "spec": str(spec_path), "data": str(data_path),
            "input_sha256": input_hashes, "provenance": spec["provenance"], "shared_y_limits": bounds,
            "dpi": FIGURE_EXPORT_DPI,
            "pdf": "Points and confidence bands rasterized at 600dpi; text, axes and fitted lines remain vectors.",
            "statistics": [{key: value for key, value in panel.items()
                            if key not in {"x", "y", "grid", "mean", "low", "high"}} for panel in panels],
            "exports": [{"png": str(output / f"{name}.png"), "pdf": str(output / f"{name}.pdf"),
                         "panels": len(selected)} for name, selected in exports],
            "output_sha256": {name: sha256(stage / name) for name in names},
        }
        (stage / receipt_name).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        for name in [*names, receipt_name]:
            (stage / name).replace(output / name)
    print(output / receipt_name)


if __name__ == "__main__":
    main()
