"""User-facing error messages for Stats window worker failures."""

from __future__ import annotations

import ast
from dataclasses import dataclass


_GROUP_FULLFFT_GRID_MARKERS = (
    "Group-level significant harmonic selection requires matching FullFFT candidate",
    "Group-level significant harmonic selection requires exact nominal oddball harmonic columns",
)


@dataclass(frozen=True)
class WorkerErrorGuidance:
    """A clearer GUI message for a known worker failure."""

    title: str
    message: str
    status: str


def build_worker_error_guidance(raw_message: str) -> WorkerErrorGuidance | None:
    """Return clearer guidance for known Stats worker errors."""
    message = str(raw_message or "")
    if any(marker in message for marker in _GROUP_FULLFFT_GRID_MARKERS):
        return _build_fullfft_grid_guidance(message)
    return None


def _build_fullfft_grid_guidance(raw_message: str) -> WorkerErrorGuidance:
    file_path, missing_columns = _extract_missing_fullfft_details(raw_message)
    details: list[str] = [
        "The Stats-Ready export stopped before reading amplitude values because "
        "the default group-level significant harmonics policy needs matching "
        "FullFFT frequency columns in every included workbook.",
        "",
        "At least one included workbook uses a different FullFFT grid. This commonly "
        "happens when a participant-condition has a much shorter usable on-bin crop, "
        "such as an interrupted condition, missing oddball markers, a recording cut, "
        "or an event-map mismatch.",
    ]
    if file_path:
        details.extend(["", f"First workbook with the mismatch:\n{file_path}"])
    if missing_columns:
        details.extend(
            [
                "",
                "Example missing neighboring-noise columns:\n"
                + ", ".join(missing_columns[:8]),
            ]
        )
    details.extend(
        [
            "",
            "Reprocess that participant-condition if the raw recording should contain "
            "the full condition. Otherwise, exclude that workbook from this export, "
            "or switch to Fixed/predefined harmonics if that matches the analysis plan.",
        ]
    )
    return WorkerErrorGuidance(
        title="Stats-Ready Export Needs Matching FullFFT Grids",
        message="\n".join(details),
        status="Stats-ready export needs matching FullFFT grids.",
    )


def _extract_missing_fullfft_details(raw_message: str) -> tuple[str, list[str]]:
    for marker in ("Missing columns in ", "Missing candidate columns in "):
        if marker not in raw_message:
            continue
        tail = raw_message.split(marker, 1)[1]
        path_text, sep, columns_text = tail.rpartition(": ")
        if not sep:
            return tail.strip(), []
        return path_text.strip(), _parse_missing_columns(columns_text.strip())
    return "", []


def _parse_missing_columns(text: str) -> list[str]:
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]
