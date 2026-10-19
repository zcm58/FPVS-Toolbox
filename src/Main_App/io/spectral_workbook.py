"""Companion-aware spectral workbook sessions and frequency-window reads."""

from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
import time
from typing import BinaryIO, List, Mapping, Sequence
from xml.etree import ElementTree
import zipfile

import pandas as pd

from Main_App.io.xlsx_xml import (
    _SPREADSHEET_NS as _SPREADSHEET_NS,
    _OFFICE_REL_NS as _OFFICE_REL_NS,
    _PACKAGE_REL_NS as _PACKAGE_REL_NS,
    _CELL_TAG as _CELL_TAG,
    _ROW_TAG as _ROW_TAG,
    _SHEET_TAG as _SHEET_TAG,
    _SHARED_STRING_TAG as _SHARED_STRING_TAG,
    _TEXT_TAG as _TEXT_TAG,
    _VALUE_TAG as _VALUE_TAG,
    _RELATIONSHIP_TAG as _RELATIONSHIP_TAG,
    _xlsx_member_path as _xlsx_member_path,
    _load_shared_strings as _load_shared_strings,
    _row_values_by_column as _row_values_by_column,
    _cell_column_index as _cell_column_index,
    _cell_text as _cell_text,
    _cell_number as _cell_number,
)

_FULLSNR_SHEET = "FullSNR"
_MISSING_FULLSNR_MESSAGE = "Worksheet named 'FullSNR' not found"


def _add_timing_detail(
    timing_details: dict[str, float] | None,
    phase: str,
    started: float,
) -> None:
    if timing_details is None:
        return
    timing_details[phase] = timing_details.get(phase, 0.0) + (
        time.perf_counter() - started
    )


def _worksheet_members(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target")
        for rel in rels_root.iter(_RELATIONSHIP_TAG)
    }
    members: dict[str, str] = {}
    for sheet in workbook_root.iter(_SHEET_TAG):
        name = sheet.attrib.get("name")
        rel_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
        target = rel_targets.get(rel_id)
        if name and target:
            members[name] = _xlsx_member_path("xl/workbook.xml", target)
    return members


class XlsxWorkbookReadSession:
    """One lazily opened XLSX archive with shared workbook metadata."""

    def __init__(
        self,
        source: str | Path | bytes,
        *,
        spectral_sheets: Mapping[str, pd.DataFrame] | None = None,
    ) -> None:
        self._source = source
        self._spectral_sheets = spectral_sheets
        self._stream: BinaryIO | None = None
        self._archive: zipfile.ZipFile | None = None
        self._shared_strings: list[str] | None = None
        self._sheet_members: dict[str, str] | None = None

    def __enter__(self) -> XlsxWorkbookReadSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def archive(self) -> zipfile.ZipFile:
        if self._archive is None:
            source: str | Path | BinaryIO
            if isinstance(self._source, bytes):
                self._stream = BytesIO(self._source)
                source = self._stream
            else:
                source = self._source
            self._archive = zipfile.ZipFile(source)
        return self._archive

    @property
    def shared_strings(self) -> list[str]:
        if self._shared_strings is None:
            self._shared_strings = _load_shared_strings(self.archive)
        return self._shared_strings

    def worksheet_member(self, sheet_name: str) -> str:
        if self._sheet_members is None:
            self._sheet_members = _worksheet_members(self.archive)
        try:
            return self._sheet_members[sheet_name]
        except KeyError as exc:
            raise ValueError(f"Worksheet named '{sheet_name}' not found") from exc

    def spectral_sheet(self, sheet_name: str) -> pd.DataFrame | None:
        """Return captured companion values; never substitute an Excel notice."""

        if self._spectral_sheets is not None:
            if not self._spectral_sheets:
                return None
            if sheet_name not in self._spectral_sheets:
                raise ValueError(f"Spectral companion is missing '{sheet_name}'.")
            return self._spectral_sheets[sheet_name]
        if isinstance(self._source, bytes):
            if "Spectral Data" in _worksheet_members(self.archive):
                raise ValueError("Spectral workbook bytes require a captured companion.")
            return None
        from Main_App.io.spectral_data import (
            read_spectral_sheet,
            spectral_companion_identity,
        )

        if spectral_companion_identity(self._source) is None:
            return None
        return read_spectral_sheet(self._source, sheet_name=sheet_name)

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None


def _row_electrode_value(row, shared_strings: Sequence[str], electrode_index: int):
    for fallback, cell in enumerate(row.iter(_CELL_TAG)):
        index = _cell_column_index(cell, fallback)
        if index == electrode_index:
            return _cell_text(cell, shared_strings)
        if index > electrode_index:
            break
    return None


def _selected_row_values(
    row,
    shared_strings: Sequence[str],
    *,
    required_positions: dict[int, int],
    electrode_index: int,
    max_required_index: int,
) -> list[object | None]:
    values: list[object | None] = [None] * len(required_positions)
    for fallback, cell in enumerate(row.iter(_CELL_TAG)):
        index = _cell_column_index(cell, fallback)
        if index > max_required_index:
            break
        position = required_positions.get(index)
        if position is None:
            continue
        if index == electrode_index:
            values[position] = _cell_text(cell, shared_strings)
        else:
            values[position] = _cell_number(cell, shared_strings)
    return values


def read_full_snr_sheet(
    excel_path: Path,
    *,
    x_min: float,
    x_max: float,
    timing_details: dict[str, float] | None = None,
    included_electrodes_upper: set[str] | None = None,
    workbook_session: XlsxWorkbookReadSession | None = None,
) -> tuple[pd.DataFrame, List[float], List[str]]:
    started = time.perf_counter()
    session = workbook_session or XlsxWorkbookReadSession(excel_path)
    context = session if workbook_session is None else nullcontext(session)
    with context:
        companion = _read_companion_selection(
            session, _FULLSNR_SHEET, x_min=x_min, x_max=x_max,
            included_electrodes_upper=included_electrodes_upper,
        )
        if companion is not None:
            _add_timing_detail(timing_details, "fullsnr_companion_read", started)
            return companion
        archive = session.archive
        sheet_member = session.worksheet_member(_FULLSNR_SHEET)
        _add_timing_detail(timing_details, "fullsnr_workbook_open", started)

        started = time.perf_counter()
        shared_strings = session.shared_strings
        _add_timing_detail(timing_details, "fullsnr_shared_strings", started)

        started = time.perf_counter()
        with archive.open(sheet_member) as worksheet_stream:
            rows = []
            columns = ["Electrode"]
            ordered_freqs: list[float] = []
            ordered_cols: list[str] = []
            selected_indexes: list[int] = []
            electrode_index = -1
            required_positions: dict[int, int] = {}
            max_required_index = -1
            header_seen = False

            for _, row in ElementTree.iterparse(worksheet_stream, events=("end",)):
                if row.tag != _ROW_TAG:
                    continue
                if not header_seen:
                    header_seen = True
                    header = _row_values_by_column(row, shared_strings)
                    if not header:
                        _add_timing_detail(timing_details, "fullsnr_header_scan", started)
                        started = time.perf_counter()
                        df = pd.DataFrame()
                        _add_timing_detail(
                            timing_details,
                            "fullsnr_dataframe_build",
                            started,
                        )
                        row.clear()
                        return df, [], []

                    freq_pairs: list[tuple[float, str, int]] = []
                    for index, column in enumerate(header):
                        if column == "Electrode":
                            electrode_index = index
                        if not isinstance(column, str) or not column.endswith("_Hz"):
                            continue
                        try:
                            freq = float(column.split("_")[0])
                        except ValueError:
                            continue
                        freq_pairs.append((freq, column, index))

                    if electrode_index < 0:
                        raise KeyError("Electrode")

                    freq_pairs.sort(key=lambda item: item[0])
                    tolerance = 1e-3
                    selected = [
                        (freq, column, index)
                        for freq, column, index in freq_pairs
                        if (x_min - tolerance) <= freq <= (x_max + tolerance)
                    ]
                    ordered_freqs = [freq for freq, _, _ in selected]
                    ordered_cols = [column for _, column, _ in selected]
                    selected_indexes = [index for _, _, index in selected]
                    _add_timing_detail(timing_details, "fullsnr_header_scan", started)
                    if not selected_indexes:
                        started = time.perf_counter()
                        df = pd.DataFrame(columns=["Electrode"])
                        _add_timing_detail(
                            timing_details,
                            "fullsnr_dataframe_build",
                            started,
                        )
                        row.clear()
                        return df, ordered_freqs, ordered_cols

                    columns = ["Electrode"] + ordered_cols
                    required_indexes = [electrode_index] + selected_indexes
                    required_positions = {
                        column_index: position
                        for position, column_index in enumerate(required_indexes)
                    }
                    max_required_index = max(required_indexes)
                    started = time.perf_counter()
                    row.clear()
                    continue

                electrode = _row_electrode_value(row, shared_strings, electrode_index)
                if (
                    included_electrodes_upper is not None
                    and str(electrode).upper() not in included_electrodes_upper
                ):
                    row.clear()
                    continue
                rows.append(
                    _selected_row_values(
                        row,
                        shared_strings,
                        required_positions=required_positions,
                        electrode_index=electrode_index,
                        max_required_index=max_required_index,
                    )
                )
                row.clear()

            if not header_seen:
                _add_timing_detail(timing_details, "fullsnr_header_scan", started)
                started = time.perf_counter()
                df = pd.DataFrame()
                _add_timing_detail(timing_details, "fullsnr_dataframe_build", started)
                return df, [], []

            if not selected_indexes:
                started = time.perf_counter()
                df = pd.DataFrame(columns=["Electrode"])
                _add_timing_detail(timing_details, "fullsnr_dataframe_build", started)
                return df, ordered_freqs, ordered_cols

            _add_timing_detail(timing_details, "fullsnr_row_stream", started)
            started = time.perf_counter()
            df = pd.DataFrame(rows, columns=columns)
            _add_timing_detail(timing_details, "fullsnr_dataframe_build", started)
            return df, ordered_freqs, ordered_cols


def _read_companion_selection(
    session: XlsxWorkbookReadSession,
    sheet_name: str,
    *,
    x_min: float,
    x_max: float,
    included_electrodes_upper: set[str] | None,
) -> tuple[pd.DataFrame, List[float], List[str]] | None:
    frame = session.spectral_sheet(sheet_name)
    if frame is None:
        return None
    if "Electrode" not in frame.columns:
        raise KeyError("Electrode")
    pairs = []
    for column in frame.columns:
        if not isinstance(column, str) or not column.endswith("_Hz"):
            continue
        try:
            frequency = float(column.split("_")[0])
        except ValueError:
            continue
        if x_min - 1e-3 <= frequency <= x_max + 1e-3:
            pairs.append((frequency, column))
    pairs.sort(key=lambda item: item[0])
    frequencies = [frequency for frequency, _column in pairs]
    columns = [column for _frequency, column in pairs]
    if not columns:
        return pd.DataFrame(columns=["Electrode"]), [], []
    selected = frame.loc[:, ["Electrode", *columns]]
    if included_electrodes_upper is not None:
        selected = selected.loc[
            selected["Electrode"].map(lambda value: str(value).upper()).isin(
                included_electrodes_upper
            )
        ]
    return selected.reset_index(drop=True).copy(), frequencies, columns


# Historical import seam retained for external and test callers.
_read_full_snr_sheet_read_only = read_full_snr_sheet

__all__ = ["XlsxWorkbookReadSession", "read_full_snr_sheet"]
