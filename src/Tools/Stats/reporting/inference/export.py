"""Deterministic native-inference workbook export."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import pandas as pd

from Tools.Stats.reporting.inference.bundle import (
    REPORT_SCHEMA_VERSION,
    NativeInferenceReportBundle,
    unique_frame_name,
)
from Tools.Stats.reporting.inference.frames import normalize_inputs


INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def sanitize_sheet_name(requested: object, used: set[str]) -> str:
    """Return a unique Excel-safe name no longer than 31 characters."""

    name = INVALID_SHEET_CHARS.sub(" ", str(requested))
    name = re.sub(r"\s+", " ", name).strip().strip("'") or "Sheet"
    base = name[:31]
    candidate = base
    index = 2
    while candidate.casefold() in used:
        suffix = f" ({index})"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        index += 1
    used.add(candidate.casefold())
    return candidate


def excel_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Render collection-valued object cells deterministically."""

    def stable_collection(value: object) -> object:
        if isinstance(value, Mapping):
            normalized = {
                str(key): stable_collection(item)
                for key, item in sorted(
                    value.items(),
                    key=lambda pair: (type(pair[0]).__name__, str(pair[0])),
                )
            }
            return json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        if isinstance(value, (set, frozenset)):
            rendered = sorted(
                (str(stable_collection(item)) for item in value),
                key=lambda item: (item.casefold(), item),
            )
            return "; ".join(rendered)
        if isinstance(value, (list, tuple)):
            return "; ".join(str(stable_collection(item)) for item in value)
        return value

    output = frame.copy()
    for column_index in range(len(output.columns)):
        values = output.iloc[:, column_index]
        if pd.api.types.is_object_dtype(values):
            output.iloc[:, column_index] = values.map(stable_collection)
    return output


def _validated_output_path(path: str | Path) -> Path:
    output_path = Path(path)
    if output_path.suffix.casefold() != ".xlsx":
        raise ValueError("Native inference workbooks must use the .xlsx extension.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _write_frames_atomic(
    frames: Mapping[str, pd.DataFrame],
    output_path: Path,
    *,
    mode: str,
    log: Callable[[str], Any],
) -> Path:
    """Write workbook frames to a sibling temporary file, then replace atomically."""

    used_sheet_names: set[str] = set()
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.stem}.",
        suffix=".tmp.xlsx",
        dir=output_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()
    written_sheets: list[str] = []
    try:
        with pd.ExcelWriter(
            temporary_path,
            engine="xlsxwriter",
            engine_kwargs={
                "options": {
                    "strings_to_formulas": False,
                    "strings_to_urls": False,
                }
            },
        ) as writer:
            writer.book.set_properties(
                {
                    "title": "FPVS Toolbox Native Inference Report",
                    "subject": f"{mode} group statistical analysis",
                    "author": "FPVS Toolbox",
                    "created": datetime(2000, 1, 1),
                }
            )
            header = writer.book.add_format(
                {
                    "bold": True,
                    "text_wrap": True,
                    "valign": "top",
                    "fg_color": "#DDEBF7",
                    "border": 1,
                }
            )
            for requested_name, frame in frames.items():
                sheet_name = sanitize_sheet_name(
                    requested_name,
                    used_sheet_names,
                )
                safe = excel_safe_frame(frame)
                safe.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]
                worksheet.freeze_panes(1, 0)
                if len(safe.columns):
                    worksheet.autofilter(
                        0,
                        0,
                        len(safe),
                        len(safe.columns) - 1,
                    )
                for column_index, column_name in enumerate(safe.columns):
                    worksheet.write(
                        0,
                        column_index,
                        str(column_name),
                        header,
                    )
                    rendered = (
                        safe.iloc[:, column_index].fillna("").astype(str)
                    )
                    max_width = (
                        int(rendered.map(len).max()) if len(rendered) else 0
                    )
                    width = min(
                        max(max_width, len(str(column_name))) + 2,
                        60,
                    )
                    worksheet.set_column(
                        column_index,
                        column_index,
                        width,
                    )
                written_sheets.append(sheet_name)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    for sheet_name in written_sheets:
        log(f"Wrote inference report sheet: {sheet_name}")
    log(f"Wrote native inference workbook: {output_path}")
    return output_path


def write_native_inference_workbook(
    bundle: NativeInferenceReportBundle,
    path: str | Path,
    log_callback: Callable[[str], Any] | None = None,
) -> Path:
    """Write every report/source frame to an explicit XLSX workbook."""

    if not isinstance(bundle, NativeInferenceReportBundle):
        raise TypeError("bundle must be a NativeInferenceReportBundle.")
    output_path = _validated_output_path(path)
    log = log_callback or (lambda _message: None)
    frames = bundle.to_frames(export_path=output_path)
    return _write_frames_atomic(
        frames,
        output_path,
        mode=bundle.mode,
        log=log,
    )


def write_native_numeric_workbook(
    prepared_payload: object | None,
    prior_results: Mapping[object, object] | None,
    path: str | Path,
    *,
    report_error: object | None = None,
    log_callback: Callable[[str], Any] | None = None,
) -> Path:
    """Write source/numeric frames even when narrative report assembly failed."""

    if prior_results is not None and not isinstance(prior_results, Mapping):
        raise TypeError("prior_results must be a mapping or None.")
    output_path = _validated_output_path(path)
    mode_value = getattr(getattr(prepared_payload, "mode", None), "value", None)
    mode = str(mode_value or "unknown")
    frames: OrderedDict[str, pd.DataFrame] = OrderedDict()
    frames["Numeric Export Metadata"] = pd.DataFrame(
        [
            {
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "mode": mode,
                "narrative_status": (
                    "failed" if report_error is not None else "not_requested"
                ),
                "export_path": str(output_path),
            }
        ]
    )
    if report_error is not None:
        frames["Report Failure"] = pd.DataFrame(
            [
                {
                    "status": "narrative_report_failed",
                    "error_type": type(report_error).__name__,
                    "error": str(report_error),
                    "numeric_results_preserved": True,
                }
            ]
        )
    for name, frame in normalize_inputs(
        prepared_payload,
        prior_results or {},
    ).items():
        output_name = name
        if output_name in frames:
            output_name = unique_frame_name(
                f"Source - {output_name}",
                frames,
            )
        frames[output_name] = frame
    log = log_callback or (lambda _message: None)
    return _write_frames_atomic(
        frames,
        output_path,
        mode=mode,
        log=log,
    )


__all__ = [
    "write_native_inference_workbook",
    "write_native_numeric_workbook",
]
