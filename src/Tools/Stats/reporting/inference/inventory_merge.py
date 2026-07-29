"""Merge declared scientific metadata into computed inventory rows."""

from __future__ import annotations

import pandas as pd


MERGED_METADATA_FIELDS = (
    "test_label",
    "method",
    "estimand",
    "alternative",
    "profile",
    "role",
    "followup_provenance",
    "family_id",
    "family_label",
    "family_size",
    "adjustment_method",
    "formula",
    "interpretation",
    "harmonic_provenance",
    "assumption_status",
)
DECLARATION_AUTHORITATIVE_FIELDS = frozenset(
    {
        "method",
        "estimand",
        "alternative",
        "profile",
        "role",
        "followup_provenance",
        "formula",
        "interpretation",
        "harmonic_provenance",
        "assumption_status",
    }
)


def _has_value(value: object) -> bool:
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return bool(str(value).strip())


def merge_declared_and_computed_rows(
    declared: list[dict[str, object]],
    computed: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach declarations by test ID and optional Condition/ROI identity."""

    merged = [dict(row) for row in computed]
    unmatched: list[dict[str, object]] = []
    for declaration in declared:
        test_id = str(declaration.get("test_id") or "").strip()
        candidates = [
            row
            for row in merged
            if test_id and str(row.get("test_id") or "").strip() == test_id
        ]
        for cell_field in ("condition", "roi"):
            declared_cell = declaration.get(cell_field)
            if not _has_value(declared_cell):
                continue
            candidates = [
                row
                for row in candidates
                if str(row.get(cell_field)) == str(declared_cell)
            ]
        if not candidates:
            unmatched.append(dict(declaration))
            continue
        for target in candidates:
            for field in MERGED_METADATA_FIELDS:
                declared_value = declaration.get(field)
                if _has_value(declared_value) and (
                    field in DECLARATION_AUTHORITATIVE_FIELDS
                    or not _has_value(target.get(field))
                ):
                    target[field] = declaration[field]
    return [*merged, *unmatched]


__all__ = ["merge_declared_and_computed_rows"]
