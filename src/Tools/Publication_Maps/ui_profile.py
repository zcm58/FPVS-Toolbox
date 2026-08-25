"""GUI-neutral presentation profiles for the embedded Scalp Maps page."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScalpMapsUiMode(str, Enum):
    """Stable presentation states derived from project and workflow capabilities."""

    SINGLE_GROUP = "single_group"
    MULTI_GROUP = "multi_group"
    REPEATED_CONDITION = "repeated_condition"
    REPEATED_SESSION_COMPARISON = "repeated_session_comparison"


@dataclass(frozen=True, slots=True)
class ScalpMapsUiProfile:
    """Visibility and reflow decisions that do not depend on Qt widgets."""

    mode: ScalpMapsUiMode
    show_paired_figure_option: bool
    show_two_group_figure_option: bool
    show_figure_layout: bool
    compact_advanced_layout: bool


def resolve_scalp_maps_ui_profile(
    *,
    repeated_project: bool,
    session_comparison_active: bool,
    canonical_group_count: int,
) -> ScalpMapsUiProfile:
    """Return one coherent presentation profile for the active workflow."""

    group_count = int(canonical_group_count)
    if group_count < 0:
        raise ValueError("canonical_group_count cannot be negative")
    if session_comparison_active and not repeated_project:
        raise ValueError(
            "session_comparison_active requires a repeated-session project"
        )

    if repeated_project and session_comparison_active:
        mode = ScalpMapsUiMode.REPEATED_SESSION_COMPARISON
    elif repeated_project:
        mode = ScalpMapsUiMode.REPEATED_CONDITION
    elif group_count <= 1:
        mode = ScalpMapsUiMode.SINGLE_GROUP
    else:
        mode = ScalpMapsUiMode.MULTI_GROUP

    show_paired = mode is not ScalpMapsUiMode.REPEATED_SESSION_COMPARISON
    show_two_group = show_paired and group_count == 2
    show_figure_layout = show_paired or show_two_group
    return ScalpMapsUiProfile(
        mode=mode,
        show_paired_figure_option=show_paired,
        show_two_group_figure_option=show_two_group,
        show_figure_layout=show_figure_layout,
        compact_advanced_layout=not show_figure_layout,
    )


__all__ = [
    "ScalpMapsUiMode",
    "ScalpMapsUiProfile",
    "resolve_scalp_maps_ui_profile",
]
