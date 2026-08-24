"""Canonical request/result preparation for repeated-session scalp-map grids."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

import pandas as pd

from Tools.Publication_Maps.excel_inputs import load_publication_dataset_index
from Tools.Publication_Maps.models import (
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.session_panels import (
    SessionMapPanelSet,
    build_repeated_session_map_panels,
)


def validate_session_grid_requests(
    requests: Sequence[PublicationMapRequest],
) -> bool:
    """Validate the exact two-group, two-session descriptive grid contract."""

    normalized = tuple(requests)
    enabled = tuple(request.export_session_grid_figure for request in normalized)
    identity_present = any(request.session_comparison_ids for request in normalized)
    if not any(enabled):
        if identity_present:
            raise ValueError(
                "Scalp Maps session comparison IDs require session-grid export."
            )
        return False
    if len(normalized) != 2 or not all(enabled):
        raise ValueError(
            "A repeated-session Scalp Maps grid requires exactly two group requests."
        )
    baseline = replace(
        normalized[0],
        conditions=(),
        group_id=None,
        group_label=None,
        group_folder=None,
    )
    if any(
        replace(
            request,
            conditions=(),
            group_id=None,
            group_label=None,
            group_folder=None,
        )
        != baseline
        for request in normalized[1:]
    ):
        raise ValueError(
            "Session-grid requests may differ only by canonical group."
        )
    if any(
        request.export_group_comparison_figure
        or request.group_comparison_ids
        or request.export_paired_figures
        or request.paired_conditions
        for request in normalized
    ):
        raise ValueError(
            "Session grids cannot be combined with condition-pair or group-comparison figures."
        )
    if any(not request.conditions for request in normalized):
        raise ValueError("Session grids require at least one task condition.")
    if normalized[0].conditions != normalized[1].conditions:
        raise ValueError("Session-grid requests must use the same ordered conditions.")
    group_ids = tuple(str(request.group_id or "").strip() for request in normalized)
    if any(not value for value in group_ids) or len(
        {value.casefold() for value in group_ids}
    ) != 2:
        raise ValueError("Session grids require two distinct canonical group IDs.")
    if any(not str(request.group_label or "").strip() for request in normalized):
        raise ValueError("Session grids require canonical group labels.")
    if any(not str(request.group_folder or "").strip() for request in normalized):
        raise ValueError("Session grids require canonical group output folders.")
    session_ids = tuple(
        str(value).strip() for value in normalized[0].session_comparison_ids
    )
    if len(session_ids) != 2 or len(
        {value.casefold() for value in session_ids}
    ) != 2:
        raise ValueError("Session grids require two distinct canonical session IDs.")
    if any(
        tuple(str(value).strip().casefold() for value in request.session_comparison_ids)
        != tuple(value.casefold() for value in session_ids)
        for request in normalized[1:]
    ):
        raise ValueError("Session-grid requests must use the same ordered sessions.")
    if any(
        tuple(str(value).strip().casefold() for value in request.session_ids)
        != tuple(value.casefold() for value in session_ids)
        for request in normalized
    ):
        raise ValueError(
            "Session-grid workbook selection must equal the ordered comparison sessions."
        )
    if not normalized[0].export_png and not normalized[0].export_pdf:
        raise ValueError("Session grids require PNG and/or PDF export.")
    return True


def validate_session_grid_project(
    requests: Sequence[PublicationMapRequest],
):
    """Return the canonical index after validating the complete 2×2 selection."""

    normalized = tuple(requests)
    validate_session_grid_requests(normalized)
    try:
        index = load_publication_dataset_index(
            normalized[0].input_root,
            project_root=normalized[0].project_root,
        )
    except Exception as exc:
        raise PublicationMapInputError(
            f"Unable to validate repeated-session Scalp Maps identity: {exc}"
        ) from exc
    if not index.is_repeated_session:
        raise PublicationMapInputError(
            "Session grids require canonical project recording/session metadata."
        )
    requested_groups = tuple(str(request.group_id) for request in normalized)
    canonical_groups = tuple(group.group_id for group in index.ordered_groups)
    if len(canonical_groups) != 2 or tuple(
        value.casefold() for value in canonical_groups
    ) != tuple(value.casefold() for value in requested_groups):
        raise PublicationMapInputError(
            "The 2×2 session grid requires the project's two canonical groups in canonical order."
        )
    requested_sessions = normalized[0].session_comparison_ids
    canonical_session_lookup = {
        session.session_id.casefold(): session.session_id
        for session in index.ordered_sessions
    }
    if any(
        str(value).casefold() not in canonical_session_lookup
        for value in requested_sessions
    ):
        raise PublicationMapInputError(
            "A selected session is no longer declared by the active project."
        )
    records = index.select(
        conditions=normalized[0].conditions,
        group_ids=requested_groups,
        session_ids=requested_sessions,
        require_nonempty_groups=True,
        require_nonempty_sessions=True,
    )
    cells = {
        (
            str(record.condition).casefold(),
            str(record.group_id).casefold(),
            str(record.session_id).casefold(),
        )
        for record in records
    }
    missing = [
        f"{condition} × {group_id} × {session_id}"
        for condition in normalized[0].conditions
        for group_id in requested_groups
        for session_id in requested_sessions
        if (
            condition.casefold(),
            group_id.casefold(),
            session_id.casefold(),
        )
        not in cells
    ]
    if missing:
        raise PublicationMapInputError(
            "The repeated-session grid has missing condition × group × session cells: "
            + ", ".join(missing)
            + "."
        )
    return index, records


def build_session_panel_sets(
    results: Sequence[PublicationMapResult],
    requests: Sequence[PublicationMapRequest],
    *,
    cancel_check: Callable[[], None] | None = None,
) -> tuple[SessionMapPanelSet, ...]:
    """Combine group-scoped results into one panel set per metric."""

    if cancel_check is not None:
        cancel_check()
    normalized_results = tuple(results)
    normalized_requests = tuple(requests)
    if len(normalized_results) != 2:
        raise PublicationMapInputError(
            "Session grids require two completed canonical group results."
        )
    _index, records = validate_session_grid_project(normalized_requests)
    if cancel_check is not None:
        cancel_check()
    harmonic_sets = {
        tuple(result.selected_harmonics_hz) for result in normalized_results
    }
    selection_fingerprints = {
        str(result.selection_metadata.get("selection_fingerprint", ""))
        for result in normalized_results
    }
    qc_fingerprints = {
        str(result.qc_provenance.get("applied_exclusions_sha256", ""))
        for result in normalized_results
    }
    if (
        len(harmonic_sets) != 1
        or not next(iter(harmonic_sets), ())
        or len(selection_fingerprints) != 1
        or not next(iter(selection_fingerprints), "")
    ):
        raise PublicationMapInputError(
            "Session-grid groups used different saved harmonic selections."
        )
    if len(qc_fingerprints) != 1 or not next(iter(qc_fingerprints), ""):
        raise PublicationMapInputError(
            "Session-grid groups used different QC exclusion snapshots."
        )
    for result, request in zip(
        normalized_results, normalized_requests, strict=True
    ):
        if str(result.group_id or "").casefold() != str(
            request.group_id or ""
        ).casefold():
            raise PublicationMapInputError(
                "Session-grid result group identity does not match its request."
            )
    long_values = pd.concat(
        [result.long_values for result in normalized_results],
        ignore_index=True,
    )
    first_request = normalized_requests[0]
    group_ids = tuple(str(request.group_id) for request in normalized_requests)
    metrics = tuple(dict.fromkeys(PublicationMetric(value) for value in first_request.metrics))
    panel_sets: list[SessionMapPanelSet] = []
    for condition in first_request.conditions:
        for metric in metrics:
            if cancel_check is not None:
                cancel_check()
            panel_sets.append(
                build_repeated_session_map_panels(
                    long_values=long_values,
                    workbook_records=records,
                    condition=condition,
                    metric=metric,
                    selected_harmonics_hz=(
                        normalized_results[0].selected_harmonics_hz
                    ),
                    group_ids=group_ids,
                    session_ids=first_request.session_comparison_ids,
                )
            )
    return tuple(panel_sets)


__all__ = [
    "build_session_panel_sets",
    "validate_session_grid_project",
    "validate_session_grid_requests",
]
