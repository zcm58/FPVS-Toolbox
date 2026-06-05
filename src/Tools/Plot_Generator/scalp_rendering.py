"""Scalp input preparation and topomap rendering helpers."""

from __future__ import annotations

from typing import Dict, List

import matplotlib
from matplotlib.colors import TwoSlopeNorm
import mne
import numpy as np

from Tools.Publication_Maps.colormaps import scalp_colormap
from Tools.Plot_Generator.scalp_utils import ScalpInputs, prepare_scalp_inputs

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_SCALP_CMAP = scalp_colormap(name="FpvsPlotGeneratorScalpSequential")


class PlotScalpRenderingMixin:
    """Worker-state helpers for scalp map input preparation and rendering."""

    def _scalp_oddball_frequencies(self) -> List[float]:
        return list(self.oddballs)

    def _prepare_scalp_inputs(
        self, subject_maps: Dict[str, Dict[str, float]]
    ) -> ScalpInputs | None:
        if not self.include_scalp_maps:
            return None

        inputs = self._timed_call(
            "scalp_prepare",
            lambda: prepare_scalp_inputs(
                subject_maps,
                self.roi_map.get(self.selected_roi, []),
            ),
        )
        if inputs is None and subject_maps:
            self._emit("No scalp map data available for plotting.")
        return inputs

    def _format_scalp_title(self, template: str, condition: str, roi: str) -> str:
        try:
            return template.format(condition=condition, roi=roi)
        except Exception:
            if not self._scalp_title_warned:
                self._emit(
                    "Invalid scalp title template detected. Reverting to default.",
                    0,
                    0,
                )
                self._scalp_title_warned = True
            return f"{condition} {roi} scalp map"

    def _plot_scalp_map(
        self,
        ax: plt.Axes,
        scalp_inputs: ScalpInputs,
        title: str,
        *,
        cax: plt.Axes | None = None,
    ) -> None:
        """Render a scalp topomap for the provided electrode data."""
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        vmin = self.scalp_vmin
        vmax = self.scalp_vmax

        if vmin is None or vmax is None:
            data = np.asarray(scalp_inputs.data, dtype=float)
            max_abs = float(np.nanmax(np.abs(data))) if data.size else 0.0
            if max_abs == 0:
                max_abs = 1.0
            vmin = -max_abs
            vmax = max_abs

        vlim = (float(vmin), float(vmax))
        norm: TwoSlopeNorm | None = None
        use_cnorm = vlim[0] < 0 < vlim[1]
        if use_cnorm:
            norm = TwoSlopeNorm(vmin=vlim[0], vcenter=0.0, vmax=vlim[1])

        im = None
        if use_cnorm and norm is not None:
            try:
                im, _ = mne.viz.plot_topomap(
                    scalp_inputs.data,
                    scalp_inputs.info,
                    axes=ax,
                    cmap=_SCALP_CMAP,
                    cnorm=norm,
                    contours=0,
                    sensors=True,
                    show=False,
                    outlines="head",
                )
            except TypeError:
                use_cnorm = False
                lim = max(abs(vlim[0]), abs(vlim[1]))
                vlim = (-lim, lim)

        if im is None:
            try:
                im, _ = mne.viz.plot_topomap(
                    scalp_inputs.data,
                    scalp_inputs.info,
                    axes=ax,
                    cmap=_SCALP_CMAP,
                    vlim=vlim,
                    contours=0,
                    sensors=True,
                    show=False,
                    outlines="head",
                )
            except TypeError:
                try:
                    im, _ = mne.viz.plot_topomap(
                        scalp_inputs.data,
                        scalp_inputs.info,
                        axes=ax,
                        cmap=_SCALP_CMAP,
                        vmin=vlim[0],
                        vmax=vlim[1],
                        contours=0,
                        sensors=True,
                        show=False,
                        outlines="head",
                    )
                except TypeError:
                    lim = max(abs(vlim[0]), abs(vlim[1]))
                    im, _ = mne.viz.plot_topomap(
                        scalp_inputs.data,
                        scalp_inputs.info,
                        axes=ax,
                        cmap=_SCALP_CMAP,
                        vmin=-lim,
                        vmax=lim,
                        contours=0,
                        sensors=True,
                        show=False,
                        outlines="head",
                    )

        if cax is None:
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4.5%", pad=0.08)

        cbar = plt.colorbar(im, cax=cax)
        cbar.ax.set_ylabel("uV")
        cbar.ax.yaxis.set_label_position("right")
        cbar.ax.yaxis.set_ticks_position("right")

        ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
        ax.set_anchor("C")
