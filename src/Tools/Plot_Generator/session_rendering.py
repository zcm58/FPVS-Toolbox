"""Publication-style repeated-session SNR figure rendering."""

from __future__ import annotations

import math
import time
from typing import Sequence

import numpy as np

from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    FIGURE_STANDARD_LANDSCAPE_SIZE_IN,
    apply_axis_text_style,
    figure_legend_kwargs,
    figure_text_kwargs,
)
from Tools.Plot_Generator.render_naming import (
    SESSION_COMPARISON_SUFFIX,
    claim_figure_stem,
)
from Tools.Plot_Generator.rendering import (
    _PNG_COMPRESSION_LEVEL,
    _add_reference_lines,
    _closest_frequency_indices,
    plt,
)
from Tools.Plot_Generator.session_aggregation import SessionSNRAggregation
from Tools.Plot_Generator.session_controls import FIXED_ORDER_CAVEAT


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
            tick_start = math.ceil(self.x_min)
            tick_end = math.floor(self.x_max) + 1
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
                    ax.plot(frequency_array, values, color=color, label=label)
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
                ax.set_xlim(self.x_min, self.x_max)
                ax.set_ylim(self.y_min, self.y_max)
                ax.set_xticks(range(tick_start, tick_end))
                _add_reference_lines(
                    ax,
                    x_min=self.x_min,
                    x_max=self.x_max,
                    y_min=self.y_min,
                    y_max=self.y_max,
                    tick_start=tick_start,
                    tick_end=tick_end,
                )
                if not self.use_matlab_style:
                    ax.axhline(1.0, color="gray", linestyle="--", linewidth=1)
                ax.set_ylabel(self.ylabel, **figure_text_kwargs("axis_label"))
                ax.set_xlabel(self.xlabel, **figure_text_kwargs("axis_label"))
                ax.legend(loc="upper right", frameon=True, **figure_legend_kwargs())
                ax.grid(axis="y", linestyle=":", linewidth=0.8, color="gray")
                apply_axis_text_style(ax)

            figure_title = self.title or aggregation.condition
            fig.suptitle(
                f"{figure_title} — {roi}",
                **figure_text_kwargs("panel_label"),
            )
            fig.text(
                0.5,
                0.012,
                FIXED_ORDER_CAVEAT,
                ha="center",
                va="bottom",
                wrap=True,
                **figure_text_kwargs("small"),
            )
            fig.tight_layout(rect=(0.0, 0.055, 1.0, 0.95))
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
                fig.savefig(
                    png_path,
                    dpi=FIGURE_EXPORT_DPI,
                    pil_kwargs={"compress_level": _PNG_COMPRESSION_LEVEL},
                )
                fig.savefig(pdf_path, format="pdf", dpi=FIGURE_EXPORT_DPI)
            finally:
                self._mark_timing("file_save", save_started)
                plt.close(fig)
            self._record_figure_pair(png_path=png_path, pdf_path=pdf_path)
            self._emit(f"Saved {png_path.name}")


__all__ = ["SessionPlotRenderingMixin"]
