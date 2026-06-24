"""Selected-column `.xlsx` reader for publication scalp-map metric sheets."""

from __future__ import annotations

from collections.abc import Sequence
import posixpath
from pathlib import Path
from xml.etree import ElementTree
import zipfile

import pandas as pd

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


def read_metric_sheet_selected_columns(
    excel_path: str | Path,
    *,
    sheet_name: str,
    required_columns: Sequence[str],
) -> pd.DataFrame:
    """Read only existing requested columns from one scalp-map metric worksheet.

    Missing requested columns are omitted so the caller can preserve its current
    exact-column diagnostics. No workbook data is cached.
    """

    columns = _unique_requested_columns(required_columns)
    with zipfile.ZipFile(excel_path) as archive:
        worksheet_member = _worksheet_member(archive, sheet_name)
        shared_strings = _load_shared_strings(archive)
        with archive.open(worksheet_member) as worksheet_stream:
            return _read_selected_columns_from_stream(
                worksheet_stream,
                shared_strings=shared_strings,
                required_columns=columns,
            )


def _unique_requested_columns(columns: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for column in columns:
        normalized = str(column)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _worksheet_member(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target")
        for rel in rels_root.iter(_RELATIONSHIP_TAG)
    }
    for sheet in workbook_root.iter(_SHEET_TAG):
        if sheet.attrib.get("name") != sheet_name:
            continue
        rel_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
        target = rel_targets.get(rel_id)
        if target:
            return _xlsx_member_path("xl/workbook.xml", target)
        break
    raise ValueError(f"Worksheet named '{sheet_name}' not found")


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


def _read_selected_columns_from_stream(
    worksheet_stream,
    *,
    shared_strings: Sequence[str],
    required_columns: Sequence[str],
) -> pd.DataFrame:
    selected_positions: dict[int, int] = {}
    selected_columns: list[str] = []
    max_selected_index = -1
    rows: list[list[object | None]] = []
    header_seen = False

    for _, row in ElementTree.iterparse(worksheet_stream, events=("end",)):
        if row.tag != _ROW_TAG:
            continue
        if not header_seen:
            header_seen = True
            header = _row_values_by_column(row, shared_strings)
            position_by_name = {
                str(value): index
                for index, value in enumerate(header)
                if value not in (None, "")
            }
            for column in required_columns:
                source_index = position_by_name.get(str(column))
                if source_index is None:
                    continue
                selected_positions[source_index] = len(selected_columns)
                selected_columns.append(str(column))
                max_selected_index = max(max_selected_index, source_index)
            row.clear()
            continue

        if selected_columns:
            rows.append(
                _selected_row_values(
                    row,
                    shared_strings,
                    selected_positions=selected_positions,
                    selected_columns=selected_columns,
                    max_selected_index=max_selected_index,
                )
            )
        row.clear()

    return pd.DataFrame(rows, columns=selected_columns)


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


def _selected_row_values(
    row,
    shared_strings: Sequence[str],
    *,
    selected_positions: dict[int, int],
    selected_columns: Sequence[str],
    max_selected_index: int,
) -> list[object | None]:
    values: list[object | None] = [None] * len(selected_columns)
    for fallback, cell in enumerate(row.iter(_CELL_TAG)):
        index = _cell_column_index(cell, fallback)
        if index > max_selected_index:
            break
        output_position = selected_positions.get(index)
        if output_position is None:
            continue
        if selected_columns[output_position] == "Electrode":
            values[output_position] = _cell_text(cell, shared_strings)
        else:
            values[output_position] = _cell_number(cell, shared_strings)
    return values


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


__all__ = ("read_metric_sheet_selected_columns",)
