"""Publication-style repeated-session SNR figure rendering."""

from __future__ import annotations

import time
from typing import Sequence

import numpy as np

from Main_App.exports.figure_style import (
    FIGURE_STANDARD_LANDSCAPE_SIZE_IN,
    figure_legend_kwargs,
    figure_text_kwargs,
)
from Tools.Plot_Generator.render_naming import (
    SESSION_COMPARISON_SUFFIX,
    claim_figure_stem,
)
from Tools.Plot_Generator.rendering import (
    _closest_frequency_indices,
    plt,
)
from Tools.Plot_Generator.session_aggregation import SessionSNRAggregation
from Tools.Plot_Generator.export_plan import save_worker_figure_pair
from Tools.Plot_Generator.spectrum_style import style_spectrum_axis

FIXED_ORDER_CAVEAT = (
    "Phase is confounded with visit order and elapsed time because every participant "
    "completed the sessions in the same order."
)


def _numeric_curve(values: Sequence[float | None]) -> np.ndarray:
    return np.asarray(
        [float(value) if value is not None else np.nan for value in values],
        dtype=float,
    )


class SessionPlotRenderingMixin:
    """Render stable-group facets with canonical session overlays."""

    def _plot_session_comparison(
        self,
        frequencies: Sequence[float],
        aggregation: SessionSNRAggregation,
    ) -> None:
        frequency_array = np.asarray(frequencies, dtype=float)
        oddball_indices = _closest_frequency_indices(
            frequency_array,
            self._visible_oddball_frequencies(frequencies),
        )
        roi_names = tuple(dict.fromkeys(cell.roi for cell in aggregation.cells))
        colors = (self.stem_color, self.stem_color_b)
        group_labels = {
            cell.group_id.casefold(): cell.group_label for cell in aggregation.cells
        }
        for roi in roi_names:
            if self._cancellation_checkpoint():
                return
            render_started = time.perf_counter()
            row_count = len(aggregation.group_ids)
            standard_width, standard_height = FIGURE_STANDARD_LANDSCAPE_SIZE_IN
            fig, axes = plt.subplots(
                row_count,
                1,
                squeeze=False,
                figsize=(standard_width, standard_height * row_count),
            )
            for row, group_id in enumerate(aggregation.group_ids):
                ax = axes[row, 0]
                ax.set_title(
                    group_labels.get(group_id.casefold(), group_id),
                    **figure_text_kwargs("panel_label"),
                )
                for session_index, session_id in enumerate(aggregation.session_ids):
                    cell = aggregation.cell(group_id, session_id, roi)
                    values = _numeric_curve(cell.plotted_values)
                    label = (
                        f"{cell.session_label} (Visit {cell.visit_index}, "
                        f"n={cell.participant_n_roi})"
                    )
                    color = colors[session_index % len(colors)]
                    ax.plot(frequency_array, values, color=color, label=label, linewidth=0.8)
                    if oddball_indices.size:
                        ax.scatter(
                            frequency_array[oddball_indices],
                            values[oddball_indices],
                            color=color,
                            edgecolor="black",
                            marker="o" if session_index == 0 else "^",
                            s=22,
                            zorder=4,
                        )
                style_spectrum_axis(ax, self, self._visible_oddball_frequencies(frequencies))
                ax.legend(loc="upper right", frameon=False, **figure_legend_kwargs())

            figure_title = self.title or aggregation.condition
            fig.text(
                0.5,
                0.012,
                FIXED_ORDER_CAVEAT,
                ha="center",
                va="bottom",
                wrap=True,
                **figure_text_kwargs("small"),
            )
            fig.tight_layout(rect=(0.0, 0.055, 1.0, 1.0))
            if self._cancellation_checkpoint():
                plt.close(fig)
                return
            figure_stem = claim_figure_stem(
                self,
                base_title=figure_title,
                roi=roi,
                suffix=SESSION_COMPARISON_SUFFIX,
            )
            png_path = self.out_dir / f"{figure_stem}.png"
            pdf_path = png_path.with_suffix(".pdf")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            self._mark_timing("plot_render", render_started)
            save_started = time.perf_counter()
            try:
                if not save_worker_figure_pair(self, fig, png_path, pdf_path):
                    return
            finally:
                self._mark_timing("file_save", save_started)
                plt.close(fig)
            self._record_figure_pair(png_path=png_path, pdf_path=pdf_path)
            self._emit(f"Saved {png_path.name}")


__all__ = ["SessionPlotRenderingMixin"]
