"""Ordered condition-overlay collection and shared-grid validation."""

from __future__ import annotations

from .excel_inputs import _frequency_grids_match
from .render_naming import condition_overlay_title


class ConditionOverlayWorkflowMixin:
    """Collect every requested condition before rendering an overlay."""

    @property
    def overlay_conditions(self) -> tuple[str, ...]:
        return (self.condition, self.condition_b or "", *self.extra_conditions)

    def _run_condition_overlay(self) -> None:
        conditions = self.overlay_conditions
        if (
            not 2 <= len(conditions) <= 5
            or any(not condition.strip() for condition in conditions)
            or len(set(conditions)) != len(conditions)
        ):
            raise ValueError("Select between two and five different conditions to overlay.")
        for values in (
            self.extra_colors, self.legend_extra_conditions, self.legend_extra_peaks
        ):
            if values and len(values) != len(self.extra_conditions):
                raise ValueError("Extra condition colors and labels must match the selected conditions.")

        files = []
        for condition in conditions:
            if self._cancellation_checkpoint():
                return
            files.append(self._list_excel_files(condition))
        total = sum(len(items) for items in files)
        offset = 0
        collected = []
        comparison = condition_overlay_title(conditions)
        for condition, excel_files in zip(conditions, files):
            if self._cancellation_checkpoint():
                return
            frequencies, subject_data = self._collect_data(
                condition, excel_files=excel_files, offset=offset, total_override=total
            )
            if self._cancellation_checkpoint():
                return
            offset += len(excel_files)
            if not frequencies or not subject_data:
                error = f"Condition '{condition}' has no usable FullSNR data"
                self._record_failure(item=comparison, error=error)
                self._emit(f"Cannot overlay {comparison}: {error.lower()}.", total, total)
                return
            if collected and not _frequency_grids_match(collected[0][0], frequencies):
                self._record_failure(
                    item=comparison, error="Condition overlay FullSNR frequency grid mismatch"
                )
                subject = "the two conditions" if len(conditions) == 2 else "the selected conditions"
                self._emit(
                    f"Cannot overlay {comparison}: {subject} use different FullSNR "
                    f"frequency grids ('{conditions[0]}' and '{condition}'). "
                    "Reprocess the conditions with the same frequency-grid settings.",
                    total, total,
                )
                return
            collected.append((frequencies, subject_data))

        self._clamp_x_max_to_observed_frequency_grid(*(item[0] for item in collected))
        averaged = []
        for _frequencies, subject_data in collected:
            if self._cancellation_checkpoint():
                return
            averaged.append(self._aggregate_roi_data(subject_data))
        if self._cancellation_checkpoint():
            return
        matched = self._matched_condition_overlay_roi_data(conditions, averaged)
        if not matched:
            return
        self._revalidate_analysis_context_for_output()
        if len(matched) == 2:
            self._prepare_overlay_source_curves(
                frequencies_hz=collected[0][0],
                condition_a=conditions[0], subject_data_a=collected[0][1],
                plotted_data_a=matched[0],
                condition_b=conditions[1], subject_data_b=collected[1][1],
                plotted_data_b=matched[1],
            )
            self._plot_overlay(collected[0][0], *matched)
        else:
            self._prepare_condition_overlay_source_curves(
                frequencies_hz=collected[0][0],
                conditions=conditions,
                subject_data=[item[1] for item in collected],
                plotted_data=matched,
            )
            self._plot_overlay(collected[0][0], *matched[:2], extra_data=matched[2:])
