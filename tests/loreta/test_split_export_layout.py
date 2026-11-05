"""Long comparison labels must not overlap hemisphere headings or anatomy."""

from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from Tools.LORETA_Visualizer import renderer


@pytest.mark.parametrize("scale", [0.5, 1.0, 1.7])
def test_long_comparison_header_fits_and_separates_all_text_bounds(scale):
    width = round(renderer.DEFAULT_SPLIT_FIGURE_WIDTH * scale)
    draw = ImageDraw.Draw(Image.new("RGBA", (width, width)))
    label = "A: Words (paired n = 3) · Baseline-corrected amplitude"
    layout = renderer._split_figure_header_layout(
        draw, label, width=width, scale_factor=scale,
        show_condition_label=True, show_hemisphere_labels=True,
    )
    title_font = renderer._pil_font("panel_label", scale_factor=scale,
                                    point_size=renderer.SPLIT_FIGURE_CONDITION_LABEL_SIZE_PT, bold=True)
    heading_font = renderer._pil_font("axis_label", scale_factor=scale,
                                      point_size=renderer.SPLIT_FIGURE_HEMISPHERE_LABEL_SIZE_PT, bold=True)
    assert len(layout.title_lines) >= 2
    previous_bottom = 0.0
    for text, y in layout.title_lines:
        bounds = draw.textbbox((width / 2, y), text, font=title_font, anchor="mm")
        assert 0.0 <= bounds[0] < bounds[2] <= width
        assert bounds[1] > previous_bottom
        previous_bottom = bounds[3]
    for x, text in ((width / 4, "Left"), (3 * width / 4, "Right")):
        bounds = draw.textbbox((x, layout.hemisphere_y), text, font=heading_font, anchor="mm")
        assert bounds[1] > previous_bottom
        assert bounds[3] < layout.height


def test_label_wrap_preserves_words_and_bounds_unbroken_identifiers():
    draw = ImageDraw.Draw(Image.new("RGBA", (1950, 1000)))
    font = renderer._pil_font("panel_label", scale_factor=1.0, point_size=14, bold=True)
    label = "Repeated letters: Words and faces " + "A" * 90
    lines = renderer._wrap_split_figure_label(draw, label, font, maximum_width=900)
    assert "".join(lines).replace(" ", "") == label.replace(" ", "")
    assert all(draw.textlength(line, font=font) <= 900 for line in lines)


def test_stacked_comparisons_reserve_identical_header_height_for_equal_brain_scale(monkeypatch):
    panels = [(SimpleNamespace(label=label, scalar_range=(-1.0, 1.0),
                               left_state=SimpleNamespace(signed_values=True)), {}, {})
              for label in ("A: Words", "B: A much longer condition label with cohort details · Baseline-corrected amplitude")]
    calls = []
    monkeypatch.setattr(renderer, "_draw_split_figure_panel", lambda *_args, **kwargs: calls.append(kwargs))
    renderer._render_publication_split_image(panels, width=1950, height=2025)
    assert calls[0]["header_height"] == calls[1]["header_height"]
    assert calls[0]["header_height"] >= max(call["header_layout"].height for call in calls)
    assert calls[0]["panel_height"] == calls[1]["panel_height"]
