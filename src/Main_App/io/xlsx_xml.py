"""Internal XLSX XML primitives shared by the exact and spectral readers.

Reader-specific selection, caching and missing-column policies stay with each
reader. These helpers decode cells and archive relationships only.
"""

from __future__ import annotations

from collections.abc import Sequence
import posixpath
from xml.etree import ElementTree
import zipfile

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_TAG = f"{{{_SPREADSHEET_NS}}}c"
_ROW_TAG = f"{{{_SPREADSHEET_NS}}}row"
_SHEET_TAG = f"{{{_SPREADSHEET_NS}}}sheet"
_SHARED_STRING_TAG = f"{{{_SPREADSHEET_NS}}}si"
_TEXT_TAG = f"{{{_SPREADSHEET_NS}}}t"
_VALUE_TAG = f"{{{_SPREADSHEET_NS}}}v"
_RELATIONSHIP_TAG = f"{{{_PACKAGE_REL_NS}}}Relationship"


def _xlsx_member_path(source_member: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    source_dir = posixpath.dirname(source_member)
    return posixpath.normpath(posixpath.join(source_dir, target))


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(text.text or "" for text in item.iter(_TEXT_TAG))
        for item in root.iter(_SHARED_STRING_TAG)
    ]


def _row_values_by_column(row, shared_strings: Sequence[str]) -> list[str | None]:
    values_by_column: dict[int, str | None] = {}
    max_index = -1
    for fallback, cell in enumerate(row.iter(_CELL_TAG)):
        index = _cell_column_index(cell, fallback)
        values_by_column[index] = _cell_text(cell, shared_strings)
        max_index = max(max_index, index)
    if max_index < 0:
        return []
    return [values_by_column.get(index) for index in range(max_index + 1)]


def _cell_column_index(cell, fallback: int) -> int:
    reference = cell.attrib.get("r", "")
    index = 0
    found_column = False
    for char in reference:
        if not char.isalpha():
            break
        found_column = True
        index = (index * 26) + (ord(char.upper()) - ord("A") + 1)
    return index - 1 if found_column else fallback


def _cell_text(cell, shared_strings: Sequence[str]) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(_TEXT_TAG))

    value = cell.find(_VALUE_TAG)
    if value is None or value.text is None:
        return None
    raw = value.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def _cell_number(cell, shared_strings: Sequence[str]) -> object | None:
    raw = _cell_text(cell, shared_strings)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return raw
