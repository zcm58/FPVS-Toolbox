from pathlib import Path
from types import SimpleNamespace

import pytest

from Tools.Plot_Generator import export_plan
from Tools.Plot_Generator.export_plan import inspect_destinations, publish_figure_pair
from Tools.Plot_Generator.render_naming import claim_figure_stem


def _render(png, pdf):
    png.write_bytes(b"new png")
    pdf.write_bytes(b"new pdf")


def _old_pair(root, stem="A - ROI"):
    png, pdf = root / f"{stem}.png", root / f"{stem}.pdf"
    png.write_bytes(b"old png")
    pdf.write_bytes(b"old pdf")
    return png, pdf


def test_preflight_is_read_only_and_keep_both_changes_only_collisions(tmp_path):
    old = _old_pair(tmp_path)
    identities = (("A", "ROI", ""), ("B", "ROI", ""))
    choices = inspect_destinations(str(tmp_path), identities)
    assert len(choices.collisions) == 1
    assert set(tmp_path.iterdir()) == set(old)
    assert [item.png_path.name for item in choices.replace] == ["A - ROI.png", "B - ROI.png"]
    assert [item.png_path.name for item in choices.keep_both] == ["A - ROI (2).png", "B - ROI.png"]
    for item in choices.keep_both:
        assert publish_figure_pair(item, _render, lambda: False)
    assert [path.read_bytes() for path in old] == [b"old png", b"old pdf"]
    assert (tmp_path / "A - ROI (2).pdf").read_bytes() == b"new pdf"


@pytest.mark.parametrize("existing", ["png", "pdf", "both"])
def test_replace_handles_complete_or_partial_existing_pair(tmp_path, existing):
    for extension in ("png", "pdf"):
        if existing in (extension, "both"):
            (tmp_path / f"A - ROI.{extension}").write_bytes(b"old")
    choices = inspect_destinations(str(tmp_path), (("A", "ROI", ""),))
    assert len(choices.collisions) == 1
    assert publish_figure_pair(choices.replace[0], _render, lambda: False)
    assert [path.read_bytes() for path in choices.replace[0].paths] == [b"new png", b"new pdf"]


def test_render_failure_preserves_both_old_files(tmp_path):
    old = _old_pair(tmp_path)
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]

    def broken(png, pdf):
        png.write_bytes(b"new png")
        raise OSError("PDF render failed")

    with pytest.raises(OSError, match="PDF render failed"):
        publish_figure_pair(destination, broken, lambda: False)
    assert [path.read_bytes() for path in old] == [b"old png", b"old pdf"]
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize("replace_existing", [True, False])
def test_second_publication_failure_rolls_back_first(tmp_path, monkeypatch, replace_existing):
    old = _old_pair(tmp_path) if replace_existing else ()
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]
    original_replace = export_plan.os.replace
    original_open = Path.open

    def replace(source, target):
        if Path(source).name == destination.paths[1].name:
            raise OSError("PDF commit failed")
        return original_replace(source, target)

    def open_path(path, mode="r", *args, **kwargs):
        if path == destination.paths[1] and mode == "xb":
            raise OSError("PDF commit failed")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(export_plan.os, "replace", replace)
    monkeypatch.setattr(Path, "open", open_path)
    with pytest.raises(OSError, match="PDF commit failed"):
        publish_figure_pair(destination, _render, lambda: False)
    assert set(tmp_path.iterdir()) == set(old)
    if old:
        assert [path.read_bytes() for path in old] == [b"old png", b"old pdf"]


def test_cancel_after_render_preserves_old_pair(tmp_path):
    old = _old_pair(tmp_path)
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]
    assert not publish_figure_pair(destination, _render, lambda: True)
    assert [path.read_bytes() for path in old] == [b"old png", b"old pdf"]


@pytest.mark.parametrize("existing", [True, False])
def test_files_changed_after_approval_are_not_overwritten(tmp_path, existing):
    if existing:
        _old_pair(tmp_path)
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]
    destination.png_path.write_bytes(b"external change after approval")
    with pytest.raises(FileExistsError, match="changed after export confirmation"):
        publish_figure_pair(destination, _render, lambda: False)
    assert destination.png_path.read_bytes() == b"external change after approval"


def test_names_are_unique_across_batch_and_keep_both_reserves_all_pairs(tmp_path):
    _old_pair(tmp_path, "A_B - ROI")
    choices = inspect_destinations(str(tmp_path), (("A/B", "ROI", ""), ("A:B", "ROI", "")))
    names = [item.png_path.name for item in choices.keep_both]
    assert len(set(names)) == 2
    owner = SimpleNamespace(_figure_export_plan=choices.keep_both)
    assert claim_figure_stem(owner, base_title="A/B", roi="ROI") == choices.keep_both[0].png_path.stem
    with pytest.raises(ValueError, match="not in the confirmed"):
        claim_figure_stem(owner, base_title="Unapproved", roi="ROI")


def test_cancelled_preflight_never_creates_output_folder(tmp_path):
    target = tmp_path / "new"
    assert inspect_destinations(str(target), (("A", "ROI", ""),), lambda: True) is None
    assert not target.exists()


@pytest.mark.parametrize(
    "identities",
    [
        (("Faces", "ROI", ""), ("faces", "ROI", "")),
        (("Faces", "LOT", ""), ("Faces", "lot", "")),
    ],
)
def test_case_only_names_get_distinct_approved_destinations(tmp_path, identities):
    choices = inspect_destinations(str(tmp_path), identities)
    names = [item.png_path.name.casefold() for item in choices.replace]
    assert len(set(names)) == 2
    owner = SimpleNamespace(_figure_export_plan=choices.replace)
    for item in choices.replace:
        title, roi, suffix = item.identity
        assert claim_figure_stem(owner, base_title=title, roi=roi, suffix=suffix) == item.png_path.stem
        assert publish_figure_pair(item, _render, lambda: False)
    assert len(list(tmp_path.iterdir())) == 4


def test_missing_staged_pdf_does_not_leave_an_empty_output(tmp_path):
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]
    with pytest.raises(OSError, match="both PNG and PDF"):
        publish_figure_pair(destination, lambda png, _pdf: png.write_bytes(b"png"), lambda: False)
    assert list(tmp_path.iterdir()) == []


def test_rollback_failure_keeps_recovery_copy(tmp_path, monkeypatch):
    _old_pair(tmp_path)
    destination = inspect_destinations(str(tmp_path), (("A", "ROI", ""),)).replace[0]
    original_replace = export_plan.os.replace

    def replace(source, target):
        if Path(source).name in {destination.paths[1].name, "previous.png"}:
            raise PermissionError("File is locked")
        return original_replace(source, target)

    monkeypatch.setattr(export_plan.os, "replace", replace)
    with pytest.raises(OSError, match="Recovery files are preserved"):
        publish_figure_pair(destination, _render, lambda: False)
    recovery = next(tmp_path.glob(".snr-export-*/previous.png"))
    assert recovery.read_bytes() == b"old png"
    assert destination.paths[1].read_bytes() == b"old pdf"
