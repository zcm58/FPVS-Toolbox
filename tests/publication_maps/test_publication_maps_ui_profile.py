from __future__ import annotations

import pytest

from Tools.Publication_Maps.ui_profile import (
    ScalpMapsUiMode,
    resolve_scalp_maps_ui_profile,
)


@pytest.mark.parametrize(
    (
        "repeated_project",
        "session_comparison_active",
        "group_count",
        "expected_mode",
        "show_paired",
        "show_two_group",
        "show_layout",
    ),
    (
        (
            False,
            False,
            1,
            ScalpMapsUiMode.SINGLE_GROUP,
            True,
            False,
            True,
        ),
        (
            False,
            False,
            2,
            ScalpMapsUiMode.MULTI_GROUP,
            True,
            True,
            True,
        ),
        (
            False,
            False,
            3,
            ScalpMapsUiMode.MULTI_GROUP,
            True,
            False,
            True,
        ),
        (
            True,
            False,
            2,
            ScalpMapsUiMode.REPEATED_CONDITION,
            True,
            True,
            True,
        ),
        (
            True,
            True,
            2,
            ScalpMapsUiMode.REPEATED_SESSION_COMPARISON,
            False,
            False,
            False,
        ),
    ),
)
def test_scalp_maps_ui_profile_matrix(
    repeated_project: bool,
    session_comparison_active: bool,
    group_count: int,
    expected_mode: ScalpMapsUiMode,
    show_paired: bool,
    show_two_group: bool,
    show_layout: bool,
) -> None:
    profile = resolve_scalp_maps_ui_profile(
        repeated_project=repeated_project,
        session_comparison_active=session_comparison_active,
        canonical_group_count=group_count,
    )

    assert profile.mode is expected_mode
    assert profile.show_paired_figure_option is show_paired
    assert profile.show_two_group_figure_option is show_two_group
    assert profile.show_figure_layout is show_layout


def test_scalp_maps_ui_profile_rejects_negative_group_count() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        resolve_scalp_maps_ui_profile(
            repeated_project=False,
            session_comparison_active=False,
            canonical_group_count=-1,
        )


def test_scalp_maps_ui_profile_rejects_impossible_session_mode() -> None:
    with pytest.raises(ValueError, match="requires a repeated-session project"):
        resolve_scalp_maps_ui_profile(
            repeated_project=False,
            session_comparison_active=True,
            canonical_group_count=2,
        )
