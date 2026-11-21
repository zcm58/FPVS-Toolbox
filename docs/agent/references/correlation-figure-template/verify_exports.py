"""Read-only PNG/PDF checks. Requires Pillow and pypdf, not Qt or application imports."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

DPI = 600.0
DPI_TOLERANCE = 0.1
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def concatenate(matrix, current):
    a, b, c, d, e, f = matrix
    g, h, i, j, k, m = current
    return a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j, e * g + f * i + k, e * h + f * j + m


def inspect_content(stream, reader, resources, current=IDENTITY, user_unit=1.0, depth=0):
    """Measure painted images in their effective page transform, including nested Forms."""
    require(depth < 32, "Excessive PDF Form nesting")
    resources = resources.get_object()
    font_resources = resources.get("/Font", {})
    if hasattr(font_resources, "get_object"):
        font_resources = font_resources.get_object()
    fonts = {str(font.get_object().get("/BaseFont", "")) for font in font_resources.values()}
    objects = resources.get("/XObject", {})
    if hasattr(objects, "get_object"):
        objects = objects.get_object()
    images, stack = [], []
    for operands, operator in ContentStream(stream, reader).operations:
        if operator == b"q":
            stack.append(current)
        elif operator == b"Q":
            require(bool(stack), "Unbalanced PDF graphics-state restore")
            current = stack.pop()
        elif operator == b"cm":
            current = concatenate(tuple(float(value) for value in operands), current)
        elif operator == b"Do":
            obj = objects[operands[0]].get_object()
            if obj.get("/Subtype") == "/Image":
                pixels = [int(obj["/Width"]), int(obj["/Height"])]
                points = [math.hypot(*current[:2]) * user_unit, math.hypot(*current[2:4]) * user_unit]
                require(all(math.isfinite(value) and value > 0 for value in points), "Invalid PDF image dimensions")
                resolution = [pixel * 72 / point for pixel, point in zip(pixels, points, strict=True)]
                require(all(abs(value - DPI) <= DPI_TOLERANCE for value in resolution), f"PDF image DPI {resolution}")
                images.append({"pixels": pixels, "effective_dpi": resolution})
            elif obj.get("/Subtype") == "/Form":
                matrix = tuple(float(value) for value in obj.get("/Matrix", IDENTITY))
                nested, nested_fonts = inspect_content(
                    obj, reader, obj.get("/Resources", resources), concatenate(matrix, current), user_unit, depth + 1
                )
                images.extend(nested)
                fonts.update(nested_fonts)
    require(not stack, "Unbalanced PDF graphics-state save")
    return images, fonts


def verify_pair(export):
    png, pdf = Path(export["png"]), Path(export["pdf"])
    require(png.is_absolute() and pdf.is_absolute(), "Receipt export paths must be absolute")
    require(png.suffix.lower() == ".png" and pdf.suffix.lower() == ".pdf", "Expected PNG/PDF export paths")
    with Image.open(png) as raster:
        require(raster.format == "PNG", f"Not a PNG: {png}")
        pixels, resolution = list(raster.size), list(raster.info.get("dpi", ()))
        require(len(resolution) == 2, f"Missing PNG DPI metadata: {png}")
        require(all(abs(value - DPI) <= DPI_TOLERANCE for value in resolution), f"PNG DPI {resolution}: {png}")
        raster.verify()
    reader = PdfReader(pdf)
    require(len(reader.pages) == 1, f"Expected one PDF page: {pdf}")
    page = reader.pages[0]
    require(bool((page.extract_text() or "").strip()), f"Missing searchable PDF text: {pdf}")
    user_unit = float(page.get("/UserUnit", 1))
    require(math.isfinite(user_unit) and user_unit > 0, f"Invalid PDF UserUnit: {pdf}")
    points = [float(page.mediabox.width) * user_unit, float(page.mediabox.height) * user_unit]
    if int(page.get("/Rotate", 0)) % 180:
        points.reverse()
    require(
        all(abs(pixel - point * DPI / 72) <= 1 for pixel, point in zip(pixels, points, strict=True)),
        f"PNG pixels {pixels} do not match PDF page points {points} at 600 DPI: {pdf}",
    )
    images, fonts = inspect_content(page.get_contents(), reader, page["/Resources"], user_unit=user_unit)
    require(bool(images), f"Expected explicit 600-DPI raster layers in hybrid PDF: {pdf}")
    require(bool(fonts) and all("arial" in font.lower() for font in fonts), f"Expected Arial fonts: {sorted(fonts)}")
    return {
        "png": str(png), "pdf": str(pdf), "png_pixels": pixels, "png_dpi": resolution,
        "page_points": points, "pdf_images": images, "fonts": sorted(fonts), "searchable_text": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path, help="JSON with an exports list of absolute png/pdf paths")
    args = parser.parse_args()
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        exports = receipt["exports"]
        require(isinstance(exports, list) and bool(exports), "Receipt exports must be a nonempty list")
        results = [verify_pair(export) for export in exports]
        print(json.dumps({"ok": True, "target_dpi": DPI, "dpi_tolerance": DPI_TOLERANCE, "exports": results}))
    except (KeyError, TypeError, ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
