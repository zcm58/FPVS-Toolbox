"""Figure export for a camera view captured by the native scalp viewer."""

from __future__ import annotations

import textwrap
from pathlib import Path

from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure

from Main_App.exports.figure_style import (
    FIGURE_EXPORT_DPI, FIGURE_JOURNAL_TEXT_WIDTH_IN, apply_axis_text_style, figure_text_kwargs,
)
from Tools.Publication_Maps.metrics import _require_managed_publication_release, verify_publication_workbooks_unchanged
from Tools.Publication_Maps.models import PublicationMapInputError, PublicationMapRequest
from Tools.Publication_Maps.output_contract import PublicationArtifactTransaction, validate_output_root


VIEW_IMAGE_WIDTH_IN = FIGURE_JOURNAL_TEXT_WIDTH_IN * 0.76


def draw_view_scale(figure, axis, panel):
    bar = figure.colorbar(ScalarMappable(norm=panel.norm, cmap=panel.cmap), cax=axis, extend=panel.extend)
    bar.set_label(panel.colorbar_label, **figure_text_kwargs("axis_label"))
    apply_axis_text_style(axis)


def export_camera_view(image, panel, filename: Path, cancel_check) -> tuple[Path, ...]:
    """Publish the captured viewport with its original scale and editable PDF text."""
    cancel_check()
    filename = Path(filename).absolute()
    request = PublicationMapRequest(input_root=panel.input_root, output_root=filename.parent, conditions=())
    destination = validate_output_root(request)
    base = panel.output_base_root.absolute()
    if filename.parent.is_relative_to(base) and not destination.is_relative_to(base.resolve()):
        raise PublicationMapInputError("The selected folder points outside the Scalp Maps output directory.")
    title = textwrap.fill(panel.title, width=55)
    title_height = 0.18 + 0.22 * len(title.splitlines())
    note_height = 0.22 if panel.missing_count else 0
    image_height = VIEW_IMAGE_WIDTH_IN * image.shape[0] / image.shape[1]
    height = max(image_height + title_height + note_height + 0.18, 2.7)
    figure = Figure(figsize=(FIGURE_JOURNAL_TEXT_WIDTH_IN, height), dpi=FIGURE_EXPORT_DPI)
    try:
        figure.suptitle(title, y=1 - 0.08 / height, **figure_text_kwargs("condition_label"))
        bottom = (0.12 + note_height) / height
        plot_height = (height - title_height - note_height - 0.16) / height
        plot = figure.add_axes((0.025, bottom, 0.76, plot_height))
        plot.imshow(image, interpolation="none")
        plot.set_axis_off()
        scale = figure.add_axes((0.81, bottom + 0.1 * plot_height, 0.023, 0.8 * plot_height))
        draw_view_scale(figure, scale, panel)
        if panel.missing_count:
            figure.text(0.405, 0.10 / height, f"Missing montage values omitted: {panel.missing_count}",
                        ha="center", **figure_text_kwargs("annotation"))
        with PublicationArtifactTransaction(request) as transaction:
            for extension in (".png", ".pdf"):
                cancel_check()
                path = transaction.stage_path(filename.with_suffix(extension))
                figure.savefig(path, dpi=FIGURE_EXPORT_DPI)
            verify_publication_workbooks_unchanged(panel.source_workbooks, cancel_check=cancel_check)
            release = _require_managed_publication_release(panel.project_root)
            if release is not None and release.final_release_receipt_fingerprint != panel.release_fingerprint:
                raise PublicationMapInputError("The project's final QC release changed. Reopen the 3D viewer to export.")
            return transaction.commit(cancel_check=cancel_check)
    finally:
        figure.clear()
