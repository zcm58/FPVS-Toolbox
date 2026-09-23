"""Measured legends outside condition-overlay data axes."""

from __future__ import annotations

import textwrap

from matplotlib.font_manager import FontProperties

from Main_App.exports.figure_style import figure_legend_kwargs


def _wrap_legend_label(label, renderer, font, maximum_width):
    """Wrap to measured display width, including unusually long single words."""

    lines = []
    for paragraph in label.splitlines() or [""]:
        remaining = paragraph
        while remaining:
            if renderer.get_text_width_height_descent(remaining, font, False)[0] <= maximum_width:
                lines.append(remaining)
                break
            low, high = 1, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                width = renderer.get_text_width_height_descent(remaining[:middle], font, False)[0]
                if width <= maximum_width:
                    low = middle
                else:
                    high = middle - 1
            chunk = textwrap.wrap(remaining, width=low, break_long_words=True, break_on_hyphens=False)[0]
            lines.append(chunk)
            remaining = remaining[len(chunk):].lstrip()
    return "\n".join(lines)


def add_condition_overlay_legend(fig, ax) -> None:
    """Grow below the plot to fit a two-column, full-size publication legend."""

    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    # Finish the data area first; its physical dimensions are preserved below.
    fig.tight_layout()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    width, height = fig.get_size_inches()
    position = ax.get_position().frozen()
    font = FontProperties(**figure_legend_kwargs()["prop"])
    # Reserve each column's handle, text padding, and the inter-column gap.
    maximum_width = ((width - 0.4) / 2 - 0.65) * fig.dpi
    wrapped = [_wrap_legend_label(label, renderer, font, maximum_width) for label in labels]
    legend = fig.legend(
        handles, wrapped, ncol=2, loc="lower center", frameon=True,
        borderaxespad=0, columnspacing=1.5, **figure_legend_kwargs(),
    )
    legend_height = legend.get_window_extent(renderer).height / fig.dpi
    gap, margin = 0.08, 0.15
    extra_height = gap + legend_height + margin
    new_height = height + extra_height
    fig.set_size_inches(width, new_height)
    ax.set_position([
        position.x0, (position.y0 * height + extra_height) / new_height,
        position.width, position.height * height / new_height,
    ])
    legend.set_bbox_to_anchor((0.5, margin / new_height), transform=fig.transFigure)
