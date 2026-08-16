"""Exact plotted-curve values and participant-support bookkeeping."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SourceCurve:
    """One plotted curve plus the exact participant support behind each point."""

    curve_id: str
    condition: str
    roi: str
    group: str | None
    plotted_values: tuple[float | None, ...]
    participant_n_by_frequency: tuple[int, ...]
    participant_n_roi: int
    participant_ids: tuple[str, ...]


def _json_number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def build_source_curve(
    *,
    curve_id: str,
    condition: str,
    roi: str,
    plotted_values: Sequence[float],
    subject_data: Mapping[str, Mapping[str, Sequence[float]]],
    participant_ids: Iterable[str],
    frequency_count: int,
    group: str | None = None,
) -> SourceCurve:
    """Build exact ROI and per-frequency Ns for an already plotted curve."""

    usable_ids: list[str] = []
    per_frequency = [0] * frequency_count
    for participant_id in sorted({str(value) for value in participant_ids}):
        values = subject_data.get(participant_id, {}).get(roi, ())
        finite_any = False
        for index in range(min(frequency_count, len(values))):
            if _json_number(values[index]) is None:
                continue
            per_frequency[index] += 1
            finite_any = True
        if finite_any:
            usable_ids.append(participant_id)
    normalized_values = tuple(
        _json_number(plotted_values[index]) if index < len(plotted_values) else None
        for index in range(frequency_count)
    )
    return SourceCurve(
        curve_id=str(curve_id),
        condition=str(condition),
        roi=str(roi),
        group=str(group) if group is not None else None,
        plotted_values=normalized_values,
        participant_n_by_frequency=tuple(per_frequency),
        participant_n_roi=len(usable_ids),
        participant_ids=tuple(usable_ids),
    )


class PlotSourceDataMixin:
    """Prepare source curves without coupling rendering to publication."""

    @staticmethod
    def _participants_with_roi(
        subject_data: Mapping[str, Mapping[str, Sequence[float]]],
        roi: str,
    ) -> set[str]:
        return {
            str(participant_id)
            for participant_id, roi_values in subject_data.items()
            if any(_json_number(value) is not None for value in roi_values.get(roi, ()))
        }

    def _prepare_single_source_curves(
        self,
        *,
        frequencies_hz: Sequence[float],
        condition: str,
        subject_data: Mapping[str, Mapping[str, Sequence[float]]],
        plotted_roi_data: Mapping[str, Sequence[float]],
        group_curves: Mapping[str, Mapping[str, Sequence[float]]] | None = None,
    ) -> None:
        pending: dict[str, tuple[SourceCurve, ...]] = {}
        group_curves = group_curves or {}
        self.roi_sample_sizes.clear()
        for roi, pooled_values in plotted_roi_data.items():
            curves: list[SourceCurve] = []
            if group_curves:
                for group in self.selected_groups or group_curves.keys():
                    values = group_curves.get(group, {}).get(roi)
                    if not values:
                        continue
                    participants = {
                        participant_id
                        for participant_id in self._participants_with_roi(
                            subject_data, roi
                        )
                        if self.subject_groups.get(participant_id) == group
                    }
                    curves.append(
                        build_source_curve(
                            curve_id=f"{condition}:{group}:{roi}",
                            condition=condition,
                            roi=roi,
                            group=group,
                            plotted_values=values,
                            subject_data=subject_data,
                            participant_ids=participants,
                            frequency_count=len(frequencies_hz),
                        )
                    )
            else:
                participants = self._participants_with_roi(subject_data, roi)
                curve = build_source_curve(
                    curve_id=f"{condition}:{roi}",
                    condition=condition,
                    roi=roi,
                    plotted_values=pooled_values,
                    subject_data=subject_data,
                    participant_ids=participants,
                    frequency_count=len(frequencies_hz),
                )
                self.roi_sample_sizes[roi] = curve.participant_n_roi
                curves.append(curve)
            if curves:
                pending[roi] = tuple(curves)
        self._set_pending_source_curves(frequencies_hz, pending)

    def _prepare_overlay_source_curves(
        self,
        *,
        frequencies_hz: Sequence[float],
        condition_a: str,
        subject_data_a: Mapping[str, Mapping[str, Sequence[float]]],
        plotted_data_a: Mapping[str, Sequence[float]],
        condition_b: str,
        subject_data_b: Mapping[str, Mapping[str, Sequence[float]]],
        plotted_data_b: Mapping[str, Sequence[float]],
    ) -> None:
        pending: dict[str, tuple[SourceCurve, ...]] = {}
        self.overlay_roi_sample_sizes = {condition_a: {}, condition_b: {}}
        for roi, values_a in plotted_data_a.items():
            values_b = plotted_data_b.get(roi)
            if not values_b:
                continue
            participants_a = self._participants_with_roi(subject_data_a, roi)
            participants_b = self._participants_with_roi(subject_data_b, roi)
            curve_a = build_source_curve(
                curve_id=f"{condition_a}:{roi}",
                condition=condition_a,
                roi=roi,
                plotted_values=values_a,
                subject_data=subject_data_a,
                participant_ids=participants_a,
                frequency_count=len(frequencies_hz),
            )
            curve_b = build_source_curve(
                curve_id=f"{condition_b}:{roi}",
                condition=condition_b,
                roi=roi,
                plotted_values=values_b,
                subject_data=subject_data_b,
                participant_ids=participants_b,
                frequency_count=len(frequencies_hz),
            )
            self.overlay_roi_sample_sizes[condition_a][roi] = curve_a.participant_n_roi
            self.overlay_roi_sample_sizes[condition_b][roi] = curve_b.participant_n_roi
            pending[roi] = (curve_a, curve_b)
        self._set_pending_source_curves(frequencies_hz, pending)

    def _set_pending_source_curves(
        self,
        frequencies_hz: Sequence[float],
        curves: Mapping[str, tuple[SourceCurve, ...]],
    ) -> None:
        self._pending_source_curves = dict(curves)
        self._source_curves_seen.extend(
            curve for roi_curves in curves.values() for curve in roi_curves
        )
        grid = [float(value) for value in frequencies_hz]
        if grid not in self._frequency_grids_seen:
            self._frequency_grids_seen.append(grid)


__all__ = ["PlotSourceDataMixin", "SourceCurve", "build_source_curve"]
