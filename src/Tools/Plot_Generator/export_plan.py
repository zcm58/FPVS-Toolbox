"""Destination planning and recoverable publication of SNR figure pairs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import tempfile
from types import SimpleNamespace
from typing import Callable, Sequence

from Main_App.exports.figure_style import FIGURE_EXPORT_DPI

from .render_naming import claim_figure_stem

FigureIdentity = tuple[str, str, str]
FileStamp = tuple[int, int, int, int] | None


def _stamp(path: Path) -> FileStamp:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        raise ValueError(f"The figure destination is not a file: {path.name}")
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class FigureExport:
    identity: FigureIdentity
    png_path: Path
    expected: tuple[FileStamp, FileStamp]

    @property
    def paths(self) -> tuple[Path, Path]:
        return self.png_path, self.png_path.with_suffix(".pdf")

    @property
    def collides(self) -> bool:
        return any(stamp is not None for stamp in self.expected)


@dataclass(frozen=True)
class ExportChoices:
    replace: tuple[FigureExport, ...]
    keep_both: tuple[FigureExport, ...]

    @property
    def collisions(self) -> tuple[FigureExport, ...]:
        return tuple(item for item in self.replace if item.collides)


def inspect_destinations(
    output_folder: str,
    identities: Sequence[FigureIdentity],
    cancelled: Callable[[], bool] = lambda: False,
) -> ExportChoices | None:
    """Read destination metadata on a worker; never create or modify files."""
    root = Path(output_folder).resolve()
    owner = SimpleNamespace()
    planned: list[FigureExport] = []
    for identity in identities:
        if cancelled():
            return None
        title, roi, suffix = identity
        identity = (str(title).strip() or "SNR Plot", str(roi).strip() or "ROI", suffix)
        stem = claim_figure_stem(owner, base_title=title, roi=roi, suffix=suffix)
        png = root / f"{stem}.png"
        planned.append(FigureExport(identity, png, (_stamp(png), _stamp(png.with_suffix(".pdf")))))
    reserved = {item.png_path.name.casefold() for item in planned}
    copies: list[FigureExport] = []
    for item in planned:
        if cancelled():
            return None
        if not item.collides:
            copies.append(item)
            continue
        number = 2
        while True:
            if cancelled():
                return None
            png = item.png_path.with_name(f"{item.png_path.stem} ({number}).png")
            if png.name.casefold() not in reserved and _stamp(png) is None and _stamp(png.with_suffix(".pdf")) is None:
                break
            number += 1
        reserved.add(png.name.casefold())
        copies.append(FigureExport(item.identity, png, (None, None)))
    return ExportChoices(tuple(planned), tuple(copies))


def publish_figure_pair(
    destination: FigureExport,
    render: Callable[[Path, Path], None],
    cancelled: Callable[[], bool],
) -> bool:
    """Stage both files, check approval freshness, and roll back a failed pair."""
    paths = destination.paths
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".snr-export-", dir=paths[0].parent))
    preserve_recovery = False
    try:
        staged = tuple(staging / path.name for path in paths)
        render(*staged)
        if cancelled():
            return False
        if not all(path.is_file() for path in staged):
            raise OSError("The figure renderer did not produce both PNG and PDF files.")
        if tuple(_stamp(path) for path in paths) != destination.expected:
            raise FileExistsError(
                f"The destination changed after export confirmation: {paths[0].stem}. "
                "No files in this pair were replaced. Generate again to review the destinations."
            )
        backups = tuple(staging / f"previous{path.suffix}" for path in paths)
        for path, backup, stamp in zip(paths, backups, destination.expected):
            if stamp is not None:
                shutil.copy2(path, backup)
        if cancelled():
            return False
        if tuple(_stamp(path) for path in paths) != destination.expected:
            raise FileExistsError(
                "The figure destination changed while preparing replacement. "
                "Generate again to review the destinations."
            )
        committed: list[int] = []
        try:
            for index, (source, target, stamp) in enumerate(zip(staged, paths, destination.expected)):
                if stamp is None:
                    # Creating a new destination must never replace a file that appeared meanwhile.
                    with source.open("rb") as incoming, target.open("xb") as output:
                        committed.append(index)
                        shutil.copyfileobj(incoming, output)
                else:
                    os.replace(source, target)
                    committed.append(index)
        except OSError:
            recovery_errors = []
            for index in reversed(committed):
                try:
                    if destination.expected[index] is None:
                        paths[index].unlink(missing_ok=True)
                    else:
                        os.replace(backups[index], paths[index])
                except OSError as exc:
                    recovery_errors.append(exc)
            if recovery_errors:
                preserve_recovery = True
                raise OSError(
                    f"Could not restore the previous figure pair. Recovery files are preserved in {staging}"
                ) from recovery_errors[0]
            raise
    finally:
        if not preserve_recovery and staging.parent.resolve() == paths[0].parent.resolve():
            shutil.rmtree(staging)
    return True


def save_worker_figure_pair(owner, figure, png_path: Path, pdf_path: Path) -> bool:
    """Save a rendered figure using the GUI-approved plan, or new files only."""
    plan = getattr(owner, "_figure_export_plan", None)
    if plan is None:
        destination = FigureExport(("", "", ""), png_path.resolve(), (None, None))
    else:
        destination = next((item for item in plan if item.png_path == png_path.resolve()), None)
        if destination is None or destination.paths[1] != pdf_path.resolve():
            raise ValueError("The figure destination is not in the confirmed export plan.")

    def render(staged_png: Path, staged_pdf: Path) -> None:
        figure.savefig(staged_png, dpi=FIGURE_EXPORT_DPI, pil_kwargs={"compress_level": 1})
        if not owner._cancellation_checkpoint():
            figure.savefig(staged_pdf, format="pdf", dpi=FIGURE_EXPORT_DPI)

    return publish_figure_pair(destination, render, owner._cancellation_checkpoint)


__all__ = [
    "ExportChoices", "FigureExport", "FigureIdentity", "inspect_destinations",
    "publish_figure_pair", "save_worker_figure_pair",
]
