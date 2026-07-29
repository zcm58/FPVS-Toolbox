"""Canonical test-inventory extraction from heterogeneous result frames."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.frames import (
    finite_float,
    first_nonmissing,
    select_p_column,
)
from Tools.Stats.reporting.inference.inventory_adapters import (
    canonical_reject,
    effect_size_fields,
    estimand_for,
    estimate_fields,
    frame_is_result,
    headline_contract,
    label_for,
    method_for,
    n_for,
    role_for,
    row_status,
    run_defaults,
    section_for,
)
from Tools.Stats.reporting.inference.inventory_merge import (
    merge_declared_and_computed_rows,
)
from Tools.Stats.reporting.inference.inventory_schema import INVENTORY_COLUMNS


def _formula(row: pd.Series) -> str:
    parts = [
        f"{label}: {value}"
        for label, value in (
            ("full", first_nonmissing(row, ("full_formula",))),
            ("reduced", first_nonmissing(row, ("reduced_formula",))),
        )
        if value is not None
    ]
    return "; ".join(parts)


def inventory_rows(
    frames: Mapping[str, pd.DataFrame],
    *,
    alpha: float,
    default_n: object | None = None,
) -> list[dict[str, object]]:
    """Extract computed test rows using canonical p-value precedence."""

    rows: list[dict[str, object]] = []
    defaults = run_defaults(frames)
    for frame_name, frame in frames.items():
        if frame.empty or not frame_is_result(frame_name, frame):
            continue
        p_column, p_source = select_p_column(frame)
        if p_column is None:
            continue
        section = section_for(frame_name, frame)
        for row_index, row in frame.iterrows():
            status, reportable = row_status(row)
            p_value = finite_float(row[p_column])
            if p_value is not None and not 0.0 <= p_value <= 1.0:
                p_value = None
                reportable = False
                status = f"{status}; invalid_p_value"
            row_alpha = finite_float(first_nonmissing(row, ("alpha",)))
            if row_alpha is None or not 0.0 < row_alpha < 1.0:
                row_alpha = alpha
            reject, reject_source = canonical_reject(
                row,
                p_value=p_value,
                alpha=row_alpha,
                p_source=p_source,
            )
            headline_eligible, headline_reason = headline_contract(
                frame_name=frame_name,
                p_source=p_source,
                row=row,
            )
            estimate, ci_low, ci_high = estimate_fields(row)
            effect_label, effect_value = effect_size_fields(row)
            observed_n = n_for(row)
            explicit_test_id = first_nonmissing(row, ("test_id",))
            condition = first_nonmissing(row, ("condition", "Condition"))
            roi = first_nonmissing(row, ("roi", "ROI"))
            assumption_status = first_nonmissing(
                row,
                (
                    "assumption_status",
                    "sphericity_status",
                    "diagnostic_status",
                    "model_status",
                ),
            )
            if assumption_status is None:
                assumption_status = "see diagnostic source frames"
            rows.append(
                {
                    "test_id": (
                        str(explicit_test_id)
                        if explicit_test_id is not None
                        else f"{frame_name.replace(' ', '_').lower()}_{row_index}"
                    ),
                    "section": section,
                    "source_frame": frame_name,
                    "test_label": label_for(section, row),
                    "method": method_for(frame_name, row, p_source),
                    "estimand": estimand_for(section, row),
                    "alternative": first_nonmissing(row, ("alternative",))
                    or defaults["alternative"],
                    "profile": first_nonmissing(
                        row, ("analysis_profile", "profile")
                    )
                    or defaults["profile"],
                    "role": role_for(frame_name, row),
                    "followup_provenance": first_nonmissing(
                        row, ("followup_provenance",)
                    ),
                    "status": status,
                    "assumption_status": assumption_status,
                    "reportable": reportable,
                    "headline_eligible": headline_eligible,
                    "headline_reason": headline_reason,
                    "n": observed_n if observed_n is not None else default_n,
                    "estimate": estimate,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "effect_size_name": effect_label,
                    "effect_size": effect_value,
                    "p_value_used": p_value,
                    "p_value_column": p_column,
                    "p_value_source": p_source,
                    "significant": (
                        reject if reportable and reject is not None else None
                    ),
                    "alpha": row_alpha,
                    "family_id": first_nonmissing(
                        row, ("family_id", "multiplicity_family_id")
                    ),
                    "family_label": first_nonmissing(
                        row, ("family_label",)
                    ),
                    "family_size": first_nonmissing(
                        row, ("family_size",)
                    ),
                    "adjustment_method": first_nonmissing(
                        row, ("adjustment_method", "p_correction")
                    ),
                    "canonical_reject": reject,
                    "reject_source": reject_source,
                    "formula": _formula(row),
                    "interpretation": first_nonmissing(
                        row,
                        (
                            "interpretation",
                            "effect_size_method",
                            "notes",
                            "note",
                        ),
                    ),
                    "harmonic_provenance": first_nonmissing(
                        row, ("harmonic_provenance",)
                    )
                    or defaults["harmonic_provenance"],
                    "condition": condition,
                    "roi": roi,
                }
            )
    return rows


def explicit_inventory_rows(
    frames: Mapping[str, pd.DataFrame],
) -> list[dict[str, object]]:
    """Preserve test declarations supplied by analysis metadata."""

    rows: list[dict[str, object]] = []
    for frame_name, frame in frames.items():
        if "test inventory" not in frame_name.casefold() or frame.empty:
            continue
        for _, row in frame.iterrows():
            rows.append(_declaration_row(frame_name, row))
    return rows


def _declaration_row(
    frame_name: str,
    row: pd.Series,
) -> dict[str, object]:
    return {
        "test_id": first_nonmissing(row, ("test_id",)) or "",
        "section": first_nonmissing(row, ("section", "scope")) or "declared",
        "source_frame": frame_name,
        "test_label": first_nonmissing(row, ("test_label",)) or "",
        "method": first_nonmissing(row, ("method",)) or "",
        "estimand": first_nonmissing(row, ("estimand",)),
        "alternative": first_nonmissing(row, ("alternative",)),
        "profile": first_nonmissing(row, ("analysis_profile", "profile")),
        "role": first_nonmissing(row, ("role",)) or "primary",
        "followup_provenance": first_nonmissing(
            row, ("followup_provenance",)
        ),
        "status": first_nonmissing(row, ("status",)) or "declared",
        "assumption_status": first_nonmissing(row, ("assumption_status",)),
        "reportable": first_nonmissing(row, ("reportable",)),
        "headline_eligible": False,
        "headline_reason": "declaration_without_numeric_result",
        "n": first_nonmissing(row, ("n", "N", "N_Pairs")),
        "estimate": first_nonmissing(row, ("estimate",)),
        "ci_low": first_nonmissing(row, ("ci_low", "ci95_low")),
        "ci_high": first_nonmissing(row, ("ci_high", "ci95_high")),
        "effect_size_name": first_nonmissing(
            row, ("effect_size_name",)
        )
        or "",
        "effect_size": first_nonmissing(row, ("effect_size",)),
        "p_value_used": first_nonmissing(row, ("p_value_used",)),
        "p_value_column": first_nonmissing(row, ("p_value_column",)) or "",
        "p_value_source": first_nonmissing(row, ("p_value_source",))
        or "declared",
        "significant": first_nonmissing(row, ("significant",)),
        "alpha": first_nonmissing(row, ("alpha",)),
        "family_id": first_nonmissing(row, ("family_id",)),
        "family_label": first_nonmissing(row, ("family_label",)),
        "family_size": first_nonmissing(row, ("family_size",)),
        "adjustment_method": first_nonmissing(
            row, ("adjustment_method",)
        ),
        "canonical_reject": first_nonmissing(
            row, ("canonical_reject", "reject_adjusted")
        ),
        "reject_source": "declared",
        "formula": first_nonmissing(row, ("formula",)) or "",
        "interpretation": first_nonmissing(
            row, ("interpretation", "notes")
        ),
        "harmonic_provenance": first_nonmissing(
            row, ("harmonic_provenance",)
        ),
        "condition": first_nonmissing(row, ("condition", "Condition")),
        "roi": first_nonmissing(row, ("roi", "ROI")),
    }


__all__ = [
    "INVENTORY_COLUMNS",
    "explicit_inventory_rows",
    "inventory_rows",
    "merge_declared_and_computed_rows",
]
