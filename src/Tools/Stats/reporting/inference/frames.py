"""Source-frame collection and scalar normalization helpers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
import re

import numpy as np
import pandas as pd

from Tools.Stats.reporting.inference.bundle import unique_frame_name


GENERIC_FRAME_KEYS = frozenset(
    {
        "data",
        "dataframe",
        "df",
        "frame",
        "result",
        "results",
        "table",
        "payload",
    }
)
WORKER_FRAME_KEYS = ("export_frames", "frames")
WORKER_ALIAS_KEYS = frozenset(
    {
        "export_frames",
        "frames",
        "prepared_payload",
        "primary_object",
        "result",
    }
)
P_VALUE_PRIORITY = (
    ("p_adjusted", "multiplicity_adjusted"),
    ("p_adjusted_max_t", "multiplicity_adjusted"),
    ("p_reported", "canonical_reported"),
    ("p_value_chi2", "likelihood_ratio"),
    ("p (chi2)", "likelihood_ratio"),
    ("p_value_wald", "wald"),
    ("P>|z|", "wald"),
    ("p_raw", "raw"),
    ("p_value", "raw"),
    ("p", "raw"),
    ("Pr > F", "raw"),
)


def display_key(value: object) -> str:
    """Convert enum/string payload keys to stable readable labels."""

    raw = getattr(value, "value", value)
    text = str(raw).strip()
    if not text:
        return "Unnamed"
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip().title()


def add_frame(
    frames: OrderedDict[str, pd.DataFrame],
    name: str,
    frame: pd.DataFrame,
) -> None:
    """Add a copied frame and preserve an explicit legacy LRT attachment."""

    for existing_name, existing in frames.items():
        if (
            existing_name == name
            or existing_name.startswith(f"{name} (")
        ) and existing.equals(frame):
            return
    output_name = unique_frame_name(name or "Unnamed", frames)
    frames[output_name] = frame.copy()
    lrt_table = frame.attrs.get("lrt_table")
    if isinstance(lrt_table, pd.DataFrame):
        lrt_name = unique_frame_name(f"{output_name} LRT", frames)
        frames[lrt_name] = lrt_table.copy()


def scalar_metadata_frame(value: Mapping[object, object]) -> pd.DataFrame:
    """Convert scalar metadata entries to an explicit field/value frame."""

    rows = []
    for key, item in value.items():
        if isinstance(item, (Mapping, pd.DataFrame, list, tuple, set)):
            if isinstance(item, (list, tuple, set)) and all(
                np.isscalar(member) or member is None for member in item
            ):
                rendered = "; ".join(map(str, item))
            else:
                continue
        elif np.isscalar(item) or item is None:
            rendered = item
        else:
            continue
        rows.append({"field": str(key), "value": rendered})
    return pd.DataFrame(rows, columns=["field", "value"])


def collect_payload_frames(
    value: object,
    *,
    label: str,
    frames: OrderedDict[str, pd.DataFrame],
    depth: int = 0,
) -> None:
    """Recursively collect supported frame-like payloads without mutating them."""

    if value is None or depth > 4:
        return
    if isinstance(value, pd.DataFrame):
        add_frame(frames, label, value)
        return
    to_frames = getattr(value, "to_frames", None)
    if callable(to_frames):
        result = to_frames()
        if isinstance(result, Mapping):
            for child_name, child in result.items():
                if isinstance(child, pd.DataFrame):
                    add_frame(frames, str(child_name), child)
            return
    if isinstance(value, Mapping):
        canonical_worker_frames: Mapping[object, object] | None = None
        for frame_key in WORKER_FRAME_KEYS:
            candidate = value.get(frame_key)
            if isinstance(candidate, Mapping):
                if canonical_worker_frames is None:
                    canonical_worker_frames = candidate
                if any(
                    isinstance(item, pd.DataFrame)
                    for item in candidate.values()
                ):
                    canonical_worker_frames = candidate
                    break
        if canonical_worker_frames is not None:
            for child_name, child in canonical_worker_frames.items():
                if isinstance(child, pd.DataFrame):
                    add_frame(frames, str(child_name), child)
            for raw_key, child in value.items():
                key_token = (
                    str(getattr(raw_key, "value", raw_key))
                    .strip()
                    .casefold()
                )
                if key_token in WORKER_ALIAS_KEYS:
                    continue
                if isinstance(child, pd.DataFrame):
                    add_frame(frames, display_key(raw_key), child)
                elif isinstance(child, Mapping) and (
                    "metadata" in key_token or "diagnostic" in key_token
                ):
                    collect_payload_frames(
                        child,
                        label=display_key(raw_key),
                        frames=frames,
                        depth=depth + 1,
                    )
            return
        scalar_frame = scalar_metadata_frame(value)
        if not scalar_frame.empty and (
            label.casefold().endswith("metadata")
            or "metadata" in {str(key).casefold() for key in value}
        ):
            add_frame(frames, f"{label} Metadata", scalar_frame)
        for raw_key, child in value.items():
            key = display_key(raw_key)
            key_token = str(getattr(raw_key, "value", raw_key)).strip().casefold()
            child_label = label if key_token in GENERIC_FRAME_KEYS else key
            if isinstance(child, pd.DataFrame):
                add_frame(frames, child_label, child)
            elif callable(getattr(child, "to_frames", None)) or isinstance(
                child, Mapping
            ):
                collect_payload_frames(
                    child,
                    label=child_label if child_label != label else label,
                    frames=frames,
                    depth=depth + 1,
                )
        return
    attributes = vars(value) if hasattr(value, "__dict__") else {}
    for attribute in (
        "design",
        "design_audit",
        "frames",
        "named_frames",
        "metadata",
        "result",
        "results",
        "table",
    ):
        if attribute in attributes:
            collect_payload_frames(
                attributes[attribute],
                label=display_key(attribute),
                frames=frames,
                depth=depth + 1,
            )


def normalize_inputs(
    prepared: object | None,
    step_payloads: Mapping[object, object],
) -> OrderedDict[str, pd.DataFrame]:
    """Collect prepared/design and step results into one ordered frame mapping."""

    frames: OrderedDict[str, pd.DataFrame] = OrderedDict()
    collect_payload_frames(prepared, label="Prepared Data", frames=frames)
    for step, payload in step_payloads.items():
        collect_payload_frames(payload, label=display_key(step), frames=frames)
    return frames


def column(frame: pd.DataFrame, *names: str) -> str | None:
    """Find a column case-insensitively."""

    by_casefold = {str(item).casefold(): str(item) for item in frame.columns}
    for name in names:
        match = by_casefold.get(name.casefold())
        if match is not None:
            return match
    return None


def first_nonmissing(row: pd.Series, names: tuple[str, ...]) -> object | None:
    """Return the first scalar non-missing value among candidate columns."""

    by_casefold = {str(item).casefold(): item for item in row.index}
    for name in names:
        item = by_casefold.get(name.casefold())
        if item is None:
            continue
        value = row[item]
        if value is not None and not bool(pd.isna(value)):
            return value
    return None


def finite_float(value: object) -> float | None:
    """Coerce a finite numeric scalar, otherwise return ``None``."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def bool_value(value: object, *, default: bool) -> bool:
    """Coerce common exported boolean labels."""

    if value is None or bool(pd.isna(value)):
        return default
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "ok", "estimated", "reportable"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return bool(value)


def select_p_column(frame: pd.DataFrame) -> tuple[str | None, str]:
    """Select at frame level so adjusted missing values never fall back to raw."""

    for candidate, source in P_VALUE_PRIORITY:
        match = column(frame, candidate)
        if match is not None:
            return match, source
    return None, "unavailable"


__all__ = [
    "bool_value",
    "column",
    "display_key",
    "finite_float",
    "first_nonmissing",
    "normalize_inputs",
    "select_p_column",
]
