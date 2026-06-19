"""Render FPVS stimulus sequence illustrations."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PIL import Image, ImageOps

from Main_App.exports.figure_style import FIGURE_EXPORT_DPI, figure_text_kwargs

SUPPORTED_IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
DEFAULT_IMAGE_COUNT = 5
DEFAULT_FIGURE_SIZE_IN = (13.333, 7.5)
DEFAULT_PNG_DPI = FIGURE_EXPORT_DPI
_CANVAS_WIDTH = 16.0
_CANVAS_HEIGHT = 9.0
_IMAGE_SIZE_UNITS = 2.28
_IMAGE_Y0 = 5.78
_IMAGE_CENTERS_X = (1.7, 4.7, 7.7, 10.7, 13.7)
_MIN_SOURCE_IMAGE_DPI = 500
_RATE_LABEL_X = 14.78
_WAVEFORM_END_X = 14.62
_ODDBALL_COLOR = "#FF0000"
_ODDBALL_FRAME_PAD = 0.11
_ODDBALL_FRAME_LINE_WIDTH_PT = 2.4
_RATE_LABEL_FONT_ROLE = "annotation"
_RATE_LABEL_FONT_SIZE_PT = 16
_TIMING_LINE_WIDTH_PT = 2.6


@dataclass(frozen=True)
class SequenceFigureSpec:
    """Inputs for rendering a fixed five-slot FPVS sequence figure."""

    image_paths: tuple[Path, ...]
    output_dir: Path
    basename: str = "fpvs_sequence_figure"
    base_frequency_hz: str = "6"
    oddball_frequency_hz: str = "1.2"
    png_dpi: int = DEFAULT_PNG_DPI
    figure_size_in: tuple[float, float] = DEFAULT_FIGURE_SIZE_IN
    export_svg: bool = True


@dataclass(frozen=True)
class SequenceFigureResult:
    """Result paths and warnings from a sequence figure render."""

    png_path: Path
    pdf_path: Path
    svg_path: Path | None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def output_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = [self.png_path, self.pdf_path]
        if self.svg_path is not None:
            paths.append(self.svg_path)
        return tuple(paths)


def render_sequence_figure(spec: SequenceFigureSpec) -> SequenceFigureResult:
    """Render a sequence illustration and save PNG/PDF outputs."""
    _validate_spec(spec)
    output_stem = _safe_stem(spec.basename)
    png_path = spec.output_dir / f"{output_stem}.png"
    pdf_path = spec.output_dir / f"{output_stem}.pdf"
    svg_path = spec.output_dir / f"{output_stem}.svg" if spec.export_svg else None

    images, warnings = _load_slot_images(spec)
    fig = _build_figure(spec, images)
    try:
        fig.savefig(png_path, dpi=spec.png_dpi, facecolor="white")
        fig.savefig(pdf_path, dpi=spec.png_dpi, facecolor="white")
        if svg_path is not None:
            fig.savefig(svg_path, dpi=spec.png_dpi, facecolor="white")
    finally:
        plt.close(fig)

    return SequenceFigureResult(
        png_path=png_path,
        pdf_path=pdf_path,
        svg_path=svg_path,
        warnings=tuple(warnings),
    )


def _validate_spec(spec: SequenceFigureSpec) -> None:
    if len(spec.image_paths) != DEFAULT_IMAGE_COUNT:
        raise ValueError(f"Select exactly {DEFAULT_IMAGE_COUNT} stimulus images.")
    if spec.png_dpi <= 0:
        raise ValueError("PNG DPI must be greater than zero.")
    if spec.figure_size_in[0] <= 0 or spec.figure_size_in[1] <= 0:
        raise ValueError("Figure size must be greater than zero.")
    if not spec.output_dir.exists() or not spec.output_dir.is_dir():
        raise ValueError("Select an existing output folder.")
    for path in spec.image_paths:
        if not path.exists() or not path.is_file():
            raise ValueError(f"Image does not exist: {path}")
        if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image format: {path.name}")


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "fpvs_sequence_figure"


def _load_slot_images(spec: SequenceFigureSpec) -> tuple[list[Image.Image], list[str]]:
    warnings: list[str] = []
    required_px = _required_source_pixels(spec)
    images: list[Image.Image] = []
    for index, path in enumerate(spec.image_paths, start=1):
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            short_side = min(image.size)
            if short_side < required_px:
                warnings.append(
                    f"Slot {index} source image is {image.size[0]}x{image.size[1]} px; "
                    f"about {required_px} px on the short side is recommended for "
                    f"{_MIN_SOURCE_IMAGE_DPI} DPI source imagery in the exported figure."
                )
            images.append(_center_crop_square(image))
    return images, warnings


def _required_source_pixels(spec: SequenceFigureSpec) -> int:
    width_in = spec.figure_size_in[0] * (_IMAGE_SIZE_UNITS / _CANVAS_WIDTH)
    return max(1, round(width_in * _MIN_SOURCE_IMAGE_DPI))


def _center_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _build_figure(spec: SequenceFigureSpec, images: Iterable[Image.Image]) -> Figure:
    fig = plt.figure(figsize=spec.figure_size_in, facecolor="white", constrained_layout=False)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, _CANVAS_WIDTH)
    ax.set_ylim(0, _CANVAS_HEIGHT)
    ax.set_axis_off()

    for index, (center_x, image) in enumerate(zip(_IMAGE_CENTERS_X, images), start=1):
        x0 = center_x - _IMAGE_SIZE_UNITS / 2
        x1 = center_x + _IMAGE_SIZE_UNITS / 2
        y0 = _IMAGE_Y0
        y1 = _IMAGE_Y0 + _IMAGE_SIZE_UNITS
        ax.imshow(image, extent=(x0, x1, y0, y1), interpolation="lanczos", zorder=2)
        if index == DEFAULT_IMAGE_COUNT:
            ax.add_patch(
                Rectangle(
                    (x0 - _ODDBALL_FRAME_PAD, y0 - _ODDBALL_FRAME_PAD),
                    _IMAGE_SIZE_UNITS + 2 * _ODDBALL_FRAME_PAD,
                    _IMAGE_SIZE_UNITS + 2 * _ODDBALL_FRAME_PAD,
                    fill=False,
                    linewidth=_ODDBALL_FRAME_LINE_WIDTH_PT,
                    edgecolor="#3E6B89",
                    zorder=3,
                )
            )

    _draw_stimulus_timing(ax, spec)
    return fig


def _draw_stimulus_timing(ax, spec: SequenceFigureSpec) -> None:
    line_color = "#202020"
    label_kwargs = _rate_label_kwargs(line_color)
    oddball_label_kwargs = _rate_label_kwargs(_ODDBALL_COLOR)
    pulse_y = 3.9
    pulse_top = 5.08
    pulse_half_width = 0.86
    baseline_start = 0.65
    baseline_end = _WAVEFORM_END_X

    pulse_edges = [
        (center_x - pulse_half_width, center_x + pulse_half_width)
        for center_x in _IMAGE_CENTERS_X
    ]
    _draw_square_wave(
        ax,
        pulse_edges=pulse_edges,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_y=pulse_y,
        peak_y=pulse_top,
        color=line_color,
    )

    ax.text(
        _RATE_LABEL_X,
        _midpoint(pulse_y, pulse_top),
        f"F = {spec.base_frequency_hz} Hz",
        ha="left",
        va="center",
        **label_kwargs,
    )

    oddball_y = 1.32
    oddball_top = 2.72
    _draw_square_wave(
        ax,
        pulse_edges=[pulse_edges[-1]],
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_y=oddball_y,
        peak_y=oddball_top,
        color=_ODDBALL_COLOR,
    )
    ax.text(
        _RATE_LABEL_X,
        _midpoint(oddball_y, oddball_top),
        f"f = {spec.oddball_frequency_hz} Hz",
        ha="left",
        va="center",
        **oddball_label_kwargs,
    )


def _draw_square_wave(
    ax,
    *,
    pulse_edges: list[tuple[float, float]],
    baseline_start: float,
    baseline_end: float,
    baseline_y: float,
    peak_y: float,
    color: str,
) -> None:
    low_segments: list[tuple[float, float]] = [(baseline_start, pulse_edges[0][0])]
    low_segments.extend(
        (previous_right, next_left)
        for (_, previous_right), (next_left, _) in zip(pulse_edges, pulse_edges[1:])
    )
    low_segments.append((pulse_edges[-1][1], baseline_end))

    for segment_start, segment_end in low_segments:
        ax.plot(
            [segment_start, segment_end],
            [baseline_y, baseline_y],
            color=color,
            linewidth=_TIMING_LINE_WIDTH_PT,
        )
    for left, right in pulse_edges:
        ax.plot([left, left], [baseline_y, peak_y], color=color, linewidth=_TIMING_LINE_WIDTH_PT)
        ax.plot([left, right], [peak_y, peak_y], color=color, linewidth=_TIMING_LINE_WIDTH_PT)
        ax.plot([right, right], [peak_y, baseline_y], color=color, linewidth=_TIMING_LINE_WIDTH_PT)


def _midpoint(first: float, second: float) -> float:
    return (first + second) / 2


def _rate_label_kwargs(color: str) -> dict[str, object]:
    kwargs = figure_text_kwargs(_RATE_LABEL_FONT_ROLE)
    kwargs["fontsize"] = _RATE_LABEL_FONT_SIZE_PT
    kwargs["color"] = color
    return kwargs
