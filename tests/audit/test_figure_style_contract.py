from __future__ import annotations

import importlib.util
import os
import sys

from PIL import Image
import pytest

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
from Main_App.exports.table_style import (
    TABLE_BODY_FONT_SIZE_PX,
    TABLE_FONT_FAMILY_CSS,
    TABLE_HEADER_FONT_SIZE_PX,
    table_font_size_px,
)

FIGURE_RENDERER_FILES = (
    "src/Tools/Free_Harmonic_Clustering/render_cluster_maps.py",
    "src/Tools/Sequence_Figure/renderer.py",
    "src/Tools/Plot_Generator/rendering.py",
    "src/Tools/Publication_Maps/rendering.py",
    "src/Tools/Publication_Maps/session_rendering.py",
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


def test_publication_table_style_is_gui_neutral() -> None:
    exporter = (
        repo_root()
        / ".agents"
        / "skills"
        / "publication-table-export"
        / "scripts"
        / "export_publication_table.py"
    ).read_text(encoding="utf-8")

    assert "Main_App.exports.table_style" in exporter
    assert "Main_App.gui.typography" not in exporter
    assert "Main_App.gui.style_tokens" not in exporter
    assert TABLE_FONT_FAMILY_CSS == '"Segoe UI", Arial, sans-serif'
    assert table_font_size_px("header") == TABLE_HEADER_FONT_SIZE_PX == 16
    assert table_font_size_px("body") == TABLE_BODY_FONT_SIZE_PX == 14


@pytest.fixture
def export_publication_table(tmp_path, monkeypatch):
    exporter_path = (
        repo_root()
        / ".agents"
        / "skills"
        / "publication-table-export"
        / "scripts"
        / "export_publication_table.py"
    )
    spec = importlib.util.spec_from_file_location("publication_table_export_test", exporter_path)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, exporter)
    spec.loader.exec_module(exporter)

    source = tmp_path / "source.csv"
    source.write_text("Condition,Mean\nFaces,1.25\nWords,2.50\n", encoding="utf-8")

    def export(project_root):
        return exporter.main([
            "--project-root",
            str(project_root),
            "--input",
            str(source),
            "--output-name",
            "summary",
        ])

    return export


def test_publication_table_export_retains_svg_and_600_dpi_png(tmp_path, export_publication_table) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    result = export_publication_table(project_root)

    output_dir = project_root / "9 - Tables"
    svg_path = output_dir / "summary.svg"
    png_path = output_dir / "summary.png"
    assert result == 0
    assert svg_path.is_file()
    assert png_path.is_file()
    assert "Main_App.gui" not in svg_path.read_text(encoding="utf-8")
    with Image.open(png_path) as image:
        dpi = image.info.get("dpi")
        assert dpi is not None
        assert dpi[0] == pytest.approx(600, abs=1)
        assert dpi[1] == pytest.approx(600, abs=1)


def test_publication_table_export_rejects_redirected_table_directory(tmp_path, export_publication_table) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    output_dir = project_root / "9 - Tables"
    try:
        output_dir.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows directory symlink privileges unavailable")
        raise

    with pytest.raises(SystemExit, match="Publication table directory must stay"):
        export_publication_table(project_root)

    assert list(outside.iterdir()) == []


def test_publication_table_export_rejects_linked_output_before_writing(tmp_path, export_publication_table) -> None:
    project_root = tmp_path / "project"
    output_dir = project_root / "9 - Tables"
    output_dir.mkdir(parents=True)
    outside = tmp_path / "existing.png"
    outside.write_bytes(b"outside content")
    png_path = output_dir / "summary.png"
    os.link(outside, png_path)
    svg_path = output_dir / "summary.svg"
    svg_path.write_bytes(b"previous SVG")

    with pytest.raises(OSError, match="Refusing a linked or non-regular file"):
        export_publication_table(project_root)

    assert outside.read_bytes() == b"outside content"
    assert png_path.samefile(outside)
    assert svg_path.read_bytes() == b"previous SVG"
    assert not (output_dir / "summary.html").exists()
