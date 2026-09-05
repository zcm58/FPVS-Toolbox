"""Worker-thread FullSNR/FullFFT reads and spectral-QC report routing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import List, Sequence
from xml.etree import ElementTree
import zipfile

import pandas as pd

from Tools.Plot_Generator.full_snr_reader import (
    XlsxWorkbookReadSession,
    _read_full_snr_sheet_read_only,
)
from Tools.Plot_Generator.source_identity import SourceWorkbookSnapshot
from Tools.Plot_Generator.spectral_qc import (
    SPECTRAL_QC_METHOD_VERSION,
    SpectralQcResult,
    SpectralQcThresholds,
    electrode_snr_data,
    flag_spectral_qc_electrode_outliers,
    interpolate_fullfft_electrode_data,
    read_full_fft_sheet_read_only,
    summarize_spectral_qc_records,
)


class PlotSpectralQcWorkflowMixin:
    """Keep optional spectral-QC IO outside the core collection loop."""

    def _read_full_snr_direct(
        self,
        excel_path: Path,
        *,
        included_electrodes_upper: set[str] | None,
        workbook_session: XlsxWorkbookReadSession | None = None,
    ) -> tuple[pd.DataFrame, List[float], List[str]]:
        return self._timed_call(
            "excel_load",
            lambda: _read_full_snr_sheet_read_only(
                excel_path,
                x_min=self.x_min,
                x_max=self.x_max,
                timing_details=self._timing_details,
                included_electrodes_upper=included_electrodes_upper,
                workbook_session=workbook_session,
            ),
        )

    def _read_full_fft_direct(
        self,
        excel_path: Path,
        *,
        included_electrodes_upper: set[str] | None,
        workbook_session: XlsxWorkbookReadSession | None = None,
    ) -> tuple[pd.DataFrame, List[float], List[str]]:
        return self._timed_call(
            "excel_load",
            lambda: read_full_fft_sheet_read_only(
                excel_path,
                x_min=self.x_min,
                x_max=self.x_max,
                timing_details=self._timing_details,
                included_electrodes_upper=included_electrodes_upper,
                workbook_session=workbook_session,
            ),
        )

    def _read_workbook_sheets(
        self,
        excel_path: Path,
        *,
        snapshot: SourceWorkbookSnapshot,
        included_electrodes_upper: set[str],
    ) -> tuple[
        tuple[pd.DataFrame, List[float], List[str]],
        tuple[pd.DataFrame, List[float], List[str]] | None,
        str | None,
    ]:
        """Read required SNR and optional QC sheets from one archive session."""

        fft_input = None
        qc_unavailable_reason = None
        with XlsxWorkbookReadSession(
            snapshot.content, spectral_sheets=snapshot.spectral_sheets
        ) as session:
            snr_input = self._read_full_snr_direct(
                excel_path,
                included_electrodes_upper=(
                    None if self.spectral_qc_enabled else included_electrodes_upper
                ),
                workbook_session=session,
            )
            if self.spectral_qc_enabled and not self._cancellation_checkpoint():
                try:
                    fft_input = self._read_full_fft_direct(
                        excel_path,
                        included_electrodes_upper=None,
                        workbook_session=session,
                    )
                except (
                    OSError,
                    KeyError,
                    TypeError,
                    ValueError,
                    zipfile.BadZipFile,
                    ElementTree.ParseError,
                ) as exc:
                    qc_unavailable_reason = (
                        f"spectral-QC evidence read/conversion failed: {exc}"
                    )
        return snr_input, fft_input, qc_unavailable_reason

    def _note_spectral_qc_unavailable(
        self,
        unavailable: dict[str, str],
        *,
        condition: str,
        participant_id: str,
        workbook_path: Path,
        reason: str,
    ) -> None:
        unavailable[participant_id] = reason
        message = (
            f"Spectral QC skipped {workbook_path.name} for {participant_id}: "
            f"{reason}. SNR plotting continues."
        )
        self._emit(f"Warning: {message}", 0, 0)
        self._record_warning(
            code="spectral_qc_input_unavailable",
            item=f"{condition}:{participant_id}",
            message=message,
        )

    def _assemble_spectral_qc_evidence(
        self,
        excel_path: Path,
        *,
        ordered_freqs: Sequence[float],
        excluded_electrodes: Sequence[str],
        snr_input: tuple[pd.DataFrame, Sequence[float], Sequence[str]] | None = None,
        fft_input: tuple[pd.DataFrame, Sequence[float], Sequence[str]] | None = None,
        unavailable_reason: str | None = None,
    ) -> tuple[dict[str, list[float]], dict[str, list[float]], str | None]:
        """Return optional QC evidence without failing valid ROI plotting."""

        if unavailable_reason is not None:
            return {}, {}, unavailable_reason
        try:
            if snr_input is None:
                snr_input = self._read_full_snr_direct(
                    excel_path,
                    included_electrodes_upper=None,
                )
            snr_frame, snr_freqs, snr_cols = snr_input
            if self._cancellation_checkpoint():
                return {}, {}, None
            if fft_input is None:
                fft_input = self._read_full_fft_direct(
                    excel_path,
                    included_electrodes_upper=None,
                )
            fft_frame, fft_freqs, fft_cols = fft_input
            if not snr_cols or not fft_cols or list(snr_freqs) != list(ordered_freqs):
                return {}, {}, "spectral-QC sheets or frequency grids were unavailable"
            snr_by_electrode = electrode_snr_data(snr_frame, snr_cols)
            fft_by_electrode = interpolate_fullfft_electrode_data(
                fft_frame,
                fft_freqs,
                fft_cols,
                ordered_freqs,
            )
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as exc:
            return {}, {}, f"spectral-QC evidence read/conversion failed: {exc}"
        for electrode in excluded_electrodes:
            snr_by_electrode.pop(str(electrode).upper(), None)
            fft_by_electrode.pop(str(electrode).upper(), None)
        if not snr_by_electrode or not fft_by_electrode:
            return {}, {}, "spectral-QC electrode values were unavailable"
        return snr_by_electrode, fft_by_electrode, None

    def _apply_spectral_qc_to_condition(
        self,
        condition: str,
        freqs: Sequence[float],
        subject_snr_data: dict[str, dict[str, list[float]]],
        subject_fft_data: dict[str, dict[str, list[float]]],
        source_workbooks: dict[str, str],
        unavailable_workbooks: Mapping[str, str],
        candidate_participant_ids: Sequence[str],
    ) -> None:
        thresholds = SpectralQcThresholds()
        if not self.spectral_qc_enabled:
            self._record_spectral_qc_audit(
                condition=condition,
                status="disabled",
                thresholds=thresholds,
                candidate_participant_ids=candidate_participant_ids,
                eligible_workbook_ids=(),
                unavailable_workbooks={},
                result=None,
            )
            return
        if self._cancellation_checkpoint():
            return
        if not subject_fft_data:
            unavailable = dict(unavailable_workbooks)
            for participant_id in candidate_participant_ids:
                unavailable.setdefault(
                    str(participant_id),
                    "no eligible FullSNR/FullFFT spectral-QC evidence",
                )
            self._record_spectral_qc_audit(
                condition=condition,
                status="unavailable",
                thresholds=thresholds,
                candidate_participant_ids=candidate_participant_ids,
                eligible_workbook_ids=(),
                unavailable_workbooks=unavailable,
                result=None,
            )
            return
        result = flag_spectral_qc_electrode_outliers(
            condition=condition,
            freqs=freqs,
            subject_snr_data=subject_snr_data,
            subject_fft_data=subject_fft_data,
            source_workbooks=source_workbooks,
            oddball_freq=self._analysis_oddball_freq,
            base_freq=self._analysis_base_freq,
            thresholds=thresholds,
            cancellation_checkpoint=self._cancellation_checkpoint,
        )
        if self._cancellation_checkpoint():
            return
        if result.checked_cells == 0:
            reason = (
                "No electrode-frequency cells had the shared finite evidence "
                f"required across at least {thresholds.min_subjects} participants."
            )
            self._emit(f"Warning: Spectral QC unavailable for {condition}: {reason}")
            self._record_warning(
                code="spectral_qc_insufficient_shared_evidence",
                item=condition,
                message=reason,
            )
            self._record_spectral_qc_audit(
                condition=condition,
                status="unavailable",
                status_reason=reason,
                thresholds=thresholds,
                candidate_participant_ids=candidate_participant_ids,
                eligible_workbook_ids=sorted(source_workbooks),
                unavailable_workbooks=unavailable_workbooks,
                result=result,
            )
            return
        status = "partial" if unavailable_workbooks else "complete"
        self._record_spectral_qc_audit(
            condition=condition,
            status=status,
            thresholds=thresholds,
            candidate_participant_ids=candidate_participant_ids,
            eligible_workbook_ids=sorted(source_workbooks),
            unavailable_workbooks=unavailable_workbooks,
            result=result,
        )
        self._record_spectral_qc_flags(
            summarize_spectral_qc_records(result.records)
        )
    def _record_spectral_qc_audit(
        self,
        *,
        condition: str,
        status: str,
        status_reason: str | None = None,
        thresholds: SpectralQcThresholds,
        candidate_participant_ids: Sequence[str],
        eligible_workbook_ids: Sequence[str],
        unavailable_workbooks: Mapping[str, str],
        result: SpectralQcResult | None,
    ) -> None:
        context = self._snr_analysis_context
        source_kind = (
            context.provenance.get("source_kind") if context is not None else None
        )
        self.spectral_qc_runs.append(
            {
                "condition": condition,
                "status": status,
                "status_reason": status_reason,
                "method_version": SPECTRAL_QC_METHOD_VERSION,
                "thresholds": asdict(thresholds),
                "resolved_rates_hz": {
                    "base": self._analysis_base_freq,
                    "oddball": self._analysis_oddball_freq,
                },
                "source_kind": source_kind,
                "cohort_participant_ids": sorted(
                    {str(value) for value in candidate_participant_ids}
                ),
                "eligible_workbook_ids": sorted(
                    {str(value) for value in eligible_workbook_ids}
                ),
                "unavailable_workbooks": [
                    {"participant_id": participant_id, "reason": reason}
                    for participant_id, reason in sorted(
                        (str(key), str(value))
                        for key, value in unavailable_workbooks.items()
                    )
                ],
                "checked_cells": result.checked_cells if result is not None else 0,
                "flagged_cells": result.flagged_cells if result is not None else 0,
            }
        )


__all__ = ["PlotSpectralQcWorkflowMixin"]
