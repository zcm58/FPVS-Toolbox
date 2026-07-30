"""Reporting limitations for secondary ANOVA compatibility checks."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.frames import column, first_nonmissing


LimitationEntry = tuple[str, str, str, str]


def _named_frame(
    frames: Mapping[str, pd.DataFrame],
    requested: str,
) -> pd.DataFrame | None:
    requested_key = requested.casefold()
    for name, frame in frames.items():
        name_key = name.casefold()
        if name_key == requested_key or name_key.startswith(
            f"{requested_key} ("
        ):
            return frame
    return None


def anova_compatibility_limitation_entries(
    frames: Mapping[str, pd.DataFrame],
    *,
    mode: str,
) -> list[LimitationEntry]:
    """Describe a completed or skipped check without changing LMM findings."""

    entries: list[LimitationEntry] = []
    compatibility = _named_frame(frames, "ANOVA Compatibility")
    status_frame = _named_frame(frames, "ANOVA Compatibility Status")
    has_numeric_results = (
        isinstance(compatibility, pd.DataFrame)
        and not compatibility.empty
        and column(
            compatibility,
            "p_adjusted",
            "p_reported",
            "p_value",
            "p",
            "Pr > F",
        )
        is not None
    )
    if has_numeric_results:
        entries.append(
            (
                "information",
                "method",
                "anova_compatibility_secondary",
                "ANOVA compatibility results are secondary balanced-design "
                "checks only; they do not gate, replace, or change the primary "
                "LMM screening conclusion.",
            )
        )
        if mode == "multi":
            entries.append(
                (
                    "information",
                    "method",
                    "anova_multi_broad_response_cell",
                    "The broad Group x response-cell ANOVA compatibility check "
                    "does not decompose Group x Condition, Group x ROI, or "
                    "Group x Condition x ROI.",
                )
            )
    if not isinstance(status_frame, pd.DataFrame) or status_frame.empty:
        return entries
    status_value = first_nonmissing(
        status_frame.iloc[0],
        ("status", "step_status", "compatibility_status"),
    )
    if str(status_value or "").strip().casefold() != "skipped":
        return entries
    reason = first_nonmissing(
        status_frame.iloc[0],
        ("message", "reason", "skip_reason", "reason_code"),
    )
    reason_text = str(reason or "").strip().rstrip(".")
    suffix = f": {reason_text}" if reason_text else ""
    entries.append(
        (
            "information",
            "method",
            "anova_compatibility_skipped",
            "The secondary ANOVA compatibility check was skipped"
            f"{suffix}. The primary LMM screening was unaffected.",
        )
    )
    return entries


__all__ = ["anova_compatibility_limitation_entries"]
