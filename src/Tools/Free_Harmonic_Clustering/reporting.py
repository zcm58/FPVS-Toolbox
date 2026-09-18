"""Read-only repeated-batch reporting; never selects or recalculates inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import AnalysisDesign, RepeatedSessionContrastFamily

if TYPE_CHECKING:
    from .api import RepeatedSessionBatchResult, RepeatedSessionContrastOutcome
    from .models import ClusterRecord


EXPLORATORY_CRITERION = (
    "Two-sided global p < .05 before cross-condition Holm correction, "
    "but family Holm p > .05. Full-batch Holm is shown separately."
)


@dataclass(frozen=True, slots=True)
class RepeatedSessionReportRow:
    """Compact display data with the original outcome index for map navigation."""

    run_index: int
    family_id: str
    family_label: str
    condition: str
    within_run_cluster_count: int
    global_p: float
    holm_family_p: float
    holm_batch_p: float
    is_exploratory: bool
    detail_text: str
    exploratory_cluster_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RepeatedSessionReport:
    """Immutable reporting snapshot without participant or permutation arrays."""

    rows: tuple[RepeatedSessionReportRow, ...]

    @property
    def exploratory_count(self) -> int:
        return sum(row.is_exploratory for row in self.rows)


def _p_text(value: float) -> str:
    # Keep near-threshold values distinct from exactly .05 in the detail view.
    text = f"{value:.8g}"
    return repr(float(value)) if float(text) == 0.05 and value != 0.05 else text


def _cluster_detail(outcome: RepeatedSessionContrastOutcome, cluster: ClusterRecord) -> str:
    prepared = outcome.prepared_run.prepared
    direction = "greater than" if cluster.sign == "positive" else "less than"
    lines = [
        f"Cluster {cluster.cluster_id} ({cluster.sign}): A {direction} B",
        f"Within-run two-sided cluster p = {_p_text(cluster.adjusted_two_sided_p_value)}",
        f"Signed-tail cluster p = {_p_text(cluster.p_value)}; cluster mass = {cluster.mass:.6g}",
    ]
    if cluster.effect_size is not None:
        lines.append(
            f"Descriptive effect ({cluster.effect_size_kind}) = {cluster.effect_size:.6g} "
            "(estimated from the selected cluster)"
        )
    # Describe actual node membership by harmonic, never a sensor-union x
    # harmonic-union product that would add nodes absent from the cluster.
    members: dict[int, list[str]] = {}
    for sensor_index, harmonic_index in zip(cluster.sensor_indices, cluster.harmonic_indices, strict=True):
        members.setdefault(harmonic_index, []).append(prepared.sensor_names[sensor_index])
    lines.append("Electrodes in this cluster, by harmonic:")
    for harmonic_index, sensors in sorted(members.items()):
        order = int(prepared.harmonic_orders[harmonic_index])
        hz = float(prepared.harmonics_hz[harmonic_index])
        lines.append(f"  H{order} ({hz:g} Hz): {', '.join(sensors)}")
    return "\n".join(lines)


def _detail_text(outcome: RepeatedSessionContrastOutcome, is_exploratory: bool) -> str:
    run = outcome.prepared_run
    prepared = run.prepared
    if is_exploratory:
        status = "Exploratory finding: p < .05 before Holm; does not pass family Holm."
    elif outcome.holm_within_family_p_value <= 0.05:
        status = "Passes Holm correction within its prespecified contrast family."
    else:
        status = "Does not meet the exploratory p < .05 criterion or pass family Holm."
    lines = [
        status,
        "",
        f"Condition: {run.condition}",
        f"Comparison: {run.family_label}",
        "",
        f"Global p before cross-condition Holm: {_p_text(outcome.global_two_sided_p_value)}",
        f"Holm p across conditions in this family: {_p_text(outcome.holm_within_family_p_value)}",
        f"Holm p across the full batch: {_p_text(outcome.holm_all_batch_p_value)}",
        "The global p already uses within-run maximum-cluster correction. "
        "Holm values describe this comparison, not individual clusters or electrodes.",
        "",
        "What was compared (A minus B)",
        f"A: {prepared.arm_a_label}",
        f"B: {prepared.arm_b_label}",
    ]
    if prepared.request.design is AnalysisDesign.PAIRED_CONDITIONS:
        lines.append(f"Complete participants: {len(prepared.participant_ids_a)} paired across the two sessions.")
    else:
        lines.append(
            f"Complete participants: A n = {len(prepared.participant_ids_a)}; "
            f"B n = {len(prepared.participant_ids_b)} (both sessions per participant)."
        )
    if run.family is RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE:
        lines.append(
            "This compares session differences between groups. Its sign alone does not "
            "tell you whether either group increased or decreased."
        )
    elif run.family is RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS:
        lines.append("Each participant's two sessions were averaged before normalization and group comparison.")
    else:
        lines.append("The two session profiles were normalized separately before the paired comparison.")
    lines.extend(
        [
            "FHC measures the normalized electrode-by-harmonic response pattern, not total response amplitude.",
            "",
            "Clusters with within-run two-sided p < .05",
        ]
    )
    clusters = tuple(cluster for cluster in outcome.result.clusters if cluster.adjusted_two_sided_p_value < 0.05)
    if clusters:
        lines.extend(_cluster_detail(outcome, cluster) + "\n" for cluster in clusters)
    else:
        lines.append("No clusters meet this strict reporting threshold.")
    lines.extend(
        [
            "Interpretation",
            "Exploratory findings are leads for follow-up, not findings confirmed after family Holm correction. "
            "All comparisons remain in the main results; this view does not rerun tests or recalculate correction.",
            "Cluster locations and effect sizes are descriptive after selection; individual electrodes and "
            "harmonics are not established as pointwise significant.",
            "With fixed session order, phase/session differences also include visit order, elapsed time, and retest effects.",
            "The legacy FHC calibration does not validate the repeated-session extension; see Methods and Provenance.",
        ]
    )
    return "\n".join(lines)


def build_repeated_session_report(result: RepeatedSessionBatchResult) -> RepeatedSessionReport:
    """Report stored p-values, preserving the original order and Holm boundary.

    Existing inference treats family Holm p <= .05 as passing. The requested
    exploratory view uses strict pre-Holm p < .05 and excludes those passes,
    including cases that fail only the secondary full-batch correction.
    """

    rows = []
    for index, outcome in enumerate(result.outcomes):
        exploratory = outcome.global_two_sided_p_value < 0.05 and outcome.holm_within_family_p_value > 0.05
        rows.append(
            RepeatedSessionReportRow(
                run_index=index,
                family_id=outcome.family_id,
                family_label=outcome.prepared_run.family_label,
                condition=outcome.condition,
                within_run_cluster_count=sum(cluster.significant for cluster in outcome.result.clusters),
                global_p=outcome.global_two_sided_p_value,
                holm_family_p=outcome.holm_within_family_p_value,
                holm_batch_p=outcome.holm_all_batch_p_value,
                is_exploratory=exploratory,
                detail_text=_detail_text(outcome, exploratory),
                exploratory_cluster_ids=tuple(
                    cluster.cluster_id
                    for cluster in outcome.result.clusters
                    if exploratory and cluster.adjusted_two_sided_p_value < 0.05
                ),
            )
        )
    return RepeatedSessionReport(rows=tuple(rows))
