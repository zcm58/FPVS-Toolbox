"""Repeated-session data collection for SNR Plot Generator workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from Main_App.projects import ProjectDatasetIndex, WorkbookRecord
from Tools.Plot_Generator.excel_inputs import _frequency_grids_match
from Tools.Plot_Generator.session_aggregation import (
    SessionSNRAggregation,
    aggregate_repeated_session_snr,
)
from Tools.Plot_Generator.source_data import SourceCurve


class SessionPlotConfigurationError(ValueError):
    """Raised when a session comparison cannot be bound to canonical records."""


@dataclass(frozen=True, slots=True)
class SessionPlotSelection:
    """Validated canonical records for one repeated-session SNR figure."""

    condition: str
    session_ids: tuple[str, str]
    group_ids: tuple[str, ...]
    records: tuple[WorkbookRecord, ...]


def validate_session_plot_selection(
    index: ProjectDatasetIndex,
    *,
    condition: str,
    session_ids: Sequence[str],
    group_ids: Sequence[str] = (),
) -> SessionPlotSelection:
    """Resolve an exact condition/group/session selection without inference."""

    if not index.is_repeated_session:
        raise SessionPlotConfigurationError(
            "Session comparison requires canonical project recording/session metadata."
        )
    condition_text = str(condition).strip()
    if not condition_text or condition_text.casefold() == "all":
        raise SessionPlotConfigurationError(
            "Choose one task condition for a repeated-session SNR comparison."
        )
    known_conditions = {value.casefold(): value for value in index.conditions}
    if condition_text.casefold() not in known_conditions:
        raise SessionPlotConfigurationError(
            f"Unknown canonical condition {condition_text!r}."
        )
    requested_sessions = tuple(str(value).strip() for value in session_ids)
    if (
        len(requested_sessions) != 2
        or not all(requested_sessions)
        or len({value.casefold() for value in requested_sessions}) != 2
    ):
        raise SessionPlotConfigurationError(
            "Session comparison requires two distinct canonical sessions."
        )
    known_sessions = {
        session.session_id.casefold(): session.session_id
        for session in index.ordered_sessions
    }
    unknown_sessions = [
        value for value in requested_sessions if value.casefold() not in known_sessions
    ]
    if unknown_sessions:
        raise SessionPlotConfigurationError(
            "Unknown canonical session(s): " + ", ".join(unknown_sessions) + "."
        )
    canonical_sessions = tuple(
        known_sessions[value.casefold()] for value in requested_sessions
    )

    known_groups = {
        group.group_id.casefold(): group.group_id for group in index.ordered_groups
    }
    requested_groups = tuple(
        dict.fromkeys(str(value).strip() for value in group_ids if str(value).strip())
    )
    if not requested_groups:
        requested_groups = tuple(group.group_id for group in index.ordered_groups)
    if not requested_groups:
        raise SessionPlotConfigurationError(
            "Session comparison requires canonical stable group identity."
        )
    unknown_groups = [
        value for value in requested_groups if value.casefold() not in known_groups
    ]
    if unknown_groups:
        raise SessionPlotConfigurationError(
            "Unknown canonical group(s): " + ", ".join(unknown_groups) + "."
        )
    canonical_groups = tuple(known_groups[value.casefold()] for value in requested_groups)
    records = index.select(
        conditions=(known_conditions[condition_text.casefold()],),
        group_ids=canonical_groups,
        session_ids=canonical_sessions,
        require_nonempty_groups=True,
        require_nonempty_sessions=True,
    )
    for record in records:
        missing = [
            field
            for field in ("recording_id", "session_id", "session_label", "visit_index")
            if getattr(record, field, None) in (None, "")
        ]
        if missing:
            raise SessionPlotConfigurationError(
                "Repeated-session SNR requires canonical "
                + ", ".join(missing)
                + f" for {record.path}."
            )
    present_cells = {
        (str(record.group_id).casefold(), str(record.session_id).casefold())
        for record in records
    }
    missing_cells = [
        f"{group_id} × {session_id}"
        for group_id in canonical_groups
        for session_id in canonical_sessions
        if (group_id.casefold(), session_id.casefold()) not in present_cells
    ]
    if missing_cells:
        raise SessionPlotConfigurationError(
            "Session comparison requires every selected group × session cell; "
            "missing: " + ", ".join(missing_cells) + "."
        )
    return SessionPlotSelection(
        condition=known_conditions[condition_text.casefold()],
        session_ids=(canonical_sessions[0], canonical_sessions[1]),
        group_ids=canonical_groups,
        records=records,
    )


class SessionPlotWorkflowMixin:
    """Collect session-separated curves before participant IDs can collide."""

    def _run_session_comparison(self) -> None:
        index = self._load_dataset_index()
        selection = validate_session_plot_selection(
            index,
            condition=self.condition,
            session_ids=self.session_comparison_ids,
            group_ids=self.session_group_ids,
        )
        frequencies: list[float] | None = None
        curves_by_recording: dict[str, Mapping[str, Sequence[object]]] = {}
        total = len(selection.records)
        offset = 0
        for session_id in selection.session_ids:
            records = tuple(
                record
                for record in selection.records
                if str(record.session_id).casefold() == session_id.casefold()
            )
            session_frequencies, participant_curves = self._collect_data(
                selection.condition,
                excel_files=[record.path for record in records],
                offset=offset,
                total_override=total,
            )
            offset += len(records)
            if self._cancellation_checkpoint():
                return
            if frequencies is None:
                frequencies = list(session_frequencies)
            elif not _frequency_grids_match(frequencies, session_frequencies):
                raise SessionPlotConfigurationError(
                    "Selected sessions use different FullSNR frequency grids. "
                    "Reprocess both sessions with matching settings."
                )
            for record in records:
                participant_values = participant_curves.get(record.participant_id.upper())
                if participant_values is None:
                    continue
                curves_by_recording[str(record.recording_id)] = participant_values
        if not frequencies or not curves_by_recording:
            raise SessionPlotConfigurationError(
                "No usable repeated-session FullSNR curves were available."
            )
        aggregation = aggregate_repeated_session_snr(
            workbook_records=selection.records,
            curves_by_recording=curves_by_recording,
            condition=selection.condition,
            session_pair=selection.session_ids,
            roi_names=self._selected_roi_names(),
        )
        self._revalidate_analysis_context_for_output()
        self._prepare_session_source_curves(
            frequencies_hz=frequencies,
            aggregation=aggregation,
        )
        self._plot_session_comparison(
            frequencies,
            aggregation,
        )

    def _prepare_session_source_curves(
        self,
        *,
        frequencies_hz: Sequence[float],
        aggregation: SessionSNRAggregation,
    ) -> None:
        pending: dict[str, tuple[SourceCurve, ...]] = {}
        roi_names = tuple(dict.fromkeys(cell.roi for cell in aggregation.cells))
        for roi in roi_names:
            curves: list[SourceCurve] = []
            for cell in aggregation.cells:
                if cell.roi != roi:
                    continue
                curves.append(
                    SourceCurve(
                        curve_id=(
                            f"{aggregation.condition}:{cell.group_id}:"
                            f"{cell.session_id}:{roi}"
                        ),
                        condition=aggregation.condition,
                        roi=roi,
                        group=cell.group_label,
                        plotted_values=cell.plotted_values,
                        participant_n_by_frequency=cell.participant_n_by_frequency,
                        participant_n_roi=cell.participant_n_roi,
                        participant_ids=cell.participant_ids,
                    )
                )
            if curves:
                pending[roi] = tuple(curves)
        self._set_pending_source_curves(frequencies_hz, pending)


__all__ = [
    "SessionPlotConfigurationError",
    "SessionPlotSelection",
    "SessionPlotWorkflowMixin",
    "validate_session_plot_selection",
]
