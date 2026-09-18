"""Small GUI-neutral snapshots of descriptive FHC scalp maps.

The background is an arm-mean difference in the actual analyzed tensors.
Membership remains the original sensor-major electrode x harmonic membership;
neither the background nor a harmonic slice creates a new statistical test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .models import AnalysisDesign, ClusterPermutationResult, ClusterRecord, PreparedContrast

if TYPE_CHECKING:
    from .api import RepeatedSessionContrastOutcome


@dataclass(frozen=True, slots=True)
class ClusterMapData:
    """Immutable, participant-free sensor x harmonic display snapshot."""

    sensor_names: tuple[str, ...]
    harmonic_orders: tuple[int, ...]
    harmonics_hz: tuple[float, ...]
    mean_difference: np.ndarray
    cluster_labels: np.ndarray
    clusters: tuple[ClusterRecord, ...]
    arm_a_label: str
    arm_b_label: str
    run_label: str = ""
    value_label: str = "Mean normalized SNR difference"
    multiplicity_note: str = ""

    def __post_init__(self) -> None:
        sensors = tuple(str(value) for value in self.sensor_names)
        orders = tuple(int(value) for value in self.harmonic_orders)
        frequencies = tuple(float(value) for value in self.harmonics_hz)
        if not sensors or len({value.casefold() for value in sensors}) != len(sensors):
            raise ValueError("Map sensor names must be non-empty and unique.")
        if any(not value.strip() for value in sensors):
            raise ValueError("Map sensor names must not be blank.")
        if not orders or len(orders) != len(frequencies):
            raise ValueError("Map harmonic orders and frequencies must align.")
        if (
            any(value < 1 for value in orders)
            or len(set(orders)) != len(orders)
            or any(not np.isfinite(value) or value <= 0 for value in frequencies)
        ):
            raise ValueError("Map harmonics must have unique positive orders and finite positive frequencies.")
        difference = np.array(self.mean_difference, dtype=np.float64, copy=True, order="C")
        labels = np.array(self.cluster_labels, dtype=np.int64, copy=True, order="C")
        shape = (len(sensors), len(orders))
        if difference.shape != shape or labels.shape != shape:
            raise ValueError(f"Map difference and cluster labels must have shape {shape}.")
        if not np.all(np.isfinite(difference)):
            raise ValueError("Map differences must be finite.")
        clusters = tuple(self.clusters)
        if any(not cluster.significant for cluster in clusters):
            raise ValueError("Map cluster records must contain significant clusters only.")
        _validate_membership(labels, clusters)
        difference.setflags(write=False)
        labels.setflags(write=False)
        object.__setattr__(self, "sensor_names", sensors)
        object.__setattr__(self, "harmonic_orders", orders)
        object.__setattr__(self, "harmonics_hz", frequencies)
        object.__setattr__(self, "mean_difference", difference)
        object.__setattr__(self, "cluster_labels", labels)
        object.__setattr__(self, "clusters", clusters)
        for name in ("arm_a_label", "arm_b_label", "run_label", "value_label", "multiplicity_note"):
            object.__setattr__(self, name, str(getattr(self, name)))

    @property
    def color_limit(self) -> float:
        """One finite symmetric scale for every harmonic and cluster filter."""

        limit = float(np.max(np.abs(self.mean_difference)))
        return limit if limit > 0 else 1.0


def _validate_membership(labels: np.ndarray, clusters: tuple[ClusterRecord, ...]) -> None:
    records = {cluster.cluster_id: cluster for cluster in clusters}
    if len(records) != len(clusters):
        raise ValueError("Map cluster IDs must be unique.")
    observed_ids = {int(value) for value in np.unique(labels) if value != 0}
    if observed_ids != set(records):
        raise ValueError("Map cluster labels and records contain different IDs.")
    sensor_count, harmonic_count = labels.shape
    flat_labels = labels.reshape(-1)
    for cluster in clusters:
        nodes = cluster.node_indices
        if len(set(nodes)) != len(nodes):
            raise ValueError("Map cluster membership must contain unique nodes.")
        for node, sensor, harmonic in zip(
            nodes, cluster.sensor_indices, cluster.harmonic_indices, strict=True
        ):
            if sensor >= sensor_count or harmonic >= harmonic_count:
                raise ValueError("Map cluster membership index exceeds the result tensor.")
            if node != sensor * harmonic_count + harmonic or flat_labels[node] != cluster.cluster_id:
                raise ValueError("Map cluster membership does not match sensor-major labels.")
        if set(np.flatnonzero(flat_labels == cluster.cluster_id)) != set(nodes):
            raise ValueError("Map labels contain members absent from the cluster record.")


def _value_label(prepared: PreparedContrast) -> str:
    family_id = prepared.request.contrast_family_id
    if family_id == "group_session_change":
        return "Mean normalized SNR change difference"
    if family_id == "session_averaged_groups":
        return "Mean session-averaged normalized SNR difference"
    if family_id and family_id.startswith("paired_sessions_within_group"):
        return "Mean normalized SNR session difference"
    return "Mean normalized SNR difference"


def build_cluster_map_data(
    prepared: PreparedContrast,
    result: ClusterPermutationResult,
    *,
    run_label: str = "",
    multiplicity_note: str = "",
) -> ClusterMapData:
    """Reduce analyzed tensors without retaining participants or null arrays."""

    if result.design is not prepared.request.design:
        raise ValueError("Prepared contrast and map result designs do not match.")
    shape = (len(prepared.sensor_names), len(prepared.harmonics_hz))
    if result.observed_t.shape != shape or result.cluster_labels.shape != shape:
        raise ValueError(f"Map result must have shape {shape}.")
    _validate_membership(result.cluster_labels, result.clusters)
    for cluster in result.clusters:
        node_t = result.observed_t.reshape(-1)[list(cluster.node_indices)]
        if not np.all(node_t * np.sign(cluster.cluster_id) > 0):
            raise ValueError("Cluster sign must match its observed node statistics.")
    clusters = tuple(sorted(
        (cluster for cluster in result.clusters if cluster.significant),
        key=lambda cluster: (cluster.p_value, cluster.cluster_id),
    ))
    significant_ids = tuple(cluster.cluster_id for cluster in clusters)
    labels = np.where(np.isin(result.cluster_labels, significant_ids), result.cluster_labels, 0)
    # Repeated composite tensors have already been constructed by preparation.
    # Do not normalize again, pool sessions, or use candidate SNR/t values here.
    if prepared.request.design is AnalysisDesign.PAIRED_CONDITIONS:
        # Match the analyzed paired contrast before averaging: subtracting two
        # nearly equal arm means could otherwise erase a small valid effect.
        mean_difference = np.mean(prepared.values_a - prepared.values_b, axis=0)
    else:
        mean_difference = np.mean(prepared.values_a, axis=0) - np.mean(prepared.values_b, axis=0)
    return ClusterMapData(
        sensor_names=prepared.sensor_names,
        harmonic_orders=tuple(int(value) for value in prepared.harmonic_orders),
        harmonics_hz=tuple(float(value) for value in prepared.harmonics_hz),
        mean_difference=mean_difference,
        cluster_labels=labels,
        clusters=clusters,
        arm_a_label=prepared.arm_a_label,
        arm_b_label=prepared.arm_b_label,
        run_label=run_label or prepared.request.condition_a,
        value_label=_value_label(prepared),
        multiplicity_note=multiplicity_note,
    )


def build_repeated_cluster_map_data(outcome: RepeatedSessionContrastOutcome) -> ClusterMapData:
    """Keep repeated-run identity and run-level Holm annotations together."""

    run = outcome.prepared_run
    note = (
        f"Raw cluster p values are within-run, sign-specific. "
        f"Run-global two-sided p = {outcome.global_two_sided_p_value:.4g}; "
        f"Holm within family p = {outcome.holm_within_family_p_value:.4g}; "
        f"Holm across batch p = {outcome.holm_all_batch_p_value:.4g}. "
        "Holm values apply to the run, not individual clusters. "
        "Session differences include fixed visit/order, elapsed-time, and retest effects."
    )
    return build_cluster_map_data(
        run.prepared,
        outcome.result,
        run_label=f"{run.condition} | {run.family_label}",
        multiplicity_note=note,
    )


__all__ = ["ClusterMapData", "build_cluster_map_data", "build_repeated_cluster_map_data"]
