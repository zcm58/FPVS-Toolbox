"""Read-only presentation of a frozen FHC analysis plan and its results."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .models import AnalysisDesign
from .reporting import RepeatedSessionReport, RepeatedSessionReportRow, _p_text
from .visualization import ClusterMapData, build_cluster_map_data

if TYPE_CHECKING:
    from .planned_analysis import PlannedAnalysisResult, PlannedComparisonOutcome


def outcome_status(outcome: PlannedComparisonOutcome) -> str:
    if outcome.family_adjusted_p <= 0.05:
        return "Passes family Holm"
    if outcome.global_p < 0.05:
        return "Exploratory: does not pass family Holm"
    return "Does not pass family Holm"


def _details(outcome: PlannedComparisonOutcome, family_size: int) -> str:
    comparison, prepared = outcome.comparison, outcome.contrast
    lines = [
        outcome_status(outcome),
        "",
        f"Family: {comparison.family_label} ({family_size} planned comparisons)",
        f"Comparison: {comparison.label}",
        f"Condition: {comparison.condition}",
        "",
        f"Global p before cross-comparison Holm: {_p_text(outcome.global_p)}",
        f"Family Holm p: {_p_text(outcome.family_adjusted_p)}",
        f"Full-plan Holm p (additional conservative summary): {_p_text(outcome.batch_adjusted_p)}",
        "The global p already accounts for the within-comparison cluster search and both signs. "
        "Family Holm is the primary correction across planned comparisons. "
        "These Holm values apply to the comparison, not individual clusters or electrodes.",
        "",
        "What was compared (A minus B)",
        f"A: {prepared.arm_a_label}",
        f"B: {prepared.arm_b_label}",
    ]
    if comparison.design is AnalysisDesign.PAIRED_CONDITIONS:
        lines.append(f"Complete paired participants: {len(prepared.participant_ids_a)}")
    else:
        lines.append(f"Participants: A n = {len(prepared.participant_ids_a)}; B n = {len(prepared.participant_ids_b)}")
    if comparison.session_ids:
        if comparison.kind.value in {"between_groups", "between_conditions"}:
            lines.append(f"Averaged visits: {comparison.session_ids[0]} and {comparison.session_ids[1]}.")
        else:
            lines.append(f"Visit order: {comparison.session_ids[0]} minus {comparison.session_ids[1]}.")
        if comparison.kind.value == "group_visit_change":
            lines.append(
                "Each visit is normalized separately. The visit difference is not normalized again. "
                "The sign of this group difference does not show whether either group increased or decreased."
            )
        elif comparison.kind.value in {"between_groups", "between_conditions"}:
            lines.append(
                "Candidate SNR is averaged across both visits within participant and condition, "
                "then each resulting arm profile is normalized once."
            )
        else:
            lines.append("The two visit profiles are normalized separately before the paired comparison.")
    lines.extend(["", "Clusters with within-comparison two-sided p < .05"])
    clusters = tuple(c for c in outcome.result.clusters if c.adjusted_two_sided_p_value < 0.05)
    for cluster in clusters:
        lines.append(
            f"Cluster {cluster.cluster_id} ({cluster.sign}): two-sided cluster p = "
            f"{_p_text(cluster.adjusted_two_sided_p_value)}; mass = {cluster.mass:.6g}"
        )
        if cluster.effect_size is not None:
            lines.append(
                f"Descriptive effect ({cluster.effect_size_kind}) = {cluster.effect_size:.6g} "
                "(estimated after cluster selection)"
            )
        members: dict[int, list[str]] = {}
        for sensor, harmonic in zip(cluster.sensor_indices, cluster.harmonic_indices, strict=True):
            members.setdefault(harmonic, []).append(prepared.sensor_names[sensor])
        for harmonic, sensors in sorted(members.items()):
            lines.append(
                f"  H{int(prepared.harmonic_orders[harmonic])} "
                f"({float(prepared.harmonics_hz[harmonic]):g} Hz): {', '.join(sensors)}"
            )
    if not clusters:
        lines.append("No clusters meet this strict reporting threshold.")
    lines.extend(
        [
            "",
            "Interpretation",
            "Exploratory findings are leads for follow-up and did not survive family Holm correction. "
            "Filtering this report never changes the planned correction family.",
            "FHC compares normalized electrode-by-harmonic patterns, not total response amplitude. "
            "Cluster membership and selected effect sizes are descriptive; individual electrodes and harmonics "
            "are not established as pointwise significant.",
            "The legacy single-contrast calibration does not validate this planned family extension.",
        ]
    )
    if comparison.session_ids:
        lines.append("With fixed visit order, visit differences also include elapsed-time, order, and retest effects.")
    return "\n".join(lines)


def build_analysis_plan_report(result: PlannedAnalysisResult) -> RepeatedSessionReport:
    """Reuse the compact report contract while retaining original comparison indices."""
    sizes: dict[str, int] = {}
    for comparison in result.plan.comparisons:
        sizes[comparison.family_id] = sizes.get(comparison.family_id, 0) + 1
    rows = []
    for index, outcome in enumerate(result.outcomes):
        comparison = outcome.comparison
        exploratory = outcome.global_p < 0.05 and outcome.family_adjusted_p > 0.05
        rows.append(
            RepeatedSessionReportRow(
                run_index=index,
                family_id=comparison.family_id,
                family_label=comparison.family_label,
                condition=comparison.condition,
                within_run_cluster_count=sum(c.significant for c in outcome.result.clusters),
                global_p=outcome.global_p,
                holm_family_p=outcome.family_adjusted_p,
                holm_batch_p=outcome.batch_adjusted_p,
                is_exploratory=exploratory,
                detail_text=_details(outcome, sizes[comparison.family_id]),
                exploratory_cluster_ids=tuple(
                    c.cluster_id for c in outcome.result.clusters if exploratory and c.adjusted_two_sided_p_value < 0.05
                ),
                comparison_label=comparison.label,
            )
        )
    return RepeatedSessionReport(rows=tuple(rows))


def build_planned_cluster_map_data(outcome: PlannedComparisonOutcome) -> ClusterMapData:
    comparison = outcome.comparison
    note = (
        f"{comparison.family_label}: global p = {outcome.global_p:.4g}; "
        f"family Holm p = {outcome.family_adjusted_p:.4g}; "
        f"full-plan Holm p = {outcome.batch_adjusted_p:.4g}. "
        f"{outcome_status(outcome)}. Holm applies to the comparison, not individual clusters."
    )
    data = build_cluster_map_data(outcome.contrast, outcome.result, run_label=comparison.label, multiplicity_note=note)
    value_label = "Mean normalized SNR difference"
    if comparison.session_ids:
        if comparison.kind.value == "group_visit_change":
            value_label = "Mean normalized SNR visit-change difference"
        elif comparison.kind.value in {"between_groups", "between_conditions"}:
            value_label = "Mean visit-averaged normalized SNR difference"
        else:
            value_label = "Mean normalized SNR visit difference"
    return replace(data, value_label=value_label)
