"""Demo condition definitions for the LORETA visualizer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoLoretaCondition:
    """Tool-local synthetic condition metadata."""

    condition_id: str
    label: str
    activation_region: str
    source_model: str


DEMO_LORETA_CONDITIONS: tuple[DemoLoretaCondition, ...] = (
    DemoLoretaCondition(
        condition_id="occipital",
        label="Occipital demo condition",
        activation_region="occipital",
        source_model="volume_grid",
    ),
    DemoLoretaCondition(
        condition_id="frontal",
        label="Frontal demo condition",
        activation_region="frontal",
        source_model="volume_grid",
    ),
    DemoLoretaCondition(
        condition_id="deep_medial_temporal",
        label="Deep medial temporal demo",
        activation_region="deep_medial_temporal",
        source_model="volume_grid",
    ),
)


def default_condition() -> DemoLoretaCondition:
    """Return the default demo condition."""
    return DEMO_LORETA_CONDITIONS[0]


def condition_by_id(condition_id: str) -> DemoLoretaCondition:
    """Return a demo condition by id, falling back to the default."""
    for condition in DEMO_LORETA_CONDITIONS:
        if condition.condition_id == condition_id:
            return condition
    return default_condition()
