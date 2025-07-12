"""Core image resizing logic used by both GUI frontends."""

from __future__ import annotations

import os
from typing import Callable, List, Tuple

from PIL import Image, ImageOps


def process_images_in_folder(
    input_folder: str,
    output_folder: str,
    target_width: int,
    target_height: int,
    desired_ext: str,
    update_callback: Callable[[str, int, int], None],
    cancel_flag: Callable[[], bool],
    overwrite_all: bool = False,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], int]:
    """Resize all images in *input_folder* and save them to *output_folder*.

    Parameters
    ----------
    input_folder:
        Directory containing images to resize.
    output_folder:
        Directory where resized images will be written.
    target_width:
        Desired width in pixels.
    target_height:
        Desired height in pixels.
    desired_ext:
        Desired file extension (e.g. ``"jpg"``).
    update_callback:
        Function called with progress updates.
    cancel_flag:
        Function returning ``True`` if processing should stop.
    overwrite_all:
        Whether to overwrite existing files.
    Returns
    -------
    skips, failures, processed
        Tuple containing lists of skipped and failed files and the number
        of processed files.
    """
    valid_exts = [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]
    files = [
        f
        for f in os.listdir(input_folder)
        if os.path.isfile(os.path.join(input_folder, f))
    ]
    total_files = len(files)
    processed = 0

    skip_details: List[Tuple[str, str]] = []
    write_failures: List[Tuple[str, str]] = []

    for file in files:
        if cancel_flag():
            update_callback("Processing cancelled.\n", processed, total_files)
            return skip_details, write_failures, processed

        file_path = os.path.join(input_folder, file)
        _, ext = os.path.splitext(file)
        ext = ext.lower()

        if ext == ".webp":
            skip_details.append(
                (
                    file,
                    ".webp files are not compatible with PsychoPy and cannot be converted to .jpg, .jpeg, or .png.",
                )
            )
            processed += 1
            update_callback(f"Skipped {file} (unsupported: .webp)\n", processed, total_files)
            continue

        if ext in valid_exts:
            try:
                with Image.open(file_path) as img:
                    img = ImageOps.exif_transpose(img)
                    orig_w, orig_h = img.size
                    scale = max(target_width / orig_w, target_height / orig_h)
                    new_size = (round(orig_w * scale), round(orig_h * scale))
                    resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    left = (new_size[0] - target_width) // 2
                    top = (new_size[1] - target_height) // 2
                    final = resized.crop((left, top, left + target_width, top + target_height))
            except Exception as e:  # pragma: no cover - file errors are rare in tests
                skip_details.append((file, f"Read error: {e}"))
                processed += 1
                update_callback(f"Could not read {file}: {e}\n", processed, total_files)
                continue

            base, _ = os.path.splitext(file)
            new_name = f"{base} Resized.{desired_ext}"
            out_path = os.path.join(output_folder, new_name)

            if os.path.exists(out_path):
                if not overwrite_all:
                    skip_details.append((file, "File exists"))
                    processed += 1
                    update_callback(f"Skipped {file} (exists)\n", processed, total_files)
                    continue

            try:
                final.save(out_path)
                processed += 1
                update_callback(f"Processed {file} → {new_name}\n", processed, total_files)
            except Exception as e:  # pragma: no cover - file errors are rare in tests
                write_failures.append((file, str(e)))
                processed += 1
                update_callback(f"Error writing {file}: {e}\n", processed, total_files)
        else:
            skip_details.append((file, "Unsupported format"))
            processed += 1
            update_callback(f"Skipped {file} (unsupported)\n", processed, total_files)

    return skip_details, write_failures, processed
