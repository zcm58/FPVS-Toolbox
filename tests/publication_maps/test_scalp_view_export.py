"""Late source and destination checks for exporting from an open 3D viewer."""

from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace

import matplotlib
from matplotlib.colors import Normalize
import numpy as np
import pytest

from Tools.Publication_Maps import scalp_view_export
from Tools.Publication_Maps.metrics import _capture_workbook_identity
from Tools.Publication_Maps.models import PublicationMapInputError, PublicationMetric, WorkbookEntry
from Tools.Publication_Maps.scalp_io import biosemi64_info
from Tools.Publication_Maps.scalp_scene import ScalpSurfacePanel


@pytest.fixture
def panel(tmp_path):
    inputs = tmp_path / "Excel"
    inputs.mkdir()
    workbook = inputs / "P01.xlsx"
    workbook.write_bytes(b"first result")
    entry = _capture_workbook_identity(WorkbookEntry("Shapes", "P01", workbook), cancel_check=None)
    return ScalpSurfacePanel(
        label="Shapes · BCA", metric=PublicationMetric.BCA, colorbar_label="Amplitude (µV)",
        data=np.zeros(64), info=biosemi64_info(), cmap=matplotlib.colormaps["viridis"], norm=Normalize(0, 1),
        extend="neither", missing_count=0, title="Shapes", input_root=inputs,
        output_root=tmp_path / "Figures", output_base_root=tmp_path / "Figures",
        source_workbooks=(entry,), project_root=None, release_fingerprint="",
    )


@pytest.mark.parametrize("changed", ["workbook", "release"])
def test_stale_view_keeps_both_original_figures(tmp_path, panel, changed, monkeypatch):
    panel.output_root.mkdir()
    target = panel.output_root / "shapes.png"
    originals = {target: b"old png", target.with_suffix(".pdf"): b"old pdf"}
    for path, data in originals.items():
        path.write_bytes(data)
    if changed == "workbook":
        panel.source_workbooks[0].path.write_bytes(b"updated result")
    else:
        panel = replace(panel, project_root=tmp_path, release_fingerprint="earlier receipt")
        monkeypatch.setattr(scalp_view_export, "_require_managed_publication_release",
                            lambda path: SimpleNamespace(final_release_receipt_fingerprint="new receipt"))
    with pytest.raises(PublicationMapInputError, match="changed"):
        scalp_view_export.export_camera_view(np.zeros((12, 18, 3)), panel, target, lambda: None)
    assert {p: p.read_bytes() for p in panel.output_root.iterdir()} == originals


@pytest.mark.parametrize("linked", ["output_root", "group_folder"])
def test_camera_export_rejects_implicit_link_outside_output_base(tmp_path, panel, linked):
    outside = tmp_path / "Other"
    outside.mkdir()
    project = tmp_path / "Project"
    base = project / "Figures"
    link = base if linked == "output_root" else base / "Group"
    link.parent.mkdir(parents=True)
    panel = replace(panel, project_root=project, output_root=link / "Views", output_base_root=base)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PublicationMapInputError, match="outside"):
        scalp_view_export.prepare_camera_export_folder(panel)
    with pytest.raises(PublicationMapInputError, match="outside"):
        scalp_view_export.export_camera_view(np.zeros((12, 18, 3)), panel, link / "view.png", lambda: None)
    assert list(outside.iterdir()) == []


def test_first_camera_export_creates_group_folder_below_project(tmp_path, panel):
    project = tmp_path / "Project"
    project.mkdir()
    panel = replace(panel, project_root=project, output_base_root=Path("Figures"),
                    output_root=Path("Figures/Control"))
    assert not (project / "Figures").exists()
    folder = scalp_view_export.prepare_camera_export_folder(panel)
    assert folder == project / "Figures" / "Control"
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_camera_default_folder_rejects_processed_input_tree(panel):
    invalid = panel.input_root / "Figures"
    with pytest.raises(ValueError, match="processed Excel input"):
        scalp_view_export.prepare_camera_export_folder(replace(panel, output_root=invalid))
    assert not invalid.exists()


def test_dotted_camera_view_name_preserves_other_session_files(panel):
    panel = replace(panel, title="Win $$")
    panel.output_root.mkdir()
    for extension in (".png", ".pdf"):
        (panel.output_root / ("session" + extension)).write_bytes(b"earlier view")
    target = panel.output_root / "session.2"
    png, pdf = scalp_view_export.camera_view_paths(target)
    assert png.name == "session.2.png" and pdf.name == "session.2.pdf"
    assert scalp_view_export.camera_view_paths(png) == scalp_view_export.camera_view_paths(pdf) == (png, pdf)
    paths = scalp_view_export.export_camera_view(np.zeros((12, 18, 3)), panel, target, lambda: None)
    assert set(paths) == {png, pdf}
    assert png.read_bytes().startswith(b"\x89PNG") and pdf.read_bytes().startswith(b"%PDF")
    assert all((panel.output_root / ("session" + ext)).read_bytes() == b"earlier view" for ext in (".png", ".pdf"))
