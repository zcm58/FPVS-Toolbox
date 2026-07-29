"""Native-inference report orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from Tools.Stats.reporting.inference.bundle import (
    METHOD_DEPENDENT_PHRASE,
    NativeInferenceReportBundle,
    REPORT_SCHEMA_VERSION,
)
from Tools.Stats.reporting.inference.design import (
    design_summary,
    limitations_frame,
)
from Tools.Stats.reporting.inference.frames import normalize_inputs
from Tools.Stats.reporting.inference.inventory import (
    INVENTORY_COLUMNS,
    explicit_inventory_rows,
    inventory_rows,
    merge_declared_and_computed_rows,
)
from Tools.Stats.reporting.inference.language import (
    at_a_glance_text,
    detailed_methods_text,
)
from Tools.Stats.reporting.inference.methods import (
    correction_family_frame,
    methods_frame,
)


VALID_MODES = frozenset({"single", "multi"})


def _run_summary_frame(
    mode: str,
    alpha: float,
    frames: Mapping[str, pd.DataFrame],
    inventory: pd.DataFrame,
    design: Mapping[str, object],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "mode": mode,
                "alpha": alpha,
                "n_frozen_participants": design.get("n"),
                "n_groups": design.get("n_groups"),
                "complete_conditions": design.get("complete_conditions"),
                "excluded_conditions": design.get("excluded_conditions"),
                "n_source_frames": len(frames),
                "n_inventory_rows": len(inventory),
                "n_reportable_rows": int(
                    inventory.get("reportable", pd.Series(dtype=bool))
                    .eq(True)
                    .sum()
                ),
                "interpretation_rule": METHOD_DEPENDENT_PHRASE,
            }
        ]
    )


def _normalize_mode(mode: str) -> str:
    normalized = str(mode).strip().casefold().replace("-", "_")
    aliases = {
        "single_group": "single",
        "single": "single",
        "multi_group": "multi",
        "multigroup": "multi",
        "multi": "multi",
    }
    result = aliases.get(normalized, normalized)
    if result not in VALID_MODES:
        raise ValueError("mode must be 'single' or 'multi'.")
    return result


def build_native_inference_report(
    mode: str,
    prepared: object | None = None,
    step_payloads: Mapping[object, object] | None = None,
    *,
    alpha: float = 0.05,
    export_path: str | Path | None = None,
    prepared_payload: object | None = None,
    prior_results: Mapping[object, object] | None = None,
) -> NativeInferenceReportBundle:
    """Build a single- or multi-group native-inference report bundle.

    ``prepared_payload`` and ``prior_results`` are explicit aliases used by the
    pipeline worker. They cannot be supplied with their canonical counterparts.
    """

    normalized_mode = _normalize_mode(mode)
    alpha_value = float(alpha)
    if not 0.0 < alpha_value < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1.")
    if prepared is not None and prepared_payload is not None:
        raise ValueError("Supply prepared or prepared_payload, not both.")
    if step_payloads is not None and prior_results is not None:
        raise ValueError("Supply step_payloads or prior_results, not both.")
    prepared_value = prepared if prepared_payload is None else prepared_payload
    payload_values = step_payloads if prior_results is None else prior_results
    if payload_values is None:
        payload_values = {}
    if not isinstance(payload_values, Mapping):
        raise TypeError("step_payloads/prior_results must be a mapping.")

    frames = normalize_inputs(prepared_value, payload_values)
    design = design_summary(frames)
    inventory = pd.DataFrame(
        merge_declared_and_computed_rows(
            explicit_inventory_rows(frames),
            inventory_rows(
                frames,
                alpha=alpha_value,
                default_n=design.get("n"),
            ),
        ),
        columns=INVENTORY_COLUMNS,
    )
    if not inventory.empty:
        inventory = inventory.drop_duplicates(
            subset=[
                "source_frame",
                "test_id",
                "test_label",
                "p_value_column",
                "condition",
                "roi",
            ],
            keep="last",
        ).reset_index(drop=True)
    correction_families = correction_family_frame(inventory, frames)
    methods = methods_frame(inventory)
    limitations = limitations_frame(inventory, frames, design)
    return NativeInferenceReportBundle(
        mode=normalized_mode,
        named_frames=frames,
        test_inventory=inventory,
        methods=methods,
        limitations=limitations,
        correction_families=correction_families,
        run_summary=_run_summary_frame(
            normalized_mode,
            alpha_value,
            frames,
            inventory,
            design,
        ),
        at_a_glance=at_a_glance_text(
            normalized_mode,
            inventory,
            limitations,
            design,
            export_path=None if export_path is None else Path(export_path),
        ),
        detailed_methods=detailed_methods_text(
            normalized_mode,
            alpha_value,
            inventory,
            methods,
            limitations,
            correction_families,
            design,
        ),
        export_path=None if export_path is None else Path(export_path),
    )


__all__ = ["build_native_inference_report"]
