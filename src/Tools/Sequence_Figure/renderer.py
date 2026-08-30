"""Render FPVS stimulus sequence illustrations."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import textwrap
from pathlib import Path
from typing import Iterable, TypeAlias

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle
from PIL import Image, ImageOps

from Main_App.exports.figure_style import FIGURE_EXPORT_DPI, figure_text_kwargs

SUPPORTED_IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
DEFAULT_IMAGE_COUNT = 5
DEFAULT_CONDITION_COUNT = 3
MAX_CONDITION_COUNT = 4
MAX_CONDITION_LABEL_LENGTH = 24
DEFAULT_ODDBALL_CYCLES = 2
DEFAULT_FIGURE_SIZE_IN = (13.333, 7.5)
DEFAULT_PNG_DPI = FIGURE_EXPORT_DPI
_CANVAS_WIDTH = 16.0
_CANVAS_HEIGHT = 9.0
_IMAGE_SIZE_UNITS = 0.92
_FOUR_CONDITION_IMAGE_SIZE_UNITS = 0.76
_CONDITION_LABEL_X = 1.65
_SEQUENCE_START_X = 2.25
_SEQUENCE_END_X = 13.45
_GRID_TOP_CENTER_Y = 7.55
_GRID_BOTTOM_CENTER_Y = 5.2
_GRID_BOTTOM_CENTER_Y_FOUR_ROWS = 4.85
_MIN_SOURCE_IMAGE_DPI = 500
_RATE_LABEL_X = 14.38
_WAVEFORM_END_X = 14.18
_BASE_COLOR = "#3E6B89"
_BASE_FRAME_COLOR = "#6F8EA5"
_ODDBALL_COLOR = "#FF0000"
_ODDBALL_FRAME_COLOR = "#C94C4C"
_GRAYSCALE_BASE_COLOR = "#202020"
_GRAYSCALE_ODDBALL_COLOR = "#666666"
_ODDBALL_FRAME_LINE_WIDTH_PT = 2.4
_BASE_FRAME_LINE_WIDTH_PT = 1.4
_RATE_LABEL_FONT_ROLE = "annotation"
_RATE_LABEL_FONT_SIZE_PT = 16
_TIMING_LINE_WIDTH_PT = 2.6

ConditionImagePaths: TypeAlias = tuple[Path, ...]
SequenceImagePaths: TypeAlias = tuple[ConditionImagePaths, ...]


@dataclass(frozen=True)
class SequenceFigureSpec:
    """Inputs for rendering a bounded FPVS condition sequence figure."""

    image_paths: SequenceImagePaths | tuple[Path, ...]
    output_dir: Path
    basename: str = "fpvs_sequence_figure"
    base_frequency_hz: str = "6"
    oddball_frequency_hz: str = "1.2"
    png_dpi: int = DEFAULT_PNG_DPI
    figure_size_in: tuple[float, float] = DEFAULT_FIGURE_SIZE_IN
    export_svg: bool = True
    condition_labels: tuple[str, ...] = ()
    grayscale_safe: bool = False
    transparent_pdf: bool = False


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
        fig.savefig(png_path, dpi=spec.png_dpi, facecolor="white", transparent=False)
        fig.savefig(
            pdf_path,
            dpi=spec.png_dpi,
            facecolor="none" if spec.transparent_pdf else "white",
            transparent=spec.transparent_pdf,
        )
        if svg_path is not None:
            fig.savefig(svg_path, dpi=spec.png_dpi, facecolor="white", transparent=False)
    finally:
        plt.close(fig)

    return SequenceFigureResult(
        png_path=png_path,
        pdf_path=pdf_path,
        svg_path=svg_path,
        warnings=tuple(warnings),
    )


def _validate_spec(spec: SequenceFigureSpec) -> None:
    condition_paths = _condition_image_paths(spec)
    if not condition_paths:
        raise ValueError("Select images for at least one FPVS condition.")
    if len(condition_paths) > MAX_CONDITION_COUNT:
        raise ValueError(f"Sequence figures support at most {MAX_CONDITION_COUNT} conditions.")
    if spec.condition_labels and len(spec.condition_labels) != len(condition_paths):
        raise ValueError("Provide one condition label for each FPVS condition.")
    for label in spec.condition_labels:
        if not label.strip():
            raise ValueError("Condition labels cannot be blank.")
        if len(label.strip()) > MAX_CONDITION_LABEL_LENGTH:
            raise ValueError(
                f"Condition labels must be {MAX_CONDITION_LABEL_LENGTH} characters or fewer."
            )
    for condition_index, image_paths in enumerate(condition_paths, start=1):
        if len(image_paths) != DEFAULT_IMAGE_COUNT:
            raise ValueError(
                f"Condition {condition_index} requires exactly {DEFAULT_IMAGE_COUNT} stimulus images."
            )
    if spec.png_dpi <= 0:
        raise ValueError("PNG DPI must be greater than zero.")
    if spec.figure_size_in[0] <= 0 or spec.figure_size_in[1] <= 0:
        raise ValueError("Figure size must be greater than zero.")
    if not spec.output_dir.exists() or not spec.output_dir.is_dir():
        raise ValueError("Select an existing output folder.")
    for image_paths in condition_paths:
        for path in image_paths:
            if not path.exists() or not path.is_file():
                raise ValueError(f"Image does not exist: {path}")
            if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                raise ValueError(f"Unsupported image format: {path.name}")


def _condition_image_paths(spec: SequenceFigureSpec) -> SequenceImagePaths:
    if not spec.image_paths:
        return ()
    first_item = spec.image_paths[0]
    if isinstance(first_item, Path):
        return (tuple(Path(path) for path in spec.image_paths),)
    return tuple(tuple(Path(path) for path in condition_paths) for condition_paths in spec.image_paths)


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "fpvs_sequence_figure"


def _load_slot_images(spec: SequenceFigureSpec) -> tuple[list[list[Image.Image]], list[str]]:
    warnings: list[str] = []
    condition_paths = _condition_image_paths(spec)
    required_px = _required_source_pixels(spec, condition_count=len(condition_paths))
    images: list[list[Image.Image]] = []
    for condition_index, image_paths in enumerate(condition_paths, start=1):
        condition_images: list[Image.Image] = []
        for slot_index, path in enumerate(image_paths, start=1):
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
                short_side = min(image.size)
                if short_side < required_px:
                    warnings.append(
                        f"Condition {condition_index} slot {slot_index} source image is "
                        f"{image.size[0]}x{image.size[1]} px; about {required_px} px on the "
                        "short side is recommended for "
                        f"{_MIN_SOURCE_IMAGE_DPI} DPI source imagery in the exported figure."
                    )
                condition_images.append(_center_crop_square(image))
        images.append(condition_images)
    return images, warnings


def _required_source_pixels(spec: SequenceFigureSpec, *, condition_count: int) -> int:
    width_in = spec.figure_size_in[0] * (
        _image_size_units(condition_count=condition_count) / _CANVAS_WIDTH
    )
    return max(1, round(width_in * _MIN_SOURCE_IMAGE_DPI))


def _center_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _build_figure(spec: SequenceFigureSpec, images: Iterable[Iterable[Image.Image]]) -> Figure:
    condition_images = [list(row) for row in images]
    fig = plt.figure(figsize=spec.figure_size_in, facecolor="white", constrained_layout=False)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, _CANVAS_WIDTH)
    ax.set_ylim(0, _CANVAS_HEIGHT)
    ax.set_axis_off()

    _draw_condition_sequences(ax, condition_images, spec)

    _draw_stimulus_timing(ax, spec)
    return fig


def _draw_condition_sequences(
    ax,
    condition_images: list[list[Image.Image]],
    spec: SequenceFigureSpec,
) -> None:
    condition_count = len(condition_images)
    image_size = _image_size_units(condition_count=condition_count)
    centers_x = _sequence_centers_x()
    centers_y = _condition_centers_y(condition_count=condition_count)
    grid_y0 = min(centers_y) - image_size / 2 - 0.16
    grid_y1 = max(centers_y) + image_size / 2 + 0.16

    base_frame_color = _GRAYSCALE_BASE_COLOR if spec.grayscale_safe else _BASE_FRAME_COLOR
    oddball_frame_color = (
        _GRAYSCALE_ODDBALL_COLOR if spec.grayscale_safe else _ODDBALL_FRAME_COLOR
    )
    oddball_line_style = "--" if spec.grayscale_safe else "-"
    condition_labels = spec.condition_labels or tuple(
        f"Condition {index}" for index in range(1, condition_count + 1)
    )

    for oddball_center_x in _oddball_centers_x():
        ax.add_patch(
            Rectangle(
                (oddball_center_x - image_size / 2 - 0.16, grid_y0),
                image_size + 0.32,
                grid_y1 - grid_y0,
                facecolor=oddball_frame_color,
                edgecolor=oddball_frame_color,
                linewidth=1.0,
                linestyle=oddball_line_style,
                hatch="///" if spec.grayscale_safe else None,
                alpha=0.08,
                zorder=1,
            )
        )

    label_kwargs = figure_text_kwargs("condition_label")
    label_kwargs["color"] = "#202020"
    for condition_label, center_y, row_images in zip(
        condition_labels,
        centers_y,
        condition_images,
    ):
        ax.text(
            _CONDITION_LABEL_X,
            center_y,
            _wrapped_condition_label(ax, condition_label, label_kwargs),
            ha="right",
            va="center",
            parse_math=False,
            **label_kwargs,
        )
        for sequence_index, center_x in enumerate(centers_x):
            slot_index = sequence_index % DEFAULT_IMAGE_COUNT
            image = row_images[slot_index]
            x0 = center_x - image_size / 2
            x1 = center_x + image_size / 2
            y0 = center_y - image_size / 2
            y1 = center_y + image_size / 2
            is_oddball = slot_index == DEFAULT_IMAGE_COUNT - 1
            frame_color = oddball_frame_color if is_oddball else base_frame_color
            frame_width = _ODDBALL_FRAME_LINE_WIDTH_PT if is_oddball else _BASE_FRAME_LINE_WIDTH_PT
            ax.imshow(image, extent=(x0, x1, y0, y1), interpolation="lanczos", zorder=2)
            ax.add_patch(
                Rectangle(
                    (x0, y0),
                    image_size,
                    image_size,
                    fill=False,
                    linewidth=frame_width,
                    edgecolor=frame_color,
                    linestyle=oddball_line_style if is_oddball else "-",
                    zorder=3,
                )
            )


def _wrapped_condition_label(ax, label: str, text_kwargs: dict[str, object]) -> str:
    """Fit the bounded label into its margin without reducing figure type size."""
    label = label.strip()
    renderer = ax.figure.canvas.get_renderer()
    font = FontProperties(
        family=text_kwargs["fontfamily"],
        size=text_kwargs["fontsize"],
        weight=text_kwargs["fontweight"],
    )
    available_width = ax.bbox.width * (_CONDITION_LABEL_X - 0.1) / _CANVAS_WIDTH
    for width in range(len(label), 0, -1):
        wrapped = textwrap.fill(label, width=width, break_on_hyphens=False)
        if all(
            renderer.get_text_width_height_descent(line, font, ismath=False)[0] <= available_width
            for line in wrapped.splitlines()
        ):
            return wrapped
    return label


def _draw_stimulus_timing(ax, spec: SequenceFigureSpec) -> None:
    line_color = _GRAYSCALE_BASE_COLOR if spec.grayscale_safe else _BASE_COLOR
    oddball_color = _GRAYSCALE_ODDBALL_COLOR if spec.grayscale_safe else _ODDBALL_COLOR
    oddball_line_style = "--" if spec.grayscale_safe else "-"
    label_kwargs = _rate_label_kwargs(line_color)
    oddball_label_kwargs = _rate_label_kwargs(oddball_color)
    pulse_y = 3.18
    pulse_top = 3.94
    pulse_half_width = 0.36
    baseline_start = 0.65
    baseline_end = _WAVEFORM_END_X

    pulse_edges = [
        (center_x - pulse_half_width, center_x + pulse_half_width)
        for center_x in _sequence_centers_x()
    ]
    _draw_square_wave(
        ax,
        pulse_edges=pulse_edges,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_y=pulse_y,
        peak_y=pulse_top,
        color=line_color,
        linestyle="-",
    )

    ax.text(
        _RATE_LABEL_X,
        _midpoint(pulse_y, pulse_top),
        f"F = {spec.base_frequency_hz} Hz",
        ha="left",
        va="center",
        **label_kwargs,
    )

    oddball_y = 1.42
    oddball_top = 2.18
    oddball_edges = [
        pulse_edges[index]
        for index in range(DEFAULT_IMAGE_COUNT - 1, len(pulse_edges), DEFAULT_IMAGE_COUNT)
    ]
    _draw_square_wave(
        ax,
        pulse_edges=oddball_edges,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        baseline_y=oddball_y,
        peak_y=oddball_top,
        color=oddball_color,
        linestyle=oddball_line_style,
    )
    ax.text(
        _RATE_LABEL_X,
        _midpoint(oddball_y, oddball_top),
        f"f = {spec.oddball_frequency_hz} Hz",
        ha="left",
        va="center",
        **oddball_label_kwargs,
    )
    _draw_oddball_arrows(ax, oddball_edges, oddball_y, color=oddball_color)


def _draw_square_wave(
    ax,
    *,
    pulse_edges: list[tuple[float, float]],
    baseline_start: float,
    baseline_end: float,
    baseline_y: float,
    peak_y: float,
    color: str,
    linestyle: str,
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
            linestyle=linestyle,
        )
    for left, right in pulse_edges:
        ax.plot(
            [left, left],
            [baseline_y, peak_y],
            color=color,
            linewidth=_TIMING_LINE_WIDTH_PT,
            linestyle=linestyle,
        )
        ax.plot(
            [left, right],
            [peak_y, peak_y],
            color=color,
            linewidth=_TIMING_LINE_WIDTH_PT,
            linestyle=linestyle,
        )
        ax.plot(
            [right, right],
            [peak_y, baseline_y],
            color=color,
            linewidth=_TIMING_LINE_WIDTH_PT,
            linestyle=linestyle,
        )


def _midpoint(first: float, second: float) -> float:
    return (first + second) / 2


def _sequence_centers_x() -> tuple[float, ...]:
    total_slots = DEFAULT_IMAGE_COUNT * DEFAULT_ODDBALL_CYCLES
    step = (_SEQUENCE_END_X - _SEQUENCE_START_X) / (total_slots - 1)
    return tuple(_SEQUENCE_START_X + step * index for index in range(total_slots))


def _oddball_centers_x() -> tuple[float, ...]:
    return tuple(
        _sequence_centers_x()[index]
        for index in range(DEFAULT_IMAGE_COUNT - 1, DEFAULT_IMAGE_COUNT * DEFAULT_ODDBALL_CYCLES, DEFAULT_IMAGE_COUNT)
    )


def _condition_centers_y(*, condition_count: int) -> tuple[float, ...]:
    if condition_count <= 1:
        return (_midpoint(_GRID_TOP_CENTER_Y, _GRID_BOTTOM_CENTER_Y),)
    bottom_y = _GRID_BOTTOM_CENTER_Y_FOUR_ROWS if condition_count == MAX_CONDITION_COUNT else _GRID_BOTTOM_CENTER_Y
    step = (_GRID_TOP_CENTER_Y - bottom_y) / (condition_count - 1)
    return tuple(_GRID_TOP_CENTER_Y - step * index for index in range(condition_count))


def _image_size_units(*, condition_count: int) -> float:
    return _FOUR_CONDITION_IMAGE_SIZE_UNITS if condition_count == MAX_CONDITION_COUNT else _IMAGE_SIZE_UNITS


def _draw_oddball_arrows(
    ax,
    oddball_edges: list[tuple[float, float]],
    oddball_baseline_y: float,
    *,
    color: str,
) -> None:
    text_kwargs = figure_text_kwargs("annotation")
    text_kwargs["color"] = color
    for left, right in oddball_edges:
        center_x = _midpoint(left, right)
        ax.annotate(
            "Oddball",
            xy=(center_x, oddball_baseline_y - 0.02),
            xytext=(center_x, 0.44),
            ha="center",
            va="center",
            arrowprops={
                "arrowstyle": "->",
                "color": color,
                "linewidth": 1.8,
                "shrinkA": 2,
                "shrinkB": 2,
            },
            **text_kwargs,
        )


def _rate_label_kwargs(color: str) -> dict[str, object]:
    kwargs = figure_text_kwargs(_RATE_LABEL_FONT_ROLE)
    kwargs["fontsize"] = _RATE_LABEL_FONT_SIZE_PT
    kwargs["color"] = color
    return kwargs
