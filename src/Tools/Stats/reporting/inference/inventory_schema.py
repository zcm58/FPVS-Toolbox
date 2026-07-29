"""Stable columns for the canonical native-inference test inventory."""

from __future__ import annotations


INVENTORY_COLUMNS = [
    "test_id",
    "section",
    "source_frame",
    "test_label",
    "method",
    "estimand",
    "alternative",
    "profile",
    "role",
    "followup_provenance",
    "status",
    "assumption_status",
    "reportable",
    "headline_eligible",
    "headline_reason",
    "n",
    "estimate",
    "ci_low",
    "ci_high",
    "effect_size_name",
    "effect_size",
    "p_value_used",
    "p_value_column",
    "p_value_source",
    "significant",
    "alpha",
    "family_id",
    "family_label",
    "family_size",
    "adjustment_method",
    "canonical_reject",
    "reject_source",
    "formula",
    "interpretation",
    "harmonic_provenance",
    "condition",
    "roi",
]


__all__ = ["INVENTORY_COLUMNS"]
