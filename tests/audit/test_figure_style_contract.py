from __future__ import annotations

from tests import repo_root

from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI,
    FIGURE_FONT_FAMILY,
    FIGURE_OUTPUT_FORMATS,
    FIGURE_PANEL_LABEL_SIZE_PT,
    FIGURE_SMALL_TEXT_MIN_SIZE_PT,
    FIGURE_SUBSCRIPT_SUPERSCRIPT_MIN_SIZE_PT,
    FIGURE_TEXT_SIZE_PT,
    figure_text_kwargs,
)

FIGURE_RENDERER_FILES = (
    "src/Tools/Sequence_Figure/renderer.py",
    "src/Tools/Plot_Generator/rendering.py",
    "src/Tools/Publication_Maps/rendering.py",
    "src/Tools/Ratio_Calculator/plots.py",
    "src/Tools/Individual_Detectability/core.py",
    "src/Tools/LORETA_Visualizer/renderer.py",
)


def test_shared_figure_style_matches_elsevier_publication_contract() -> None:
    axis_kwargs = figure_text_kwargs("axis_label")
    legend_kwargs = figure_text_kwargs("legend")
    panel_kwargs = figure_text_kwargs("panel_label")
    small_kwargs = figure_text_kwargs("small")

    assert FIGURE_EXPORT_DPI == 600
    assert FIGURE_OUTPUT_FORMATS == ("pdf", "png")
    assert FIGURE_FONT_FAMILY == "Arial"
    assert axis_kwargs["fontsize"] == FIGURE_TEXT_SIZE_PT == 10
    assert legend_kwargs["fontsize"] == FIGURE_TEXT_SIZE_PT
    assert panel_kwargs["fontsize"] == FIGURE_PANEL_LABEL_SIZE_PT == 12
    assert panel_kwargs["fontweight"] == "bold"
    assert small_kwargs["fontsize"] == FIGURE_SMALL_TEXT_MIN_SIZE_PT == 7
    assert FIGURE_SUBSCRIPT_SUPERSCRIPT_MIN_SIZE_PT == 7


def test_figure_renderers_do_not_import_gui_typography() -> None:
    blocked_tokens = (
        "Main_App.gui.typography",
        "Main_App.gui.components import matplotlib_font_kwargs",
        "matplotlib_font_kwargs",
        "FONT_ROLES",
    )

    root = repo_root()
    offenders: list[str] = []
    for rel_path in FIGURE_RENDERER_FILES:
        text = (root / rel_path).read_text(encoding="utf-8")
        for token in blocked_tokens:
            if token in text:
                offenders.append(f"{rel_path}: {token}")

    assert offenders == []
