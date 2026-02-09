from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Ratio_Calculator.constants import ROI_DEFS_DEFAULT
from Tools.Ratio_Calculator.plots import PlotPanel, make_raincloud_figure_roi_x


def _build_ratio_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(202401)
    rois = list(ROI_DEFS_DEFAULT.keys())
    included_pids = [f"P{i:03d}" for i in range(1, 11)]
    excluded_pids = [f"P{i:03d}" for i in range(11, 13)]

    rows: list[dict[str, object]] = []
    for roi in rois:
        for pid in included_pids:
            rows.append(
                {
                    "participant_id": pid,
                    "ROI": roi,
                    "val": float(rng.normal(loc=1.1, scale=0.15)),
                    "is_manual_excluded": False,
                }
            )
        for pid in excluded_pids:
            rows.append(
                {
                    "participant_id": pid,
                    "ROI": roi,
                    "val": float(rng.normal(loc=0.9, scale=0.2)),
                    "is_manual_excluded": True,
                }
            )

    df_part_all = pd.DataFrame(rows)
    df_group_used = (
        df_part_all[~df_part_all["is_manual_excluded"]]
        .groupby("ROI", as_index=False)["val"]
        .agg(mean="mean", sem=lambda x: float(np.std(x, ddof=1) / np.sqrt(len(x))))
    )
    return df_part_all, df_group_used


def test_ratio_plot_saves_png(tmp_path: Path) -> None:
    df_part_all, df_group_used = _build_ratio_frames()
    out_base = tmp_path / "ratio_plot"
    make_raincloud_figure_roi_x(
        df_part_all,
        df_group_used,
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="Ratio", hline_y=1.0, ylim=None),
        out_base,
        ROI_DEFS_DEFAULT,
        palette_choice="vibrant",
        run_label="unit-test",
        png_dpi=72,
        xlabel="ROI",
    )

    assert out_base.with_suffix(".png").exists()
    assert out_base.with_suffix(".pdf").exists()
