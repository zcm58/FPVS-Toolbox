"""Companion-file discovery for BrainVision recordings.

BVCDF links its files in the header; BVRF uses one common base name. Paths here
identify the complete source for copying and provenance, never just the header.
"""
from __future__ import annotations

import configparser
import os
import re
from pathlib import Path, PureWindowsPath


class BrainProductsFormatError(ValueError):
    """A recording cannot be interpreted without guessing its format."""


HEADER_EXTENSIONS = (".vhdr", ".bvrh")


def read_brainvision_header(path: str | Path) -> configparser.ConfigParser:
    """Parse the declared text encoding without treating percent signs as macros."""
    path = Path(path)
    payload = path.read_bytes()
    codepage = re.search(rb"(?im)^Codepage\s*=\s*([^\r\n]+)", payload)
    encoding = codepage.group(1).decode("ascii").strip() if codepage else "utf-8-sig"
    if encoding.upper() == "ANSI":
        encoding = "cp1252"
    try:
        text = payload.decode(encoding)
    except UnicodeDecodeError:
        if codepage:
            raise BrainProductsFormatError("The BrainVision header does not match its declared encoding.") from None
        text = payload.decode("cp1252")
    except LookupError as exc:
        raise BrainProductsFormatError(f"Unsupported BrainVision text encoding: {encoding}.") from exc
    section = text.find("[Common Infos]")
    if section < 0:
        raise BrainProductsFormatError("The BrainVision header has no [Common Infos] section.")
    # The free-form comment section is not INI metadata.
    text = text[section:].split("[Comment]", 1)[0]
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise BrainProductsFormatError(f"Invalid BrainVision header: {exc}") from exc
    return parser


def _existing_file(path: Path, root: Path) -> Path:
    # Reject an unrelated absolute path (including a different Windows share)
    # before attempting filesystem access, then check the actual link target.
    if not Path(os.path.abspath(path)).is_relative_to(root):
        raise BrainProductsFormatError("Brain Products files must remain inside the recording folder.")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise BrainProductsFormatError("Brain Products files must remain inside the recording folder.")
    if not resolved.is_file():
        raise FileNotFoundError(f"Required Brain Products recording file is missing: {path}")
    return resolved


def _linked_file(header: Path, value: str, root: Path, *, native_paths: bool = False) -> Path:
    if not value.strip():
        raise BrainProductsFormatError("A BrainVision companion filename is empty.")
    if PureWindowsPath(value).drive and not Path(value).is_absolute():
        raise BrainProductsFormatError("BrainVision companions must identify a file inside the recording folder.")
    declared = header.parent / value
    relocated = header.parent / value.replace("\\", "/")
    file = _existing_file(relocated, root)
    # The native MNE reader opens the declared spelling literally on POSIX.
    # Never validate one path and let it open a different file with that name.
    if native_paths and declared != relocated and declared.resolve() != file:
        raise BrainProductsFormatError("Use forward slashes for nested BrainVision paths on this platform.")
    return file


def _bvrf_companion(header: Path, suffix: str, root: Path, *, required: bool = True) -> Path | None:
    """Resolve Windows-created upper-case extensions on case-sensitive hosts."""
    name = header.with_suffix(suffix).name.casefold()
    matches = [entry for entry in header.parent.iterdir() if entry.name.casefold() == name]
    if len(matches) > 1:
        raise BrainProductsFormatError(f"Ambiguous BVRF companion filenames differing only by case: {name}")
    if matches:
        return _existing_file(matches[0], root)
    if required:
        raise FileNotFoundError(f"Required Brain Products recording file is missing: {header.with_suffix(suffix)}")
    return None


def source_files(path: str | Path, *, native_paths: bool = False) -> tuple[Path, ...]:
    """Return existing header, data, markers, and optional impedance paths."""
    selected = Path(path)
    root = selected.parent.resolve(strict=True)
    header = _existing_file(root / selected.name, root)
    extension = header.suffix.lower()
    if extension == ".vhdr":
        parser = read_brainvision_header(header)
        try:
            common = parser["Common Infos"]
            data = _linked_file(header, common["DataFile"], root, native_paths=native_paths)
            markers = _linked_file(header, common["MarkerFile"], root, native_paths=native_paths)
        except KeyError as exc:
            raise BrainProductsFormatError("BrainVision headers must name DataFile and MarkerFile.") from exc
        if len({header, data, markers}) != 3:
            raise BrainProductsFormatError("BrainVision header, data and markers must be different files.")
        marker_header = read_brainvision_header(markers)
        try:
            marker_data = _linked_file(markers, marker_header["Common Infos"]["DataFile"], root)
        except KeyError as exc:
            raise BrainProductsFormatError("BrainVision marker file must name its DataFile.") from exc
        if marker_data != data:
            raise BrainProductsFormatError("BrainVision header and marker file name different data files.")
        return header, data, markers
    if extension == ".bvrh":
        files = [header, _bvrf_companion(header, ".bvrd", root), _bvrf_companion(header, ".bvrm", root)]
        impedance = _bvrf_companion(header, ".bvri", root, required=False)
        if impedance is not None:
            files.append(impedance)
        return tuple(files)
    raise BrainProductsFormatError("Select the BrainVision .vhdr or .bvrh header, not a companion file.")
